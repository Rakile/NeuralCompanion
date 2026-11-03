"""MuseTalk preview-frame playback helpers owned by the MuseTalk addon."""

from __future__ import annotations

import os
import time
from core.continuous_audio import continuous_media_seconds, continuous_pending_frame


def _publish_ua_companion_orb_frame(frame_path, *, frame_index, runtime_config, emitted_at):
    try:
        from addons.ua_companion_orb_overlay import stream_runtime as ua_companion_orb_stream_runtime
    except Exception:
        return False
    if not ua_companion_orb_stream_runtime.should_suppress_musetalk_preview(runtime_config or {}):
        return False
    ua_companion_orb_stream_runtime.publish_frame_path(
        frame_path,
        frame_index=int(frame_index or 0),
        runtime_config=runtime_config or {},
        timestamp_seconds=float(emitted_at or time.time()),
    )
    return True


def stream_musetalk_preview_frames(playback_state, stop_event, *, runtime_config, list_png_frames, musetalk_state_module):
    state = dict(playback_state or {})
    pending_audio_start = bool(state.get("audio_start_pending", False))
    if pending_audio_start:
        chunk_id = state.get("chunk_id")
        while not stop_event.is_set():
            live_state = dict(
                getattr(musetalk_state_module, "current_musetalk_frame_data", {}) or {}
            )
            if live_state.get("chunk_id") != chunk_id:
                return
            if not live_state.get("audio_start_pending", False):
                if live_state.get("status") != "ready":
                    return
                state = live_state
                break
            wait = getattr(stop_event, "wait", None)
            if callable(wait):
                wait(0.005)
            else:
                time.sleep(0.005)
        else:
            return
        if stop_event.is_set():
            return
    frame_paths = list(state.get("frame_paths", []) or [])
    frame_dir = state.get("frame_dir", "")
    fps = max(int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24), 1)
    expected_frame_count = int(state.get("expected_frame_count", 0) or len(frame_paths))
    if expected_frame_count <= 0:
        expected_frame_count = len(frame_paths)
    trim_start_frames = int(state.get("trim_start_frames", 0) or 0)
    start_index = int(state.get("start_index", 0) or 0)
    chunk_id = state.get("chunk_id")
    status = state.get("status", "idle")
    loop = bool(state.get("loop", False))
    progressive_audio = bool(state.get("progressive_audio", False))

    def _refresh_frame_paths():
        nonlocal frame_paths
        if not frame_dir:
            return
        scanned_paths = list_png_frames(frame_dir)
        if trim_start_frames > 0 and scanned_paths:
            trimmed = scanned_paths[min(trim_start_frames, len(scanned_paths) - 1):]
            if trimmed:
                scanned_paths = trimmed
        if scanned_paths:
            frame_paths = scanned_paths

    if not frame_paths and frame_dir:
        _refresh_frame_paths()
    if not frame_paths:
        return

    start_time = (
        float(state.get("sync_time", time.time()) or time.time())
        if pending_audio_start
        else time.time()
    )
    frame_index = 0
    last_emitted_path = None
    while not stop_event.is_set():
        media = None
        if not loop:
            live_state = getattr(musetalk_state_module, "current_musetalk_frame_data", {}) or {}
            if progressive_audio or "audio_chunk_index" in state or "audio_media_seconds" in state:
                if live_state.get("chunk_id") != chunk_id or live_state.get("status") != "ready":
                    return
            if "audio_chunk_index" in state or "audio_media_seconds" in state:
                media = continuous_media_seconds(live_state, time.monotonic())
                if media is None or live_state.get("audio_start_pending", False):
                    time.sleep(.005)
                    continue
        if media is not None:
            frame_index = int(media * fps)
            if frame_index >= len(frame_paths):
                _refresh_frame_paths()
            target_index = min(frame_index, len(frame_paths) - 1)
        elif loop and frame_paths:
            target_index = frame_index % len(frame_paths)
        else:
            target_index = frame_index
        if target_index >= len(frame_paths):
            _refresh_frame_paths()
        if target_index >= len(frame_paths):
            if not loop and not progressive_audio and frame_index >= max(expected_frame_count - 1, 0):
                break
            time.sleep(0.005)
            continue

        frame_path = frame_paths[target_index]
        if frame_path != last_emitted_path:
            emitted_at = time.time()
            if not _publish_ua_companion_orb_frame(
                frame_path,
                frame_index=target_index,
                runtime_config=runtime_config,
                emitted_at=emitted_at,
            ):
                musetalk_state_module.write_musetalk_preview_frame(
                    {
                        "chunk_id": chunk_id,
                        "status": status,
                        "loop": loop,
                        "frame_path": frame_path,
                        "frame_index": target_index,
                        "source_index": start_index + target_index,
                        "fps": fps,
                        "emitted_at": emitted_at,
                    }
                )
            last_emitted_path = frame_path

        if media is not None:
            if not progressive_audio and media >= float(state.get("duration_seconds", 0.) or 0.) > 0:
                break
            time.sleep(.005)
            continue

        frame_index += 1
        if not loop and not progressive_audio and frame_index >= max(expected_frame_count, len(frame_paths)):
            break

        target_time = start_time + (frame_index / fps)
        while not stop_event.is_set():
            remaining = target_time - time.time()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.005))


