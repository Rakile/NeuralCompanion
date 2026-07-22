from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from addons.audio_story_mode import tts_segment_queue
from addons.audio_story_mode.tts_segment_queue import (
    SEGMENT_SCHEMA_VERSION,
    build_tts_queue_plan,
    clear_audio_story_tts_cache,
    load_ready_segment,
    publish_ready_segment,
    ready_seconds_from,
)


CHUNKS = [
    {"start_seconds": index * 10.0, "end_seconds": (index + 1) * 10.0, "text": f"line {index}"}
    for index in range(5)
]
CACHE = Path("cache")


def _duration_probe(path: Path) -> float:
    if path.read_bytes() == b"valid wav":
        return 12.0
    return 0.0


def test_plan_groups_windows_near_twenty_five_seconds() -> None:
    chunks = [
        {"start_seconds": index * 10.0, "end_seconds": (index + 1) * 10.0, "text": f"line {index}"}
        for index in range(5)
    ]
    plan = build_tts_queue_plan(chunks, {"voice": "a"}, Path("cache"), "project-a")
    assert [segment.window_indices for segment in plan.segments] == [(0, 1, 2), (3, 4)]


def test_project_cache_tokens_are_safe_contained_and_stable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        cache_root = Path(temporary).resolve()
        tts_root = (cache_root / "tts_segments").resolve()
        normal = build_tts_queue_plan(
            CHUNKS, {"voice": "a"}, cache_root, "project-a"
        )
        normal_root = normal.segments[0].audio_path.parent
        assert normal_root.parent.name == "project-a"
        assert tts_root in normal_root.resolve().parents

        unsafe_ids = (
            "..",
            ".",
            "CON",
            "project. ",
            "x" * 512,
        )
        unsafe_tokens = []
        for project_id in unsafe_ids:
            plan = build_tts_queue_plan(
                CHUNKS, {"voice": "a"}, cache_root, project_id
            )
            queue_root = plan.segments[0].audio_path.parent.resolve()
            assert tts_root in queue_root.parents, (project_id, queue_root)
            token = queue_root.parent.name
            assert token not in {"", ".", ".."}
            assert token.rstrip(". ") == token
            assert token.casefold() != "con"
            assert len(token) <= 96
            unsafe_tokens.append(token.casefold())
        assert len(set(unsafe_tokens)) == len(unsafe_tokens)


def test_buffer_preferences_do_not_change_segment_signatures() -> None:
    first = build_tts_queue_plan(
        CHUNKS,
        {
            "voice": "a",
            "buffer_seconds": 5.0,
            "startup_buffer_seconds": 10.0,
            "render_ahead_seconds": 20.0,
        },
        CACHE,
        "p",
    )
    second = build_tts_queue_plan(
        CHUNKS,
        {
            "voice": "a",
            "buffer_seconds": 30.0,
            "startup_buffer_seconds": 2.0,
            "render_ahead_seconds": 5.0,
        },
        CACHE,
        "p",
    )
    assert [item.signature for item in first.segments] == [item.signature for item in second.segments]


def test_voice_or_text_change_invalidates_only_affected_segments() -> None:
    original = build_tts_queue_plan(CHUNKS, {"voice": "a"}, CACHE, "p")
    changed_chunks = [dict(item) for item in CHUNKS]
    changed_chunks[-1]["text"] = "replacement"
    changed = build_tts_queue_plan(changed_chunks, {"voice": "a"}, CACHE, "p")
    assert original.segments[0].signature == changed.segments[0].signature
    assert original.segments[-1].signature != changed.segments[-1].signature
    voice_changed = build_tts_queue_plan(CHUNKS, {"voice": "b"}, CACHE, "p")
    assert all(a.signature != b.signature for a, b in zip(original.segments, voice_changed.segments))


def test_long_window_is_not_split_even_when_it_exceeds_maximum() -> None:
    plan = build_tts_queue_plan(
        [{"start_seconds": 0.0, "end_seconds": 35.0, "text": "long"}],
        {"voice": "a"},
        CACHE,
        "p",
    )
    assert len(plan.segments) == 1
    assert plan.segments[0].window_indices == (0,)
    assert plan.segments[0].estimated_seconds == 35.0


def test_publication_is_atomic_and_loads_valid_ready_segment() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        plan = build_tts_queue_plan(CHUNKS, {"voice": "a"}, root, "p").segments[0]
        temporary_audio = root / "rendering.wav"
        temporary_audio.write_bytes(b"valid wav")
        ready = publish_ready_segment(plan, temporary_audio, 12.0, [(0, 0.0, 10.0)])
        assert ready.plan == plan
        assert not temporary_audio.exists()
        assert plan.audio_path.is_file()
        assert plan.metadata_path.is_file()
        assert not plan.metadata_path.with_suffix(".json.tmp").exists()
        loaded = load_ready_segment(plan, _duration_probe)
        assert loaded == ready


def test_cache_validation_rejects_invalid_metadata_and_duration_probe_failure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        plan = build_tts_queue_plan(CHUNKS, {"voice": "a"}, root, "p").segments[0]
        temporary_audio = root / "rendering.wav"
        temporary_audio.write_bytes(b"valid wav")
        publish_ready_segment(plan, temporary_audio, 12.0, [])
        plan.metadata_path.write_text("not json", encoding="utf-8")
        assert load_ready_segment(plan, _duration_probe) is None
        plan.metadata_path.write_text("[]", encoding="utf-8")
        assert load_ready_segment(plan, _duration_probe) is None
        plan.metadata_path.write_text(
            json.dumps({"schema_version": SEGMENT_SCHEMA_VERSION, "signature": "wrong", "duration_seconds": 12.0}),
            encoding="utf-8",
        )
        assert load_ready_segment(plan, _duration_probe) is None
        plan.metadata_path.write_text(
            json.dumps({"schema_version": SEGMENT_SCHEMA_VERSION, "signature": plan.signature, "duration_seconds": 12.0}),
            encoding="utf-8",
        )
        assert load_ready_segment(plan, lambda _path: (_ for _ in ()).throw(OSError("bad wav"))) is None


