"""Concrete production ownership for avatar construction and lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import threading
from typing import Any, Protocol

from core import avatar_runtime, avatar_runtime_context
from core.runtime.avatar import AvatarService
from core.runtime.body_profile import BodyProfileService, BodyProfileSnapshot
from core.runtime.config import RuntimeConfigService
from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.lifecycle import WorkerSupervisor


class ProductionAvatarRuntimeActions(Protocol):
    """Host actions required while constructing production avatar adapters."""

    def invalidate_available_emotion_names(self) -> None: ...

    def log_memory_checkpoint(self, *args: object, **kwargs: object) -> None: ...

    def record_reply_metric(self, *args: object, **kwargs: object) -> None: ...


class ProductionAvatarPreviewState(Protocol):
    """Finite Scenic/MuseTalk preview publication surface."""

    def set_current_musetalk_frame_data(self, payload: dict[str, Any]) -> None: ...

    def write_musetalk_preview_frame(self, payload: dict[str, Any]) -> None: ...


class AvatarAddonCapabilityGateway(Protocol):
    """Existing targeted addon-capability boundary used for legacy fallback."""

    def invoke_addon_capability(
        self,
        addon_id: str,
        capability: str,
        payload: dict[str, Any] | None = None,
    ) -> object: ...


class ProductionAvatarOwner:
    """Own selected avatar creation, lifecycle, and editable body state.

    Construction receives finite collaborators and snapshots all runtime config.
    Mutable body mirrors exist only to support the established adapter contracts;
    ``BodyProfileService`` remains authoritative for mutations and projections.
    """

    __slots__ = (
        "_actions",
        "_active_adapter",
        "_addon_gateway",
        "_avatar",
        "_avatar_profile",
        "_body",
        "_config",
        "_current_body_state",
        "_hand_calibration",
        "_hand_debug",
        "_lock",
        "_logger",
        "_playback_stop_requested",
        "_preview_state",
        "_stop_requested",
        "_worker_supervisor",
        "_work_lease_source",
    )

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        avatar: AvatarService,
        body: BodyProfileService,
        runtime_actions: ProductionAvatarRuntimeActions,
        stop_requested: avatar_runtime_context.StopSignal,
        playback_stop_requested: avatar_runtime_context.StopSignal,
        preview_state: ProductionAvatarPreviewState,
        hand_debug: Mapping[str, Any],
        worker_supervisor: WorkerSupervisor | None = None,
        work_lease_source: avatar_runtime_context.WorkLeaseSource | None = None,
        addon_gateway: AvatarAddonCapabilityGateway | None = None,
        logger: Callable[[str], None] = print,
    ) -> None:
        self._lock = threading.RLock()
        self._config = config
        self._avatar = avatar
        self._body = body
        self._actions = runtime_actions
        self._stop_requested = stop_requested
        self._playback_stop_requested = playback_stop_requested
        self._preview_state = preview_state
        self._hand_debug = _mutable_mapping(hand_debug)
        self._worker_supervisor = worker_supervisor
        self._work_lease_source = work_lease_source
        self._addon_gateway = addon_gateway
        self._logger = logger
        self._active_adapter: avatar_runtime.AvatarAdapter | None = None
        self._avatar_profile: dict[str, Any] = {}
        self._current_body_state: dict[str, Any] = {}
        self._hand_calibration: dict[str, Any] = {}
        self._sync_body_mirrors(self._body.snapshot())

    def selected_provider_id(self) -> str:
        return avatar_runtime.normalize_provider_id(
            str(self._config.get("avatar_mode", "vseeface") or ""),
            fallback="vseeface",
        )

    def provider_catalog(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(provider.to_summary() for provider in avatar_runtime.list_providers())

    def select_provider(self, provider_id: str) -> str:
        selected = avatar_runtime.normalize_provider_id(provider_id, fallback="vseeface")
        self._config.update("avatar_mode", selected)
        return selected

    def construction_inputs(self) -> avatar_runtime_context.AvatarConstructionInputs:
        """Build provider-specific inputs from owner-held finite collaborators."""

        with self._lock:
            lease_factory = (
                self._work_lease_source.current
                if self._work_lease_source is not None
                else None
            )
            return avatar_runtime_context.build_avatar_construction_inputs(
                runtime_config=self._config.to_dict(),
                avatar_profile=self._avatar_profile,
                current_body_state=self._current_body_state,
                edit_emotion_getter=self._edit_emotion,
                force_edit_mode_getter=self._force_edit_mode,
                hand_debug=self._hand_debug,
                hand_calibration=self._hand_calibration,
                update_body_profile_fn=self.update_body_profile,
                update_hand_calibration_fn=self.update_body_hand_calibration,
                invalidate_available_emotion_names_fn=(
                    self._actions.invalidate_available_emotion_names
                ),
                avatar_preview_state_module=self._preview_state,
                log_memory_checkpoint_fn=self._actions.log_memory_checkpoint,
                stop_flag_event=self._stop_requested,
                stop_playback_event=self._playback_stop_requested,
                dry_run_module=self._actions,
                worker_supervisor=self._worker_supervisor,
                worker_lease_factory=lease_factory,
            )

    def create_selected_adapter(self) -> avatar_runtime.AvatarAdapter | None:
        provider_id = self.selected_provider_id()
        if provider_id == "none":
            return None
        gateway = self._addon_gateway
        return avatar_runtime_context.create_avatar_adapter_for_mode(
            provider_id,
            construction_inputs=self.construction_inputs(),
            addon_capability_invoker=(
                gateway.invoke_addon_capability if gateway is not None else None
            ),
            addon_manager_available=gateway is not None,
            logger=self._logger,
        )

    def active_adapter(self) -> avatar_runtime.AvatarAdapter | None:
        with self._lock:
            return self._active_adapter

    def attach_selected(self) -> CommandResult[avatar_runtime.AvatarAdapter | None]:
        """Stop the old adapter, construct the selection, and attach it."""

        stopped = self._avatar.stop()
        if not stopped.accepted:
            return CommandResult(False, failure=stopped.failure)
        try:
            candidate = self.create_selected_adapter()
        except BaseException as exc:
            return _failure(
                "avatar_creation_failed",
                f"Could not create selected avatar: {exc}",
                exc,
            )
        attached = self._avatar.attach(candidate)
        if not attached.accepted:
            return CommandResult(False, failure=attached.failure)
        with self._lock:
            self._active_adapter = candidate
        return CommandResult(True, candidate)

    def start(self) -> CommandResult[None]:
        return self._avatar.start(self._config.snapshot())

    def warm_up(self) -> CommandResult[bool]:
        adapter = self.active_adapter()
        if not avatar_runtime.adapter_matches_provider(adapter, "musetalk"):
            return CommandResult(True, False)
        callback = getattr(adapter, "warm_up", None)
        if not callable(callback):
            return _failure(
                "avatar_warmup_unsupported",
                "The selected MuseTalk adapter does not support warmup",
            )
        try:
            callback()
        except BaseException as exc:
            return _failure(
                "avatar_warmup_failed",
                f"Could not warm up MuseTalk: {exc}",
                exc,
            )
        return CommandResult(True, True)

    def set_idle(self) -> CommandResult[bool]:
        adapter = self.active_adapter()
        if not avatar_runtime.adapter_matches_provider(adapter, "musetalk"):
            return CommandResult(True, False)
        lease_source = self._work_lease_source
        if lease_source is None:
            return _failure(
                "avatar_idle_lease_unavailable",
                "MuseTalk idle publication requires a work lease",
            )
        return self._avatar.set_musetalk_idle_state(lease_source.current())

    def startup(self) -> CommandResult[avatar_runtime.AvatarAdapter | None]:
        """Run the production attach/start/warmup/idle sequence."""

        attached = self.attach_selected()
        if not attached.accepted:
            return attached
        started = self.start()
        if not started.accepted:
            self.shutdown()
            return CommandResult(False, failure=started.failure)
        warmed = self.warm_up()
        if not warmed.accepted:
            failure = warmed.failure
            self._logger(
                "Avatar warmup failed; continuing: "
                + (failure.message if failure is not None else "unknown failure")
            )
        idled = self.set_idle()
        if not idled.accepted:
            failure = idled.failure
            self._logger(
                "Avatar idle setup failed; continuing: "
                + (failure.message if failure is not None else "unknown failure")
            )
        return CommandResult(True, self.active_adapter())

    def stop(self) -> CommandResult[None]:
        """Stop provider activity while retaining the attached adapter."""

        return self._avatar.stop()

    def shutdown(self) -> CommandResult[None]:
        """Stop and release the active adapter reference."""

        stopped = self._avatar.stop()
        if not stopped.accepted:
            return stopped
        detached = self._avatar.attach(None)
        if not detached.accepted:
            return detached
        with self._lock:
            self._active_adapter = None
        return CommandResult(True)

    def body_snapshot(self) -> BodyProfileSnapshot:
        return self._body.snapshot()

    def set_body_live_sync(self, enabled: object) -> BodyProfileSnapshot:
        with self._lock:
            return self._apply_body_snapshot(self._body.set_live_sync(enabled))

    def select_body_emotion(self, emotion: object) -> BodyProfileSnapshot:
        with self._lock:
            return self._apply_body_snapshot(self._body.select_emotion(emotion))

    def update_body_pose(self, key: object, value: object) -> BodyProfileSnapshot:
        with self._lock:
            return self._apply_body_snapshot(self._body.update_pose(key, value))

    def update_body_profile(self, profile: object) -> BodyProfileSnapshot:
        with self._lock:
            return self._apply_body_snapshot(self._body.update_profile(profile))

    def update_body_hand_calibration(self, values: object) -> BodyProfileSnapshot:
        with self._lock:
            return self._apply_body_snapshot(
                self._body.update_hand_calibration(values)
            )

    def _apply_body_snapshot(
        self,
        snapshot: BodyProfileSnapshot,
    ) -> BodyProfileSnapshot:
        self._sync_body_mirrors(snapshot)
        return snapshot

    def _sync_body_mirrors(self, snapshot: BodyProfileSnapshot) -> None:
        _replace_mapping(self._avatar_profile, snapshot.profile)
        # Snapshots contain edited fields, while animation adds interpolated
        # fields. Keep those fields present when a slider changes mid-frame.
        self._current_body_state.update(_mutable_mapping(snapshot.state))
        _replace_mapping(self._hand_calibration, snapshot.hand_calibration)

    def _edit_emotion(self) -> str:
        return self._body.snapshot().edit_emotion

    def _force_edit_mode(self) -> bool:
        return self._body.snapshot().force_edit_mode


def _replace_mapping(target: dict[str, Any], source: Mapping[str, object]) -> None:
    replacement = _mutable_mapping(source)
    target.update(replacement)
    for key in target.keys() - replacement.keys():
        del target[key]


def _mutable_mapping(source: Mapping[str, object]) -> dict[str, Any]:
    return {str(key): _mutable_copy(value) for key, value in source.items()}


def _mutable_copy(value: object) -> Any:
    if isinstance(value, Mapping):
        return _mutable_mapping(value)
    if isinstance(value, tuple):
        return [_mutable_copy(item) for item in value]
    if isinstance(value, frozenset):
        return {_mutable_copy(item) for item in value}
    return deepcopy(value)


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = [
    "AvatarAddonCapabilityGateway",
    "ProductionAvatarOwner",
    "ProductionAvatarPreviewState",
    "ProductionAvatarRuntimeActions",
]