def stream_delegated_audio_progress(playback_state, stop_event, *, musetalk_state_module):
    state = dict(playback_state or {})
    duration_seconds = max(0.0, float(state.get("duration_seconds", 0.0) or 0.0))
    expected_frame_count = max(
        2,
        int(state.get("expected_frame_count", 0) or 0),
        int(round(duration_seconds * 50.0)) if duration_seconds > 0 else 2,
    )
    sequence_index = int(state.get("sequence_index", 0) or 0)
    chunk_id = state.get("chunk_id")
    sync_time = float(state.get("sync_time", time.time()) or time.time())
    is_single_still = bool(state.get("frame_paths")) and not state.get("frame_dir") and len(state.get("frame_paths") or []) == 1

    while not stop_event.is_set():
        elapsed = max(0.0, time.time() - sync_time)
        live_state = getattr(musetalk_state_module, "current_musetalk_frame_data", {}) or {}
        if live_state.get("chunk_id") != chunk_id:
            break
        media = None if live_state.get("loop", False) else continuous_media_seconds(live_state, time.monotonic())
        if media is not None:
            elapsed = media
        progress = min(elapsed / duration_seconds, 1.0) if duration_seconds > 0 else 1.0
        if is_single_still:
            preview_frame_index = 0
        elif media is not None:
            fps = max(int(live_state.get("fps", 24) or 24), 1)
            preview_frame_index = min(int(media * fps), expected_frame_count - 1)
        else:
            preview_frame_index = min(int(progress * max(expected_frame_count - 1, 1)), expected_frame_count - 1)
        live_state = getattr(musetalk_state_module, "current_musetalk_frame_data", {}) or {}
        if live_state.get("chunk_id") != chunk_id:
            break
        musetalk_state_module.update_current_musetalk_frame_data(
            sequence_index=sequence_index,
            expected_frame_count=expected_frame_count,
            frame_count=expected_frame_count,
            preview_chunk_id=chunk_id,
            preview_frame_index=preview_frame_index,
            preview_source_index=(int(live_state.get("start_index", 0) or 0) if media is not None else 0) + preview_frame_index,
            sync_time=sync_time,
            duration_seconds=duration_seconds,
            status="ready",
        )
        if progress >= 1.0:
            break
        time.sleep(0.02)


def prime_musetalk_preview_frame(playback_state, *, runtime_config, list_png_frames, musetalk_state_module):
    state = dict(playback_state or {})
    frame_paths = list(state.get("frame_paths", []) or [])
    if not frame_paths:
        frame_dir = state.get("frame_dir", "")
        trim_start_frames = int(state.get("trim_start_frames", 0) or 0)
        if frame_dir:
            frame_paths = list_png_frames(frame_dir)
            if trim_start_frames > 0 and frame_paths:
                trimmed = frame_paths[min(trim_start_frames, len(frame_paths) - 1):]
                if trimmed:
                    frame_paths = trimmed
    if not frame_paths:
        return

    media = None if state.get("loop", False) else continuous_media_seconds(state, time.monotonic())
    held = continuous_pending_frame(state)
    fps = max(int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24), 1)
    index = min(int(media * fps), len(frame_paths) - 1) if media is not None else 0
    first_frame_path = frame_paths[index]
    source_index = int(state.get("start_index", 0) or 0) + index
    if held is not None:
        first_frame_path, index, source_index = held
    if not first_frame_path or not os.path.exists(first_frame_path):
        return

    emitted_at = time.time()
    if _publish_ua_companion_orb_frame(
        first_frame_path,
        frame_index=index,
        runtime_config=runtime_config,
        emitted_at=emitted_at,
    ):
        return

    musetalk_state_module.write_musetalk_preview_frame(
        {
            "chunk_id": state.get("chunk_id"),
            "status": state.get("status", "idle"),
            "loop": bool(state.get("loop", False)),
            "frame_path": first_frame_path,
            "frame_index": index,
            "source_index": source_index,
            "fps": max(int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24), 1),
            "emitted_at": emitted_at,
        }
    )