def test_cache_validation_rejects_duration_mismatch_and_nonfinite_values() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        plan = build_tts_queue_plan(CHUNKS, {"voice": "a"}, root, "p").segments[0]
        temporary_audio = root / "rendering.wav"
        temporary_audio.write_bytes(b"valid wav")
        publish_ready_segment(plan, temporary_audio, 12.0, [])
        plan.metadata_path.write_text(
            json.dumps(
                {
                    "schema_version": SEGMENT_SCHEMA_VERSION,
                    "signature": plan.signature,
                    "duration_seconds": 11.0,
                }
            ),
            encoding="utf-8",
        )
        assert load_ready_segment(plan, _duration_probe) is None
        plan.metadata_path.write_text(
            json.dumps(
                {
                    "schema_version": SEGMENT_SCHEMA_VERSION,
                    "signature": plan.signature,
                    "duration_seconds": float("inf"),
                }
            ),
            encoding="utf-8",
        )
        assert load_ready_segment(plan, lambda _path: float("inf")) is None


def test_cache_validation_rejects_malformed_chunk_offsets() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        plan = build_tts_queue_plan(CHUNKS, {"voice": "a"}, root, "p").segments[0]
        temporary_audio = root / "rendering.wav"
        temporary_audio.write_bytes(b"valid wav")
        publish_ready_segment(plan, temporary_audio, 12.0, [])
        for malformed_offsets in (
            {},
            [[]],
            [[0, 1.0]],
            [[0, 1.0, float("inf")]],
            [[0, 8.0, 2.0]],
            [[-1, 0.0, 1.0]],
            [[0.0, 0.0, 1.0]],
            [[0, 0.0, 13.0]],
        ):
            plan.metadata_path.write_text(
                json.dumps(
                    {
                        "schema_version": SEGMENT_SCHEMA_VERSION,
                        "signature": plan.signature,
                        "duration_seconds": 12.0,
                        "chunk_offsets": malformed_offsets,
                    }
                ),
                encoding="utf-8",
            )
            assert load_ready_segment(plan, _duration_probe) is None


def test_ready_seconds_sums_contiguous_buffer_after_local_offset() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        segments = build_tts_queue_plan(CHUNKS, {"voice": "a"}, Path(temporary), "p").segments
        first = publish_ready_segment(
            segments[0], _write_audio(Path(temporary) / "first.wav"), 12.0, []
        )
        second = publish_ready_segment(
            segments[1], _write_audio(Path(temporary) / "second.wav"), 8.0, []
        )
        assert ready_seconds_from({0: first, 1: second}, 0, 3.0) == 17.0
        assert ready_seconds_from({0: first, 2: second}, 0) == 12.0


def _write_audio(path: Path) -> Path:
    path.write_bytes(b"valid wav")
    return path


def test_cache_clear_only_removes_audio_story_tts_artifacts_under_root() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        segments = root / "tts_segments" / "project" / "queue"
        segments.mkdir(parents=True)
        (segments / "segment.wav").write_bytes(b"valid wav")
        (root / "tts_story_legacy.wav").write_bytes(b"valid wav")
        (root / "tts_story_legacy.json").write_text("{}", encoding="utf-8")
        unrelated = root / "keep.wav"
        unrelated.write_bytes(b"keep")
        file_count, directory_count = clear_audio_story_tts_cache(root)
        assert (file_count, directory_count) == (3, 1)
        assert unrelated.is_file()
        assert not (root / "tts_segments").exists()
        assert not (root / "tts_story_legacy.wav").exists()
        assert not (root / "tts_story_legacy.json").exists()


def test_cache_clear_rejects_a_tts_segments_link_resolving_to_root() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        marker = root / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        link = root / "tts_segments"
        try:
            link.symlink_to(root, target_is_directory=True)
        except (NotImplementedError, OSError):
            assert not tts_segment_queue._is_strict_descendant(root, root)
            return
        try:
            clear_audio_story_tts_cache(root)
        except ValueError:
            pass
        else:
            raise AssertionError("cache clear accepted a target resolving to its root")
        assert marker.is_file()


def test_cache_clear_refuses_tts_segments_link_to_unrelated_data() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        unrelated = root / "unrelated_data"
        unrelated.mkdir()
        marker = unrelated / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        link = root / "tts_segments"
        try:
            link.symlink_to(unrelated, target_is_directory=True)
        except (NotImplementedError, OSError):
            class LinkLike:
                @staticmethod
                def is_symlink() -> bool:
                    return True

            assert tts_segment_queue._is_link_or_junction(LinkLike())
            return
        try:
            clear_audio_story_tts_cache(root)
        except ValueError:
            pass
        else:
            raise AssertionError("cache clear accepted a TTS cache link")
        assert link.is_symlink()
        assert marker.is_file()


class _FakeAudio:
    def __init__(self, duration_seconds: float = 0.0):
        self.duration_seconds = max(0.0, float(duration_seconds or 0.0))

    def __add__(self, other):
        return _FakeAudio(self.duration_seconds + float(other.duration_seconds or 0.0))

    def __iadd__(self, other):
        self.duration_seconds += float(other.duration_seconds or 0.0)
        return self

    def export(self, path: str, *, format: str) -> None:
        assert format == "wav"
        Path(path).write_text(str(self.duration_seconds), encoding="utf-8")


