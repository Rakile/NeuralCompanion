from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.musetalk_avatar import preview_runtime


def _function_body(source: str, name: str) -> str:
    marker = f"def {name}("
    start = source.index(marker)
    next_start = source.find("\ndef ", start + len(marker))
    return source[start:] if next_start < 0 else source[start:next_start]


def main() -> None:
    engine_source = (ROOT_DIR / "engine.py").read_text(encoding="utf-8")
    for required in (
        "def start_ua_companion_orb_musetalk_idle_stream(",
        "def stop_ua_companion_orb_musetalk_idle_stream(",
        "_ua_musetalk_idle_stream_thread",
    ):
        if required not in engine_source:
            raise AssertionError(f"Engine is missing UE MuseTalk idle stream support: {required}")

    clear_body = _function_body(engine_source, "clear_avatar_stream_state")
    if "stop_ua_companion_orb_musetalk_idle_stream()" not in clear_body:
        raise AssertionError("Clearing avatar stream state should stop the UE MuseTalk idle stream.")

    for function_name in (
        "set_musetalk_idle_state",
        "set_musetalk_idle_state_for_avatar",
        "transition_musetalk_to_local_idle",
        "loop_current_musetalk_state",
        "freeze_current_musetalk_frame",
    ):
        body = _function_body(engine_source, function_name)
        if "start_ua_companion_orb_musetalk_idle_stream(" not in body:
            raise AssertionError(f"{function_name} should start UE MuseTalk idle streaming after priming an idle frame.")

    speech_stream_index = engine_source.index("target=stream_musetalk_preview_frames")
    speech_stream_prefix = engine_source[max(0, speech_stream_index - 900) : speech_stream_index]
    if "stop_ua_companion_orb_musetalk_idle_stream()" not in speech_stream_prefix:
        raise AssertionError("Speech preview streaming should stop any previous UE MuseTalk idle stream first.")

    emitted: list[tuple[str, int]] = []
    stop_event = threading.Event()
    original_publish = preview_runtime._publish_ua_companion_orb_frame

    def fake_publish(frame_path, *, frame_index, runtime_config, emitted_at):
        emitted.append((str(frame_path), int(frame_index)))
        if len(emitted) >= 4:
            stop_event.set()
        return True

    try:
        preview_runtime._publish_ua_companion_orb_frame = fake_publish
        preview_runtime.stream_musetalk_preview_frames(
            {
                "frame_paths": ["idle_a.png", "idle_b.png"],
                "fps": 60,
                "expected_frame_count": 2,
                "chunk_id": "idle",
                "status": "idle",
                "loop": True,
            },
            stop_event,
            runtime_config={"ua_companion_orb_send_musetalk_face_mask": True},
            list_png_frames=lambda _frame_dir: [],
            musetalk_state_module=None,
        )
    finally:
        preview_runtime._publish_ua_companion_orb_frame = original_publish

    if len(emitted) < 4:
        raise AssertionError(f"Looping UE MuseTalk preview should keep publishing frames until stopped: {emitted!r}")
    if emitted[:4] != [("idle_a.png", 0), ("idle_b.png", 1), ("idle_a.png", 0), ("idle_b.png", 1)]:
        raise AssertionError(f"Looping UE MuseTalk preview did not wrap through idle frames: {emitted!r}")

    normal_preview_frames: list[dict] = []

    class NormalPreviewState:
        @staticmethod
        def write_musetalk_preview_frame(payload):
            normal_preview_frames.append(dict(payload or {}))
            if len(normal_preview_frames) >= 3:
                normal_stop_event.set()

    normal_stop_event = threading.Event()

    def publish_inactive(*args, **kwargs):
        return False

    try:
        preview_runtime._publish_ua_companion_orb_frame = publish_inactive
        preview_runtime.stream_musetalk_preview_frames(
            {
                "frame_paths": ["qt_a.png", "qt_b.png"],
                "fps": 60,
                "expected_frame_count": 2,
                "chunk_id": "qt_preview",
                "status": "idle",
                "loop": True,
            },
            normal_stop_event,
            runtime_config={"ua_companion_orb_send_musetalk_face_mask": False},
            list_png_frames=lambda _frame_dir: [],
            musetalk_state_module=NormalPreviewState,
        )
    finally:
        preview_runtime._publish_ua_companion_orb_frame = original_publish

    observed_normal = [
        (frame.get("frame_path"), frame.get("frame_index"), frame.get("chunk_id"))
        for frame in normal_preview_frames[:3]
    ]
    expected_normal = [
        ("qt_a.png", 0, "qt_preview"),
        ("qt_b.png", 1, "qt_preview"),
        ("qt_a.png", 0, "qt_preview"),
    ]
    if observed_normal != expected_normal:
        raise AssertionError(f"Normal MuseTalk preview loop was not preserved: {observed_normal!r}")

    print("smoke_ua_idle_loop_stream: ok")


if __name__ == "__main__":
    main()