def _continuous_available_frames(state, fallback):
    paths = list(state.get("frame_paths") or ())
    if state.get("frame_dir"):
        from core.runtime_files import list_png_frames
        scanned = list_png_frames(state["frame_dir"])
        if scanned:
            trim = max(0, int(state.get("trim_start_frames", 0) or 0))
            paths = scanned[min(trim, len(scanned) - 1):]
    return len(paths) if paths else fallback


def estimate_displayed_musetalk_frames(state, now=None, *, runtime_config=None, now_monotonic=None):
    state = state or {}
    held = continuous_pending_frame(state)
    if held is not None:
        return held[1] + 1
    frame_count = int(state.get("frame_count", 0) or 0)
    if frame_count <= 0:
        return 0
    if state.get("loop", False):
        return frame_count
    now = time.time() if now is None else now
    sync_time = float(state.get("sync_time", 0.0) or 0.0)
    elapsed = max(0.0, now - sync_time)
    duration_seconds = float(state.get("duration_seconds", 0.0) or 0.0)
    media = continuous_media_seconds(state, time.monotonic() if now_monotonic is None else now_monotonic)
    if media is not None:
        frame_count = _continuous_available_frames(state, frame_count)
        fps = max(int(state.get("fps", (runtime_config or {}).get("musetalk_fps", 24)) or 24), 1)
        frame_index = min(int(media * fps), frame_count - 1)
    elif duration_seconds > 0:
        progress = min(elapsed / duration_seconds, 1.0)
        frame_span = max(frame_count - 1, 1)
        frame_index = min(int(progress * frame_span), frame_count - 1)
    else:
        runtime_config = runtime_config or {}
        fps = int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24)
        frame_index = min(int(elapsed * max(fps, 1)), frame_count - 1)
    return frame_index + 1


def get_current_musetalk_source_index(
    state=None,
    *,
    runtime_config=None,
    musetalk_state_module=None,
    advance_to_next_frame=False,
    now=None,
    now_monotonic=None,
):
    """Resolve the source-frame index currently represented by preview state."""
    if state is None and musetalk_state_module is not None:
        state = getattr(musetalk_state_module, "current_musetalk_frame_data", {}) or {}
    state = state or {}
    runtime_config = runtime_config or {}
    held = continuous_pending_frame(state)
    if held is not None:
        return held[2] + int(bool(advance_to_next_frame))
    start_index = int(state.get("start_index", 0) or 0)
    source_indices = list(state.get("source_indices", []) or [])
    frame_count = int(state.get("frame_count", 0) or len(state.get("frame_paths", []) or []))
    if frame_count <= 0:
        return start_index

    sync_time = float(state.get("sync_time", 0.0) or 0.0)
    current_time = time.time() if now is None else now
    elapsed = max(0.0, current_time - sync_time) if sync_time else 0.0
    if state.get("loop", False):
        fps = int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24)
        frame_index = int(elapsed * max(fps, 1)) % frame_count
    else:
        media = continuous_media_seconds(state, time.monotonic() if now_monotonic is None else now_monotonic)
        duration_seconds = float(state.get("duration_seconds", 0.0) or 0.0)
        if media is not None:
            frame_count = _continuous_available_frames(state, frame_count)
            fps = max(int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24), 1)
            frame_index = min(int(media * fps), frame_count - 1)
        elif duration_seconds > 0:
            progress = min(elapsed / duration_seconds, 1.0)
            frame_span = max(frame_count - 1, 1)
            frame_index = min(int(progress * frame_span), frame_count - 1)
        else:
            fps = int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24)
            frame_index = min(int(elapsed * max(fps, 1)), frame_count - 1)

    if source_indices and 0 <= frame_index < len(source_indices):
        current_index = int(source_indices[frame_index])
    else:
        current_index = start_index + frame_index
    if advance_to_next_frame:
        current_index += 1
    return current_index