class _FakeTtsRuntime:
    def __init__(self):
        self.rendered_indices: list[int] = []
        self.fail_indices: set[int] = set()
        self.init_calls = 0
        self.seed_calls: list[int] = []
        self.generation_kwargs: list[dict] = []
        self.sample_rates: list[int] = []
        self.split_into_two_subchunks = False
        self.generation_started = threading.Event()
        self.release_generation = threading.Event()
        self.block_generation = False
        self.block_generation_indices: set[int] = set()
        self.final_probe_duration: float | None = None
        self.final_probe_error: Exception | None = None
        self.final_probe_paths: list[Path] = []
        self.live_sample_rate = 24000
        self.live_voice_path = "fake-voice.wav"
        self.live_seed = 17
        self.live_generation_kwargs = {"temperature": 0.25}
        self.settings_snapshot_value = {"voice": "fake", "temperature": 0.25}
        self.sample_rate_after_init: int | None = None

    def init_tts(self) -> bool:
        self.init_calls += 1
        if self.sample_rate_after_init is not None:
            self.live_sample_rate = int(self.sample_rate_after_init)
        return True

    @staticmethod
    def get_text_chunk_limits() -> tuple[int, int]:
        return 120, 180

    @staticmethod
    def audio_silent(*, duration: int) -> _FakeAudio:
        return _FakeAudio(float(duration or 0) / 1000.0)

    def intelligent_chunk_text(self, text: str, _target: int, _maximum: int) -> list[str]:
        if self.split_into_two_subchunks:
            return [f"{text} part one", f"{text} part two"]
        return [text]

    def tts_sample_rate(self, *, default: int) -> int:
        assert default == 24000
        return int(self.live_sample_rate)

    def tts_voice_path(self) -> str:
        return str(self.live_voice_path)

    def tts_seed(self) -> int:
        return int(self.live_seed)

    def set_seed(self, seed: int) -> None:
        self.seed_calls.append(int(seed))

    def tts_generation_kwargs(self) -> dict:
        return dict(self.live_generation_kwargs)

    def generate_tts(self, text: str, **kwargs):
        match = re.search(r"segment\s+(\d+)", str(text))
        assert match is not None, text
        index = int(match.group(1))
        self.rendered_indices.append(index)
        self.generation_kwargs.append(dict(kwargs))
        self.generation_started.set()
        if self.block_generation or index in self.block_generation_indices:
            assert self.release_generation.wait(2.0), "fake generation gate timed out"
        if index in self.fail_indices:
            raise RuntimeError(f"fake failure at segment {index}")
        return 30.0

    def save_tts_wav(self, path: str, wav, sample_rate: int) -> None:
        self.sample_rates.append(int(sample_rate))
        Path(path).write_text(str(float(wav)), encoding="utf-8")

    def audio_from_wav(self, path: str) -> _FakeAudio:
        audio_path = Path(path)
        if audio_path.name.startswith("tts_piece_"):
            self.final_probe_paths.append(audio_path)
            if self.final_probe_error is not None:
                raise self.final_probe_error
            if self.final_probe_duration is not None:
                return _FakeAudio(self.final_probe_duration)
        return _FakeAudio(float(audio_path.read_text(encoding="utf-8")))

    def audio_duration_seconds(self, path: str | Path) -> float:
        audio_path = Path(path)
        if (
            audio_path.name.startswith("segment_")
            and self.final_probe_duration is not None
        ):
            return float(self.final_probe_duration)
        return float(audio_path.read_text(encoding="utf-8"))

    @staticmethod
    def safe_delete(path: str) -> None:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass

    def tts_settings_snapshot(self) -> dict:
        return dict(self.settings_snapshot_value)

    def boundaries(self) -> dict[str, object]:
        return {
            "init_tts": self.init_tts,
            "get_text_chunk_limits": self.get_text_chunk_limits,
            "audio_silent": self.audio_silent,
            "intelligent_chunk_text": self.intelligent_chunk_text,
            "tts_sample_rate": self.tts_sample_rate,
            "tts_voice_path": self.tts_voice_path,
            "tts_seed": self.tts_seed,
            "set_seed": self.set_seed,
            "tts_generation_kwargs": self.tts_generation_kwargs,
            "generate_tts": self.generate_tts,
            "save_tts_wav": self.save_tts_wav,
            "audio_from_wav": self.audio_from_wav,
            "audio_duration_seconds": self.audio_duration_seconds,
            "safe_delete": self.safe_delete,
            "tts_settings_snapshot": self.tts_settings_snapshot,
        }


@contextmanager
def _patched_tts_runtime(controller_module, fake_runtime: _FakeTtsRuntime):
    previous = {
        name: getattr(controller_module.audio_story_runtime, name)
        for name in fake_runtime.boundaries()
    }
    try:
        for name, boundary in fake_runtime.boundaries().items():
            setattr(controller_module.audio_story_runtime, name, boundary)
        yield
    finally:
        for name, boundary in previous.items():
            setattr(controller_module.audio_story_runtime, name, boundary)


class _TestStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def resolve(self, name: str) -> Path:
        path = self.root / str(name)
        path.mkdir(parents=True, exist_ok=True)
        return path


class _TestContext:
    def __init__(self, root: Path):
        self.storage = _TestStorage(root)

    @staticmethod
    def get_service(_name: str):
        return None


