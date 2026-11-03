"""Host-owned, provider-specific avatar adapter construction inputs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from core import avatar_runtime
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerSupervisor


class StopSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


@dataclass(frozen=True)
class MuseTalkRuntimeActions:
    """Narrow host actions used by the MuseTalk adapter."""

    _invalidate_emotions: Callable[[], None]
    _log_memory_checkpoint: Callable[..., None]
    _record_reply_metric: Callable[..., None]

    def invalidate_available_emotion_names(self) -> None:
        self._invalidate_emotions()

    def log_memory_checkpoint(self, *args, **kwargs) -> None:
        self._log_memory_checkpoint(*args, **kwargs)

    def record_reply_metric(self, *args, **kwargs) -> None:
        self._record_reply_metric(*args, **kwargs)


@dataclass(frozen=True)
class WorkLeaseSource:
    _current_lease: Callable[[], WorkLease]

    def current(self) -> WorkLease:
        return self._current_lease()


@dataclass(frozen=True)
class MuseTalkAdapterInputs:
    runtime_config: Mapping[str, Any]
    runtime_actions: MuseTalkRuntimeActions
    stop_requested: StopSignal
    playback_stop_requested: StopSignal
    worker_supervisor: WorkerSupervisor | None
    work_lease_source: WorkLeaseSource | None
    phone_presentation_getter: Callable[..., Mapping[str, Any] | None] | None = None


@dataclass(frozen=True)
class ScenicPreviewActions:
    """Exact host publications used by the Scenic adapter."""

    _invalidate_emotions: Callable[[], None]
    _set_current_frame_data: Callable[[dict[str, Any]], None]
    _write_preview_frame: Callable[[dict[str, Any]], None]

    def invalidate_available_emotion_names(self) -> None:
        self._invalidate_emotions()

    def set_current_frame_data(self, payload: dict[str, Any]) -> None:
        self._set_current_frame_data(payload)

    def write_preview_frame(self, payload: dict[str, Any]) -> None:
        self._write_preview_frame(payload)


@dataclass(frozen=True)
class ScenicAdapterInputs:
    runtime_config: Mapping[str, Any]
    preview_actions: ScenicPreviewActions


@dataclass(frozen=True)
class AvatarConstructionInputs:
    """Explicit construction inputs selected by a provider's declared type."""

    musetalk: MuseTalkAdapterInputs
    scenic: ScenicAdapterInputs
    legacy: avatar_runtime.AvatarRuntimeContext


