"""Typed coordination for normal speech preparation and serialized playback."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from core import speech_text, text_chunking
from core.synthesis_order import SynthesisOrder
from core.runtime.avatar import AvatarService
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.controllers import (
    ControllerCancellationSignal,
    ControllerRegistrationHandle,
    ControllerSetupLease,
    ControllerSetupRegistry,
    ControllerSetupTransaction,
    RouteEffectOwner,
)
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerHandle
from core.runtime.playback import (
    DeliveredChunk,
    PlaybackObserver,
    PlaybackOwner,
    PlaybackReceipt,
    PlaybackService,
    spawn_route_worker,
)
from core.runtime.speech_output import (
    SpeechOutputService,
    SpeechOutputStream,
    SpeechPlan,
    dedupe_adjacent_stream_text,
)


@dataclass(frozen=True, slots=True)
class VoiceSegmentationRequest:
    text: str
    tts_backend: str
    streaming: bool
    stream_start: bool = False
    stream_source_index: int = 0
    source_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class VoiceSegmentationPolicy:
    requires_full_text: bool = False
    preserve_input_chunks: bool = False


@dataclass(frozen=True, slots=True)
class VoiceSegment:
    text: str
    voice_path: str = ""
    voice_language: str = ""
    source_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


class SpeechRouteAddonGateway(Protocol):
    """Typed addon boundary used by normal speech routing."""

    def voice_stream_policy(
        self,
        request: VoiceSegmentationRequest,
    ) -> VoiceSegmentationPolicy: ...

    def voice_segments(
        self,
        request: VoiceSegmentationRequest,
    ) -> Sequence[VoiceSegment]: ...


class PassthroughSpeechRouteAddonGateway:
    """Default gateway for compositions without addon voice segmentation."""

    def voice_stream_policy(
        self,
        request: VoiceSegmentationRequest,
    ) -> VoiceSegmentationPolicy:
        del request
        return VoiceSegmentationPolicy()

    def voice_segments(
        self,
        request: VoiceSegmentationRequest,
    ) -> tuple[VoiceSegment, ...]:
        return (VoiceSegment(request.text),) if request.text.strip() else ()


@dataclass(frozen=True, slots=True)
class SpeechRouteRequest:
    lease: WorkLease
    config: RuntimeConfigSnapshot
    source_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    initial_expression: str = "neutral"
    voice_path: str = ""
    voice_language: str = ""
    preserve_input_chunks: bool = False


class NormalSpeechRoute:
    """Application-facing control for one exact normal speech route."""

    def __init__(
        self,
        coordinator: "NormalSpeechRouteCoordinator",
        lease: WorkLease,
        token: CancellationToken,
    ) -> None:
        self.route_id = uuid.uuid4().hex
        self.lease = lease
        self._coordinator = coordinator
        self._token = token
        self._complete = threading.Event()
        self._audio_started = threading.Event()
        self._lock = threading.Lock()
        self._receipt: PlaybackReceipt | None = None
        self._failure: RuntimeFailure | None = None
        self._cleanup_count = 0

    @property
    def done(self) -> bool:
        return self._complete.is_set()

    @property
    def cancelled(self) -> bool:
        return self._token.cancelled

    @property
    def receipt(self) -> PlaybackReceipt | None:
        with self._lock:
            return self._receipt

    @property
    def failure(self) -> RuntimeFailure | None:
        with self._lock:
            return self._failure

    @property
    def audio_started(self) -> threading.Event:
        """Trusted device-playback start receipt for this exact route."""
        return self._audio_started

    def _mark_audio_started(self) -> None:
        self._audio_started.set()

    def cancel(
        self,
        reason: str = "speech_interrupted",
    ) -> CommandResult[PlaybackReceipt | None]:
        return self._coordinator.cancel(self, reason)

    def pause(self) -> CommandResult[None]:
        return self._coordinator.pause(self)

    def resume(self) -> CommandResult[None]:
        return self._coordinator.resume(self)

    def wait(self, timeout: float | None = None) -> bool:
        return self._complete.wait(timeout)

    def playback_retired(self) -> bool:
        """Distinguish producer cancellation from exact device-route retirement."""
        return self._coordinator.playback_retired(self)

    def _set_receipt(self, receipt: PlaybackReceipt) -> None:
        with self._lock:
            if self._receipt is None:
                self._receipt = receipt

    def _finish(
        self,
        *,
        failure: RuntimeFailure | None = None,
    ) -> None:
        with self._lock:
            if self._complete.is_set():
                return
            if failure is not None and self._failure is None:
                self._failure = failure
            self._cleanup_count += 1
            self._complete.set()


@dataclass(slots=True)
class _RouteState:
    route: NormalSpeechRoute
    token: CancellationToken
    setup: ControllerSetupLease
    registration: ControllerRegistrationHandle
    playback_owner: PlaybackOwner
    route_owner: RouteEffectOwner
    stream: "_ObservedRouteStream | None" = None
    observer: "_AvatarRouteObserver | None" = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    cleaned: bool = False


class _AvatarRouteObserver(PlaybackObserver):
    def __init__(
        self,
        avatar: AvatarService,
        state: _RouteState,
    ) -> None:
        self._avatar = avatar
        self._state = state
        self._lock = threading.Lock()
        self._delivered: list[DeliveredChunk] = []
        self._terminal = False

    def on_playback_started(self, chunk: DeliveredChunk) -> None:
        with self._lock:
            if (self._terminal or chunk.lease != self._state.playback_owner.lease
                    or chunk.owner_generation != self._state.playback_owner.generation
                    or (self._delivered and chunk.index <= self._delivered[-1].index)):
                return
            self._delivered.append(chunk)
        self._avatar.on_playback_started(
            chunk,
            route_owner=self._state.route_owner,
        )

    def on_audio_started(self, chunk: DeliveredChunk) -> None:
        with self._lock:
            if (self._terminal or not self._delivered
                    or chunk.lease != self._state.playback_owner.lease
                    or chunk.owner_generation != self._state.playback_owner.generation
                    or chunk.index != self._delivered[-1].index):
                return
        self._state.route._mark_audio_started()
        self._avatar.on_audio_started(chunk, route_owner=self._state.route_owner)

    def on_audio_progress(self, chunk, sample) -> None:
        with self._lock:
            if (self._terminal or not self._delivered or sample.key != chunk.index
                    or chunk.lease != self._state.playback_owner.lease
                    or chunk.owner_generation != self._state.playback_owner.generation
                    or self._delivered[-1].index != chunk.index):
                return
        self._avatar.on_audio_progress(chunk, sample, route_owner=self._state.route_owner)

    def on_playback_waiting(self, owner: PlaybackOwner) -> None:
        with self._lock:
            if self._terminal:
                return
        self._avatar.on_playback_waiting(owner, route_owner=self._state.route_owner)

    def on_playback_finished(self, receipt: PlaybackReceipt) -> None:
        with self._lock:
            if self._terminal:
                return
            self._terminal = True
        self._state.route._set_receipt(receipt)
        self._avatar.on_playback_finished(
            receipt,
            route_owner=self._state.route_owner,
        )

    def on_playback_paused(self, owner: PlaybackOwner) -> None:
        with self._lock:
            if self._terminal:
                return
        self._avatar.on_playback_paused(
            owner,
            route_owner=self._state.route_owner,
        )

    def on_cancelled(self, reason: str) -> None:
        with self._lock:
            if self._terminal:
                return
            self._terminal = True
            delivered = tuple(self._delivered)
        receipt = PlaybackReceipt(
            delivered,
            str(reason or "speech_cancelled"),
            self._state.playback_owner,
        )
        self._state.route._set_receipt(receipt)
        self._avatar.on_playback_finished(receipt)


class _ObservedRouteStream:
    """Bind one prepared source to avatar correlation and route cleanup."""

    _REMOTE_RENDER_DRAIN_SECONDS = 60.0

    def __init__(
        self,
        source: object,
        state: _RouteState,
        coordinator: "NormalSpeechRouteCoordinator",
        avatar: AvatarService,
        config: RuntimeConfigSnapshot | None = None,
    ) -> None:
        self._source = source
        self._state = state
        self._coordinator = coordinator
        self._avatar = avatar
        self._remote_render_deadline: float | None = None
        self._remote_render_failure: RuntimeFailure | None = None
        self.lease = state.route.lease
        mode = str(config.values.get("avatar_mode", "")).strip().lower() if config is not None else ""
        self.local_playback_eligible = mode == "none" or (
            mode == "scenic" and avatar.snapshot().provider_id.strip().lower() == "scenic"
        ) or (
            mode == "musetalk" and avatar.snapshot().provider_id.strip().lower() == "musetalk"
            and avatar.visual_coordinator() is not None)
        if not self.local_playback_eligible and mode and avatar.snapshot().provider_id.strip().lower() == mode:
            adapter = avatar.adapter()
            self.local_playback_eligible = bool(
                getattr(adapter, "supports_frame_buffer", False)
                and str(getattr(adapter, "avatar_provider_id", "")).strip().lower() == mode
                and avatar.visual_coordinator() is not None)

    @property
    def done(self) -> bool:
        if not bool(getattr(self._source, "done", False)):
            return False
        if self.cancelled or self.failure is not None or self._state.token.cancelled:
            return True
        if not self._avatar.has_pending_remote_renders(self.lease):
            return True
        # Audio is already handed to the phone. Only retain the exact route's
        # lifetime here, so finishing the turn cannot cancel its final render.
        now = time.monotonic()
        if self._remote_render_deadline is None:
            self._remote_render_deadline = now + self._REMOTE_RENDER_DRAIN_SECONDS
        if now >= self._remote_render_deadline:
            self._remote_render_failure = RuntimeFailure(
                "avatar_remote_render_timeout",
                "Phone avatar rendering did not finish before the route deadline.",
            )
        return False

    @property
    def cancelled(self) -> bool:
        return bool(getattr(self._source, "cancelled", False))

    @property
    def failure(self) -> RuntimeFailure | None:
        return getattr(self._source, "failure", None) or self._remote_render_failure

    def next_ready(self, timeout=None, *, admit_lease=None):
        ready = self._source.next_ready(timeout=timeout, admit_lease=admit_lease)
        if ready is None:
            self._wait_for_remote_render_poll(timeout)
        if ready is not None:
            prepared = getattr(ready, "chunk", ready)
            self._avatar.on_audio_prepared(prepared)
            self._avatar.wait_until_audio_ready(
                prepared,
                self._state.token,
                route_owner=self._state.route_owner,
                on_waiting=lambda: self._avatar.on_playback_waiting(
                    self._state.playback_owner, route_owner=self._state.route_owner,
                ),
            )
        return ready

    def next_local_ready(self, timeout=None, *, admit_lease=None):
        """Transfer the ordered source handoff without visible admission."""
        ready = self._source.next_ready(timeout=timeout, admit_lease=admit_lease)
        if ready is None:
            self._wait_for_remote_render_poll(timeout)
        return ready

    def _wait_for_remote_render_poll(self, timeout) -> None:
        # A finished audio source returns immediately. Yield while only the
        # asynchronous renderer remains, including on the local feeder lane.
        if (bool(getattr(self._source, "done", False)) and not self.done
                and self.failure is None):
            self._state.token.wait(.05 if timeout is None else min(.05, max(0., timeout)))

    def preflight_local_audio(self, prepared: object) -> CommandResult[bool]:
        self._avatar.on_audio_prepared(prepared)
        return self._avatar.preflight_audio_ready(prepared, self._state.token,
                                                 route_owner=self._state.route_owner)

    def start_local_feeder(self, target):
        return spawn_route_worker(
            self._coordinator._speech_output.workers, self._state.route_owner,
            name="nc-local-preflight", lease=self.lease, target=target)

    def cancel(self, reason: str = "speech_cancelled") -> None:
        try:
            self._source.cancel(reason)
        finally:
            self._avatar.release_remote_renders(self.lease)
            observer = self._state.observer
            if observer is not None:
                observer.on_cancelled(reason)
            self._coordinator._cleanup(self._state, failure=self.failure)

    def close(self) -> None:
        try:
            close = getattr(self._source, "close", None)
            if callable(close):
                close()
        finally:
            self._avatar.release_remote_renders(self.lease)
            self._coordinator._cleanup(self._state, failure=self.failure)

    def discard_ready(self, prepared: object) -> None:
        discard = getattr(self._source, "discard_ready", None)
        if callable(discard):
            discard(prepared)

    def ready_chunks(self) -> tuple[object, ...]:
        ready = getattr(self._source, "ready_chunks", None)
        return tuple(ready()) if callable(ready) else ()

    def has_live_producers(self) -> bool:
        predicate = getattr(self._source, "has_live_producers", None)
        return bool(predicate()) if callable(predicate) else False


class _StreamingSpeechStream:
    """Aggregate incrementally planned streams without weakening lease handoff."""

    def __init__(
        self,
        *,
        speech_output: SpeechOutputService,
        addons: SpeechRouteAddonGateway,
        chunks: Iterable[str],
        request: SpeechRouteRequest,
        policy: VoiceSegmentationPolicy,
        token: CancellationToken,
        route_owner: RouteEffectOwner,
        prepared_sentence_splitter: text_chunking.PreparedSentenceSplitter | None,
    ) -> None:
        self.lease = request.lease
        self._speech_output = speech_output
        self._addons = addons
        self._chunks = chunks
        self._request = request
        self._policy = policy
        self._token = token
        self._route_owner = route_owner
        self._prepared_sentence_splitter = prepared_sentence_splitter
        self._condition = threading.Condition()
        self._streams: deque[SpeechOutputStream] = deque()
        self._producer_done = False
        self._synthesis_order = SynthesisOrder()
        self._cancelled = False
        self._closed = False
        self._failure: RuntimeFailure | None = None
        self._producer: WorkerHandle | None = None
        self._max_pending = max(
            1,
            min(
                16,
                int(request.config.values.get("tts_route_stream_buffer_segments", 2) or 2),
            ),
        )

    @property
    def done(self) -> bool:
        with self._condition:
            return self._producer_done and not self._streams

    @property
    def cancelled(self) -> bool:
        with self._condition:
            return self._cancelled or self._token.cancelled

    @property
    def failure(self) -> RuntimeFailure | None:
        with self._condition:
            return self._failure

    def start(self) -> CommandResult[None]:
        spawned = spawn_route_worker(
            self._speech_output.workers,
            self._route_owner,
            name="nc-normal-speech-stream",
            lease=self.lease,
            target=self._produce,
        )
        if not spawned.accepted or spawned.value is None:
            failure = spawned.failure or RuntimeFailure(
                "speech_stream_start_failed",
                "The streaming speech producer could not start.",
            )
            self._fail(failure)
            return CommandResult(False, failure=failure)
        self._producer = spawned.value
        return CommandResult(True)

    def next_ready(self, timeout=None, *, admit_lease=None):
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        while True:
            with self._condition:
                if self._cancelled or self._closed:
                    return None
                source = self._streams[0] if self._streams else None
                if source is None and self._producer_done:
                    return None
                if source is None:
                    remaining = self._remaining(deadline)
                    if remaining == 0.0:
                        return None
                    self._condition.wait(remaining)
                    continue

            remaining = self._remaining(deadline)
            wait = 0.05 if remaining is None else min(0.05, remaining)
            ready = source.next_ready(timeout=wait, admit_lease=admit_lease)
            if ready is not None:
                return ready
            if source.failure is not None:
                self._fail(source.failure)
                return None
            if source.done or source.cancelled:
                with self._condition:
                    if self._streams and self._streams[0] is source:
                        self._streams.popleft()
                        self._condition.notify_all()
                source.close()
                continue
            if deadline is not None and self._remaining(deadline) == 0.0:
                return None

    def cancel(self, reason: str = "speech_cancelled") -> None:
        resolved = str(reason or "speech_cancelled")
        self._token.cancel(resolved)
        with self._condition:
            if self._cancelled:
                return
            self._cancelled = True
            streams = tuple(self._streams)
            self._streams.clear()
            self._condition.notify_all()
        close_iterator = getattr(self._chunks, "close", None)
        if callable(close_iterator):
            try:
                close_iterator()
            except BaseException:
                pass
        for source in streams:
            source.cancel(resolved)
            source.close()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            needs_cancel = not self._producer_done or bool(self._streams)
        if needs_cancel:
            self.cancel("speech_stream_closed")

    def discard_ready(self, prepared: object) -> None:
        with self._condition:
            streams = tuple(self._streams)
        for source in streams:
            source.discard_ready(prepared)

    def ready_chunks(self) -> tuple[object, ...]:
        with self._condition:
            streams = tuple(self._streams)
        ready: list[object] = []
        for source in streams:
            ready.extend(source.ready_chunks())
        return tuple(ready)

    def has_live_producers(self) -> bool:
        producer = self._producer
        if producer is not None and producer.thread.is_alive():
            return True
        with self._condition:
            streams = tuple(self._streams)
        return any(
            any(handle.thread.is_alive() for handle in source._handles_snapshot())
            for source in streams
        )

    def _produce(self, _worker_token, owner: RouteEffectOwner) -> None:
        next_index = 0
        source_index = 0
        expression = self._request.initial_expression
        previous = ""
        try:
            source_chunks: Iterable[str]
            if self._policy.requires_full_text:
                buffered: list[str | VoiceSegment] = []
                for chunk in self._chunks:
                    if self.cancelled:
                        return
                    value = chunk if isinstance(chunk, VoiceSegment) else str(chunk or "").strip()
                    if value:
                        buffered.append(value)
                if any(isinstance(piece, VoiceSegment) for piece in buffered):
                    source_chunks = tuple(buffered)
                else:
                    combined = speech_text.join_stream_tts_chunks(buffered)
                    source_chunks = (combined,) if combined else ()
            else:
                source_chunks = self._chunks

            for raw_piece in source_chunks:
                if self.cancelled:
                    return
                typed = raw_piece if isinstance(raw_piece, VoiceSegment) else None
                piece, _deduped = (typed.text, False) if typed is not None else dedupe_adjacent_stream_text(previous, str(raw_piece or ""))
                previous = piece.strip() or previous
                if not piece.strip():
                    continue
                segmentation_request = self._segmentation_request(piece, source_index)
                if typed is not None:
                    from dataclasses import replace
                    segmentation_request = replace(segmentation_request, source_metadata=_frozen_mapping(
                        {**segmentation_request.source_metadata, **typed.source_metadata}))
                source_index += 1
                segments_result = owner.run_step(
                    "addon_voice_segments",
                    lambda request=segmentation_request: self._addons.voice_segments(
                        request
                    ),
                )
                if not segments_result.accepted:
                    self._fail(
                        segments_result.failure
                        or RuntimeFailure(
                            "speech_addon_route_stale",
                            "Addon voice segmentation lost route authority.",
                        )
                    )
                    return
                segments = _normalized_segments(segments_result.value, piece)
                if typed is not None:
                    segments = tuple(VoiceSegment(part.text, typed.voice_path, typed.voice_language,
                        _frozen_mapping({**part.source_metadata, **typed.source_metadata})) for part in segments)
                plan = _plan_segments(
                    self._speech_output,
                    segments,
                    self._request,
                    streaming=True,
                    start_index=next_index,
                    initial_expression=expression,
                    preserve_input_chunks=(
                        self._policy.preserve_input_chunks
                        or self._request.preserve_input_chunks
                    ),
                    prepared_sentence_splitter=self._prepared_sentence_splitter,
                )
                if not plan.chunks:
                    continue
                next_index = plan.chunks[-1].index + 1
                expression = plan.terminal_expression
                source = self._speech_output.prepare(
                    plan,
                    self.lease,
                    self._token,
                    route_effect_owner=self._route_owner,
                    generation_order=self._synthesis_order,
                )
                if not self._append(source):
                    source.cancel("speech_stream_cancelled")
                    source.close()
                    return
        except BaseException as exc:
            self._fail(
                RuntimeFailure(
                    "speech_stream_failed",
                    f"Streaming speech preparation failed: {exc}",
                    exc,
                )
            )
        finally:
            with self._condition:
                self._producer_done = True
                self._condition.notify_all()

    def _append(self, source: SpeechOutputStream) -> bool:
        with self._condition:
            while (
                not self._cancelled
                and not self._closed
                and not self._token.cancelled
                and len(self._streams) >= self._max_pending
            ):
                self._condition.wait(0.05)
            if self._cancelled or self._closed or self._token.cancelled:
                return False
            self._streams.append(source)
            self._condition.notify_all()
            return True

    def _segmentation_request(
        self,
        text: str,
        source_index: int,
    ) -> VoiceSegmentationRequest:
        return VoiceSegmentationRequest(
            text=str(text or ""),
            tts_backend=str(self._request.config.values.get("tts_backend", "") or ""),
            streaming=True,
            stream_start=int(source_index) == 0,
            stream_source_index=max(0, int(source_index)),
            source_metadata=_frozen_mapping(self._request.source_metadata),
        )

    def _fail(self, failure: RuntimeFailure) -> None:
        with self._condition:
            if self._failure is None:
                self._failure = failure
            self._producer_done = True
            self._condition.notify_all()

    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())


class NormalSpeechRouteCoordinator:
    """Join typed speech services into one production normal-reply route."""

    def __init__(
        self,
        *,
        speech_output: SpeechOutputService,
        playback: PlaybackService,
        controllers: ControllerSetupRegistry,
        avatar: AvatarService,
        addons: SpeechRouteAddonGateway | None = None,
        prepared_sentence_splitter: text_chunking.PreparedSentenceSplitter | None = None,
        before_speech: Callable[[str], CommandResult] | None = None,
    ) -> None:
        self._before_speech = before_speech
        self._speech_output = speech_output
        self._playback = playback
        self._controllers = controllers
        self._avatar = avatar
        self._addons = addons or PassthroughSpeechRouteAddonGateway()
        self._prepared_sentence_splitter = prepared_sentence_splitter
        self._lock = threading.Lock()
        self._routes: dict[str, _RouteState] = {}

    def speak_complete(
        self,
        text: str,
        request: SpeechRouteRequest,
    ) -> CommandResult[NormalSpeechRoute]:
        return self._open_route(str(text or ""), None, request)

    def speak_stream(
        self,
        chunks: Iterable[str],
        request: SpeechRouteRequest,
    ) -> CommandResult[NormalSpeechRoute]:
        return self._open_route("", chunks, request)

    def interrupt(
        self,
        route: NormalSpeechRoute,
        reason: str = "speech_interrupted",
    ) -> CommandResult[PlaybackReceipt | None]:
        return self.cancel(route, reason)

    def cancel(
        self,
        route: NormalSpeechRoute,
        reason: str = "speech_cancelled",
    ) -> CommandResult[PlaybackReceipt | None]:
        if route._coordinator is not self:
            return _failure(
                "speech_route_unknown",
                "The speech route belongs to another coordinator.",
            )
        with self._lock:
            state = self._routes.get(route.route_id)
        if state is None:
            return CommandResult(True, route.receipt)
        resolved = str(reason or "speech_cancelled")
        stream = state.stream
        if stream is None:
            route._token.cancel(resolved)
            self._cleanup(state)
            return CommandResult(True, route.receipt)
        try:
            # Commit the exact playback receipt before token subscribers expose
            # source.error or block in provider teardown. No owner lock is held.
            cancelled = self._playback.cancel_stream(stream, resolved)
        finally:
            route._token.cancel(resolved)
        if cancelled.accepted:
            if cancelled.value is not None:
                route._set_receipt(cancelled.value)
            return CommandResult(True, cancelled.value)
        stream.cancel(resolved)
        return CommandResult(True, route.receipt)

    def pause(self, route: NormalSpeechRoute) -> CommandResult[None]:
        state = self._route_state(route)
        if isinstance(state, CommandResult):
            return state
        if state.stream is None:
            return _failure(
                "speech_route_not_ready",
                "The speech route is not ready for playback control.",
            )
        return self._playback.pause_stream(state.stream)

    def resume(self, route: NormalSpeechRoute) -> CommandResult[None]:
        state = self._route_state(route)
        if isinstance(state, CommandResult):
            return state
        if state.stream is None:
            return _failure(
                "speech_route_not_ready",
                "The speech route is not ready for playback control.",
            )
        return self._playback.resume_stream(state.stream)

    def playback_retired(self, route: NormalSpeechRoute) -> bool:
        if route._coordinator is not self or not route.done:
            return False
        snapshot = self._playback.snapshot()
        # Cancellation can finish the producer while the serial device is still
        # draining. Playback promotes the current route only after device cleanup.
        # A stopping service is also not proof of retirement (it can detach early).
        return not snapshot.stopping and not any(
            active is not None and active.lease == route.lease
            for active in (snapshot.current, snapshot.next)
        )

    def active_routes(self) -> tuple[NormalSpeechRoute, ...]:
        with self._lock:
            return tuple(state.route for state in self._routes.values())

    def _route_state(
        self,
        route: NormalSpeechRoute,
    ) -> _RouteState | CommandResult[None]:
        if route._coordinator is not self:
            return _failure(
                "speech_route_unknown",
                "The speech route belongs to another coordinator.",
            )
        with self._lock:
            state = self._routes.get(route.route_id)
        if state is None:
            return _failure(
                "speech_route_finished",
                "The speech route is no longer active.",
            )
        return state

    def _open_route(
        self,
        text: str,
        chunks: Iterable[str] | None,
        request: SpeechRouteRequest,
    ) -> CommandResult[NormalSpeechRoute]:
        invalid = self._validate_request(request)
        if invalid is not None:
            return CommandResult(False, failure=invalid)
        if self._before_speech is not None:
            cancelled = self._before_speech("new_speech")
            if not cancelled.accepted:
                return CommandResult(False, failure=cancelled.failure)

        token = CancellationToken()
        route = NormalSpeechRoute(self, request.lease, token)
        cancellation = ControllerCancellationSignal.from_token(token)
        setup_result = self._controllers.begin_latest(request.lease, cancellation)
        if not setup_result.accepted or setup_result.value is None:
            return CommandResult(False, failure=setup_result.failure)
        setup = setup_result.value

        activated = self._controllers.activate(setup, route, cancellation)
        if not activated.accepted or activated.value is None:
            self._controllers.cancel_setup(setup, "speech_route_setup_failed")
            return CommandResult(False, failure=activated.failure)
        registration = activated.value
        transaction = ControllerSetupTransaction(self._controllers, setup, registration)
        playback_owner: PlaybackOwner | None = None
        route_owner: RouteEffectOwner | None = None
        state: _RouteState | None = None
        plan: SpeechPlan | None = None
        try:
            transaction.require_step(self._avatar.begin_reply)
            policy = VoiceSegmentationPolicy()
            source: object
            if chunks is None:
                segment_request = self._segmentation_request(text, request, streaming=False)
                segments = _normalized_segments(
                    transaction.require_step(
                        lambda: self._addons.voice_segments(segment_request)
                    ),
                    text,
                )
                plan = _plan_segments(
                    self._speech_output,
                    segments,
                    request,
                    streaming=False,
                    preserve_input_chunks=request.preserve_input_chunks,
                    prepared_sentence_splitter=self._prepared_sentence_splitter,
                )
                source = self._speech_output.prepare(
                    plan,
                    request.lease,
                    token,
                    start=False,
                )
            else:
                policy_request = self._segmentation_request("", request, streaming=True)
                policy = _normalized_policy(
                    transaction.require_step(
                        lambda: self._addons.voice_stream_policy(policy_request)
                    )
                )
                source = None

            low_priority = request.source_metadata.get('chess_low_priority') is True
            reserved = self._playback.reserve_owner(request.lease, **({'only_if_idle': True} if low_priority else {}))
            if not reserved.accepted or reserved.value is None:
                raise _RouteOpenFailure(
                    reserved.failure
                    or RuntimeFailure(
                        "playback_owner_stale",
                        "The normal speech route could not reserve playback ownership.",
                    )
                )
            playback_owner = reserved.value
            published = transaction.publish()
            if not published.accepted:
                raise _RouteOpenFailure(
                    published.failure
                    or RuntimeFailure(
                        "controller_setup_stale",
                        "The normal speech controller setup could not be published.",
                    )
                )
            route_activation = self._controllers.activate_route(
                registration,
                playback_owner,
            )
            if not route_activation.accepted or route_activation.value is None:
                raise _RouteOpenFailure(
                    route_activation.failure
                    or RuntimeFailure(
                        "route_effect_stale",
                        "The normal speech route could not own playback effects.",
                    )
                )
            route_owner = route_activation.value

            if chunks is not None:
                source = _StreamingSpeechStream(
                    speech_output=self._speech_output,
                    addons=self._addons,
                    chunks=chunks,
                    request=request,
                    policy=policy,
                    token=token,
                    route_owner=route_owner,
                    prepared_sentence_splitter=self._prepared_sentence_splitter,
                )

            assert source is not None
            state = _RouteState(
                route,
                token,
                setup,
                registration,
                playback_owner,
                route_owner,
            )
            observer = _AvatarRouteObserver(self._avatar, state)
            stream = _ObservedRouteStream(source, state, self, self._avatar, request.config)
            state.observer = observer
            state.stream = stream
            with self._lock:
                self._routes[route.route_id] = state

            if isinstance(source, SpeechOutputStream):
                assert plan is not None
                started = self._speech_output.start_preparation(
                    source,
                    plan,
                    route_effect_owner=route_owner,
                )
            else:
                started = source.start()
            if not started.accepted:
                raise _RouteOpenFailure(
                    started.failure
                    or RuntimeFailure(
                        "speech_preparation_start_failed",
                        "Normal speech preparation could not start.",
                    )
                )

            offered = (self._playback.enqueue_if_idle(stream, stream.lease, owner=playback_owner,
                       route_effect_owner=route_owner, observer=observer) if low_priority else
                       self._publish(stream, playback_owner, route_owner, observer))
            if not offered.accepted:
                raise _RouteOpenFailure(
                    offered.failure
                    or RuntimeFailure(
                        "speech_playback_rejected",
                        "Normal speech playback publication was rejected.",
                    )
                )
            return CommandResult(True, route)
        except _RouteOpenFailure as exc:
            failure = exc.failure
        except BaseException as exc:
            failure = RuntimeFailure(
                "speech_route_setup_failed",
                f"Normal speech route setup failed: {exc}",
                exc,
            )

        token.cancel(failure.category)
        if playback_owner is not None:
            self._playback.release_owner(playback_owner)
        if state is not None and state.stream is not None:
            state.stream.cancel(failure.category)
            route._finish(failure=failure)
        else:
            if route_owner is not None:
                route_owner.close()
            transaction.cancel(failure.category)
            self._controllers.retire(registration)
        return CommandResult(False, failure=failure)

    def _publish(
        self,
        stream: _ObservedRouteStream,
        playback_owner: PlaybackOwner,
        route_owner: RouteEffectOwner,
        observer: PlaybackObserver,
    ) -> CommandResult[str]:
        if self._playback.snapshot().current is None:
            return self._playback.enqueue(
                stream,
                stream.lease,
                owner=playback_owner,
                route_effect_owner=route_owner,
                observer=observer,
            )
        return self._playback.replace_next(
            stream,
            stream.lease,
            owner=playback_owner,
            route_effect_owner=route_owner,
            observer=observer,
        )

    def _cleanup(
        self,
        state: _RouteState,
        *,
        failure: RuntimeFailure | None = None,
    ) -> None:
        with state.lock:
            if state.cleaned:
                return
            state.cleaned = True
        self._controllers.retire(state.registration)
        with self._lock:
            if self._routes.get(state.route.route_id) is state:
                self._routes.pop(state.route.route_id, None)
        state.route._finish(failure=failure)

    def _validate_request(self, request: SpeechRouteRequest) -> RuntimeFailure | None:
        lease = request.lease
        if lease.turn_id is None or lease.route_generation is None:
            return RuntimeFailure(
                "speech_route_lease_invalid",
                "Normal speech requires an exact turn and route lease.",
            )
        if not self._playback.lease_is_current(lease):
            return RuntimeFailure(
                "speech_route_stale_lease",
                "The normal speech route lease is stale.",
            )
        return None

    @staticmethod
    def _segmentation_request(
        text: str,
        request: SpeechRouteRequest,
        *,
        streaming: bool,
    ) -> VoiceSegmentationRequest:
        return VoiceSegmentationRequest(
            text=str(text or ""),
            tts_backend=str(request.config.values.get("tts_backend", "") or ""),
            streaming=streaming,
            source_metadata=_frozen_mapping(request.source_metadata),
        )


class _RouteOpenFailure(RuntimeError):
    def __init__(self, failure: RuntimeFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


def _plan_segments(
    speech_output: SpeechOutputService,
    segments: Sequence[VoiceSegment],
    request: SpeechRouteRequest,
    *,
    streaming: bool,
    start_index: int = 0,
    initial_expression: str | None = None,
    preserve_input_chunks: bool = False,
    prepared_sentence_splitter: text_chunking.PreparedSentenceSplitter | None = None,
) -> SpeechPlan:
    chunks = []
    source_text: list[str] = []
    next_index = max(0, int(start_index))
    expression = str(initial_expression or request.initial_expression or "neutral")
    for segment in segments:
        text = str(segment.text or "").strip()
        if not text:
            continue
        metadata = dict(request.source_metadata)
        metadata.update(dict(segment.source_metadata))
        metadata["speech_route_streaming"] = bool(streaming)
        plan = speech_output.plan(
            text,
            request.config,
            start_index=next_index,
            initial_expression=expression,
            preserve_input_chunk=preserve_input_chunks,
            voice_path=str(segment.voice_path or request.voice_path or ""),
            voice_language=str(segment.voice_language or request.voice_language or ""),
            source_metadata=metadata,
            prepared_sentence_splitter=prepared_sentence_splitter,
        )
        chunks.extend(plan.chunks)
        source_text.append(text)
        expression = plan.terminal_expression
        if plan.chunks:
            next_index = plan.chunks[-1].index + 1
    return SpeechPlan(
        source_text="\n".join(source_text),
        chunks=tuple(chunks),
        config=request.config,
        terminal_expression=expression,
    )


def _normalized_segments(
    value: Sequence[VoiceSegment] | None,
    fallback_text: str,
) -> tuple[VoiceSegment, ...]:
    segments = tuple(item for item in tuple(value or ()) if isinstance(item, VoiceSegment))
    if segments:
        return segments
    text = str(fallback_text or "")
    return (VoiceSegment(text),) if text.strip() else ()


def _normalized_policy(value: object) -> VoiceSegmentationPolicy:
    return value if isinstance(value, VoiceSegmentationPolicy) else VoiceSegmentationPolicy()


def _frozen_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return MappingProxyType(dict(value or {}))


def _failure(category: str, message: str) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message))


__all__ = [
    "NormalSpeechRoute",
    "NormalSpeechRouteCoordinator",
    "PassthroughSpeechRouteAddonGateway",
    "SpeechRouteAddonGateway",
    "SpeechRouteRequest",
    "VoiceSegment",
    "VoiceSegmentationPolicy",
    "VoiceSegmentationRequest",
]