class _QueueWorkerHarness:
    def __init__(self, controller, app):
        self.controller = controller
        self.app = app
        self.states: list[dict] = []
        self.segment_payloads: list[dict] = []
        self.failures: list[dict] = []
        self.completions: list[dict] = []
        controller.ttsQueueStateChanged.connect(self.states.append)
        controller.ttsSegmentReady.connect(self.segment_payloads.append)
        controller.ttsQueueFailed.connect(self.failures.append)
        controller.ttsQueueComplete.connect(self.completions.append)

    def start(self) -> None:
        self.controller._pending_autoplay_tts = True
        self.controller._start_tts_render(self.controller._compute_tts_signature())

    def wait_until(self, predicate, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        self.app.processEvents()
        return bool(predicate())

    def wait_for_state(self, state: str, timeout: float = 3.0) -> bool:
        return self.wait_until(
            lambda: any(str(item.get("state") or "") == state for item in self.states),
            timeout,
        )

    @property
    def ready_seconds(self) -> float:
        payload = next(
            item for item in self.states if str(item.get("state") or "") == "Ready"
        )
        return float(payload.get("ready_seconds", 0.0) or 0.0)

    @property
    def autoplay_requests(self) -> int:
        return sum(bool(item.get("autoplay_requested")) for item in self.states)

    @property
    def ready_seconds_from_playhead(self) -> float:
        controller = self.controller
        local_offset = max(
            0.0,
            float(controller._tts_playback_position_seconds or 0.0)
            - float(controller._tts_active_segment_global_offset or 0.0),
        )
        return ready_seconds_from(
            controller._tts_ready_segments,
            controller._tts_active_segment_index,
            local_offset,
        )

    @property
    def validated_segment_paths(self) -> list[Path]:
        return [
            ready.plan.audio_path
            for _index, ready in sorted(self.controller._tts_ready_segments.items())
        ]

    @property
    def worker_stopped(self) -> bool:
        worker = getattr(self.controller, "_tts_render_thread", None)
        return worker is None or not worker.is_alive()

    def advance_playback(self, seconds: float) -> None:
        self.controller._on_player_position_changed(int(round(float(seconds) * 1000.0)))

    def stop(self) -> None:
        worker = getattr(self.controller, "_tts_render_thread", None)
        self.controller._stop_story()
        if worker is not None:
            worker.join(timeout=2.0)
        self.app.processEvents()


def _worker_chunks(count: int) -> list[dict]:
    return [
        {
            "start_seconds": float(index * 30),
            "end_seconds": float((index + 1) * 30),
            "text": f"segment {index}",
        }
        for index in range(count)
    ]


def _controller_and_app(root: Path):
    from PySide6 import QtCore
    from addons.audio_story_mode import controller as controller_module

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    controller = controller_module.AudioStoryModeController(_TestContext(root))
    controller.current_story_project_id = "worker-project"
    return controller_module, controller, app


def test_segment_worker_starts_at_actual_buffer_and_waits_at_ahead_limit() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(8)
        controller._stored_tts_startup_buffer_seconds = 30
        controller._stored_tts_render_ahead_seconds = 120
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_for_state("Ready")
                assert harness.ready_seconds == 30.0
                assert harness.autoplay_requests == 1
                assert harness.wait_until(lambda: len(fake_runtime.rendered_indices) == 4)
                time.sleep(0.05)
                assert fake_runtime.rendered_indices == [0, 1, 2, 3]

                harness.advance_playback(20.0)
                assert harness.wait_until(
                    lambda: harness.ready_seconds_from_playhead >= 120.0
                )
                assert fake_runtime.rendered_indices == [0, 1, 2, 3, 4]

                harness.stop()
                assert harness.worker_stopped
                assert harness.validated_segment_paths
                assert all(path.exists() for path in harness.validated_segment_paths)
                assert all(
                    item.get("audio_prompt_path") == "fake-voice.wav"
                    and item.get("temperature") == 0.25
                    for item in fake_runtime.generation_kwargs
                )
                assert fake_runtime.seed_calls == [17] * len(fake_runtime.rendered_indices)
                assert fake_runtime.sample_rates == [24000] * len(fake_runtime.rendered_indices)
        finally:
            if not harness.worker_stopped:
                fake_runtime.release_generation.set()
                harness.stop()


def test_queue_plan_building_runs_off_the_controller_thread() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)
        controller_thread = threading.get_ident()
        original_builder = controller_module.build_tts_queue_plan
        build_threads: list[int] = []

        def guarded_builder(*args, **kwargs):
            build_threads.append(threading.get_ident())
            assert build_threads[-1] != controller_thread, (
                "queue-plan hashing ran on the controller thread"
            )
            return original_builder(*args, **kwargs)

        controller_module.build_tts_queue_plan = guarded_builder
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_for_state("Complete")
                assert build_threads and all(
                    thread_id != controller_thread for thread_id in build_threads
                )
        finally:
            controller_module.build_tts_queue_plan = original_builder
            if not harness.worker_stopped:
                harness.stop()


def test_bundle_file_validation_never_runs_on_the_controller_thread() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)
        controller_thread = threading.get_ident()
        original_stat = controller._tts_bundle_stat_fingerprint
        validation_threads: list[int] = []

        def guarded_stat(path: Path) -> dict[str, int]:
            validation_threads.append(threading.get_ident())
            assert validation_threads[-1] != controller_thread, (
                "bundle filesystem validation ran on the controller thread"
            )
            return original_stat(path)

        controller._tts_bundle_stat_fingerprint = guarded_stat
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_for_state("Complete")
                assert validation_threads and all(
                    thread_id != controller_thread
                    for thread_id in validation_threads
                )
        finally:
            controller._tts_bundle_stat_fingerprint = original_stat
            if not harness.worker_stopped:
                harness.stop()


def test_far_ahead_seek_prioritizes_target_then_backfills_in_story_order() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(8)
        controller._stored_tts_startup_buffer_seconds = 60
        controller._stored_tts_render_ahead_seconds = 60
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(
                    lambda: fake_runtime.rendered_indices == [0, 1]
                )
                controller._stored_tts_render_ahead_seconds = 600
                with controller._tts_render_condition:
                    controller._tts_buffering_target_seconds = 150.0
                    controller._tts_render_target_segment_index = 5
                    controller._tts_render_target_segment_global_offset = 150.0
                    controller._tts_playback_position_seconds = 150.0
                    controller._tts_queue_state = "Buffering"
                    controller._tts_render_condition.notify_all()
                assert harness.wait_for_state("Complete")
                assert fake_runtime.rendered_indices == [0, 1, 5, 6, 2, 3, 4, 7]
                assert sorted(controller._tts_ready_segments) == list(range(8))
                assert harness.completions[-1]["segment_count"] == 8
        finally:
            if not harness.worker_stopped:
                harness.stop()