def _config_snapshot(runtime_config: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(deepcopy(dict(runtime_config)))


def build_avatar_construction_inputs(
    *,
    runtime_config: dict[str, Any],
    avatar_profile: dict[str, Any],
    current_body_state: dict[str, Any],
    edit_emotion_getter: Callable[[], str],
    force_edit_mode_getter: Callable[[], bool],
    hand_debug: dict[str, Any],
    hand_calibration: dict[str, Any],
    invalidate_available_emotion_names_fn: Callable[[], None],
    avatar_preview_state_module: Any = None,
    musetalk_state_module: Any = None,
    log_memory_checkpoint_fn: Callable[..., None],
    stop_flag_event: StopSignal,
    stop_playback_event: StopSignal,
    dry_run_module: Any,
    worker_supervisor: WorkerSupervisor | None = None,
    worker_lease_factory: Callable[[], WorkLease] | None = None,
    update_body_profile_fn: Callable[[object], object] | None = None,
    update_hand_calibration_fn: Callable[[object], object] | None = None,
) -> AvatarConstructionInputs:
    if avatar_preview_state_module is None:
        avatar_preview_state_module = musetalk_state_module
    config_snapshot = _config_snapshot(runtime_config)
    actions = MuseTalkRuntimeActions(
        invalidate_available_emotion_names_fn,
        log_memory_checkpoint_fn,
        dry_run_module.record_reply_metric,
    )
    preview_set_current = getattr(
        avatar_preview_state_module,
        "set_current_musetalk_frame_data",
        None,
    )
    preview_write = getattr(
        avatar_preview_state_module,
        "write_musetalk_preview_frame",
        None,
    )
    scenic_preview_actions = ScenicPreviewActions(
        _invalidate_emotions=invalidate_available_emotion_names_fn,
        _set_current_frame_data=(
            preview_set_current if callable(preview_set_current) else lambda _payload: None
        ),
        _write_preview_frame=(
            preview_write if callable(preview_write) else lambda _payload: None
        ),
    )
    legacy = avatar_runtime.AvatarRuntimeContext(
        runtime_config=deepcopy(dict(runtime_config)),
        worker_supervisor=worker_supervisor,
        worker_lease_factory=worker_lease_factory,
        dependencies={
            "avatar_profile": avatar_profile,
            "current_body_state": current_body_state,
            "edit_emotion_getter": edit_emotion_getter,
            "force_edit_mode_getter": force_edit_mode_getter,
            "hand_debug": hand_debug,
            "hand_calibration": hand_calibration,
            "update_body_profile": update_body_profile_fn,
            "update_hand_calibration": update_hand_calibration_fn,
            "invalidate_available_emotion_names_fn": invalidate_available_emotion_names_fn,
            "avatar_preview_state_module": avatar_preview_state_module,
        },
    )
    return AvatarConstructionInputs(
        musetalk=MuseTalkAdapterInputs(
            runtime_config=config_snapshot,
            runtime_actions=actions,
            stop_requested=stop_flag_event,
            playback_stop_requested=stop_playback_event,
            worker_supervisor=worker_supervisor,
            work_lease_source=(
                WorkLeaseSource(worker_lease_factory)
                if worker_lease_factory is not None
                else None
            ),
        ),
        scenic=ScenicAdapterInputs(
            runtime_config=config_snapshot,
            preview_actions=scenic_preview_actions,
        ),
        legacy=legacy,
    )


def create_avatar_adapter_for_mode(
    avatar_mode: str,
    *,
    construction_inputs: AvatarConstructionInputs,
    addon_capability_invoker: Callable[[str, str, dict[str, Any]], Any] | None = None,
    addon_manager_available: bool = False,
    logger: Callable[[str], None] = print,
) -> avatar_runtime.AvatarAdapter | None:
    mode = avatar_runtime.normalize_provider_id(avatar_mode, fallback="vseeface")
    provider = avatar_runtime.get_provider(mode)
    if provider is not None:
        input_type = provider.construction_input_type
        if input_type is MuseTalkAdapterInputs:
            construction_input = construction_inputs.musetalk
            if callable(addon_capability_invoker):
                def phone_presentation_getter(request=None) -> Mapping[str, Any] | None:
                    try:
                        result = addon_capability_invoker(
                            "nc.main_chat_remote",
                            "runtime.main_chat_remote.presentation",
                            dict(request or {}),
                        )
                    except Exception:
                        return None
                    return result if isinstance(result, Mapping) else None

                construction_input = replace(
                    construction_input,
                    phone_presentation_getter=phone_presentation_getter,
                )
        elif input_type is ScenicAdapterInputs:
            construction_input = construction_inputs.scenic
        elif input_type is avatar_runtime.AvatarRuntimeContext:
            construction_input = construction_inputs.legacy
        elif input_type is None:
            construction_input = None
        else:
            raise TypeError(
                f"Avatar provider '{mode}' declared unsupported construction input "
                f"{input_type.__name__}."
            )
        return avatar_runtime.create_avatar_adapter(
            mode,
            construction_input=construction_input,
        )

    if avatar_runtime.list_providers() or addon_manager_available:
        logger(f"Avatar provider '{mode}' is unavailable or disabled; continuing without avatar.")
        return None

    if mode == "none":
        return None
    adapter = None
    if callable(addon_capability_invoker) and mode != "musetalk":
        construction_input = (
            construction_inputs.scenic
            if mode == "scenic"
            else construction_inputs.legacy
        )
        adapter = addon_capability_invoker(
            mode,
            "runtime.create_adapter",
            {"construction_input": construction_input},
        )
    if adapter is None:
        logger(f"Avatar provider '{mode}' is unavailable; continuing without avatar.")
    return adapter
