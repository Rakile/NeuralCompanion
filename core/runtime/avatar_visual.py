"""Lease-bound MuseTalk frame, idle, transition, and cleanup coordination."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
import threading
import time
from typing import Protocol

from core.runtime.avatar_assets import MuseTalkAssetStore
from core.musetalk_timing import start_musetalk_timing, trace_musetalk_timing
from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.controllers import RouteEffectOwner
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerHandle, WorkerSupervisor
from core.runtime.playback import spawn_route_worker


LeaseCheck = Callable[[WorkLease], bool]
EffectCommit = Callable[[WorkLease, Callable[[], object]], CommandResult[object]]


class MuseTalkVisualAdapter(Protocol):
    """Finite provider surface required for visible MuseTalk transitions."""

    avatar_provider_id: str
    default_avatar_id: str

    def get_idle_payload(
        self,
        *,
        avatar_id: str | None = None,
    ) -> Mapping[str, object] | None: ...

    def build_idle_payload_from_state(
        self,
        *,
        current_state: Mapping[str, object],
        advance_to_next_frame: bool,
    ) -> Mapping[str, object] | None: ...

    def build_transition_payload(
        self,
        from_avatar_id: str,
        to_avatar_id: str,
    ) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class AvatarVisualCapabilities:
    """Named addon publications used by MuseTalk visual coordination."""

    frame_snapshot: Callable[[], Mapping[str, object]]
    publish_frame: Callable[[Mapping[str, object]], object]
    reset_expression: Callable[[], object] | None = None
    reset_pipeline: Callable[[], object] | None = None
    prime_frame: Callable[[Mapping[str, object]], object] | None = None
    stream_frames: Callable[[Mapping[str, object], object], object] | None = None
    stream_audio_progress: Callable[[Mapping[str, object], object], object] | None = None
    estimate_displayed_frames: Callable[[Mapping[str, object], float | None], int] | None = None
    current_source_index: Callable[[Mapping[str, object], bool], int] | None = None
    preview_stream_enabled: Callable[[], bool] | None = None
    shutdown_requested: Callable[[], bool] | None = None
    cleanup_blocked: Callable[[], bool] | None = None
    fps: Callable[[], int] | None = None
    publish_audio_progress: Callable[[Mapping[str, object]], object] | None = None


@dataclass(frozen=True, slots=True)
class AvatarVisualSnapshot:
    running: bool
    frame: Mapping[str, object]
    idle_stream_key: str
    idle_stream_active: bool


class AvatarVisualCoordinator:
    """Own visible MuseTalk state transitions and every delayed child effect."""

    def __init__(
        self,
        *,
        workers: WorkerSupervisor,
        adapter: Callable[[], MuseTalkVisualAdapter | None],
        lease_is_current: LeaseCheck,
        capabilities: AvatarVisualCapabilities,
        assets: MuseTalkAssetStore | None = None,
        commit_effect: EffectCommit | None = None,
        clock=time.time,
    ) -> None:
        self._workers = workers
        self._adapter = adapter
        self._lease_is_current = lease_is_current
        self._capabilities = capabilities
        self._assets = assets
        self._commit_effect = commit_effect or self._commit_if_current
        self._clock = clock
        self._lock = threading.Lock()
        self._running = False
        self._idle_stream_key = ""
        self._idle_stream_handle: WorkerHandle | None = None
        self._active_stream_handle: WorkerHandle | None = None
        self._speech_lease: WorkLease | None = None
        self._speech_route_owner: RouteEffectOwner | None = None
        self._speech_chunk_id: object = None

    def start(self) -> CommandResult[None]:
        with self._lock:
            self._running = True
        return CommandResult(True)

    def snapshot(self) -> AvatarVisualSnapshot:
        frame = _freeze_mapping(self._capabilities.frame_snapshot())
        with self._lock:
            handle = self._idle_stream_handle
            return AvatarVisualSnapshot(
                running=self._running,
                frame=frame,
                idle_stream_key=self._idle_stream_key,
                idle_stream_active=bool(handle is not None and handle.thread.is_alive()),
            )

    def matches_provider(self, provider_id: str) -> bool:
        adapter = self._adapter()
        actual = str(getattr(adapter, "avatar_provider_id", "") or "").strip().lower()
        return bool(actual and actual == str(provider_id or "").strip().lower())

    def clear(self, lease: WorkLease) -> CommandResult[bool]:
        return self._run_effect("avatar_visual_clear", lease, None, lambda: self._clear(lease))

    def set_idle(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        return self._run_effect(
            "musetalk_idle_state",
            lease,
            route_owner,
            lambda: self._set_idle_admitted(lease, route_owner),
        )

    def set_idle_for_avatar(
        self,
        avatar_id: str,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        target = str(avatar_id or "").strip()
        return self._run_effect(
            "musetalk_avatar_idle_state",
            lease,
            route_owner,
            lambda: self._set_idle_for_avatar_admitted(target, lease, route_owner),
        )

    def transition_to_local_idle(
        self,
        lease: WorkLease,
        *,
        advance_to_next_frame: bool = True,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        return self._run_effect(
            "musetalk_local_idle_transition",
            lease,
            route_owner,
            lambda: self._transition_to_local_idle_admitted(
                lease,
                bool(advance_to_next_frame),
                route_owner,
            ),
        )

    def transition_to_terminal_idle(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
        advance_to_next_frame: bool = True,
    ) -> CommandResult[bool]:
        """Publish route-owned terminal idle that remains after the route closes."""

        return self._run_effect(
            "musetalk_terminal_idle_transition",
            lease,
            route_owner,
            lambda: self._transition_to_local_idle_admitted(
                lease,
                bool(advance_to_next_frame),
                None,
            ),
        )

    def wait_for_chunk_buffer(
        self,
        chunk_result: Mapping[str, object],
        lease: WorkLease,
        *,
        streaming: bool,
        cancellation: CancellationToken,
        route_owner: RouteEffectOwner | None = None,
        on_waiting: Callable[[], object] | None = None,
        timeout_seconds: float = 60.0,
    ) -> CommandResult[bool]:
        """Wait outside route effects until MuseTalk has a safe initial frame buffer."""

        if not self.matches_provider("musetalk") and not getattr(self._adapter(), "supports_frame_buffer", False):
            return CommandResult(True, True)
        if route_owner is not None:
            admitted = route_owner.run_step(
                "musetalk_chunk_buffer_admission",
                lambda: route_owner.lease == lease,
            )
            if not admitted.accepted or not admitted.value:
                return _failure(
                    "avatar_visual_route_stale",
                    "MuseTalk frame buffering no longer owns its exact playback route",
                )
        frame_dir_text = str(chunk_result.get("frame_dir") or "").strip()
        frame_dir = Path(frame_dir_text) if frame_dir_text else None
        ready_event = chunk_result.get("ready_event")
        result_holder = chunk_result.get("result_holder")
        holder = result_holder if isinstance(result_holder, Mapping) else {}
        fps = _positive_int(chunk_result.get("fps"), self._fps())
        minimum = max(10, min(int(fps * 0.5), 16)) if streaming else max(
            24,
            min(int(fps * 2.5), 72),
        )
        minimum = max(minimum, int(chunk_result.get("minimum_buffer_frames", 0) or 0))
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        waiting_notified = False
        while True:
            route_cancelled = bool(
                route_owner is not None and route_owner.cancellation.cancelled
            )
            lease_stale = bool(
                route_owner is None and not self._lease_is_current(lease)
            )
            if cancellation.cancelled or route_cancelled or lease_stale:
                return _failure(
                    "avatar_visual_chunk_cancelled",
                    "MuseTalk frame buffering was cancelled",
                )
            if bool(holder.get("cancelled", False)):
                return _failure(
                    "avatar_visual_chunk_cancelled",
                    "MuseTalk cancelled the rendered speech chunk",
                )
            if chunk_result.get("ok") is False or holder.get("ok") is False or holder.get("error"):
                return _failure("avatar_visual_chunk_failed", "MuseTalk failed to render the speech chunk")
            required_buffer = chunk_result.get("required_buffer_frames")
            if callable(required_buffer):
                # The parent owns its dynamic initial lead, for PNG and RAM
                # transports alike. Recompute after each producer update.
                minimum = max(1, int(chunk_result.get("minimum_buffer_frames", 0) or 0),
                              int(required_buffer(streaming)))
            if chunk_result.get("frame_transport") == "shared_rgb":
                buffer = chunk_result.get("frame_buffer")
                required = min(minimum, max(1, int(chunk_result.get("frame_count", minimum))))
                if buffer is not None and required > buffer.capacity:
                    return _failure("avatar_visual_buffer_capacity",
                                    "Required initial avatar frames exceed the RAM buffer capacity")
                available = buffer.available_count if buffer is not None else 0
            else:
                available = len(_png_frame_paths(frame_dir))
            ready = bool(hasattr(ready_event, "is_set") and ready_event.is_set())
            if available >= minimum or (ready and available):
                return CommandResult(True, True)
            if ready:
                return _failure(
                    "avatar_visual_chunk_empty",
                    "MuseTalk completed without producing lip-sync frames",
                )
            if not waiting_notified:
                waiting_notified = True
                if on_waiting is not None:
                    try:
                        on_waiting()
                    except BaseException:
                        pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _failure(
                    "avatar_visual_chunk_timeout",
                    "MuseTalk did not produce an initial lip-sync frame buffer in time",
                )
            cancellation.wait(min(0.05, remaining))

    def begin_chunk_playback(
        self,
        chunk_result: Mapping[str, object],
        lease: WorkLease,
        *,
        text: str,
        audio_duration_seconds: float,
        route_owner: RouteEffectOwner | None,
        audio_start_pending: bool = False,
        audio_clock_sample=None,
        audio_chunk_index: int | None = None,
        continuous: bool = False,
    ) -> CommandResult[bool]:
        """Publish and stream one rendered MuseTalk chunk at audio admission."""

        def publish() -> bool:
            timing_started = start_musetalk_timing()
            holder_value = chunk_result.get("result_holder")
            holder = dict(holder_value) if isinstance(holder_value, Mapping) else {}
            if bool(holder.get("cancelled", False)):
                return False
            merged = dict(chunk_result)
            merged.update(holder)
            frame_dir_text = str(merged.get("frame_dir") or "").strip()
            frame_dir = Path(frame_dir_text) if frame_dir_text else None
            frame_paths = _png_frame_paths(frame_dir)
            trim = max(0, _integer(merged.get("trim_start_frames"), 0))
            if trim and frame_paths:
                frame_paths = frame_paths[min(trim, len(frame_paths) - 1):]
            if not frame_paths:
                return False
            fps = _positive_int(merged.get("fps"), self._fps())
            rendered_count = max(
                len(frame_paths),
                max(0, _integer(merged.get("frame_count"), 0) - trim),
                max(
                    0,
                    int(round(max(0.0, float(audio_duration_seconds)) * fps)),
                ),
            )
            started_at = float(self._clock())
            duration_seconds = max(
                max(0.0, float(audio_duration_seconds)),
                max(rendered_count - 1, 0) / max(fps, 1),
            )
            if continuous:
                duration_seconds = max(0.0, float(audio_duration_seconds))
            payload = {
                "frame_paths": frame_paths,
                "frame_dir": frame_dir_text,
                "fps": fps,
                "sync_time": started_at,
                "audio_started_at": started_at,
                "audio_start_pending": bool(audio_start_pending),
                "duration_seconds": duration_seconds,
                "expected_frame_count": rendered_count,
                "trim_start_frames": trim,
                "chunk_id": merged.get("chunk_id"),
                "text": str(text or ""),
                "status": "ready",
                "loop": False,
                "start_index": _integer(merged.get("start_index"), 0),
                "frame_count": rendered_count,
                "avatar_id": merged.get("avatar_id"),
                "sequence_index": _integer(merged.get("sequence_index"), 0),
            }
            if merged.get("progressive_audio", False):
                payload["progressive_audio"] = True
            if continuous:
                payload["audio_chunk_index"] = audio_chunk_index
                if audio_clock_sample is not None:
                    payload.update(_audio_progress_fields(audio_clock_sample))
                if audio_start_pending:
                    payload.update(_pending_frame_fields(self._frame_snapshot(), payload, started_at))
            trace_musetalk_timing("handoff_begin", timing_started, chunk=payload["chunk_id"],
                                 available=len(frame_paths), expected=rendered_count)
            self._retire_idle_stream("musetalk_speech_started")
            trace_musetalk_timing("idle_retired", timing_started, chunk=payload["chunk_id"])
            self._retire_active_stream("musetalk_speech_replaced")
            trace_musetalk_timing("speech_retired", timing_started, chunk=payload["chunk_id"])
            self._reset_expression()
            with self._lock:
                self._speech_lease = lease
                self._speech_route_owner = route_owner
                self._speech_chunk_id = payload["chunk_id"]
            self._publish_frame(payload)
            trace_musetalk_timing("state_published", timing_started, chunk=payload["chunk_id"])
            self._prime(payload)
            trace_musetalk_timing("frame_primed", timing_started, chunk=payload["chunk_id"])
            callback = self._capabilities.stream_frames
            enabled = self._capabilities.preview_stream_enabled
            if (
                route_owner is None
                or callback is None
                or (enabled is not None and not enabled())
                or self._shutdown_requested()
            ):
                return True
            frozen = _freeze_mapping(payload)
            spawned = spawn_route_worker(
                self._workers,
                route_owner,
                name=f"nc-musetalk-speech-{merged.get('chunk_id')}",
                lease=lease,
                target=lambda token, _owner: callback(frozen, token),
            )
            if spawned.accepted and spawned.value is not None:
                with self._lock:
                    self._active_stream_handle = spawned.value
            self._schedule_cleanup_admitted(
                lease,
                route_owner,
                (frame_dir_text,) if frame_dir_text else (),
                max_keep=64,
                force=False,
            )
            return bool(spawned.accepted)

        return self._run_effect(
            "musetalk_speech_chunk_playback",
            lease,
            route_owner,
            publish,
        )

    def update_audio_progress(self, lease, index, sample, *, route_owner=None):
        """Publish numeric clock state under the same exact visual route authority."""
        def publish():
            from core.continuous_audio import continuous_media_seconds
            with self._lock:
                if self._speech_lease != lease or self._speech_route_owner is not route_owner:
                    return False
                chunk_id = self._speech_chunk_id
            fields = _audio_progress_fields(sample)
            if sample.key != index or continuous_media_seconds(fields, sample.sampled_monotonic) is None:
                return False
            callback = self._capabilities.publish_audio_progress
            if callback is not None:
                return bool(callback(dict(fields, chunk_id=chunk_id, audio_chunk_index=index,
                                          audio_start_pending=False)))
            current = self._frame_snapshot()
            if (sample.key != index or current.get("audio_chunk_index") != index
                    or current.get("chunk_id") != chunk_id or current.get("loop", False)
                    or current.get("status") != "ready"
                    or continuous_media_seconds(fields, sample.sampled_monotonic) is None
                    or sample.sampled_monotonic < current.get("audio_clock_monotonic", 0.)
                    or sample.media_seconds < current.get("audio_media_seconds", 0.)):
                return False
            current.update(fields)
            current["audio_start_pending"] = False
            for key in ("audio_pending_frame_path", "audio_pending_frame_index", "audio_pending_source_index"):
                current.pop(key, None)
            self._publish_frame(current)
            return True
        return self._run_effect("musetalk_audio_progress", lease, route_owner, publish)

    def synchronize_audio_start(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        """Start the visible speech clock at device start without restarting it."""

        def synchronize() -> bool:
            with self._lock:
                if (
                    self._speech_lease != lease
                    or self._speech_route_owner is not route_owner
                ):
                    return False
                chunk_id = self._speech_chunk_id
            current = self._frame_snapshot()
            if (
                current.get("chunk_id") != chunk_id
                or str(current.get("status") or "").strip().lower() != "ready"
                or bool(current.get("loop", False))
                or not bool(current.get("audio_start_pending", False))
            ):
                return False
            started_at = float(self._clock())
            current["sync_time"] = started_at
            current["audio_started_at"] = started_at
            current["audio_start_pending"] = False
            self._publish_frame(current)
            return True

        return self._run_effect(
            "musetalk_audio_start_sync",
            lease,
            route_owner,
            synchronize,
        )

    def play_transition(
        self,
        from_avatar_id: str,
        to_avatar_id: str,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[float]:
        if not self._valid_route_owner(lease, route_owner):
            return _failure(
                "avatar_visual_route_stale",
                "MuseTalk transition no longer owns its exact playback route",
            )

        def publish_transition() -> float:
            adapter = self._adapter()
            builder = getattr(adapter, "build_transition_payload", None)
            if not self.matches_provider("musetalk") or not callable(builder):
                return 0.0
            transition = builder(str(from_avatar_id or ""), str(to_avatar_id or ""))
            if not transition:
                return 0.0
            payload = dict(transition.get("payload") or {})
            duration = max(
                0.0,
                float(
                    transition.get(
                        "duration_seconds",
                        payload.get("duration_seconds", 0.0),
                    )
                    or 0.0
                ),
            )
            transition_id = payload.get("chunk_id")
            self._reset_expression()
            self._publish_frame(payload)
            self._prime(payload)
            self._retire_idle_stream("musetalk_transition")

            def finish(token, child_owner) -> None:
                if token.wait(duration) or self._shutdown_requested():
                    return
                current = self._frame_snapshot()
                if current.get("chunk_id") != transition_id:
                    return
                self._set_idle_for_avatar_admitted(
                    str(to_avatar_id or ""),
                    lease,
                    child_owner,
                )

            spawned = spawn_route_worker(
                self._workers,
                route_owner,
                name=f"musetalk-transition-{transition_id}",
                lease=lease,
                target=finish,
            )
            return duration if spawned.accepted else 0.0

        result = route_owner.run_step("musetalk_avatar_transition", publish_transition)
        return _coerce_result(result, "avatar_visual_transition_failed")

    def maybe_transition_to_default(
        self,
        current_avatar_id: str,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[bool]:
        adapter = self._adapter()
        default_id = str(getattr(adapter, "default_avatar_id", "") or "").strip()
        current_id = str(current_avatar_id or "").strip()
        if not self.matches_provider("musetalk") or not current_id or current_id == default_id:
            return CommandResult(True, False)
        transitioned = self.play_transition(
            current_id,
            default_id,
            lease,
            route_owner=route_owner,
        )
        if not transitioned.accepted:
            return CommandResult(False, failure=transitioned.failure)
        return CommandResult(True, bool(transitioned.value and transitioned.value > 0.0))

    def loop_current(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[bool]:
        def publish() -> bool:
            current = self._frame_snapshot()
            frame_paths = tuple(current.get("frame_paths") or ())
            frame_dir = str(current.get("frame_dir") or "").strip()
            if not frame_paths and not frame_dir:
                return self._clear(lease)
            payload = dict(current)
            payload.update(
                {
                    "frame_paths": list(frame_paths),
                    "frame_dir": frame_dir,
                    "fps": _positive_int(current.get("fps"), self._fps()),
                    "sync_time": float(self._clock()),
                    "duration_seconds": 0.0,
                    "chunk_id": current.get("chunk_id", "interrupted"),
                    "text": "",
                    "status": "idle",
                    "loop": True,
                    "audio_start_pending": False,
                    "start_index": _integer(current.get("start_index"), 0),
                    "frame_count": _integer(
                        current.get("frame_count"), len(frame_paths)
                    ),
                }
            )
            self._reset_expression()
            self._publish_frame(payload)
            self._prime(payload)
            stream_started = self._start_idle_stream(payload, lease, route_owner)
            cleanup_started = self._schedule_cleanup_admitted(
                lease,
                route_owner,
                (frame_dir,) if frame_dir else (),
                max_keep=64,
                force=False,
            )
            return bool(stream_started or cleanup_started)

        return self._run_effect(
            "musetalk_loop_current_state",
            lease,
            route_owner,
            publish,
        )

    def freeze_current(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[bool]:
        def publish() -> bool:
            current = self._frame_snapshot()
            frame_paths = [str(path) for path in current.get("frame_paths") or ()]
            if not frame_paths:
                frame_dir = Path(str(current.get("frame_dir") or ""))
                if frame_dir.is_dir():
                    frame_paths = [
                        str(path)
                        for path in sorted(frame_dir.glob("*.png"))
                        if path.is_file()
                    ]
            if not frame_paths:
                return self._clear(lease)
            fps = _positive_int(current.get("fps"), self._fps())
            elapsed = max(0.0, float(self._clock()) - float(current.get("sync_time") or 0.0))
            from core.continuous_audio import continuous_media_seconds
            media = None if current.get("loop", False) else continuous_media_seconds(current, time.monotonic())
            from core.continuous_audio import continuous_pending_frame
            held = continuous_pending_frame(current)
            if held is not None:
                frame_paths, elapsed = [held[0]], 0.0
            if held is None and media is not None:
                elapsed = media
                directory = str(current.get("frame_dir") or "")
                scanned = _png_frame_paths(Path(directory)) if directory else []
                if scanned:
                    trim = max(0, _integer(current.get("trim_start_frames"), 0))
                    frame_paths = scanned[min(trim, len(scanned) - 1):]
            frame_index = min(int(elapsed * max(fps, 1)), len(frame_paths) - 1)
            payload = dict(current)
            payload.update(
                {
                    "frame_paths": [frame_paths[frame_index]],
                    "frame_dir": "",
                    "fps": fps,
                    "sync_time": float(self._clock()),
                    "duration_seconds": 0.0,
                    "chunk_id": current.get("chunk_id", "interrupted"),
                    "text": "",
                    "status": "idle",
                    "loop": True,
                    "audio_start_pending": False,
                    "start_index": _integer(current.get("start_index"), 0)
                    + frame_index if held is None else held[2],
                    "frame_count": 1,
                }
            )
            self._reset_expression()
            self._publish_frame(payload)
            self._prime(payload)
            stream_started = self._start_idle_stream(payload, lease, route_owner)
            frame_dir_text = str(current.get("frame_dir") or "").strip()
            cleanup_started = bool(
                frame_dir_text
                and self._schedule_cleanup_admitted(
                    lease,
                    route_owner,
                    (frame_dir_text,),
                    max_keep=64,
                    force=False,
                )
            )
            return bool(stream_started or cleanup_started)

        return self._run_effect(
            "musetalk_freeze_current_frame",
            lease,
            route_owner,
            publish,
        )

    def transition_after_interrupt(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
        delay_seconds: float = 0.35,
    ) -> CommandResult[bool]:
        if not self._valid_route_owner(lease, route_owner):
            return _failure(
                "avatar_visual_route_stale",
                "Delayed MuseTalk idle no longer owns its exact playback route",
            )

        def delayed(token, child_owner) -> None:
            if token.wait(max(0.0, float(delay_seconds))) or self._shutdown_requested():
                return
            self._transition_to_local_idle_admitted(lease, True, child_owner)

        spawned = spawn_route_worker(
            self._workers,
            route_owner,
            name="musetalk-interrupt-idle",
            lease=lease,
            target=delayed,
        )
        if not spawned.accepted:
            return CommandResult(False, failure=spawned.failure)
        return CommandResult(True, True)

    def stop_idle_stream(self, lease: WorkLease) -> CommandResult[bool]:
        if not self._lease_is_current(lease):
            return _failure(
                "avatar_visual_stale_lease",
                "MuseTalk idle stream lease is stale",
            )
        return CommandResult(True, self._retire_idle_stream("musetalk_idle_stream_stop"))

    def schedule_cleanup(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner | None = None,
        keep_frame_dirs: Sequence[str | Path] = (),
        max_keep: int = 64,
        force: bool = False,
    ) -> CommandResult[bool]:
        return self._run_effect(
            "musetalk_runtime_cleanup_schedule",
            lease,
            route_owner,
            lambda: self._schedule_cleanup_admitted(
                lease,
                route_owner,
                keep_frame_dirs,
                max_keep=max_keep,
                force=force,
            ),
        )

    def prime_frame(self, state: Mapping[str, object]) -> object:
        return self._prime(state)

    def stream_frames(self, state: Mapping[str, object], stop_signal: object) -> object:
        callback = self._capabilities.stream_frames
        return callback(_freeze_mapping(state), stop_signal) if callback is not None else None

    def stream_audio_progress(
        self,
        state: Mapping[str, object],
        stop_signal: object,
    ) -> object:
        callback = self._capabilities.stream_audio_progress
        return callback(_freeze_mapping(state), stop_signal) if callback is not None else None

    def estimate_displayed_frames(
        self,
        state: Mapping[str, object],
        now: float | None = None,
    ) -> int:
        callback = self._capabilities.estimate_displayed_frames
        return int(callback(_freeze_mapping(state), now)) if callback is not None else 0

    def current_source_index(
        self,
        state: Mapping[str, object] | None = None,
        *,
        advance_to_next_frame: bool = False,
    ) -> int:
        payload = self._frame_snapshot() if state is None else dict(state)
        callback = self._capabilities.current_source_index
        if callback is not None:
            return int(callback(_freeze_mapping(payload), bool(advance_to_next_frame)))
        return _integer(payload.get("start_index"), 0)

    def stop(self) -> CommandResult[None]:
        with self._lock:
            self._running = False
        try:
            self._clear_visible_state("avatar_visual_stop")
        except BaseException as exc:
            return _failure(
                "avatar_visual_stop_failed",
                f"Could not clear the avatar visual runtime: {exc}",
                exc,
            )
        return CommandResult(True)

    def _set_idle_admitted(
        self,
        lease: WorkLease,
        route_owner: RouteEffectOwner | None,
    ) -> bool:
        adapter = self._adapter()
        getter = getattr(adapter, "get_idle_payload", None)
        if not self.matches_provider("musetalk") or not callable(getter):
            return self._clear(lease)
        payload = getter()
        if not payload:
            return self._clear(lease)
        return self._publish_idle(dict(payload), lease, route_owner)

    def _set_idle_for_avatar_admitted(
        self,
        avatar_id: str,
        lease: WorkLease,
        route_owner: RouteEffectOwner | None,
    ) -> bool:
        adapter = self._adapter()
        getter = getattr(adapter, "get_idle_payload", None)
        if not self.matches_provider("musetalk") or not callable(getter):
            return self._clear(lease)
        target = str(avatar_id or "").strip() or str(
            getattr(adapter, "default_avatar_id", "") or ""
        ).strip()
        current = self._frame_snapshot()
        if (
            str(current.get("status") or "").strip().lower() == "idle"
            and str(current.get("avatar_id") or "").strip() == target
            and bool(current.get("frame_paths"))
        ):
            self._start_idle_stream(current, lease, route_owner)
            return True
        payload = getter(avatar_id=target)
        if not payload:
            return self._clear(lease)
        return self._publish_idle(dict(payload), lease, route_owner)

    def _transition_to_local_idle_admitted(
        self,
        lease: WorkLease,
        advance: bool,
        route_owner: RouteEffectOwner | None,
    ) -> bool:
        adapter = self._adapter()
        builder = getattr(adapter, "build_idle_payload_from_state", None)
        payload = None
        if self.matches_provider("musetalk") and callable(builder):
            payload = builder(
                current_state=self._frame_snapshot(),
                advance_to_next_frame=advance,
            )
        if payload:
            return self._publish_idle(dict(payload), lease, route_owner)
        return self._set_idle_admitted(lease, route_owner)

    def _publish_idle(
        self,
        payload: Mapping[str, object],
        lease: WorkLease,
        route_owner: RouteEffectOwner | None,
    ) -> bool:
        payload = dict(payload)
        payload["audio_start_pending"] = False
        self._retire_active_stream("musetalk_idle_started")
        self._reset_expression()
        self._publish_frame(payload)
        self._prime(payload)
        self._start_idle_stream(payload, lease, route_owner)
        if route_owner is not None:
            self._schedule_cleanup_admitted(
                lease,
                route_owner,
                (),
                max_keep=64,
                force=False,
            )
        return True

    def _clear(self, lease: WorkLease) -> bool:
        self._clear_visible_state("avatar_visual_clear")
        return self._lease_is_current(lease)

    def _clear_visible_state(self, reason: str) -> None:
        self._retire_idle_stream(reason)
        self._retire_active_stream(reason)
        self._reset_expression()
        callback = self._capabilities.reset_pipeline
        if callback is not None:
            callback()
        self._publish_frame(
            {
                "frame_paths": [],
                "frame_dir": "",
                "fps": self._fps(),
                "sync_time": 0.0,
                "duration_seconds": 0.0,
                "expected_frame_count": 0,
                "trim_start_frames": 0,
                "chunk_id": None,
                "text": "",
                "status": "idle",
                "loop": False,
                "start_index": 0,
                "avatar_id": None,
            }
        )

    def _start_idle_stream(
        self,
        state: Mapping[str, object],
        lease: WorkLease,
        route_owner: RouteEffectOwner | None,
    ) -> bool:
        callback = self._capabilities.stream_frames
        enabled = self._capabilities.preview_stream_enabled
        if (
            callback is None
            or (enabled is not None and not enabled())
            or not bool(state.get("loop", False))
            or (
                not bool(state.get("frame_paths"))
                and not str(state.get("frame_dir") or "").strip()
            )
            or self._shutdown_requested()
        ):
            self._retire_idle_stream("musetalk_idle_stream_disabled")
            return False
        key = _idle_stream_key(state)
        with self._lock:
            current = self._idle_stream_handle
            if (
                self._idle_stream_key == key
                and current is not None
                and current.thread.is_alive()
            ):
                return True
        self._retire_idle_stream("musetalk_idle_stream_replace")
        frozen_state = _freeze_mapping(state)
        if route_owner is not None:
            spawned = spawn_route_worker(
                self._workers,
                route_owner,
                name="nc-ua-musetalk-idle-stream",
                lease=lease,
                target=lambda token, _owner: callback(frozen_state, token),
            )
            if not spawned.accepted or spawned.value is None:
                return False
            handle = spawned.value
        else:
            try:
                handle = self._workers.spawn(
                    name="nc-ua-musetalk-idle-stream",
                    lease=lease,
                    target=lambda token: callback(frozen_state, token),
                    identity=("musetalk-idle", lease),
                )
            except BaseException:
                return False
        with self._lock:
            if not self._running:
                displaced = True
            else:
                displaced = False
                self._idle_stream_key = key
                self._idle_stream_handle = handle
        if displaced:
            self._workers.cancel_handles((handle,), "avatar_visual_stopped")
            self._workers.join_handles((handle,))
            return False
        return True

    def _schedule_cleanup_admitted(
        self,
        lease: WorkLease,
        route_owner: RouteEffectOwner | None,
        keep_frame_dirs: Sequence[str | Path],
        *,
        max_keep: int,
        force: bool,
    ) -> bool:
        if self._assets is None:
            return False
        cleanup_blocked = self._capabilities.cleanup_blocked
        if not force and cleanup_blocked is not None and cleanup_blocked():
            return False
        keep = tuple(keep_frame_dirs)

        def cleanup(_token: CancellationToken, _owner=None) -> object:
            return self._assets.cleanup(keep, max_keep=max_keep, force=force)

        if route_owner is not None:
            spawned = spawn_route_worker(
                self._workers,
                route_owner,
                name="musetalk-runtime-cleanup",
                lease=lease,
                target=cleanup,
            )
            return bool(spawned.accepted)

        def session_cleanup(token: CancellationToken) -> None:
            if token.cancelled:
                return
            self._commit_effect(
                lease,
                lambda: self._assets.cleanup(
                    keep,
                    max_keep=max_keep,
                    force=force,
                ),
            )

        try:
            self._workers.spawn(
                name="musetalk-runtime-cleanup",
                lease=lease,
                target=session_cleanup,
                identity=("musetalk-cleanup", lease),
            )
        except BaseException:
            return False
        return True

    def _run_effect(
        self,
        purpose: str,
        lease: WorkLease,
        route_owner: RouteEffectOwner | None,
        effect: Callable[[], bool],
    ) -> CommandResult[bool]:
        with self._lock:
            running = self._running
        if not running:
            return _failure("avatar_visual_stopped", "Avatar visual runtime is stopped")
        if route_owner is not None:
            if not self._valid_route_owner(lease, route_owner):
                return _failure(
                    "avatar_visual_route_stale",
                    "Avatar visual effect no longer owns its exact playback route",
                )
            result = route_owner.run_step(purpose, effect)
            return _coerce_result(result, "avatar_visual_effect_failed")
        try:
            result = self._commit_effect(lease, effect)
        except BaseException as exc:
            return _failure("avatar_visual_effect_failed", str(exc), exc)
        return _coerce_result(result, "avatar_visual_effect_failed")

    def _valid_route_owner(self, lease: WorkLease, owner: object) -> bool:
        return bool(
            isinstance(owner, RouteEffectOwner)
            and owner.lease == lease
        )

    def _retire_idle_stream(self, reason: str) -> bool:
        with self._lock:
            handle = self._idle_stream_handle
            self._idle_stream_handle = None
            self._idle_stream_key = ""
        if handle is None:
            return False
        self._workers.cancel_handles((handle,), str(reason or "musetalk_idle_stream_stop"))
        if handle.thread is not threading.current_thread():
            self._workers.join_handles((handle,))
        return True

    def _retire_active_stream(self, reason: str) -> bool:
        with self._lock:
            handle = self._active_stream_handle
            self._active_stream_handle = None
        if handle is None:
            return False
        self._workers.cancel_handles((handle,), str(reason or "musetalk_speech_stop"))
        if handle.thread is not threading.current_thread():
            self._workers.join_handles((handle,))
        return True

    def _frame_snapshot(self) -> dict[str, object]:
        return deepcopy(dict(self._capabilities.frame_snapshot() or {}))

    def _publish_frame(self, state: Mapping[str, object]) -> None:
        self._capabilities.publish_frame(deepcopy(dict(state or {})))

    def _prime(self, state: Mapping[str, object]) -> object:
        callback = self._capabilities.prime_frame
        return callback(_freeze_mapping(state)) if callback is not None else None

    def _reset_expression(self) -> None:
        callback = self._capabilities.reset_expression
        if callback is not None:
            callback()

    def _fps(self) -> int:
        callback = self._capabilities.fps
        return _positive_int(callback() if callback is not None else 24, 24)

    def _shutdown_requested(self) -> bool:
        callback = self._capabilities.shutdown_requested
        return bool(callback is not None and callback())

    def _commit_if_current(
        self,
        lease: WorkLease,
        effect: Callable[[], object],
    ) -> CommandResult[object]:
        if not self._lease_is_current(lease):
            return _failure(
                "avatar_visual_stale_lease",
                "Avatar visual effect lease is stale",
            )
        return CommandResult(True, effect())


def _idle_stream_key(state: Mapping[str, object]) -> str:
    frame_paths = tuple(state.get("frame_paths") or ())
    return "|".join(
        (
            str(state.get("chunk_id") or ""),
            str(state.get("sync_time") or ""),
            str(state.get("frame_dir") or ""),
            str(len(frame_paths)),
            str(state.get("start_index") or 0),
            str(state.get("avatar_id") or ""),
        )
    )


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return MappingProxyType(deepcopy(dict(value or {})))


def _png_frame_paths(frame_dir: Path | None) -> list[str]:
    if frame_dir is None or not frame_dir.is_dir():
        return []
    return [
        str(path)
        for path in sorted(frame_dir.glob("*.png"))
        if path.is_file()
    ]


def _pending_frame_fields(previous, current, now):
    from core.continuous_audio import continuous_media_seconds, continuous_pending_frame
    paths = list(previous.get("frame_paths") or ())
    held = continuous_pending_frame(previous)
    if previous.get("avatar_id") != current.get("avatar_id") or not paths:
        held = (current["frame_paths"][0], 0, current["start_index"])
    elif held is None:
        media = None if previous.get("loop", False) else continuous_media_seconds(previous, time.monotonic())
        if media is not None and previous.get("frame_dir"):
            scanned = _png_frame_paths(Path(str(previous["frame_dir"])))
            if scanned:
                trim = max(0, _integer(previous.get("trim_start_frames"), 0))
                paths = scanned[min(trim, len(scanned) - 1):]
        elapsed = max(0., now - float(previous.get("sync_time") or now)) if media is None else media
        duration = float(previous.get("duration_seconds") or 0.)
        if media is None and not previous.get("loop", False) and duration > 0:
            expected = max(len(paths), _integer(previous.get("expected_frame_count"), 0))
            index = int(min(elapsed / duration, 1.) * max(expected - 1, 1))
        else:
            index = int(elapsed * _positive_int(previous.get("fps"), 24))
        index = index % len(paths) if previous.get("loop", False) else min(index, len(paths) - 1)
        sources = previous.get("source_indices") or ()
        source = sources[index] if index < len(sources) else _integer(previous.get("start_index"), 0) + index
        held = (paths[index], index, source)
    return dict(audio_pending_frame_path=held[0], audio_pending_frame_index=held[1],
                audio_pending_source_index=held[2])


def _audio_progress_fields(sample):
    return dict(audio_media_seconds=sample.media_seconds,
                audio_clock_monotonic=sample.sampled_monotonic,
                audio_scheduled_through_seconds=sample.scheduled_through_seconds,
                audio_clock_running=sample.running)


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _positive_int(value: object, default: int) -> int:
    return max(1, _integer(value, default))


def _coerce_result(result: CommandResult, category: str) -> CommandResult:
    if result.accepted:
        return CommandResult(True, result.value)
    return CommandResult(
        False,
        failure=result.failure
        or RuntimeFailure(category, "Avatar visual effect was rejected"),
    )


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = [
    "AvatarVisualCapabilities",
    "AvatarVisualCoordinator",
    "AvatarVisualSnapshot",
    "MuseTalkVisualAdapter",
]