def test_segment_worker_preserves_cache_on_failure_and_retry_starts_at_missing() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        fake_runtime.fail_indices.add(3)
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(6)
        controller._stored_tts_startup_buffer_seconds = 30
        controller._stored_tts_render_ahead_seconds = 600
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                active_job_id = controller._tts_render_job_id
                assert harness.wait_for_state("Failed")
                assert controller._tts_render_job_id == active_job_id
                assert harness.failures[-1]["segment_index"] == 3
                assert sorted(controller._tts_ready_segments) == [0, 1, 2]
                preserved_paths = list(harness.validated_segment_paths)
                assert all(path.exists() for path in preserved_paths)

                retry_start = len(fake_runtime.rendered_indices)
                fake_runtime.fail_indices.clear()
                controller._retry_tts_rendering()
                assert harness.wait_for_state("Complete")
                assert fake_runtime.rendered_indices[retry_start:] == [3, 4, 5]
                assert all(path.exists() for path in preserved_paths)
                assert sorted(controller._tts_ready_segments) == [0, 1, 2, 3, 4, 5]
                assert fake_runtime.init_calls == 2
                assert not list(controller._cache_root.glob("tts_piece_*.wav"))

                completion_count = len(harness.completions)
                controller._start_tts_render(controller._compute_tts_signature())
                assert harness.wait_until(
                    lambda: len(harness.completions) > completion_count
                )
                assert fake_runtime.init_calls == 2
                assert sorted(controller._tts_ready_segments) == [0, 1, 2, 3, 4, 5]

                ready_zero = controller._tts_ready_segments[0]
                current_ownership = {
                    "job_id": controller._tts_render_job_id,
                    "project_id": controller.current_story_project_id,
                    "queue_signature": controller._tts_queue_plan.signature,
                }
                controller._tts_ready_segments = {}
                stale_ownerships = []
                for key, value in (
                    ("job_id", controller._tts_render_job_id - 1),
                    ("project_id", "stale-project"),
                    ("queue_signature", "stale-signature"),
                ):
                    ownership = dict(current_ownership)
                    ownership[key] = value
                    stale_ownerships.append(ownership)
                for stale_ownership in stale_ownerships:
                    controller.ttsSegmentReady.emit(
                        {**stale_ownership, "segment": ready_zero}
                    )
                    controller.ttsQueueStateChanged.emit(
                        {**stale_ownership, "state": "Stale"}
                    )
                    controller.ttsQueueFailed.emit(
                        {
                            **stale_ownership,
                            "segment_index": 0,
                            "detail": "stale failure",
                        }
                    )
                    controller.ttsQueueComplete.emit(stale_ownership)
                app.processEvents()
                app.processEvents()
                assert not controller._tts_ready_segments
                assert controller._tts_queue_state == "Complete"
                assert controller._tts_queue_error == ""
        finally:
            if not harness.worker_stopped:
                harness.stop()


def test_segment_worker_cancels_between_subchunks_without_locking_stop() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        fake_runtime.split_into_two_subchunks = True
        fake_runtime.block_generation = True
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(fake_runtime.generation_started.is_set)
                release_timer = threading.Timer(
                    0.25, fake_runtime.release_generation.set
                )
                release_timer.start()
                started = time.monotonic()
                worker = controller._tts_render_thread
                controller._stop_story()
                elapsed = time.monotonic() - started
                release_timer.cancel()
                fake_runtime.release_generation.set()
                assert worker is not None
                worker.join(timeout=2.0)
                app.processEvents()
                assert elapsed < 0.15, elapsed
                assert harness.worker_stopped
                assert fake_runtime.rendered_indices == [0]
                assert not controller._tts_ready_segments
                assert not list(controller._cache_root.rglob("tts_piece_*.wav"))
        finally:
            fake_runtime.release_generation.set()
            if not harness.worker_stopped:
                harness.stop()


def test_replacement_job_waits_for_cancelled_worker_inference() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        fake_runtime.block_generation = True
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(fake_runtime.generation_started.is_set)
                assert fake_runtime.rendered_indices == [0]

                controller._start_tts_render(controller._compute_tts_signature())
                time.sleep(0.05)
                assert fake_runtime.rendered_indices == [0]

                fake_runtime.release_generation.set()
                assert harness.wait_for_state("Complete")
                worker = controller._tts_render_thread
                assert worker is not None
                worker.join(timeout=2.0)
                assert fake_runtime.rendered_indices == [0, 0]
        finally:
            fake_runtime.release_generation.set()
            if not harness.worker_stopped:
                harness.stop()


def test_segment_worker_uses_exported_wav_probe_duration_for_readiness() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        fake_runtime.final_probe_duration = 12.0
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(8)
        controller._stored_tts_startup_buffer_seconds = 30
        controller._stored_tts_render_ahead_seconds = 60
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_for_state("Ready")
                assert harness.ready_seconds == 36.0
                assert harness.wait_until(lambda: len(fake_runtime.rendered_indices) == 5)
                time.sleep(0.05)
                assert fake_runtime.rendered_indices == [0, 1, 2, 3, 4]
                assert len(fake_runtime.final_probe_paths) == 5
                assert all(
                    ready.duration_seconds == 12.0
                    for ready in controller._tts_ready_segments.values()
                )
        finally:
            if not harness.worker_stopped:
                harness.stop()


