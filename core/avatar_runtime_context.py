"""Host-side avatar runtime context assembly.

This keeps avatar adapter creation glue out of engine.py while preserving the
existing runtime objects passed to addon-owned avatar providers.
"""

from __future__ import annotations

from typing import Any, Callable

from core import avatar_runtime


def build_avatar_runtime_context(
    *,
    runtime_config: dict[str, Any],
    avatar_profile: dict[str, Any],
    current_body_state: dict[str, Any],
    edit_emotion_getter: Callable[[], str],
    force_edit_mode_getter: Callable[[], bool],
    hand_debug: dict[str, Any],
    hand_calibration: dict[str, Any],
    normalize_vam_root: Callable[[Any], str],
    derive_vam_bridge_root: Callable[[Any], str],
    default_vam_root: str,
    default_vam_emotion_preset_map: dict[str, Any],
    default_vam_timeline_clip_map: dict[str, Any],
    audio_segment_cls: type | None,
    invalidate_available_emotion_names_fn: Callable[[], None],
    avatar_preview_state_module: Any = None,
    musetalk_state_module: Any = None,
    log_memory_checkpoint_fn: Callable[..., None],
    stop_flag_event: Any,
    stop_playback_event: Any,
    dry_run_module: Any,
) -> avatar_runtime.AvatarRuntimeContext:
    if avatar_preview_state_module is None:
        avatar_preview_state_module = musetalk_state_module
    return avatar_runtime.AvatarRuntimeContext(
        runtime_config=runtime_config,
        dependencies={
            "avatar_profile": avatar_profile,
            "current_body_state": current_body_state,
            "edit_emotion_getter": edit_emotion_getter,
            "force_edit_mode_getter": force_edit_mode_getter,
            "hand_debug": hand_debug,
            "hand_calibration": hand_calibration,
            "normalize_vam_root": normalize_vam_root,
            "derive_vam_bridge_root": derive_vam_bridge_root,
            "default_vam_root": default_vam_root,
            "default_vam_emotion_preset_map": default_vam_emotion_preset_map,
            "default_vam_timeline_clip_map": default_vam_timeline_clip_map,
            "audio_segment_cls": audio_segment_cls,
            "invalidate_available_emotion_names_fn": invalidate_available_emotion_names_fn,
            "avatar_preview_state_module": avatar_preview_state_module,
            "musetalk_state_module": avatar_preview_state_module,
            "log_memory_checkpoint_fn": log_memory_checkpoint_fn,
            "stop_flag_event": stop_flag_event,
            "stop_playback_event": stop_playback_event,
            "dry_run_module": dry_run_module,
        },
    )


def create_avatar_adapter_for_mode(
    avatar_mode: str,
    *,
    runtime_context: avatar_runtime.AvatarRuntimeContext,
    addon_capability_invoker: Callable[[str, str, dict[str, Any]], Any] | None = None,
    addon_manager_available: bool = False,
    logger: Callable[[str], None] = print,
) -> avatar_runtime.AvatarAdapter | None:
    mode = avatar_runtime.normalize_provider_id(avatar_mode, fallback="vseeface")
    registered_provider = avatar_runtime.get_provider(mode)
    if registered_provider is not None:
        return avatar_runtime.create_avatar_adapter(mode, runtime_context=runtime_context)

    if avatar_runtime.list_providers() or addon_manager_available:
        logger(f"⚠️ Avatar provider '{mode}' is unavailable or disabled; continuing without avatar.")
        return None

    if mode == "none":
        return None
    adapter = None
    if callable(addon_capability_invoker):
        adapter = addon_capability_invoker(
            mode,
            "runtime.create_adapter",
            {"runtime_context": runtime_context},
        )
    if adapter is None:
        logger(f"⚠️ Avatar provider '{mode}' is unavailable; continuing without avatar.")
    return adapter
