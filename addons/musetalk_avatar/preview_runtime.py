"""MuseTalk preview-frame playback helpers owned by the MuseTalk addon."""

from __future__ import annotations

import os
import time


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

    start_time = time.time()
    frame_index = 0
    last_emitted_path = None
    while not stop_event.is_set():
        if loop and frame_paths:
            target_index = frame_index % len(frame_paths)
        else:
            target_index = frame_index
        if target_index >= len(frame_paths):
            _refresh_frame_paths()
        if target_index >= len(frame_paths):
            if not loop and frame_index >= max(expected_frame_count - 1, 0):
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

        frame_index += 1
        if not loop and frame_index >= max(expected_frame_count, len(frame_paths)):
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
        progress = min(elapsed / duration_seconds, 1.0) if duration_seconds > 0 else 1.0
        if is_single_still:
            preview_frame_index = 0
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
            preview_source_index=preview_frame_index,
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

    first_frame_path = frame_paths[0]
    if not first_frame_path or not os.path.exists(first_frame_path):
        return

    emitted_at = time.time()
    if _publish_ua_companion_orb_frame(
        first_frame_path,
        frame_index=0,
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
            "frame_index": 0,
            "source_index": int(state.get("start_index", 0) or 0),
            "fps": max(int(state.get("fps", runtime_config.get("musetalk_fps", 24)) or 24), 1),
            "emitted_at": emitted_at,
        }
    )


def estimate_displayed_musetalk_frames(state, now=None, *, runtime_config=None):
    state = state or {}
    frame_count = int(state.get("frame_count", 0) or 0)
    if frame_count <= 0:
        return 0
    if state.get("loop", False):
        return frame_count
    now = time.time() if now is None else now
    sync_time = float(state.get("sync_time", 0.0) or 0.0)
    elapsed = max(0.0, now - sync_time)
    duration_seconds = float(state.get("duration_seconds", 0.0) or 0.0)
    if duration_seconds > 0:
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
):
    """Resolve the source-frame index currently represented by preview state."""
    if state is None and musetalk_state_module is not None:
        state = getattr(musetalk_state_module, "current_musetalk_frame_data", {}) or {}
    state = state or {}
    runtime_config = runtime_config or {}
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
        duration_seconds = float(state.get("duration_seconds", 0.0) or 0.0)
        if duration_seconds > 0:
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