def test_segment_worker_rejects_invalid_or_truncated_exported_wav() -> None:
    invalid_probes = (
        (float("nan"), None, "finite"),
        (None, RuntimeError("truncated fake WAV"), "truncated fake WAV"),
    )
    for duration, probe_error, expected_detail in invalid_probes:
        with tempfile.TemporaryDirectory() as temporary:
            controller_module, controller, app = _controller_and_app(Path(temporary))
            fake_runtime = _FakeTtsRuntime()
            fake_runtime.final_probe_duration = duration
            fake_runtime.final_probe_error = probe_error
            harness = _QueueWorkerHarness(controller, app)
            controller.transcript_chunks = _worker_chunks(1)
            try:
                with _patched_tts_runtime(controller_module, fake_runtime):
                    harness.start()
                    assert harness.wait_for_state("Failed", timeout=0.5)
                    assert harness.failures[-1]["segment_index"] == 0
                    assert expected_detail in harness.failures[-1]["detail"]
                    assert not controller._tts_ready_segments
                    segment = controller._tts_queue_plan.segments[0]
                    assert not segment.audio_path.exists()
                    assert not segment.metadata_path.exists()
                    assert not list(controller._cache_root.rglob("tts_piece_*.wav"))
            finally:
                if not harness.worker_stopped:
                    harness.stop()


def test_segment_worker_freezes_seed_kwargs_voice_and_sample_rate() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        fake_runtime.split_into_two_subchunks = True
        fake_runtime.block_generation = True
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(fake_runtime.generation_started.is_set)
                fake_runtime.live_seed = 99
                fake_runtime.live_generation_kwargs = {"temperature": 0.99}
                fake_runtime.live_voice_path = "mutated-voice.wav"
                fake_runtime.live_sample_rate = 44100
                fake_runtime.release_generation.set()
                assert harness.wait_for_state("Complete")
                assert fake_runtime.seed_calls == [17, 17]
                assert fake_runtime.sample_rates == [24000, 24000]
                assert [
                    item.get("temperature")
                    for item in fake_runtime.generation_kwargs
                ] == [0.25, 0.25]
                assert [
                    item.get("audio_prompt_path")
                    for item in fake_runtime.generation_kwargs
                ] == ["fake-voice.wav", "fake-voice.wav"]
        finally:
            fake_runtime.release_generation.set()
            if not harness.worker_stopped:
                harness.stop()


def test_settings_change_cancels_old_signature_and_retry_starts_new_plan() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        fake_runtime.block_generation_indices.add(1)
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(3)
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(fake_runtime.generation_started.is_set)
                assert harness.wait_until(
                    lambda: fake_runtime.rendered_indices == [0, 1]
                )
                old_plan = controller._tts_queue_plan
                old_signature = old_plan.signature
                old_job_id = controller._tts_render_job_id
                old_worker = controller._tts_render_thread
                assert sorted(controller._tts_ready_segments) == [0]
                preserved_paths = list(harness.validated_segment_paths)
                assert all(path.exists() for path in preserved_paths)
                fake_runtime.settings_snapshot_value = {
                    "voice": "changed",
                    "temperature": 0.25,
                }
                fake_runtime.live_voice_path = "changed-voice.wav"
                fake_runtime.release_generation.set()

                assert harness.wait_for_state("Failed")
                assert harness.failures[-1]["reason"] == "settings_changed"
                assert harness.failures[-1]["queue_signature"] == old_signature
                assert controller._tts_render_job_id == old_job_id + 1
                assert controller._tts_queue_failure_reason == "settings_changed"
                assert sorted(controller._tts_ready_segments) == [0]
                assert all(path.exists() for path in preserved_paths)
                assert not controller._tts_settings_watch_timer.isActive()
                assert old_worker is not None
                old_worker.join(timeout=1.0)
                assert not old_worker.is_alive()
                assert controller._tts_job_is_current(
                    old_job_id + 1,
                    old_plan.project_id,
                    old_signature,
                )
                failed_state = next(
                    item
                    for item in reversed(harness.states)
                    if item.get("state") == "Failed"
                )
                assert failed_state["job_id"] == old_job_id + 1

                controller.ttsQueueFailed.emit(dict(harness.failures[-1]))
                app.processEvents()
                assert controller._tts_render_job_id == old_job_id + 1

                completion_count = len(harness.completions)
                controller._retry_tts_rendering()
                assert controller._tts_render_job_id == old_job_id + 2
                assert harness.wait_until(
                    lambda: controller._tts_queue_plan is not None
                    and controller._tts_queue_plan.signature != old_signature
                )
                assert controller._tts_queue_plan.signature != old_signature
                assert harness.wait_until(
                    lambda: len(harness.completions) > completion_count
                )
                assert controller._tts_queue_state == "Complete"
                assert controller._tts_ready_segments[0].plan.signature != (
                    old_plan.segments[0].signature
                )
                assert all(path.exists() for path in preserved_paths)
        finally:
            fake_runtime.release_generation.set()
            if not harness.worker_stopped:
                harness.stop()


def test_settings_watcher_invalidates_worker_waiting_at_ahead_limit() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(6)
        controller._stored_tts_startup_buffer_seconds = 30
        controller._stored_tts_render_ahead_seconds = 60
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(lambda: fake_runtime.rendered_indices == [0, 1])
                time.sleep(0.05)
                assert fake_runtime.rendered_indices == [0, 1]
                assert controller._tts_settings_watch_timer.isActive()
                old_job_id = controller._tts_render_job_id
                old_signature = controller._tts_queue_plan.signature
                old_worker = controller._tts_render_thread

                fake_runtime.settings_snapshot_value = {
                    "voice": "watcher-change",
                    "temperature": 0.25,
                }
                assert harness.wait_until(
                    lambda: controller._tts_render_job_id > old_job_id,
                    timeout=1.5,
                )
                assert harness.wait_for_state("Failed")
                assert harness.failures[-1]["reason"] == "settings_changed"
                assert harness.failures[-1]["queue_signature"] == old_signature
                assert controller._tts_render_job_id == old_job_id + 1
                assert not controller._tts_settings_watch_timer.isActive()
                assert old_worker is not None
                old_worker.join(timeout=1.0)
                assert not old_worker.is_alive()
                assert not any(
                    item.get("queue_signature") == old_signature
                    for item in harness.completions
                )
                assert fake_runtime.rendered_indices == [0, 1]
                assert sorted(controller._tts_ready_segments) == [0, 1]

                watcher_failure = dict(harness.failures[-1])
                controller.ttsQueueFailed.emit(watcher_failure)
                app.processEvents()
                assert controller._tts_render_job_id == old_job_id + 1
        finally:
            if not harness.worker_stopped:
                harness.stop()


def test_segment_worker_freezes_sample_rate_after_backend_init() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        fake_runtime.live_sample_rate = 16000
        fake_runtime.sample_rate_after_init = 48000
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_for_state("Complete")
                assert fake_runtime.init_calls == 1
                assert fake_runtime.sample_rates == [48000]
        finally:
            if not harness.worker_stopped:
                harness.stop()


def test_empty_queue_start_invalidates_a_prior_waiting_worker() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(6)
        controller._stored_tts_startup_buffer_seconds = 30
        controller._stored_tts_render_ahead_seconds = 60
        prior_worker = None
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(
                    lambda: fake_runtime.rendered_indices == [0, 1]
                )
                prior_job_id = controller._tts_render_job_id
                prior_worker = controller._tts_render_thread
                assert prior_worker is not None and prior_worker.is_alive()

                controller.transcript_chunks = []
                controller._start_tts_render(controller._compute_tts_signature())

                assert controller._tts_render_job_id == prior_job_id + 1
                assert harness.wait_until(
                    lambda: controller._tts_queue_plan is not None
                    and not controller._tts_queue_plan.segments
                )
                prior_worker.join(timeout=1.0)
                assert not prior_worker.is_alive()
                assert not controller._tts_settings_watch_timer.isActive()
                assert controller._tts_queue_plan is not None
                assert not controller._tts_queue_plan.segments
        finally:
            if prior_worker is not None and prior_worker.is_alive():
                harness.stop()


def test_segment_worker_publishes_legacy_compatible_full_bundle() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(2)
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_for_state("Complete")
                payload = harness.completions[-1]
                audio_path = Path(str(payload.get("audio_path") or ""))
                metadata_path = audio_path.with_suffix(".json")
                commit_path = audio_path.with_suffix(".commit.json")
                assert audio_path.name == (
                    f"tts_story_{controller._tts_queue_plan.signature}.wav"
                )
                assert audio_path.is_file()
                assert metadata_path.is_file()
                assert commit_path.is_file()
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                commit = json.loads(commit_path.read_text(encoding="utf-8"))
                assert metadata["schema_version"] == SEGMENT_SCHEMA_VERSION
                assert metadata["signature"] == controller._tts_queue_plan.signature
                assert metadata["project_id"] == "worker-project"
                assert metadata["audio_path"] == str(audio_path.resolve())
                assert metadata["duration_seconds"] == 60.0
                assert len(metadata["chunks"]) == 2
                assert payload["chunks"] == metadata["chunks"]
                assert commit == {
                    "audio_filename": audio_path.name,
                    "audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest(),
                    "audio_size": audio_path.stat().st_size,
                    "metadata_filename": metadata_path.name,
                    "metadata_sha256": hashlib.sha256(
                        metadata_path.read_bytes()
                    ).hexdigest(),
                    "metadata_size": metadata_path.stat().st_size,
                    "schema_version": SEGMENT_SCHEMA_VERSION,
                    "signature": controller._tts_queue_plan.signature,
                }
                assert controller._tts_bundle["audio_path"] == str(
                    audio_path.resolve()
                )
                assert controller._tts_bundle["metadata_path"] == str(
                    metadata_path.resolve()
                )
                assert controller._tts_bundle["commit_path"] == str(
                    commit_path.resolve()
                )
                assert controller._tts_bundle["audio_sha256"] == commit[
                    "audio_sha256"
                ]
                assert controller._tts_signature == controller._tts_queue_plan.signature
        finally:
            if not harness.worker_stopped:
                harness.stop()


def test_full_bundle_failure_keeps_progressive_segments_and_is_retryable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)

        def fail_consolidation(*_args, **_kwargs):
            raise RuntimeError("fake full bundle failure")

        controller._consolidate_tts_queue_bundle = fail_consolidation
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_for_state("Failed")
                assert "fake full bundle failure" in harness.failures[-1]["detail"]
                assert sorted(controller._tts_ready_segments) == [0]
                assert controller._tts_ready_segments[0].plan.audio_path.is_file()
                assert controller._tts_queue_failure_reason == "bundle_failed"
                assert controller._tts_bundle is None
        finally:
            if not harness.worker_stopped:
                harness.stop()


def test_full_bundle_pair_publication_failures_leave_no_castable_commit_and_retry() -> None:
    for failure_stage in ("metadata", "commit"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller_module, controller, app = _controller_and_app(root)
            fake_runtime = _FakeTtsRuntime()
            harness = _QueueWorkerHarness(controller, app)
            controller.transcript_chunks = _worker_chunks(1)
            original_replace = controller_module.os.replace

            def fail_selected_replace(source, destination, *, _stage=failure_stage):
                destination_name = Path(destination).name
                is_commit = destination_name.endswith(".commit.json")
                is_metadata = (
                    destination_name.startswith("tts_story_")
                    and destination_name.endswith(".json")
                    and not is_commit
                )
                if (_stage == "metadata" and is_metadata) or (
                    _stage == "commit" and is_commit
                ):
                    raise OSError(f"injected {_stage} publication failure")
                return original_replace(source, destination)

            try:
                with _patched_tts_runtime(controller_module, fake_runtime):
                    controller_module.os.replace = fail_selected_replace
                    harness.start()
                    assert harness.wait_for_state("Failed")
                    plan = controller._tts_queue_plan
                    audio_path = Path(controller._cache_root) / (
                        f"tts_story_{plan.signature}.wav"
                    )
                    metadata_path = audio_path.with_suffix(".json")
                    commit_path = audio_path.with_suffix(".commit.json")
                    assert harness.failures[-1]["reason"] == "bundle_failed"
                    assert f"injected {failure_stage}" in harness.failures[-1][
                        "detail"
                    ]
                    assert sorted(controller._tts_ready_segments) == [0]
                    assert controller._tts_ready_segments[0].plan.audio_path.is_file()
                    assert controller._tts_bundle is None
                    assert not controller._tts_cast_ready()
                    assert not audio_path.exists()
                    assert not metadata_path.exists()
                    assert not commit_path.exists()

                    controller_module.os.replace = original_replace
                    completion_count = len(harness.completions)
                    controller._retry_tts_rendering()
                    assert harness.wait_until(
                        lambda: len(harness.completions) > completion_count
                    )
                    assert controller._tts_queue_state == "Complete"
                    assert audio_path.is_file()
                    assert metadata_path.is_file()
                    assert commit_path.is_file()
                    assert controller._tts_cast_ready()
            finally:
                controller_module.os.replace = original_replace
                if not harness.worker_stopped:
                    harness.stop()


def test_worker_rejects_wav_mutation_during_committed_hash_validation() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        controller_module, controller, app = _controller_and_app(Path(temporary))
        fake_runtime = _FakeTtsRuntime()
        harness = _QueueWorkerHarness(controller, app)
        controller.transcript_chunks = _worker_chunks(1)
        original_hash = controller._tts_bundle_file_sha256
        mutation_count = 0

        def mutate_after_hash(path: Path) -> str:
            nonlocal mutation_count
            candidate = Path(path)
            digest = original_hash(candidate)
            if (
                mutation_count == 0
                and candidate.name.startswith("tts_story_")
                and candidate.suffix == ".wav"
            ):
                before = candidate.stat()
                duration = float(candidate.read_text(encoding="utf-8"))
                replacement = f"+{int(duration)}."
                assert len(replacement.encode("utf-8")) == before.st_size
                candidate.write_text(replacement, encoding="utf-8")
                os.utime(
                    candidate,
                    ns=(
                        int(before.st_atime_ns),
                        int(before.st_mtime_ns) + 10_000_000,
                    ),
                )
                mutation_count += 1
            return digest

        controller._tts_bundle_file_sha256 = mutate_after_hash
        try:
            with _patched_tts_runtime(controller_module, fake_runtime):
                harness.start()
                assert harness.wait_until(
                    lambda: bool(harness.failures or harness.completions)
                )
                assert mutation_count == 1
                assert not harness.completions
                assert harness.failures[-1]["reason"] == "bundle_failed"
                assert controller._tts_queue_state == "Failed"
                assert sorted(controller._tts_ready_segments) == [0]
                assert controller._tts_bundle is None
                assert not controller._tts_cast_ready()
        finally:
            controller._tts_bundle_file_sha256 = original_hash
            if not harness.worker_stopped:
                harness.stop()


def main() -> int:
    tests = [
        test_plan_groups_windows_near_twenty_five_seconds,
        test_project_cache_tokens_are_safe_contained_and_stable,
        test_buffer_preferences_do_not_change_segment_signatures,
        test_voice_or_text_change_invalidates_only_affected_segments,
        test_long_window_is_not_split_even_when_it_exceeds_maximum,
        test_publication_is_atomic_and_loads_valid_ready_segment,
        test_cache_validation_rejects_invalid_metadata_and_duration_probe_failure,
        test_cache_validation_rejects_duration_mismatch_and_nonfinite_values,
        test_cache_validation_rejects_malformed_chunk_offsets,
        test_ready_seconds_sums_contiguous_buffer_after_local_offset,
        test_cache_clear_only_removes_audio_story_tts_artifacts_under_root,
        test_cache_clear_rejects_a_tts_segments_link_resolving_to_root,
        test_cache_clear_refuses_tts_segments_link_to_unrelated_data,
        test_segment_worker_starts_at_actual_buffer_and_waits_at_ahead_limit,
        test_queue_plan_building_runs_off_the_controller_thread,
        test_bundle_file_validation_never_runs_on_the_controller_thread,
        test_far_ahead_seek_prioritizes_target_then_backfills_in_story_order,
        test_segment_worker_preserves_cache_on_failure_and_retry_starts_at_missing,
        test_segment_worker_cancels_between_subchunks_without_locking_stop,
        test_replacement_job_waits_for_cancelled_worker_inference,
        test_segment_worker_uses_exported_wav_probe_duration_for_readiness,
        test_segment_worker_rejects_invalid_or_truncated_exported_wav,
        test_segment_worker_freezes_seed_kwargs_voice_and_sample_rate,
        test_settings_change_cancels_old_signature_and_retry_starts_new_plan,
        test_settings_watcher_invalidates_worker_waiting_at_ahead_limit,
        test_segment_worker_freezes_sample_rate_after_backend_init,
        test_empty_queue_start_invalidates_a_prior_waiting_worker,
        test_segment_worker_publishes_legacy_compatible_full_bundle,
        test_full_bundle_failure_keeps_progressive_segments_and_is_retryable,
        test_full_bundle_pair_publication_failures_leave_no_castable_commit_and_retry,
        test_worker_rejects_wav_mutation_during_committed_hash_validation,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
