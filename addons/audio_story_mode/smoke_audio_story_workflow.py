from __future__ import annotations

import copy
import importlib
import importlib.util
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import types
import wave
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_QT_APP = None


def _require_module(name: str):
    spec = importlib.util.find_spec(name)
    assert spec is not None, f"missing module: {name}"
    return importlib.import_module(name)


def _sample_sources(*durations: float):
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    paths = [f"chapter_{index + 1}.wav" for index in range(len(durations))]
    duration_by_name = dict(zip(paths, durations))
    return audio_sources.build_audio_sources(paths, lambda path: duration_by_name[Path(path).name])


def _write_silent_test_wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * 800)
    return path


def test_audio_sources_keep_order_deduplicate_and_offset() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    durations = {"chapter1.wav": 10.0, "chapter2.mp3": 7.5}
    sources = audio_sources.build_audio_sources(
        ["chapter1.wav", "chapter2.mp3", "chapter1.wav"],
        lambda path: durations[Path(path).name.lower()],
    )
    assert [item.display_name for item in sources] == ["chapter1.wav", "chapter2.mp3"]
    assert [
        (item.global_start_seconds, item.global_end_seconds) for item in sources
    ] == [(0.0, 10.0), (10.0, 17.5)]
    assert audio_sources.total_duration_seconds(sources) == 17.5


def test_audio_sources_retain_invalid_entries_without_advancing_offset() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")

    def duration_reader(path: str) -> float:
        if Path(path).name == "broken.wav":
            raise ValueError("unreadable media")
        return 4.0

    sources = audio_sources.build_audio_sources(
        ["first.wav", "broken.wav", "last.wav"], duration_reader
    )
    assert len(sources) == 3
    assert not sources[1].valid
    assert "unreadable" in sources[1].error
    assert sources[2].global_start_seconds == 4.0
    assert sources[2].global_end_seconds == 8.0


def test_range_and_seek_cross_chapter_boundary() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    sources = _sample_sources(10.0, 7.5)
    slices = audio_sources.split_global_range(sources, 8.0, 13.0)
    assert [
        (item.source.index, item.local_start_seconds, item.local_end_seconds)
        for item in slices
    ] == [(0, 8.0, 10.0), (1, 0.0, 3.0)]
    source, local_seconds = audio_sources.locate_global_position(sources, 12.25)
    assert source.index == 1
    assert local_seconds == 2.25


def test_exact_boundary_resolves_to_next_chapter() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    sources = _sample_sources(10.0, 7.5)
    source, local_seconds = audio_sources.locate_global_position(sources, 10.0)
    assert source.index == 1
    assert local_seconds == 0.0


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text


def _assert_raises(error_type, callable_value, match: str = "") -> None:
    try:
        callable_value()
    except error_type as exc:
        if match:
            assert match.lower() in str(exc).lower(), str(exc)
        return
    raise AssertionError(f"Expected {error_type.__name__}")


def test_normalize_segmented_stt_offsets_to_global_timeline() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    transcription = _require_module("addons.audio_story_mode.transcription_pipeline")
    source = _sample_sources(10.0, 7.5)[1]
    source_slice = audio_sources.AudioSourceSlice(
        source=source,
        local_start_seconds=2.0,
        local_end_seconds=5.0,
        global_start_seconds=12.0,
        global_end_seconds=15.0,
    )
    result = transcription.normalize_stt_result(
        [_FakeSegment(0.0, 1.0, "Hello")], object(), source_slice
    )
    assert result == [
        {
            "start": 12.0,
            "end": 13.0,
            "text": "Hello",
            "source_index": 1,
            "source_path": source.path,
            "source_start_seconds": 2.0,
            "source_end_seconds": 3.0,
        }
    ]


def test_normalize_transcript_only_stt_preserves_valid_text() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    transcription = _require_module("addons.audio_story_mode.transcription_pipeline")
    source = _sample_sources(10.0, 7.5)[1]
    source_slice = audio_sources.AudioSourceSlice(
        source=source,
        local_start_seconds=2.0,
        local_end_seconds=5.0,
        global_start_seconds=12.0,
        global_end_seconds=15.0,
    )
    result = transcription.normalize_stt_result(
        [], {"text": "Whole chapter text"}, source_slice
    )
    assert result[0]["text"] == "Whole chapter text"
    assert result[0]["start"] == 12.0
    assert result[0]["end"] == 15.0


def test_unavailable_and_empty_stt_are_failures() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    transcription = _require_module("addons.audio_story_mode.transcription_pipeline")
    source = _sample_sources(5.0)[0]
    source_slice = audio_sources.AudioSourceSlice(
        source=source,
        local_start_seconds=0.0,
        local_end_seconds=5.0,
        global_start_seconds=0.0,
        global_end_seconds=5.0,
    )
    _assert_raises(
        transcription.TranscriptionFailure,
        lambda: transcription.normalize_stt_result([], None, source_slice),
        "unavailable",
    )
    _assert_raises(
        transcription.TranscriptionFailure,
        lambda: transcription.normalize_stt_result([], {"language": "en"}, source_slice),
        "no speech",
    )


def test_transcribe_slices_runs_in_order_and_cleans_extracted_files() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    transcription = _require_module("addons.audio_story_mode.transcription_pipeline")
    slices = audio_sources.split_global_range(_sample_sources(10.0, 7.5), 8.0, 13.0)
    extracted: list[tuple[str, float, float]] = []
    transcribed: list[str] = []
    cleaned: list[str] = []
    messages: list[str] = []

    def extract_range(path: str, start: float, end: float) -> str:
        extracted.append((path, start, end))
        return f"clip_{len(extracted)}.wav"

    def transcribe_file(path: str):
        transcribed.append(path)
        return [_FakeSegment(0.0, 1.0, f"Text {len(transcribed)}")], {"language": "en"}

    result = transcription.transcribe_slices(
        slices,
        transcribe_file=transcribe_file,
        extract_range=extract_range,
        cleanup=cleaned.append,
        progress=lambda _percent, message: messages.append(message),
        cancelled=lambda: False,
    )
    assert transcribed == ["clip_1.wav", "clip_2.wav"]
    assert cleaned == transcribed
    assert [item["start"] for item in result] == [8.0, 10.0]
    assert any("file 2 of 2" in message.lower() for message in messages)


def test_transcribe_slice_preserves_mapping_result_offsets_and_cleanup() -> None:
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    transcription = _require_module("addons.audio_story_mode.transcription_pipeline")
    source_slice = audio_sources.split_global_range(
        _sample_sources(10.0, 7.5), 11.0, 13.0
    )[0]
    cleaned: list[str] = []

    result = transcription.transcribe_slice(
        source_slice,
        transcribe_file=lambda path: {
            "segments": [
                {"start": 0.25, "end": 1.0, "text": Path(path).stem}
            ]
        },
        extract_range=lambda _path, _start, _end: "chapter_2_clip.wav",
        cleanup=cleaned.append,
        progress=lambda _percent, _message: None,
        cancelled=lambda: False,
    )

    assert cleaned == ["chapter_2_clip.wav"]
    assert result == [
        {
            "start": 11.25,
            "end": 12.0,
            "text": "chapter_2_clip",
            "source_index": 1,
            "source_path": "chapter_2.wav",
            "source_start_seconds": 1.25,
            "source_end_seconds": 2.0,
        }
    ]


def _project_transcription_fixture(root: Path):
    project_models = _require_module("addons.audio_story_mode.project_models")
    project_store = _require_module("addons.audio_story_mode.project_store")
    store = project_store.StoryProjectStore(root)
    project = project_models.new_project_manifest(
        "Checkpointed story", project_id="transcription-project", now=1.0
    )
    for index, chapter_id in enumerate(("c1", "c2"), start=1):
        audio_path = _write_silent_test_wav(root / f"chapter_{index}.wav")
        chapter = project_models.new_chapter_manifest(
            f"Chapter {index}",
            {
                "path": str(audio_path),
                "fingerprint": {
                    "algorithm": "sha256-sampled-v1",
                    "digest": f"chapter-{index}",
                    "size_bytes": 100 + index,
                    "duration_ms": 10000,
                },
            },
            chapter_id=chapter_id,
            now=float(index),
        )
        project["chapters"][chapter_id] = chapter
        project["chapter_order"].append(chapter_id)
    return store, store.save_project(project)


def _project_transcription_launch_kwargs(
    controller,
    *,
    job_token: int | None = None,
    chunk_seconds: int = 8,
    start_seconds: float = 0.0,
    end_seconds: float = 20.0,
) -> dict:
    return {
        "job_token": (
            int(controller._transcription_job_id)
            if job_token is None
            else int(job_token)
        ),
        "project_generation": int(controller._story_project_generation),
        "project_input_fingerprint": str(
            controller._story_project_input_fingerprint or ""
        ),
        "chunk_seconds": int(chunk_seconds),
        "transcription_start_seconds": float(start_seconds),
        "transcription_end_seconds": float(end_seconds),
    }


def _transcription_runtime_identifier() -> dict:
    controller_module = _require_module("addons.audio_story_mode.controller")
    runtime_config = dict(controller_module.audio_story_runtime.runtime_config() or {})
    return json.loads(
        json.dumps(
            {
                "backend": runtime_config.get("stt_backend", ""),
                "model_size": runtime_config.get("stt_model_size", ""),
                "language": runtime_config.get("stt_language", ""),
                "backend_settings": runtime_config.get("stt_backend_settings", {}),
            },
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
    )


def _save_legacy_full_chapter_transcript(
    store, project: dict, chapter_id: str, *, selected_end_seconds: float = 10.0
) -> None:
    checkpointing = _require_module("addons.audio_story_mode.checkpointing")
    chapter = project["chapters"][chapter_id]
    audio_identity = dict(
        dict(chapter.get("audio_reference") or {}).get("fingerprint") or {}
    )
    input_fingerprint = checkpointing.settings_fingerprint(
        {
            "audio_identity": audio_identity,
            "transcription_range": {
                "start_seconds": 0.0,
                "end_seconds": 20.0,
            },
            "selected_range": {
                "start_seconds": 0.0,
                "end_seconds": selected_end_seconds,
            },
            "chunk_seconds": 8,
            "stt_runtime": _transcription_runtime_identifier(),
        }
    )
    transcript = {
        "schema_version": 1,
        "project_id": project["project_id"],
        "chapter_id": chapter_id,
        "input_fingerprint": input_fingerprint,
        "chunk_seconds": 8,
        "transcription_start_seconds": 0.0,
        "transcription_end_seconds": 20.0,
        "selected_range": {
            "start_seconds": 0.0,
            "end_seconds": selected_end_seconds,
        },
        "segments": [
            {
                "start_seconds": 0.0,
                "end_seconds": min(1.0, selected_end_seconds),
                "text": f"Stored {chapter_id}",
                "source_path": str(
                    dict(chapter.get("audio_reference") or {}).get("path") or ""
                ),
            }
        ],
    }
    reference = store.save_chapter_document(
        project["project_id"], chapter_id, "transcript", 1, transcript
    )
    checkpoint = chapter["stages"]["transcription"]
    checkpoint.update(
        {
            "status": "completed",
            "input_fingerprint": input_fingerprint,
            "expected_input_fingerprint": input_fingerprint,
            "output_fingerprint": checkpointing.settings_fingerprint(transcript),
            "output_ref": reference,
            "attempt_count": 1,
        }
    )


def _twenty_one_chapter_transcription_fixture(*, completed_count: int = 2):
    project_models = _require_module("addons.audio_story_mode.project_models")
    project_store = _require_module("addons.audio_story_mode.project_store")
    directory = tempfile.TemporaryDirectory()
    store = project_store.StoryProjectStore(Path(directory.name))
    project = project_models.new_project_manifest(
        "Twenty one chapters", project_id="twenty-one-transcription", now=1.0
    )
    for index in range(1, 22):
        chapter_id = f"c{index}"
        audio_path = _write_silent_test_wav(
            Path(directory.name) / f"chapter_{index}.wav"
        )
        chapter = project_models.new_chapter_manifest(
            f"Chapter {index}",
            {
                "path": str(audio_path),
                "fingerprint": {
                    "algorithm": "sha256-sampled-v1",
                    "digest": f"chapter-{index}",
                    "size_bytes": 100 + index,
                    "duration_ms": 10000,
                },
            },
            chapter_id=chapter_id,
            now=float(index),
        )
        project["chapters"][chapter_id] = chapter
        project["chapter_order"].append(chapter_id)
    for chapter_id in project["chapter_order"][:completed_count]:
        _save_legacy_full_chapter_transcript(store, project, chapter_id)
    project = store.save_project(project)
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._story_project_store = store
    controller.current_story_project_id = project["project_id"]
    controller._current_story_project = store.load_project(project["project_id"])
    controller._transcription_job_id = 1
    controller._story_project_generation = 1
    controller._story_project_input_fingerprint = "twenty-one-project-input"
    controller._test_temporary_directory = directory
    return controller, store, project, []


def test_project_default_transcription_ignores_stale_range_and_reuses_completed() -> None:
    controller, _store, project, transcribed = _twenty_one_chapter_transcription_fixture()
    controller._stored_transcription_start_seconds = 0
    controller._stored_transcription_end_seconds = 16
    controller._stored_selected_range_enabled = False
    try:
        documents = controller._run_project_transcription_units(
            project["project_id"],
            list(project["chapter_order"]),
            selected_range_enabled=False,
            **_project_transcription_launch_kwargs(controller, end_seconds=16.0),
            transcribe_file=lambda path: transcribed.append(Path(path).name)
            or {
                "segments": [
                    {"start": 0.0, "end": 10.0, "text": Path(path).stem}
                ]
            },
        )
    finally:
        controller.shutdown()
        controller._test_temporary_directory.cleanup()

    assert len(documents) == 21
    assert transcribed == [f"chapter_{index}.wav" for index in range(3, 22)]


def test_project_selected_range_remains_explicit_and_limited() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller, _store, project, transcribed = _twenty_one_chapter_transcription_fixture(
        completed_count=0
    )
    extracted_source_names: dict[str, str] = {}

    class _ExtractedAudio:
        def __init__(self, source_path: str):
            self._source_path = source_path

        def __getitem__(self, _slice):
            return self

        def export(self, path: str, *, format: str) -> None:
            assert format == "wav"
            Path(path).touch()
            extracted_source_names[str(path)] = Path(self._source_path).name

    original_audio_from_file = controller_module.audio_story_runtime.audio_from_file
    controller_module.audio_story_runtime.audio_from_file = (
        lambda path: _ExtractedAudio(path)
    )
    try:
        controller._run_project_transcription_units(
            project["project_id"],
            list(project["chapter_order"]),
            selected_range_enabled=True,
            transcription_start_seconds=12.0,
            transcription_end_seconds=28.0,
            job_token=controller._transcription_job_id,
            project_generation=controller._story_project_generation,
            project_input_fingerprint=controller._story_project_input_fingerprint,
            chunk_seconds=8,
            transcribe_file=lambda path: transcribed.append(
                extracted_source_names.get(str(path), Path(path).name)
            )
            or {"segments": [{"start": 0.0, "end": 1.0, "text": "selected"}]},
        )
    finally:
        controller_module.audio_story_runtime.audio_from_file = original_audio_from_file
        controller.shutdown()
        controller._test_temporary_directory.cleanup()

    assert transcribed == ["chapter_2.wav", "chapter_3.wav"]


def test_project_default_transcription_regenerates_partial_legacy_checkpoint() -> None:
    controller, store, project, transcribed = _twenty_one_chapter_transcription_fixture(
        completed_count=1
    )
    _save_legacy_full_chapter_transcript(store, project, "c2", selected_end_seconds=6.0)
    project = store.save_project(project)
    controller._current_story_project = store.load_project(project["project_id"])
    try:
        controller._run_project_transcription_units(
            project["project_id"],
            list(project["chapter_order"]),
            selected_range_enabled=False,
            **_project_transcription_launch_kwargs(controller, end_seconds=16.0),
            transcribe_file=lambda path: transcribed.append(Path(path).name)
            or {"segments": [{"start": 0.0, "end": 10.0, "text": Path(path).stem}]},
        )
    finally:
        controller.shutdown()
        controller._test_temporary_directory.cleanup()

    assert transcribed[0] == "chapter_2.wav"
    assert "chapter_1.wav" not in transcribed


def test_project_switch_resets_selected_range_before_new_audio_hydration() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    project_models = _require_module("addons.audio_story_mode.project_models")

    class _FakeCheckBox:
        def __init__(self):
            self.checked = False

        @staticmethod
        def blockSignals(_blocked: bool) -> None:
            return None

        def setChecked(self, checked: bool) -> None:
            self.checked = bool(checked)

        def isChecked(self) -> bool:
            return self.checked

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        def make_project(project_id: str, filename: str) -> dict:
            path = root / filename
            path.write_bytes(b"valid audio")
            project = project_models.new_project_manifest(
                project_id, project_id=project_id, now=1.0
            )
            chapter_id = f"{project_id}-chapter"
            project["chapters"][chapter_id] = project_models.new_chapter_manifest(
                "Chapter",
                {
                    "path": str(path),
                    "fingerprint": {
                        "algorithm": "sha256-sampled-v1",
                        "digest": project_id,
                        "size_bytes": path.stat().st_size,
                        "duration_ms": 10000,
                    },
                },
                chapter_id=chapter_id,
                now=1.0,
            )
            project["chapter_order"].append(chapter_id)
            return project

        project_a = make_project("project-a", "a.wav")
        project_b = make_project("project-b", "b.wav")
        controller = controller_module.AudioStoryModeController(context=None)
        controller.current_story_project_id = "project-a"
        controller._current_story_project = project_a
        controller._stored_selected_range_enabled = True
        controller._stored_transcription_start_seconds = 4
        controller._stored_transcription_end_seconds = 7
        controller.audio_story_selected_range_checkbox = _FakeCheckBox()
        controller.audio_story_transcription_start_spin = _FakeSlider()
        controller.audio_story_transcription_end_spin = _FakeSlider()
        try:
            controller._apply_open_story_project(project_b)
            assert controller.current_story_project_id == "project-b"
            assert controller._stored_selected_range_enabled is False
            assert not controller.audio_story_selected_range_checkbox.isChecked()
            assert not controller.audio_story_transcription_start_spin.isEnabled()
            assert not controller.audio_story_transcription_end_spin.isEnabled()
            assert controller._transcription_scope_snapshot() == (False, 0.0, 10.0)
        finally:
            controller.shutdown()


def test_project_transcription_missing_or_unreadable_middle_chapter_recovers_in_order() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    project_models = _require_module("addons.audio_story_mode.project_models")
    project_store = _require_module("addons.audio_story_mode.project_store")

    for failure_mode in ("missing", "unreadable"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = project_store.StoryProjectStore(root / "projects")
            project = project_models.new_project_manifest(
                f"Three chapters {failure_mode}",
                project_id=f"three-chapter-{failure_mode}",
                now=1.0,
            )
            audio_paths = []
            for index in range(1, 4):
                path = root / f"chapter_{index}.wav"
                path.write_bytes(f"chapter-{index}".encode("utf-8"))
                audio_paths.append(path)
                chapter_id = f"c{index}"
                project["chapters"][chapter_id] = project_models.new_chapter_manifest(
                    f"Chapter {index}",
                    {
                        "path": str(path),
                        "fingerprint": {
                            "algorithm": "sha256-sampled-v1",
                            "digest": f"chapter-{index}",
                            "size_bytes": path.stat().st_size,
                            "duration_ms": 10000,
                        },
                    },
                    chapter_id=chapter_id,
                    now=float(index),
                )
                project["chapter_order"].append(chapter_id)
            _save_legacy_full_chapter_transcript(store, project, "c1")
            project = store.save_project(project)
            if failure_mode == "missing":
                audio_paths[1].unlink()

            controller = controller_module.AudioStoryModeController(context=None)
            controller._story_project_store = store
            controller.current_story_project_id = project["project_id"]
            controller._current_story_project = store.load_project(project["project_id"])
            controller._transcription_job_id = 1
            controller._story_project_generation = 1
            controller._story_project_input_fingerprint = "three-chapter-input"
            original_duration = controller_module.audio_story_runtime.audio_duration_seconds
            unreadable = failure_mode == "unreadable"
            transcribed = []

            def validate_audio(path: str) -> float:
                if Path(path) == audio_paths[1] and unreadable:
                    raise RuntimeError("decoder rejected this audio")
                if not Path(path).is_file():
                    raise FileNotFoundError("source file is missing")
                return 10.0

            controller_module.audio_story_runtime.audio_duration_seconds = validate_audio
            try:
                try:
                    controller._run_project_transcription_units(
                        project["project_id"],
                        list(project["chapter_order"]),
                        selected_range_enabled=False,
                        **_project_transcription_launch_kwargs(
                            controller, end_seconds=30.0
                        ),
                        transcribe_file=lambda path: transcribed.append(
                            Path(path).name
                        )
                        or {
                            "segments": [
                                {"start": 0.0, "end": 10.0, "text": Path(path).stem}
                            ]
                        },
                    )
                except controller_module.TranscriptionFailure as exc:
                    detail = str(exc)
                else:
                    raise AssertionError("invalid middle chapter did not fail")

                assert "Chapter 2" in detail
                assert "restore" in detail.casefold() or "relink" in detail.casefold()
                assert transcribed == []
                failed_project = store.load_project(project["project_id"])
                statuses = [
                    failed_project["chapters"][chapter_id]["stages"]["transcription"][
                        "status"
                    ]
                    for chapter_id in project["chapter_order"]
                ]
                assert statuses == ["completed", "failed", "pending"]
                assert "Chapter 2" in failed_project["chapters"]["c2"]["stages"][
                    "transcription"
                ]["error"]

                if failure_mode == "missing":
                    audio_paths[1].write_bytes(b"chapter-2-restored")
                unreadable = False
                combined = controller._run_project_transcription_units(
                    project["project_id"],
                    list(project["chapter_order"]),
                    selected_range_enabled=False,
                    **_project_transcription_launch_kwargs(
                        controller, end_seconds=30.0
                    ),
                    transcribe_file=lambda path: transcribed.append(Path(path).name)
                    or {
                        "segments": [
                            {"start": 0.0, "end": 10.0, "text": Path(path).stem}
                        ]
                    },
                )
                assert transcribed == ["chapter_2.wav", "chapter_3.wav"]
                assert len(combined) == 3
                recovered = store.load_project(project["project_id"])
                assert [
                    recovered["chapters"][chapter_id]["stages"]["transcription"][
                        "status"
                    ]
                    for chapter_id in project["chapter_order"]
                ] == ["completed", "completed", "completed"]
            finally:
                controller_module.audio_story_runtime.audio_duration_seconds = (
                    original_duration
                )
                controller.shutdown()


def _project_analysis_fixture(root: Path):
    checkpointing = _require_module("addons.audio_story_mode.checkpointing")
    store, project = _project_transcription_fixture(root)
    for index, chapter_id in enumerate(("c1", "c2"), start=1):
        transcript = {
            "schema_version": 1,
            "project_id": project["project_id"],
            "chapter_id": chapter_id,
            "input_fingerprint": f"transcript-input-{index}",
            "chunk_seconds": 8,
            "transcription_start_seconds": 0.0,
            "transcription_end_seconds": 10.0,
            "selected_range": {"start_seconds": 0.0, "end_seconds": 10.0},
            "segments": [
                {
                    "start_seconds": 1.0,
                    "end_seconds": 2.0,
                    "text": f"Chapter {index} text",
                    "source_path": f"chapter_{index}.wav",
                }
            ],
        }
        reference = store.save_chapter_document(
            project["project_id"], chapter_id, "transcript", 1, transcript
        )
        output_fingerprint = checkpointing.settings_fingerprint(transcript)
        for stage in ("transcription", "transcript_combination"):
            stage_checkpoint = project["chapters"][chapter_id]["stages"][stage]
            stage_checkpoint.update(
                {
                    "status": "completed",
                    "input_fingerprint": f"{stage}-input-{index}",
                    "expected_input_fingerprint": f"{stage}-input-{index}",
                    "output_fingerprint": output_fingerprint,
                    "output_ref": reference,
                }
            )
    return store, store.save_project(project)


def _analysis_result(request: dict, *, chapter_id: str, story_update: dict) -> dict:
    raw_segments = [dict(item) for item in list(request.get("raw_segments") or [])]
    first = raw_segments[0]
    return {
        "job_id": int(request.get("job_id", 0) or 0),
        "audio_path": str(request.get("path") or ""),
        "audio_duration_seconds": float(request.get("audio_duration", 0.0) or 0.0),
        "chunk_seconds": int(request.get("chunk_seconds", 8) or 8),
        "transcription_start_seconds": 0,
        "transcription_end_seconds": 10,
        "image_frequency_seconds": int(request.get("image_frequency_seconds", 12) or 12),
        "image_timing_mode": "fixed_interval",
        "continuity_strength": float(request.get("continuity_strength", 0.8) or 0.8),
        "transcript_chunks": [
            {
                "index": 0,
                "start_seconds": float(first["start_seconds"]),
                "end_seconds": float(first["end_seconds"]),
                "text": str(first["text"]),
            }
        ],
        "transcript_windows": [
            {
                "start_seconds": float(first["start_seconds"]),
                "end_seconds": float(first["end_seconds"]),
                "text": str(first["text"]),
            }
        ],
        "full_text": str(first["text"]),
        "story_style_guide": "",
        "story_bible": {"characters": {}},
        "project_story_memory": story_update,
        "scene_plan": [
            {
                "chunk_index": 0,
                "scene_index": 1,
                "scene_id": f"scene-{chapter_id}",
                "start_seconds": float(first["start_seconds"]),
                "end_seconds": float(first["end_seconds"]),
            }
        ],
        "character_anchors": {},
        "location_anchors": {},
        "raw_segments": raw_segments,
    }


def _project_image_fixture(root: Path):
    checkpointing = _require_module("addons.audio_story_mode.checkpointing")
    project_models = _require_module("addons.audio_story_mode.project_models")
    project_store = _require_module("addons.audio_story_mode.project_store")
    store = project_store.StoryProjectStore(root / "projects")
    audio_path = root / "chapter.wav"
    audio_path.write_bytes(b"fake-audio")
    project = project_models.new_project_manifest(
        "Image recovery", project_id="image-project", now=1.0
    )
    chapter = project_models.new_chapter_manifest(
        "Chapter 1",
        {
            "path": str(audio_path),
            "fingerprint": {
                "algorithm": "sha256-sampled-v1",
                "digest": "image-chapter",
                "size_bytes": audio_path.stat().st_size,
                "duration_ms": 20000,
            },
        },
        chapter_id="chapter-1",
        now=1.0,
    )
    project["chapters"][chapter["chapter_id"]] = chapter
    project["chapter_order"] = [chapter["chapter_id"]]
    project = store.save_project(project)
    transcript = {
        "segments": [
            {"start_seconds": 0.0, "end_seconds": 10.0, "text": "Scene one"},
            {"start_seconds": 10.0, "end_seconds": 20.0, "text": "Scene two"},
        ]
    }
    transcript_ref = store.save_chapter_document(
        project["project_id"], chapter["chapter_id"], "transcript", 1, transcript
    )
    analysis_ref = store.save_chapter_document(
        project["project_id"],
        chapter["chapter_id"],
        "analysis",
        1,
        {"scene_plan": [{"scene_id": "scene-1"}, {"scene_id": "scene-2"}]},
    )
    project = store.load_project(project["project_id"])
    chapter = project["chapters"][chapter["chapter_id"]]
    for stage in (
        "audio_validation",
        "transcription",
        "transcript_combination",
        "story_analysis",
        "scene_planning",
    ):
        checkpoint = chapter["stages"][stage]
        fingerprint = f"{stage}-current"
        checkpoint.update(
            {
                "status": "completed",
                "input_fingerprint": fingerprint,
                "expected_input_fingerprint": fingerprint,
                "output_fingerprint": f"{stage}-output",
                "output_ref": (
                    transcript_ref
                    if stage in {"transcription", "transcript_combination"}
                    else analysis_ref
                ),
            }
        )
    project = store.save_project(project)
    chunks = [
        {
            "index": 0,
            "chapter_id": "chapter-1",
            "scene_id": "scene-1",
            "scene_index": 1,
            "start_seconds": 0.0,
            "end_seconds": 10.0,
            "text": "Scene one",
            "prompt": "A moonlit bridge",
        },
        {
            "index": 1,
            "chapter_id": "chapter-1",
            "scene_id": "scene-2",
            "scene_index": 2,
            "start_seconds": 10.0,
            "end_seconds": 20.0,
            "text": "Scene two",
            "prompt": "A lantern in the rain",
        },
    ]
    return store, project, chunks


def _configured_project_image_controller(store, project: dict, chunks: list[dict]):
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._story_project_store = store
    controller.current_story_project_id = str(project["project_id"])
    controller._current_story_project = copy.deepcopy(project)
    controller._story_project_generation = 7
    controller._story_project_input_fingerprint = "image-project-input"
    controller._image_generation_token = 11
    controller.transcript_chunks = copy.deepcopy(chunks)
    controller.scene_plan = copy.deepcopy(chunks)
    controller._visual_reply_set_state = lambda _state: True

    def save_snapshot(snapshot: dict) -> None:
        saved = store.save_project(snapshot)
        controller._current_story_project = copy.deepcopy(saved)

    controller._queue_story_project_autosave = save_snapshot
    return controller


def _owned_image_payload(controller, index: int, image_path: Path) -> dict:
    chunk = controller.transcript_chunks[index]
    return {
        "token": int(controller._image_generation_token),
        "project_id": str(controller.current_story_project_id),
        "project_generation": int(controller._story_project_generation),
        "input_fingerprint": str(controller._story_project_input_fingerprint),
        "index": int(index),
        "image_path": str(image_path),
        "prompt_text": str(chunk["prompt"]),
        "source_text": str(chunk["text"]),
        "prompt_signature": f"prompt-signature-{index + 1}",
        "generation_mode": "fresh",
        "reference_image_paths": [],
    }


def _prepared_owned_image_payload(controller, index: int, image_path: Path) -> dict:
    payload = _owned_image_payload(controller, index, image_path)
    prepared = controller._prepare_story_image_artifact(payload)
    assert prepared is not None
    payload["prepared_image"] = prepared
    payload["image_path"] = str(prepared["image_path"])
    return payload


def test_project_images_persist_retry_exact_scene_and_restore_without_provider_calls() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store, project, chunks = _project_image_fixture(root)
        controller = _configured_project_image_controller(store, project, chunks)
        first_provider_output = root / "provider-cache" / "scene-one.png"
        first_provider_output.parent.mkdir(parents=True)
        first_provider_output.write_bytes(b"scene-one-image")
        ownership_mismatches = {
            "token": int(controller._image_generation_token) + 1,
            "project_id": "other-project",
            "project_generation": int(controller._story_project_generation) + 1,
            "input_fingerprint": "stale-project-input",
        }
        for field, stale_value in ownership_mismatches.items():
            stale_payload = _owned_image_payload(
                controller, 0, first_provider_output
            )
            stale_payload[field] = stale_value
            controller._on_image_ready(stale_payload)
            assert controller._image_cache == {}
            assert "scene_checkpoints" not in controller._current_story_project[
                "chapters"
            ]["chapter-1"]
        project_models = _require_module("addons.audio_story_mode.project_models")
        stale_scene_checkpoint = project_models.checkpoint(
            "image_generation", "scene-1", status="running"
        )
        stale_scene_checkpoint["input_fingerprint"] = "stale-scene-input"
        stale_scene_checkpoint["expected_input_fingerprint"] = "stale-scene-input"
        controller._current_story_project["chapters"]["chapter-1"][
            "scene_checkpoints"
        ] = {"scene-1": stale_scene_checkpoint}
        controller._on_image_ready(
            _owned_image_payload(controller, 0, first_provider_output)
        )
        owned_image_directory = (
            store.project_path(project["project_id"]).parent
            / "chapters"
            / "chapter-1"
            / "images"
        )
        assert not owned_image_directory.exists()
        controller._current_story_project = copy.deepcopy(project)

        controller._on_image_ready(
            _prepared_owned_image_payload(controller, 0, first_provider_output)
        )
        second_failure = _owned_image_payload(
            controller, 1, root / "provider-cache" / "scene-two.png"
        )
        second_failure.update(
            {
                "detail": "content moderation rejected api_key=secret-value",
                "moderated": True,
            }
        )
        statuses = []
        controller._set_status = statuses.append
        controller._visual_reply_generation_info = lambda: {"provider": "xai"}
        controller._visual_reply_current_state = lambda: {"image_path": ""}
        controller._on_image_failed(second_failure)

        checkpointed = copy.deepcopy(controller._current_story_project)
        scene_one = checkpointed["chapters"]["chapter-1"]["scene_checkpoints"][
            "scene-1"
        ]
        scene_two = checkpointed["chapters"]["chapter-1"]["scene_checkpoints"][
            "scene-2"
        ]
        owned_scene_one = store.project_path(project["project_id"]).parent / str(
            scene_one["output_ref"]
        )
        assert owned_scene_one.is_file()
        assert owned_scene_one.read_bytes() == b"scene-one-image"
        assert scene_one["status"] == "completed"
        assert scene_two["status"] == "failed"
        assert "secret-value" not in str(scene_two["error"])
        assert any("moderation" in message.lower() for message in statuses)
        checkpointing = _require_module("addons.audio_story_mode.checkpointing")
        assert checkpointing.build_resume_plan(checkpointed) == [
            {
                "chapter_id": "chapter-1",
                "stage": "image_generation",
                "unit_id": "scene-2",
            }
        ]

        retry_scene_ids = []

        def capture_retry(_token, start_index, _end_index, *args, **kwargs):
            requested = kwargs.get("requested_indices") or (start_index,)
            retry_scene_ids.extend(
                str(controller.transcript_chunks[int(index)]["scene_id"])
                for index in requested
            )

        controller._run_visual_generation = capture_retry
        invalid = copy.deepcopy(controller._current_story_project)
        invalid["chapters"]["chapter-1"]["stages"]["scene_planning"][
            "status"
        ] = "stale"
        controller._current_story_project = invalid
        controller._retry_story_scene("scene-2", chapter_id="chapter-1")
        time.sleep(0.02)
        assert retry_scene_ids == []
        controller._current_story_project = checkpointed
        controller._retry_story_scene("scene-2", chapter_id="chapter-1")
        deadline = time.monotonic() + 1.0
        while not retry_scene_ids and time.monotonic() < deadline:
            time.sleep(0.005)
        assert retry_scene_ids == ["scene-2"]
        assert controller._current_story_project["chapters"]["chapter-1"][
            "scene_checkpoints"
        ]["scene-1"]["status"] == "completed"
        assert controller._current_story_project["chapters"]["chapter-1"][
            "scene_checkpoints"
        ]["scene-2"]["status"] == "running"
        second_provider_output = root / "provider-cache" / "scene-two.png"
        second_provider_output.write_bytes(b"scene-two-image")
        controller._on_image_ready(
            _prepared_owned_image_payload(controller, 1, second_provider_output)
        )
        completed_project = copy.deepcopy(controller._current_story_project)
        completed_scene_two = completed_project["chapters"]["chapter-1"][
            "scene_checkpoints"
        ]["scene-2"]
        assert completed_scene_two["status"] == "completed"
        assert checkpointing.build_resume_plan(completed_project) == []
        owned_scene_two = store.project_path(project["project_id"]).parent / str(
            completed_scene_two["output_ref"]
        )
        assert owned_scene_two.read_bytes() == b"scene-two-image"

        reopened_controller = _require_module(
            "addons.audio_story_mode.controller"
        ).AudioStoryModeController(context=None)
        reopened_controller._story_project_store = store
        provider_calls_after_reopen = []
        reopened_controller._generate_visual_image = (
            lambda *_args, **_kwargs: provider_calls_after_reopen.append("provider")
        )
        try:
            reopened_controller._apply_open_story_project(
                store.load_project(project["project_id"])
            )
            restored = reopened_controller._image_cache[0]
            assert Path(restored["image_path"]).resolve() == owned_scene_one.resolve()
            assert Path(
                reopened_controller._image_cache[1]["image_path"]
            ).resolve() == owned_scene_two.resolve()
            assert provider_calls_after_reopen == []
        finally:
            reopened_controller.shutdown()
            controller.shutdown()


def test_real_project_image_worker_failures_checkpoint_exact_resume_work() -> None:
    checkpointing = _require_module("addons.audio_story_mode.checkpointing")
    with tempfile.TemporaryDirectory() as directory:
        store, project, chunks = _project_image_fixture(Path(directory))
        controller = _configured_project_image_controller(store, project, chunks)
        controller._set_status = lambda _message: None
        controller._visual_reply_current_state = lambda: {"image_path": ""}
        failure_details = {
            0: "provider request failed api_key=secret-value",
            1: "content moderation rejected api_key=secret-value",
        }

        def fail_generation(
            _prompt_text: str,
            *,
            index: int,
            scene_entry=None,
            cache_result: bool = True,
        ):
            del scene_entry, cache_result
            raise RuntimeError(failure_details[index])

        controller._generate_visual_image = fail_generation
        ownership = controller._story_image_launch_ownership(
            controller._image_generation_token
        )
        try:
            for index in range(len(chunks)):
                controller._run_visual_generation(
                    controller._image_generation_token,
                    index,
                    index,
                    ownership=ownership,
                    requested_indices=(index,),
                )

            checkpoints = controller._current_story_project["chapters"][
                "chapter-1"
            ]["scene_checkpoints"]
            assert checkpoints["scene-1"]["status"] == "failed"
            assert checkpoints["scene-2"]["status"] == "failed"
            assert "secret-value" not in checkpoints["scene-1"]["error"]
            assert "secret-value" not in checkpoints["scene-2"]["error"]
            assert checkpointing.build_resume_plan(
                controller._current_story_project
            ) == [
                {
                    "chapter_id": "chapter-1",
                    "stage": "image_generation",
                    "unit_id": "scene-1",
                },
                {
                    "chapter_id": "chapter-1",
                    "stage": "image_generation",
                    "unit_id": "scene-2",
                },
            ]
        finally:
            controller.shutdown()


def test_stale_project_provider_output_is_not_cached_or_reused() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store, project, chunks = _project_image_fixture(root)
        controller = _configured_project_image_controller(store, project, chunks)
        stale_provider_output = root / "provider-cache" / "stale.png"
        current_provider_output = root / "provider-cache" / "current.png"
        stale_provider_output.parent.mkdir(parents=True)
        stale_provider_output.write_bytes(b"stale-provider-image")
        current_provider_output.write_bytes(b"current-provider-image")
        controller._visual_reply_generation_info = lambda: {
            "enabled": True,
            "generation_available": True,
            "provider": "xai",
            "model": "test-image-model",
            "response_format": "b64_json",
        }
        provider_calls = []

        def generate_fresh(_prompt_text: str, *, index: int):
            provider_calls.append(index)
            if len(provider_calls) == 1:
                controller._image_generation_token += 1
                return {"image_path": str(stale_provider_output)}
            return {"image_path": str(current_provider_output)}

        controller._generate_visual_image_from_fresh = generate_fresh
        stale_token = int(controller._image_generation_token)
        stale_ownership = controller._story_image_launch_ownership(stale_token)
        try:
            controller._run_visual_generation(
                stale_token,
                0,
                0,
                ownership=stale_ownership,
                requested_indices=(0,),
            )
            assert provider_calls == [0]
            assert controller._image_cache == {}
            assert controller._prompt_image_cache == {}
            assert "scene_checkpoints" not in controller._current_story_project[
                "chapters"
            ]["chapter-1"]

            current_token = int(controller._image_generation_token)
            controller._run_visual_generation(
                current_token,
                0,
                0,
                ownership=controller._story_image_launch_ownership(current_token),
                requested_indices=(0,),
            )
            assert provider_calls == [0, 0]
            checkpoint = controller._current_story_project["chapters"][
                "chapter-1"
            ]["scene_checkpoints"]["scene-1"]
            assert checkpoint["status"] == "completed"
            owned_path = store.project_path(project["project_id"]).parent / str(
                checkpoint["output_ref"]
            )
            assert owned_path.read_bytes() == b"current-provider-image"
            assert controller._image_cache[0]["image_path"] == str(owned_path)
            assert all(
                str(entry.get("image_path") or "") == str(owned_path)
                for entry in controller._prompt_image_cache.values()
            )
        finally:
            controller.shutdown()


def test_project_image_persistence_failure_is_failed_not_durable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store, project, chunks = _project_image_fixture(root)
        controller = _configured_project_image_controller(store, project, chunks)
        provider_output = root / "provider-cache" / "temporary.png"
        provider_output.parent.mkdir(parents=True)
        provider_output.write_bytes(b"temporary-provider-image")
        original_persist = store.persist_project_image_attempt
        store.persist_project_image_attempt = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("disk full api_key=secret-value")
        )
        controller._generate_visual_image = lambda *_args, **_kwargs: {
            "image_path": str(provider_output),
            "prompt_signature": "persistence-failure",
            "generation_mode": "fresh",
            "reference_image_paths": [],
        }
        visual_states = []
        controller._visual_reply_set_state = lambda state: visual_states.append(
            dict(state)
        ) or True
        controller._pending_play_request = {
            "token": int(controller._image_generation_token),
            "index": 0,
            "position_seconds": 0.0,
            "status_text": "Playing",
        }
        try:
            token = int(controller._image_generation_token)
            controller._run_visual_generation(
                token,
                0,
                0,
                ownership=controller._story_image_launch_ownership(token),
                requested_indices=(0,),
            )
            app = _qt_application()
            for _ in range(5):
                app.processEvents()
            checkpoint = controller._current_story_project["chapters"]["chapter-1"][
                "scene_checkpoints"
            ]["scene-1"]
            assert checkpoint["status"] == "failed"
            assert checkpoint["output_ref"] == ""
            assert "secret-value" not in checkpoint["error"]
            assert 0 not in controller._image_cache
            assert all(
                str(entry.get("image_path") or "") != str(provider_output)
                for entry in controller._prompt_image_cache.values()
            )
            assert controller._pending_play_request is None
            assert visual_states[-1]["status"] == "error"
            assert visual_states[-1]["image_path"] == ""
        finally:
            store.persist_project_image_attempt = original_persist
            controller.shutdown()


def test_legacy_visual_reply_generation_contract_remains_unchanged() -> None:
    with tempfile.TemporaryDirectory() as directory:
        image_path = Path(directory) / "legacy-provider.png"
        image_path.write_bytes(b"legacy-image")
        controller = _require_module(
            "addons.audio_story_mode.controller"
        ).AudioStoryModeController(context=None)
        controller._image_generation_token = 5
        controller._image_generation_worker_running = True
        controller._current_chunk_index = 0
        controller.transcript_chunks = [
            {
                "index": 0,
                "scene_id": "legacy-scene",
                "scene_index": 1,
                "text": "Legacy source",
                "prompt": "Legacy prompt",
            }
        ]
        controller.scene_plan = copy.deepcopy(controller.transcript_chunks)
        provider_calls = []
        visual_states = []

        def generate(prompt_text: str, *, index: int, scene_entry=None):
            provider_calls.append((prompt_text, index))
            return {
                "image_path": str(image_path),
                "prompt_text": prompt_text,
                "prompt_signature": "legacy-signature",
                "generation_mode": "fresh",
                "reference_image_paths": [],
            }

        controller._generate_visual_image = generate
        controller._visual_reply_set_state = lambda state: visual_states.append(
            dict(state)
        ) or True
        try:
            controller._run_visual_generation(5, 0, 0)
            assert provider_calls == [("Legacy prompt", 0)]
            assert controller._image_cache[0]["image_path"] == str(image_path)
            assert any(
                state.get("status") == "ready"
                and state.get("image_path") == str(image_path)
                for state in visual_states
            )
        finally:
            controller.shutdown()


def test_project_image_copy_hash_runs_off_gui_and_rechecks_exact_ownership() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store, project, chunks = _project_image_fixture(root)
        controller = _configured_project_image_controller(store, project, chunks)
        provider_output = root / "provider-cache" / "worker.png"
        provider_output.parent.mkdir(parents=True)
        provider_output.write_bytes(b"worker-image")
        controller._generate_visual_image = lambda *_args, **_kwargs: {
            "image_path": str(provider_output),
            "prompt_signature": "worker-signature",
            "generation_mode": "fresh",
            "reference_image_paths": [],
        }
        gui_thread_id = threading.get_ident()
        persistence_threads: list[int] = []
        original = store.persist_project_image_attempt

        def capture_thread(*args, **kwargs):
            persistence_threads.append(threading.get_ident())
            return original(*args, **kwargs)

        store.persist_project_image_attempt = capture_thread
        token = int(controller._image_generation_token)
        worker = threading.Thread(
            target=controller._run_visual_generation,
            args=(token, 0, 0),
            kwargs={
                "ownership": controller._story_image_launch_ownership(token),
                "requested_indices": (0,),
            },
        )
        try:
            worker.start()
            deadline = time.monotonic() + 2.0
            app = _qt_application()
            while worker.is_alive() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            worker.join(0.2)
            for _ in range(5):
                app.processEvents()
            assert not worker.is_alive()
            assert persistence_threads and all(
                thread_id != gui_thread_id for thread_id in persistence_threads
            )
            checkpoint = controller._current_story_project["chapters"]["chapter-1"][
                "scene_checkpoints"
            ]["scene-1"]
            assert checkpoint["status"] == "completed"

            stale_output = root / "provider-cache" / "stale-after-copy.png"
            stale_output.write_bytes(b"stale-after-copy")
            controller._generate_visual_image = lambda *_args, **_kwargs: {
                "image_path": str(stale_output),
                "prompt_signature": "stale-signature",
                "generation_mode": "fresh",
                "reference_image_paths": [],
            }

            def supersede_after_copy(*args, **kwargs):
                result = original(*args, **kwargs)
                controller._image_generation_token += 1
                return result

            store.persist_project_image_attempt = supersede_after_copy
            prior = copy.deepcopy(controller._current_story_project)
            stale_token = int(controller._image_generation_token)
            controller._run_visual_generation(
                stale_token,
                1,
                1,
                ownership=controller._story_image_launch_ownership(stale_token),
                requested_indices=(1,),
            )
            for _ in range(3):
                app.processEvents()
            assert controller._current_story_project == prior
        finally:
            store.persist_project_image_attempt = original
            controller.shutdown()


def test_failed_image_replacement_restores_previous_durable_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store, project, chunks = _project_image_fixture(root)
        controller = _configured_project_image_controller(store, project, chunks)
        provider_output = root / "provider-cache" / "prior.png"
        provider_output.parent.mkdir(parents=True)
        provider_output.write_bytes(b"prior-durable-image")
        try:
            controller._on_image_ready(
                _prepared_owned_image_payload(controller, 0, provider_output)
            )
            prior = copy.deepcopy(
                controller._current_story_project["chapters"]["chapter-1"][
                    "scene_checkpoints"
                ]["scene-1"]
            )
            prior_path = store.project_path(project["project_id"]).parent / prior[
                "output_ref"
            ]
            assert prior_path.read_bytes() == b"prior-durable-image"

            controller.transcript_chunks[0]["prompt"] = "A changed moonlit bridge"
            controller.scene_plan[0]["prompt"] = "A changed moonlit bridge"
            controller._run_visual_generation = lambda *_args, **_kwargs: None
            controller._retry_story_scene("scene-1", chapter_id="chapter-1")
            deadline = time.monotonic() + 1.0
            while (
                controller._current_story_project["chapters"]["chapter-1"][
                    "scene_checkpoints"
                ]["scene-1"]["status"]
                != "running"
                and time.monotonic() < deadline
            ):
                time.sleep(0.005)
            running = controller._current_story_project["chapters"]["chapter-1"][
                "scene_checkpoints"
            ]["scene-1"]
            assert running["previous_output_ref"] == prior["output_ref"]

            failure = _owned_image_payload(controller, 0, root / "missing-new.png")
            failure["prompt_text"] = "A changed moonlit bridge"
            restored = controller._checkpoint_failed_story_image(
                failure, detail="replacement failed"
            )
            assert restored["status"] == "completed"
            assert restored["output_ref"] == prior["output_ref"]
            assert restored["output_fingerprint"] == prior["output_fingerprint"]
            assert prior_path.read_bytes() == b"prior-durable-image"
        finally:
            controller.shutdown()


def test_recovery_actions_are_explicit_and_dispatch_selected_work_items() -> None:
    project_models = _require_module("addons.audio_story_mode.project_models")
    with tempfile.TemporaryDirectory() as directory:
        store, project, chunks = _project_image_fixture(Path(directory))
        chapter = project["chapters"]["chapter-1"]
        chapter["scene_checkpoints"] = {}
        for index, scene_id in enumerate(("scene-1", "scene-2")):
            checkpoint = project_models.checkpoint(
                "image_generation", scene_id, status="failed"
            )
            checkpoint["input_fingerprint"] = f"scene-input-{index}"
            checkpoint["expected_input_fingerprint"] = f"scene-input-{index}"
            checkpoint["chunk_index"] = index
            chapter["scene_checkpoints"][scene_id] = checkpoint
        project = store.save_project(project)
        controller = _configured_project_image_controller(store, project, chunks)
        retry_scene_keys = []

        def capture_retry_scene(scene_id: str, *, chapter_id: str = "") -> None:
            retry_scene_keys.append((chapter_id, scene_id))

        controller._retry_story_scene = capture_retry_scene
        try:
            controller._apply_open_story_project(project)
            assert retry_scene_keys == []
            controller.transcript_chunks = copy.deepcopy(chunks)
            controller._retry_story_project_item(
                {
                    "chapter_id": "chapter-1",
                    "stage": "image_generation",
                    "unit_id": "scene-2",
                }
            )
            assert retry_scene_keys == [("chapter-1", "scene-2")]
            resume_scene_keys = []
            controller._retry_story_scenes = resume_scene_keys.extend
            controller._resume_story_project()
            assert resume_scene_keys == [
                ("chapter-1", "scene-1"),
                ("chapter-1", "scene-2"),
            ]
        finally:
            controller.shutdown()


def test_retry_preserves_chapter_identity_for_duplicate_scene_ids() -> None:
    project_models = _require_module("addons.audio_story_mode.project_models")
    with tempfile.TemporaryDirectory() as directory:
        store, project, chunks = _project_image_fixture(Path(directory))
        project = copy.deepcopy(project)
        project["chapters"]["chapter-2"] = copy.deepcopy(
            project["chapters"]["chapter-1"]
        )
        project["chapters"]["chapter-2"]["chapter_id"] = "chapter-2"
        project["chapters"]["chapter-2"]["display_name"] = "Chapter 2"
        project["chapter_order"] = ["chapter-1", "chapter-2"]
        sibling_checkpoints = {}
        for chapter_id in project["chapter_order"]:
            checkpoint = project_models.checkpoint(
                "image_generation", "scene-shared", status="failed"
            )
            checkpoint["input_fingerprint"] = f"{chapter_id}-previous-input"
            checkpoint["expected_input_fingerprint"] = (
                f"{chapter_id}-previous-input"
            )
            sibling_checkpoints[chapter_id] = copy.deepcopy(checkpoint)
            project["chapters"][chapter_id]["scene_checkpoints"] = {
                "scene-shared": checkpoint
            }
        project = store.save_project(project)
        chunks = [
            {
                **copy.deepcopy(chunks[0]),
                "index": 0,
                "chapter_id": "chapter-1",
                "scene_id": "scene-shared",
                "prompt": "Chapter one shared scene",
            },
            {
                **copy.deepcopy(chunks[1]),
                "index": 1,
                "chapter_id": "chapter-2",
                "scene_id": "scene-shared",
                "prompt": "Chapter two shared scene",
            },
        ]
        controller = _configured_project_image_controller(store, project, chunks)
        dispatched_indices = []

        def capture_retry(_token, _start_index, _end_index, *args, **kwargs):
            del args
            dispatched_indices.extend(kwargs.get("requested_indices") or ())

        controller._run_visual_generation = capture_retry
        try:
            controller._retry_story_project_item(
                {
                    "chapter_id": "chapter-2",
                    "stage": "image_generation",
                    "unit_id": "scene-shared",
                }
            )
            deadline = time.monotonic() + 1.0
            while not dispatched_indices and time.monotonic() < deadline:
                time.sleep(0.005)
            assert dispatched_indices == [1]
            assert controller._current_story_project["chapters"]["chapter-1"][
                "scene_checkpoints"
            ]["scene-shared"] == sibling_checkpoints["chapter-1"]
            assert controller._current_story_project["chapters"]["chapter-2"][
                "scene_checkpoints"
            ]["scene-shared"]["status"] == "running"
        finally:
            controller.shutdown()


def test_project_analysis_runs_in_project_order_and_seeds_following_chapter() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_analysis_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        calls: list[str] = []
        original = controller._analyze_project_chapter_with_settings

        def analyze_injected(
            project_id: str, chapter_id: str, *, settings, job_id: int | None = None
        ):
            calls.append(chapter_id)

            def analyzer(request: dict) -> dict:
                seed = dict(request.get("continuity_seed") or {})
                if chapter_id == "c2":
                    assert seed["characters"]["hero"]["display_name"] == "Hero"
                update = (
                    {
                        "characters": {
                            "hero": {
                                "display_name": "Hero",
                                "aliases": ["Hero"],
                                "visual_identity": "dark wool coat",
                                "confidence": 0.8,
                            }
                        }
                    }
                    if chapter_id == "c1"
                    else {
                        "characters": {
                            "hero": {
                                "display_name": "Hero",
                                "aliases": ["the traveler"],
                                "confidence": 0.7,
                            }
                        }
                    }
                )
                return _analysis_result(
                    request, chapter_id=chapter_id, story_update=update
                )

            return original(
                project_id,
                chapter_id,
                settings=settings,
                analyzer=analyzer,
                job_id=job_id,
            )

        controller._analyze_project_chapter_with_settings = analyze_injected
        try:
            payload = controller._build_project_story_payload(
                7,
                ["c2", "c1"],
                {
                    "chunk_seconds": 8,
                    "image_frequency_seconds": 12,
                    "continuity_strength": 0.8,
                },
            )
            committed = store.load_story_bible(project["project_id"])
            stored_c2 = store.load_chapter_document(
                project["project_id"], "c2", "analysis"
            )
            c2_only = controller._build_project_story_payload(
                8,
                ["c2"],
                {
                    "chunk_seconds": 8,
                    "image_frequency_seconds": 12,
                    "continuity_strength": 0.8,
                },
            )
        finally:
            controller.shutdown()

    assert calls == ["c1", "c2"]
    assert committed["characters"]["hero"]["aliases"] == ["Hero", "the traveler"]
    assert [chunk["start_seconds"] for chunk in payload["transcript_chunks"]] == [
        1.0,
        11.0,
    ]
    assert stored_c2["transcript_chunks"][0]["start_seconds"] == 1.0
    assert stored_c2["job_id"] == 7
    assert c2_only["audio_duration_seconds"] == 20.0


def test_failed_project_analysis_keeps_committed_story_bible_pointer() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_analysis_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        try:
            controller._analyze_project_chapter(
                project["project_id"],
                "c1",
                analyzer=lambda request: _analysis_result(
                    request,
                    chapter_id="c1",
                    story_update={
                        "characters": {
                            "hero": {
                                "display_name": "Hero",
                                "aliases": ["Hero"],
                                "confidence": 0.8,
                            }
                        }
                    },
                ),
            )
            before = store.load_project(project["project_id"])
            _assert_raises(
                RuntimeError,
                lambda: controller._analyze_project_chapter(
                    project["project_id"],
                    "c2",
                    analyzer=lambda _payload: (_ for _ in ()).throw(
                        RuntimeError("provider failed")
                    ),
                ),
            )
            after = store.load_project(project["project_id"])
            committed = store.load_story_bible(project["project_id"])

            before_invalid = store.load_project(project["project_id"])

            def invalid_analysis(request: dict) -> dict:
                result = _analysis_result(
                    request,
                    chapter_id="c2",
                    story_update={"characters": {}},
                )
                result["scene_plan"][0]["start_seconds"] = "not-a-timestamp"
                return result

            _assert_raises(
                TypeError,
                lambda: controller._analyze_project_chapter(
                    project["project_id"], "c2", analyzer=invalid_analysis
                ),
            )
            after_invalid = store.load_project(project["project_id"])

            before_invalid_bible = store.load_project(project["project_id"])

            def invalid_story_bible(request: dict) -> dict:
                result = _analysis_result(
                    request,
                    chapter_id="c2",
                    story_update={"characters": []},
                )
                return result

            _assert_raises(
                TypeError,
                lambda: controller._analyze_project_chapter(
                    project["project_id"], "c2", analyzer=invalid_story_bible
                ),
            )
            after_invalid_bible = store.load_project(project["project_id"])
        finally:
            controller.shutdown()

    assert after["story_bible_revision"] == before["story_bible_revision"]
    assert after.get("story_bible_ref", "") == before.get("story_bible_ref", "")
    assert committed["characters"]["hero"]["display_name"] == "Hero"
    assert after["chapters"]["c2"]["stages"]["story_analysis"]["status"] == "failed"
    assert after["chapters"]["c2"]["stages"]["scene_planning"]["status"] in {
        "pending",
        "stale",
    }
    assert (
        after_invalid["story_bible_revision"]
        == before_invalid["story_bible_revision"]
    )
    assert after_invalid["story_bible_ref"] == before_invalid["story_bible_ref"]
    assert (
        after_invalid_bible["story_bible_revision"]
        == before_invalid_bible["story_bible_revision"]
    )
    assert (
        after_invalid_bible["story_bible_ref"]
        == before_invalid_bible["story_bible_ref"]
    )


def test_switched_project_analysis_does_not_commit_stale_provider_result() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_analysis_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        before = store.load_project(project["project_id"])

        def switch_project_during_analysis(request: dict) -> dict:
            controller.current_story_project_id = "another-project"
            return _analysis_result(
                request,
                chapter_id="c1",
                story_update={
                    "characters": {
                        "hero": {
                            "display_name": "Hero",
                            "aliases": ["Hero"],
                            "confidence": 0.8,
                        }
                    }
                },
            )

        try:
            _assert_raises(
                controller_module.TranscriptionFailure,
                lambda: controller._analyze_project_chapter(
                    project["project_id"],
                    "c1",
                    analyzer=switch_project_during_analysis,
                ),
                "cancelled",
            )
            after = store.load_project(project["project_id"])
        finally:
            controller.shutdown()

    assert after["story_bible_revision"] == before["story_bible_revision"]
    assert after.get("story_bible_ref", "") == before.get("story_bible_ref", "")
    assert (
        after["chapters"]["c1"]["stages"]["story_analysis"]["output_ref"]
        == before["chapters"]["c1"]["stages"]["story_analysis"]["output_ref"]
    )


def test_project_analysis_publication_does_not_need_a_final_manifest_save() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_analysis_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        before = store.load_project(project["project_id"])
        original_save = store.save_project
        save_calls = 0

        def fail_obsolete_final_save(manifest: dict) -> dict:
            nonlocal save_calls
            save_calls += 1
            if save_calls == 3:
                raise OSError("simulated obsolete final save failure")
            return original_save(manifest)

        store.save_project = fail_obsolete_final_save
        try:
            try:
                controller._analyze_project_chapter(
                    project["project_id"],
                    "c1",
                    analyzer=lambda request: _analysis_result(
                        request,
                        chapter_id="c1",
                        story_update={"characters": {}},
                    ),
                )
            except OSError:
                pass
            reopened = store.load_project(project["project_id"])
        finally:
            store.save_project = original_save
            controller.shutdown()

    analysis = reopened["chapters"]["c1"]["stages"]["story_analysis"]
    scene = reopened["chapters"]["c1"]["stages"]["scene_planning"]
    assert not (
        reopened["story_bible_revision"] > before["story_bible_revision"]
        and (analysis["status"] != "completed" or scene["status"] != "completed")
    )
    assert save_calls == 2


def test_reanalyzing_earlier_chapter_stales_only_downstream_continuity() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_analysis_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])

        def analyze(chapter_id: str):
            return controller._analyze_project_chapter(
                project["project_id"],
                chapter_id,
                analyzer=lambda request: _analysis_result(
                    request,
                    chapter_id=chapter_id,
                    story_update={
                        "characters": {
                            "hero": {
                                "display_name": "Hero",
                                "aliases": ["Hero"],
                                "confidence": 0.8,
                            }
                        }
                    },
                ),
            )

        try:
            analyze("c1")
            analyze("c2")
            ready = store.load_project(project["project_id"])
            for stage in ("transcription", "image_generation"):
                checkpoint = ready["chapters"]["c2"]["stages"][stage]
                checkpoint["status"] = "completed"
                checkpoint["input_fingerprint"] = f"{stage}-current"
                checkpoint["expected_input_fingerprint"] = f"{stage}-current"
            store.save_project(ready)

            analyze("c1")
            reopened = store.load_project(project["project_id"])
        finally:
            controller.shutdown()

    assert reopened["chapters"]["c2"]["stages"]["transcription"]["status"] == "completed"
    assert reopened["chapters"]["c2"]["stages"]["story_analysis"]["status"] == "stale"
    assert reopened["chapters"]["c2"]["stages"]["image_generation"]["status"] == "stale"


def test_project_story_memory_seed_bypasses_legacy_audio_path_store() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._stored_use_llm_story_analysis = False
    controller._stored_audio_story_analysis_mode = "story_bible"
    controller._stored_image_timing_mode = "scene_changes"
    legacy_calls: list[str] = []

    class FakeLegacyStore:
        path = Path("legacy-story-memory.json")

        def load(self):
            legacy_calls.append("load")
            return {
                "characters": {},
                "locations": {},
                "props": {},
                "style": {},
                "recent_scenes": [],
            }

        def save(self, _memory):
            legacy_calls.append("save")

    controller._story_bible_store = lambda _path="": FakeLegacyStore()
    seed = {
        "characters": {
            "hero": {
                "display_name": "Hero",
                "aliases": ["Hero"],
                "visual_identity": "dark wool coat",
                "confidence": 0.8,
            }
        }
    }
    try:
        project_payload = controller._build_story_payload(
            job_id=1,
            path="chapter.wav",
            audio_duration=10.0,
            raw_segments=[
                {
                    "start_seconds": 0.0,
                    "end_seconds": 2.0,
                    "text": "Hero entered the forest.",
                }
            ],
            chunk_seconds=8,
            image_frequency_seconds=8,
            continuity_strength=0.8,
            continuity_seed=seed,
            project_story_memory=seed,
        )
        assert legacy_calls == []
        assert project_payload["story_bible"]["characters"]["hero"]["label"] == "Hero"
        assert (
            project_payload["project_story_memory"]["characters"]["hero"][
                "visual_identity"
            ]
            == "dark wool coat"
        )

        controller._build_story_payload(
            job_id=2,
            path="legacy.wav",
            audio_duration=10.0,
            raw_segments=[
                {
                    "start_seconds": 0.0,
                    "end_seconds": 2.0,
                    "text": "Mira entered the forest.",
                }
            ],
            chunk_seconds=8,
            image_frequency_seconds=8,
            continuity_strength=0.8,
        )
    finally:
        controller.shutdown()

    assert legacy_calls and legacy_calls[0] == "load"


def test_named_project_cached_rebuilds_use_committed_memory_and_forbid_legacy_store() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_analysis_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        controller._stored_use_llm_story_analysis = False
        controller._stored_audio_story_analysis_mode = "story_bible"
        controller._stored_image_timing_mode = "scene_changes"
        controller._raw_transcript_segments = [
            {"start_seconds": 0.0, "end_seconds": 2.0, "text": "Hero returns."}
        ]
        controller._last_transcription_audio_duration = 10.0
        controller.imported_audio_path = "chapter-1.wav"
        controller._story_bible_store = lambda _path="": (_ for _ in ()).throw(
            AssertionError("legacy Story Bible store must not be used")
        )
        build_calls: list[tuple[dict, dict]] = []
        original_build = controller._build_story_payload

        def build_with_project_memory(**kwargs):
            build_calls.append(
                (
                    dict(kwargs.get("continuity_seed") or {}),
                    dict(kwargs.get("project_story_memory") or {}),
                )
            )
            return original_build(**kwargs)

        controller._build_story_payload = build_with_project_memory
        controller._apply_story_payload = lambda *_args, **_kwargs: None
        controller._reconcile_cached_images_for_current_prompts = lambda: None
        controller._sync_visual_to_position = lambda *_args, **_kwargs: None
        controller.transcriptionFinished.disconnect(
            controller._on_transcription_finished
        )
        controller._analyze_project_chapter(
            project["project_id"],
            "c1",
            analyzer=lambda request: _analysis_result(
                request,
                chapter_id="c1",
                story_update={
                    "characters": {
                        "hero": {
                            "display_name": "Hero",
                            "aliases": ["Hero"],
                            "visual_identity": "dark wool coat",
                            "confidence": 0.8,
                        }
                    }
                },
            ),
        )

        try:
            controller._rebuild_story_payload_from_cached_segments(
                preserve_playback=True
            )
            controller._run_story_payload_rebuild_job(
                controller._transcription_job_id,
                controller.imported_audio_path,
                controller._last_transcription_audio_duration,
                controller._raw_transcript_segments,
                8,
                12,
                0.8,
            )
        finally:
            controller.shutdown()

    assert len(build_calls) == 2
    for continuity_seed, project_story_memory in build_calls:
        assert continuity_seed["characters"]["hero"]["display_name"] == "Hero"
        assert project_story_memory["characters"]["hero"]["display_name"] == "Hero"


def test_instructor_failure_falls_back_to_llm_with_committed_seed() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._stored_instructor_beats_enabled = True
    seed = {
        "characters": {
            "hero": {
                "display_name": "Hero",
                "aliases": ["Hero"],
                "visual_identity": "dark wool coat",
                "confidence": 0.8,
            }
        }
    }
    calls: dict[str, object] = {}
    original_provider = controller._active_story_analysis_chat_provider
    original_instructor = controller._call_instructor_story_analysis
    original_llm = controller._call_llm_story_analysis
    controller._active_story_analysis_chat_provider = lambda: ("lmstudio", "test-model")
    controller._call_instructor_story_analysis = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("Instructor failed")
    )

    def normal_llm(**kwargs):
        calls["prompt_payload"] = kwargs["prompt_payload"]
        return json.dumps(
            {
                "story_bible": {},
                "scenes": [
                    {
                        "chunk_index": 0,
                        "scene_id": "scene-1",
                        "is_new_scene": True,
                        "active_character_ids": ["hero"],
                        "key_action": "Hero enters the forest.",
                    }
                ],
            }
        )

    controller._call_llm_story_analysis = normal_llm
    fallback = {
        "characters": {
            "hero": {
                "id": "hero",
                "label": "Hero",
                "aliases": ["Hero"],
                "appearance_anchor": "dark wool coat",
                "anchor_text": "dark wool coat",
            }
        },
        "locations": {},
        "props": {},
    }
    try:
        result = controller._build_llm_story_analysis(
            full_text="Hero enters the forest.",
            image_chunks=[
                {"start_seconds": 0.0, "end_seconds": 2.0, "text": "Hero enters."}
            ],
            story_style_guide="",
            continuity_strength=0.8,
            fallback_story_bible=fallback,
            continuity_seed=seed,
        )
    finally:
        controller._active_story_analysis_chat_provider = original_provider
        controller._call_instructor_story_analysis = original_instructor
        controller._call_llm_story_analysis = original_llm
        controller.shutdown()

    prompt_payload = dict(calls["prompt_payload"])
    assert prompt_payload["committed_story_bible"]["characters"]["hero"]["display_name"] == "Hero"
    assert result["story_bible"]["characters"]["hero"]["label"] == "Hero"


def _assert_generated_entity_id_resolves_to_committed_id(*, instructor: bool) -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._stored_instructor_beats_enabled = bool(instructor)
    controller._active_story_analysis_chat_provider = lambda: ("lmstudio", "test-model")
    parsed = {
        "story_bible": {
            "characters": [
                {
                    "id": "char_wrong",
                    "label": "Hero",
                    "aliases": ["the traveler"],
                    "appearance_anchor": "new description",
                }
            ]
        },
        "scenes": [
            {
                "chunk_index": 0,
                "scene_id": "scene-1",
                "is_new_scene": True,
                "active_character_ids": ["char_wrong"],
                "key_action": "Hero returns.",
            }
        ],
    }
    fallback = {
        "characters": {
            "hero": {
                "id": "hero",
                "label": "Hero",
                "aliases": ["Hero"],
                "appearance_anchor": "dark wool coat",
                "anchor_text": "dark wool coat",
            }
        },
        "locations": {},
        "props": {},
    }
    if instructor:
        controller._call_instructor_story_analysis = lambda **_kwargs: parsed
        controller._call_llm_story_analysis = lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("normal LLM fallback should not run")
        )
    else:
        controller._call_llm_story_analysis = lambda **_kwargs: json.dumps(parsed)
    try:
        result = controller._build_llm_story_analysis(
            full_text="Hero returns.",
            image_chunks=[
                {"start_seconds": 0.0, "end_seconds": 2.0, "text": "Hero returns."}
            ],
            story_style_guide="",
            continuity_strength=0.8,
            fallback_story_bible=fallback,
            continuity_seed={"characters": {"hero": {"display_name": "Hero"}}},
        )
    finally:
        controller.shutdown()

    hero = result["story_bible"]["characters"]["hero"]
    assert "char_wrong" in hero["aliases"]
    assert result["scenes"][0]["active_character_ids"] == ["hero"]


def test_normal_llm_generated_entity_id_resolves_to_committed_id() -> None:
    _assert_generated_entity_id_resolves_to_committed_id(instructor=False)


def test_instructor_generated_entity_id_resolves_to_committed_id() -> None:
    _assert_generated_entity_id_resolves_to_committed_id(instructor=True)


def test_project_transcription_resumes_only_interrupted_chapter() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_transcription_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        controller._stored_transcription_end_seconds = 20
        transcribed_paths: list[str] = []

        def fake_transcribe(path: str):
            transcribed_paths.append(Path(path).name)
            return {
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": Path(path).stem}
                ]
            }

        try:
            controller._run_project_transcription_units(
                project["project_id"],
                ["c1"],
                **_project_transcription_launch_kwargs(controller),
                transcribe_file=fake_transcribe,
            )
            checkpointed = store.load_project(project["project_id"])
            checkpointed["chapters"]["c2"]["stages"]["transcription"][
                "status"
            ] = "interrupted"
            store.save_project(checkpointed)
            controller._current_story_project = store.load_project(project["project_id"])
            transcribed_paths.clear()

            combined = controller._run_project_transcription_units(
                project["project_id"],
                ["c1", "c2"],
                **_project_transcription_launch_kwargs(controller),
                transcribe_file=fake_transcribe,
            )
            reopened = store.load_project(project["project_id"])
        finally:
            controller.shutdown()

    assert transcribed_paths == ["chapter_2.wav"]
    assert [segment["start_seconds"] for segment in combined] == [0.0, 10.0]
    assert (
        reopened["chapters"]["c1"]["stages"]["transcription"]["attempt_count"]
        == 1
    )
    assert (
        reopened["chapters"]["c2"]["stages"]["transcription"]["status"]
        == "completed"
    )
    assert all(
        reopened["chapters"][chapter_id]["stages"]["transcript_combination"][
            "status"
        ]
        == "completed"
        for chapter_id in ("c1", "c2")
    )


def test_project_transcription_failure_preserves_last_valid_output() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_transcription_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        controller._stored_transcription_end_seconds = 10
        try:
            controller._run_project_transcription_units(
                project["project_id"],
                ["c1"],
                **_project_transcription_launch_kwargs(
                    controller, end_seconds=10.0
                ),
                transcribe_file=lambda _path: {
                    "segments": [{"start": 0.0, "end": 1.0, "text": "valid"}]
                },
            )
            previous = store.load_project(project["project_id"])["chapters"]["c1"][
                "stages"
            ]["transcription"]
            previous_ref = previous["output_ref"]
            previous_fingerprint = previous["output_fingerprint"]
            controller._stored_transcribe_seconds += 1

            def fail_transcription(_path: str):
                raise RuntimeError("provider failed api_key=super-secret-value")

            _assert_raises(
                controller_module.TranscriptionFailure,
                lambda: controller._run_project_transcription_units(
                    project["project_id"],
                    ["c1"],
                    **_project_transcription_launch_kwargs(
                        controller, chunk_seconds=9, end_seconds=10.0
                    ),
                    transcribe_file=fail_transcription,
                ),
            )
            reopened = store.load_project(project["project_id"])
            failed = reopened["chapters"]["c1"]["stages"]["transcription"]
            stored = store.load_chapter_document(
                project["project_id"], "c1", "transcript", revision=1
            )
        finally:
            controller.shutdown()

    assert failed["status"] == "failed"
    assert failed["attempt_count"] == 2
    assert failed["output_ref"] == previous_ref
    assert failed["output_fingerprint"] == previous_fingerprint
    assert "super-secret-value" not in failed["error"]
    assert "[redacted]" in failed["error"]
    assert stored["segments"][0]["text"] == "valid"
    assert (
        reopened["chapters"]["c1"]["stages"]["transcript_combination"][
            "attempt_count"
        ]
        == 1
    )


def test_project_switch_leaves_only_active_transcription_interrupted() -> None:
    checkpointing = _require_module("addons.audio_story_mode.checkpointing")
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_transcription_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        controller._stored_transcription_end_seconds = 20
        try:
            controller._run_project_transcription_units(
                project["project_id"],
                ["c1"],
                **_project_transcription_launch_kwargs(controller),
                transcribe_file=lambda _path: {
                    "segments": [{"start": 0.0, "end": 1.0, "text": "complete"}]
                },
            )

            def switch_project(_path: str):
                controller.current_story_project_id = "new-project"
                return {
                    "segments": [{"start": 0.0, "end": 1.0, "text": "stale"}]
                }

            _assert_raises(
                controller_module.TranscriptionFailure,
                lambda: controller._run_project_transcription_units(
                    project["project_id"],
                    ["c2"],
                    **_project_transcription_launch_kwargs(controller),
                    transcribe_file=switch_project,
                ),
                "cancelled",
            )
            interrupted, changed = checkpointing.recover_interrupted(
                store.load_project(project["project_id"])
            )
        finally:
            controller.shutdown()

    assert changed
    assert (
        interrupted["chapters"]["c1"]["stages"]["transcription"]["status"]
        == "completed"
    )
    assert (
        interrupted["chapters"]["c2"]["stages"]["transcription"]["status"]
        == "interrupted"
    )


def test_stale_project_transcription_token_does_no_work_or_publication() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_transcription_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        controller._story_project_generation = 4
        controller._story_project_input_fingerprint = "owned-project-input"
        controller._transcription_job_id = 2
        before = store.load_project(project["project_id"])
        transcribed_paths: list[str] = []
        try:
            _assert_raises(
                controller_module.TranscriptionFailure,
                lambda: controller._run_project_transcription_units(
                    project["project_id"],
                    ["c1"],
                    **_project_transcription_launch_kwargs(
                        controller, job_token=1, end_seconds=10.0
                    ),
                    transcribe_file=lambda path: transcribed_paths.append(path)
                    or {
                        "segments": [
                            {"start": 0.0, "end": 1.0, "text": "must not run"}
                        ]
                    },
                ),
                "cancelled",
            )
            after = store.load_project(project["project_id"])
            _assert_raises(
                FileNotFoundError,
                lambda: store.load_chapter_document(
                    project["project_id"], "c1", "transcript"
                ),
            )
        finally:
            controller.shutdown()

    assert transcribed_paths == []
    assert after == before


def test_project_transcription_uses_frozen_launch_range_and_chunk() -> None:
    checkpointing = _require_module("addons.audio_story_mode.checkpointing")
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_transcription_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        controller._story_project_generation = 6
        controller._story_project_input_fingerprint = "frozen-project-input"
        controller._transcription_job_id = 1
        launch = _project_transcription_launch_kwargs(
            controller,
            job_token=1,
            chunk_seconds=8,
            start_seconds=0.0,
            end_seconds=10.0,
        )
        controller._stored_transcribe_seconds = 99
        controller._stored_transcription_start_seconds = 2
        controller._stored_transcription_end_seconds = 3
        controller.audio_story_transcribe_seconds_slider = types.SimpleNamespace(
            value=lambda: 77
        )
        controller.audio_story_transcription_start_spin = types.SimpleNamespace(
            value=lambda: 4
        )
        controller.audio_story_transcription_end_spin = types.SimpleNamespace(
            value=lambda: 5
        )
        transcribed_paths: list[str] = []
        try:
            controller._run_project_transcription_units(
                project["project_id"],
                ["c1"],
                selected_range_enabled=True,
                **launch,
                transcribe_file=lambda path: transcribed_paths.append(Path(path).name)
                or {
                    "segments": [
                        {"start": 0.0, "end": 1.0, "text": "frozen launch"}
                    ]
                },
            )
            stored = store.load_chapter_document(
                project["project_id"], "c1", "transcript", revision=1
            )
            reopened = store.load_project(project["project_id"])
        finally:
            del controller.audio_story_transcribe_seconds_slider
            del controller.audio_story_transcription_start_spin
            del controller.audio_story_transcription_end_spin
            controller.shutdown()

    assert transcribed_paths == ["chapter_1.wav"]
    assert stored["chunk_seconds"] == 8
    assert stored["selected_range"] == {
        "start_seconds": 0.0,
        "end_seconds": 10.0,
    }
    assert stored["transcription_start_seconds"] == 0.0
    assert stored["transcription_end_seconds"] == 10.0
    runtime_config = dict(controller_module.audio_story_runtime.runtime_config() or {})
    runtime_identifier = json.loads(
        json.dumps(
            {
                "backend": runtime_config.get("stt_backend", ""),
                "model_size": runtime_config.get("stt_model_size", ""),
                "language": runtime_config.get("stt_language", ""),
                "backend_settings": runtime_config.get("stt_backend_settings", {}),
            },
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
    )
    expected_input = checkpointing.settings_fingerprint(
        {
            "audio_identity": {
                "algorithm": "sha256-sampled-v1",
                "digest": "chapter-1",
                "size_bytes": 101,
                "duration_ms": 10000,
            },
            "transcription_scope": {
                "mode": "selected_range",
                "project_start_seconds": 0.0,
                "project_end_seconds": 10.0,
                "local_start_seconds": 0.0,
                "local_end_seconds": 10.0,
            },
            "chunk_seconds": 8,
            "stt_runtime": runtime_identifier,
        }
    )
    assert (
        reopened["chapters"]["c1"]["stages"]["transcription"][
            "input_fingerprint"
        ]
        == expected_input
    )


def test_project_transcription_original_helper_signature_remains_supported() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        store, project = _project_transcription_fixture(Path(directory))
        controller = controller_module.AudioStoryModeController(context=None)
        controller._story_project_store = store
        controller.current_story_project_id = project["project_id"]
        controller._current_story_project = store.load_project(project["project_id"])
        controller._stored_transcribe_seconds = 8
        controller._stored_transcription_start_seconds = 0
        controller._stored_transcription_end_seconds = 10
        transcribed_paths: list[str] = []

        def fake_transcribe(path: str):
            transcribed_paths.append(Path(path).name)
            controller._stored_transcribe_seconds = 99
            controller._stored_transcription_start_seconds = 2
            controller._stored_transcription_end_seconds = 3
            return {
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "compatible call"}
                ]
            }

        try:
            combined = controller._run_project_transcription_units(
                project["project_id"], ["c1"], transcribe_file=fake_transcribe
            )
            stored = store.load_chapter_document(
                project["project_id"], "c1", "transcript", revision=1
            )
        finally:
            controller.shutdown()

    assert transcribed_paths == ["chapter_1.wav"]
    assert [segment["start_seconds"] for segment in combined] == [0.0]
    assert stored["chunk_seconds"] == 8
    assert stored["transcription_start_seconds"] == 0.0
    assert stored["transcription_end_seconds"] == 20.0


def test_designer_ui_exposes_ordered_audio_queue_controls() -> None:
    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    root = ET.parse(ui_path).getroot()
    names = {
        str(node.attrib.get("name") or "")
        for node in root.iter("widget")
    }
    required = {
        "audio_story_source_list",
        "audio_story_source_move_up_button",
        "audio_story_source_move_down_button",
        "audio_story_source_remove_button",
        "audio_story_source_clear_button",
    }
    assert required <= names, sorted(required - names)


class _FakePlayer:
    def __init__(self, position_ms: int = 0):
        self._position_ms = position_ms
        self.sources: list[str] = []
        self.positionChanged = _FakeSignal()
        self.mediaStatusChanged = _FakeSignal()
        self.seekableChanged = _FakeSignal()
        self.play_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0
        self._state = _qt_player_state("StoppedState")
        self._source = None
        self._media_status = _qt_media_status("NoMedia")
        self._seekable = False

    def position(self) -> int:
        return self._position_ms

    def setPosition(self, value: int) -> None:
        self._position_ms = int(value)
        self.positionChanged.emit(self._position_ms)

    def setSource(self, value) -> None:
        self._source = value
        self.sources.append(value.toLocalFile())
        self._state = _qt_player_state("StoppedState")
        self._position_ms = 0
        self._media_status = _qt_media_status("LoadedMedia")
        self._seekable = True
        self.mediaStatusChanged.emit(self._media_status)
        self.seekableChanged.emit(True)

    def source(self):
        return self._source

    def mediaStatus(self):
        return self._media_status

    def isSeekable(self) -> bool:
        return self._seekable

    def playbackState(self):
        return self._state

    def play(self) -> None:
        self.play_calls += 1
        self._state = _qt_player_state("PlayingState")

    def pause(self) -> None:
        self.pause_calls += 1
        self._state = _qt_player_state("PausedState")

    def stop(self) -> None:
        self.stop_calls += 1
        self._state = _qt_player_state("StoppedState")


class _AsyncLoadingFakePlayer(_FakePlayer):
    def __init__(self, position_ms: int = 0):
        super().__init__(position_ms)
        self.position_attempts: list[int] = []
        self._media_status = _qt_media_status("NoMedia")
        self._seekable = False
        self._accept_positions = False

    def prime_source(self, path: Path, *, position_ms: int) -> None:
        controller_module = _require_module("addons.audio_story_mode.controller")
        self._source = controller_module.QtCore.QUrl.fromLocalFile(
            str(path.resolve())
        )
        self._media_status = _qt_media_status("LoadedMedia")
        self._seekable = True
        self._accept_positions = True
        self._position_ms = int(position_ms)

    def source(self):
        return self._source

    def mediaStatus(self):
        return self._media_status

    def isSeekable(self) -> bool:
        return self._seekable

    def setSource(self, value) -> None:
        self._source = value
        self.sources.append(value.toLocalFile())
        self._state = _qt_player_state("StoppedState")
        self._position_ms = 0
        self._media_status = _qt_media_status("LoadingMedia")
        self._seekable = False
        self._accept_positions = False
        self.mediaStatusChanged.emit(self._media_status)

    def setPosition(self, value: int) -> None:
        self.position_attempts.append(int(value))
        if self._accept_positions:
            super().setPosition(value)

    def emit_loaded(self) -> None:
        self._accept_positions = True
        self._seekable = True
        self._media_status = _qt_media_status("LoadedMedia")
        self.mediaStatusChanged.emit(self._media_status)


class _DelayedSeekFakePlayer(_AsyncLoadingFakePlayer):
    def emit_loaded_without_applying_seek(self) -> None:
        self._accept_positions = False
        self._seekable = True
        self._media_status = _qt_media_status("LoadedMedia")
        self.mediaStatusChanged.emit(self._media_status)

    def apply_delayed_position(self, value: int) -> None:
        self._position_ms = int(value)
        self.positionChanged.emit(self._position_ms)


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _FakeSlider:
    def __init__(self):
        self.minimum = 0
        self.maximum = 0
        self.current_value = 0
        self.signals_blocked = False
        self.enabled = False

    def blockSignals(self, blocked: bool) -> None:
        self.signals_blocked = bool(blocked)

    def setRange(self, minimum: int, maximum: int) -> None:
        self.minimum = int(minimum)
        self.maximum = int(maximum)

    def setValue(self, value: int) -> None:
        self.current_value = int(value)

    def value(self) -> int:
        return self.current_value

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self.enabled


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = str(text)


class _FakeButton:
    def __init__(self):
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self.enabled


def _write_committed_tts_bundle(
    root: Path,
    *,
    signature: str,
    project_id: str,
    duration_seconds: float,
    chunks: list[dict],
) -> tuple[Path, dict]:
    queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
    audio_path = root / f"tts_story_{signature}.wav"
    metadata_path = audio_path.with_suffix(".json")
    commit_path = audio_path.with_suffix(".commit.json")
    audio_path.write_bytes(b"committed fake bundle")
    metadata = {
        "schema_version": queue_module.SEGMENT_SCHEMA_VERSION,
        "audio_path": str(audio_path.resolve()),
        "duration_seconds": float(duration_seconds),
        "chunks": [dict(item) for item in chunks],
        "rendered_chunks": [dict(item) for item in chunks],
        "signature": signature,
        "queue_signature": signature,
        "project_id": project_id,
    }
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2), encoding="utf-8"
    )
    commit = {
        "schema_version": queue_module.SEGMENT_SCHEMA_VERSION,
        "signature": signature,
        "audio_filename": audio_path.name,
        "metadata_filename": metadata_path.name,
        "audio_size": audio_path.stat().st_size,
        "metadata_size": metadata_path.stat().st_size,
        "audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    }
    commit_path.write_text(
        json.dumps(commit, sort_keys=True, indent=2), encoding="utf-8"
    )

    def stat_fingerprint(path: Path) -> dict[str, int]:
        stat = path.stat()
        return {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "ctime_ns": int(stat.st_ctime_ns),
            "device": int(stat.st_dev),
            "inode": int(stat.st_ino),
        }

    identity = {
        **commit,
        "audio_path": str(audio_path.resolve()),
        "metadata_path": str(metadata_path.resolve()),
        "commit_path": str(commit_path.resolve()),
        "duration_seconds": float(duration_seconds),
        "audio_stat": stat_fingerprint(audio_path),
        "metadata_stat": stat_fingerprint(metadata_path),
        "commit_stat": stat_fingerprint(commit_path),
        "commit_sha256": hashlib.sha256(commit_path.read_bytes()).hexdigest(),
    }
    return audio_path, identity


def _overwrite_same_size_with_new_mtime(path: Path) -> None:
    before = path.stat()
    original = path.read_bytes()
    replacement = bytes((value ^ 0x5A) for value in original)
    assert replacement != original
    path.write_bytes(replacement)
    os.utime(
        path,
        ns=(int(before.st_atime_ns), int(before.st_mtime_ns) + 10_000_000),
    )
    after = path.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns != before.st_mtime_ns


def _qt_player_state(name: str):
    controller_module = _require_module("addons.audio_story_mode.controller")
    enum = getattr(controller_module.QtMultimedia.QMediaPlayer, "PlaybackState", None)
    return getattr(enum, name) if enum is not None else getattr(
        controller_module.QtMultimedia.QMediaPlayer, name
    )


def _qt_end_of_media():
    return _qt_media_status("EndOfMedia")


def _qt_media_status(name: str):
    controller_module = _require_module("addons.audio_story_mode.controller")
    enum = getattr(controller_module.QtMultimedia.QMediaPlayer, "MediaStatus", None)
    return getattr(enum, name) if enum is not None else getattr(
        controller_module.QtMultimedia.QMediaPlayer, name
    )


def _tts_playback_fixture(
    root: Path,
    durations: tuple[float, ...],
    *,
    ready_indices: tuple[int, ...] = (),
):
    controller_module = _require_module("addons.audio_story_mode.controller")
    queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._playback_mode_value = lambda: "tts"
    controller._set_status = lambda _message: None
    controller._refresh_controls = lambda: None
    controller._sync_visual_to_position = lambda *_args, **_kwargs: None
    controller._sync_visual_stream_playback_state = lambda *_args, **_kwargs: None
    controller._update_slider_range = lambda: None
    controller.transcript_chunks = [
        {
            "index": index,
            "start_seconds": sum(durations[:index]),
            "end_seconds": sum(durations[: index + 1]),
            "text": f"Window {index}",
            "prompt": f"Prompt {index}",
            "tts_start_seconds": None,
            "tts_end_seconds": None,
        }
        for index in range(len(durations))
    ]
    segment_plans = []
    ready_segments = {}
    for index, duration in enumerate(durations):
        audio_path = root / f"segment-{index}.wav"
        audio_path.write_bytes(b"fake-wav")
        segment_plan = queue_module.TtsSegmentPlan(
            index=index,
            signature=f"segment-signature-{index}",
            text=f"Window {index}",
            window_indices=(index,),
            estimated_seconds=float(duration),
            audio_path=audio_path,
            metadata_path=root / f"segment-{index}.json",
        )
        segment_plans.append(segment_plan)
        if index in ready_indices:
            ready_segments[index] = queue_module.TtsReadySegment(
                plan=segment_plan,
                duration_seconds=float(duration),
                chunk_offsets=((index, 0.0, float(duration)),),
            )
    controller._tts_queue_plan = queue_module.TtsQueuePlan(
        signature="queue-signature",
        project_id="",
        segments=tuple(segment_plans),
    )
    controller._tts_ready_segments = ready_segments
    controller._tts_render_job_id = 17
    controller._tts_render_in_progress = True
    controller._tts_queue_state = "Ready"
    controller.audio_player = _FakePlayer()
    controller.audio_player.positionChanged.connect(
        controller._on_player_position_changed
    )
    controller.audio_player.mediaStatusChanged.connect(
        controller._on_player_media_status_changed
    )
    controller.audio_player.seekableChanged.connect(
        controller._on_player_seekable_changed
    )
    return controller, tuple(segment_plans), ready_segments


def _ready_tts_payload(controller, ready) -> dict:
    return {
        "job_id": int(controller._tts_render_job_id),
        "project_id": str(controller._tts_queue_plan.project_id),
        "queue_signature": str(controller._tts_queue_plan.signature),
        "segment": ready,
    }


def test_controller_tts_buffer_ui_uses_exact_states_and_actual_progress() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 5.0), ready_indices=(0, 1)
        )
        controller.audio_story_tts_state_label = _FakeLabel()
        controller.audio_story_tts_buffered_label = _FakeLabel()
        controller.audio_story_tts_segment_label = _FakeLabel()
        controller.audio_story_tts_retry_button = _FakeButton()
        controller.audio_story_tts_clear_cache_button = _FakeButton()
        controller._stored_tts_startup_buffer_seconds = 5
        controller._stored_tts_render_ahead_seconds = 30
        controller._tts_active_segment_index = 1
        controller._tts_active_segment_global_offset = 10.0
        controller._tts_playback_position_seconds = 12.0
        allowed_states = (
            "Idle",
            "Preparing",
            "Ready",
            "Rendering Ahead",
            "Buffering",
            "Paused",
            "Complete",
            "Failed",
        )
        try:
            for state in allowed_states:
                controller._tts_queue_state = state
                controller._refresh_tts_buffer_ui()
                assert controller.audio_story_tts_state_label.text == state
                assert controller.audio_story_tts_segment_label.text == "Segment: 2 / 2"
                assert controller.audio_story_tts_buffered_label.text.startswith(
                    "Buffered: 00:03 / "
                )
                assert controller.audio_story_tts_retry_button.isEnabled() is (
                    state == "Failed"
                )
                assert controller.audio_story_tts_clear_cache_button.isEnabled()
        finally:
            controller.shutdown()


def test_controller_tts_slider_ui_path_stays_live_for_progressive_queue() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, ready = _tts_playback_fixture(
            Path(directory), (10.0, 10.0, 10.0), ready_indices=(0,)
        )
        controller.audio_story_position_slider = _FakeSlider()
        controller.imported_audio_path = "story.wav"
        controller._refresh_controls = (
            controller.__class__._refresh_controls.__get__(
                controller, controller.__class__
            )
        )
        try:
            controller._refresh_controls()
            assert controller.audio_story_position_slider.isEnabled()

            controller.audio_story_position_slider.setValue(5000)
            controller._on_slider_released()
            assert controller._tts_active_segment_index == 0
            assert controller.audio_player.position() == 5000

            controller.audio_story_position_slider.setValue(25000)
            controller._on_slider_released()
            assert controller._tts_queue_state == "Buffering"
            assert controller._tts_buffering_target_seconds == 25.0

            target_ready = _require_module(
                "addons.audio_story_mode.tts_segment_queue"
            ).TtsReadySegment(
                plan=plans[2],
                duration_seconds=10.0,
                chunk_offsets=((2, 0.0, 10.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, target_ready)
            )
            assert controller._tts_active_segment_index == 2
            assert controller.audio_player.position() == 5000

            controller._stop_story()
            assert controller._tts_queue_plan is not None
            assert 2 in controller._tts_ready_segments
            assert controller.audio_story_position_slider.isEnabled()
        finally:
            controller.shutdown()


def test_refresh_controls_keeps_range_spins_disabled_without_selected_range() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    controller = controller_module.AudioStoryModeController(context=None)
    controller.current_story_project_id = "range-project"
    controller.imported_audio_path = "chapter.wav"
    controller.imported_audio_sources = [
        audio_sources.AudioSource(
            index=0,
            path="chapter.wav",
            display_name="Chapter",
            duration_seconds=10.0,
            global_start_seconds=0.0,
            global_end_seconds=10.0,
        )
    ]
    controller.audio_story_transcription_start_spin = _FakeSlider()
    controller.audio_story_transcription_end_spin = _FakeSlider()
    try:
        controller._stored_selected_range_enabled = False
        controller._refresh_controls()
        assert not controller.audio_story_transcription_start_spin.isEnabled()
        assert not controller.audio_story_transcription_end_spin.isEnabled()
        controller._stored_selected_range_enabled = True
        controller._refresh_controls()
        assert controller.audio_story_transcription_start_spin.isEnabled()
        assert controller.audio_story_transcription_end_spin.isEnabled()
    finally:
        controller.shutdown()


def test_controller_tts_buffer_setting_change_clamps_wakes_and_persists_only() -> None:
    from PySide6 import QtWidgets

    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, ready = _tts_playback_fixture(
            Path(directory), (10.0,), ready_indices=(0,)
        )
        controller.audio_story_tts_startup_buffer_spin = QtWidgets.QSpinBox()
        controller.audio_story_tts_startup_buffer_spin.setRange(5, 120)
        controller.audio_story_tts_startup_buffer_spin.setValue(90)
        controller.audio_story_tts_render_ahead_spin = QtWidgets.QSpinBox()
        controller.audio_story_tts_render_ahead_spin.setRange(30, 600)
        controller.audio_story_tts_render_ahead_spin.setValue(30)
        notifications: list[str] = []
        controller._notify_audio_story_settings_changed = (
            lambda: notifications.append("persist")
        )
        active_job = controller._tts_render_job_id
        ready_path = ready[0].plan.audio_path
        try:
            controller._on_tts_buffer_settings_changed()
            assert controller._stored_tts_startup_buffer_seconds == 90
            assert controller._stored_tts_render_ahead_seconds == 90
            assert controller.audio_story_tts_render_ahead_spin.value() == 90
            assert notifications == ["persist"]
            assert controller._tts_render_job_id == active_job
            assert controller._tts_ready_segments == ready
            assert ready_path.is_file()
        finally:
            controller.shutdown()


def test_controller_tts_play_and_stop_stay_available_during_active_render() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0,), ready_indices=()
        )
        controller.audio_story_play_button = _FakeButton()
        controller.audio_story_pause_button = _FakeButton()
        controller.audio_story_stop_button = _FakeButton()
        controller._refresh_controls = (
            controller_module.AudioStoryModeController._refresh_controls.__get__(
                controller
            )
        )
        try:
            for state in ("Preparing", "Rendering Ahead"):
                controller._tts_queue_state = state
                controller._tts_render_in_progress = True
                controller._refresh_controls()
                assert controller.audio_story_play_button.isEnabled()
                assert controller.audio_story_stop_button.isEnabled()
        finally:
            controller.shutdown()


def test_controller_tts_pause_keeps_render_owner_while_stop_cancels_and_keeps_cache() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, ready = _tts_playback_fixture(
            Path(directory), (10.0,), ready_indices=(0,)
        )
        ready_path = ready[0].plan.audio_path
        controller.audio_player.play()
        active_job = controller._tts_render_job_id
        try:
            controller._pause_story()
            assert controller._tts_render_job_id == active_job
            assert controller._tts_queue_state == "Paused"
            assert controller._tts_ready_segments == ready
            assert ready_path.is_file()
            ownership = {
                "job_id": active_job,
                "project_id": controller._tts_queue_plan.project_id,
                "queue_signature": controller._tts_queue_plan.signature,
                "ready_seconds": 10.0,
            }
            controller._on_tts_queue_state_changed(
                {**ownership, "state": "Ready"}
            )
            controller._on_tts_queue_state_changed(
                {**ownership, "state": "Rendering Ahead"}
            )
            assert controller._tts_queue_state == "Paused"

            controller._tts_pending_media_transition = object()
            controller._tts_buffering_target_seconds = 8.0
            controller._pending_autoplay_tts = True
            controller._stop_story()
            assert controller._tts_render_job_id == active_job + 1
            assert controller._tts_queue_state == "Idle"
            assert controller._tts_pending_media_transition is None
            assert controller._tts_buffering_target_seconds is None
            assert not controller._pending_autoplay_tts
            assert controller._tts_ready_segments == ready
            assert ready_path.is_file()
            assert controller._tts_playback_position_seconds == 0.0
        finally:
            controller.shutdown()


def test_controller_transcript_replacement_cancels_tts_before_clearing_memory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, ready = _tts_playback_fixture(
            Path(directory), (10.0,), ready_indices=(0,)
        )
        active_job = controller._tts_render_job_id
        ready_path = ready[0].plan.audio_path
        controller._tts_bundle = {
            "audio_path": str(ready_path),
            "duration_seconds": 10.0,
        }
        controller._tts_signature = controller._tts_queue_plan.signature
        try:
            controller._clear_audio_story_derived_state()
            assert controller._tts_render_job_id == active_job + 1
            assert controller._tts_queue_plan is None
            assert controller._tts_ready_segments == {}
            assert controller._tts_bundle is None
            assert controller._tts_signature == ""
            assert controller.transcript_chunks == []
            assert ready_path.is_file()
        finally:
            controller.shutdown()


def test_controller_tts_cache_clear_confirms_scopes_and_reports_owned_counts() -> None:
    from PySide6 import QtWidgets

    controller_module = _require_module("addons.audio_story_mode.controller")
    queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
    app = _qt_application()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller = controller_module.AudioStoryModeController(context=None)
        controller._cache_root = root
        controller.current_story_project_id = "cache-project"
        controller.transcript_chunks = [
            {
                "text": "Keep transcript",
                "tts_start_seconds": 0.0,
                "tts_end_seconds": 1.0,
            }
        ]
        plan = queue_module.build_tts_queue_plan(
            controller.transcript_chunks, {"voice": "fake"}, root, "cache-project"
        )
        segment = plan.segments[0]
        segment.audio_path.parent.mkdir(parents=True, exist_ok=True)
        segment.audio_path.write_bytes(b"segment")
        segment.metadata_path.write_text("{}", encoding="utf-8")
        ready = queue_module.TtsReadySegment(
            plan=segment,
            duration_seconds=1.0,
            chunk_offsets=((0, 0.0, 1.0),),
        )
        bundle_path = root / f"tts_story_{plan.signature}.wav"
        bundle_metadata_path = bundle_path.with_suffix(".json")
        bundle_commit_path = bundle_path.with_suffix(".commit.json")
        bundle_path.write_bytes(b"bundle")
        bundle_metadata_path.write_text("{}", encoding="utf-8")
        bundle_commit_path.write_text("{}", encoding="utf-8")
        source_path = root / "source.wav"
        transcript_path = root / "transcript.json"
        project_path = root / "projects" / "project.json"
        image_path = root / "images" / "story.png"
        for path in (source_path, transcript_path, project_path, image_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"keep")
        controller._tts_queue_plan = plan
        controller._tts_ready_segments = {0: ready}
        controller._tts_render_job_id = 21
        controller._tts_render_in_progress = True
        controller._tts_queue_state = "Rendering Ahead"
        controller._tts_bundle = {
            "audio_path": str(bundle_path),
            "duration_seconds": 1.0,
        }
        controller._tts_signature = plan.signature
        controller._playback_mode_value = lambda: "tts"
        controller.audio_player = _FakePlayer()
        controller._ensure_player = lambda: None
        controller.audio_story_play_button = _FakeButton()
        controller.audio_story_tts_state_label = _FakeLabel()
        controller.audio_story_tts_buffered_label = _FakeLabel()
        controller.audio_story_tts_segment_label = _FakeLabel()
        controller.audio_story_tts_retry_button = _FakeButton()
        controller.audio_story_tts_clear_cache_button = _FakeButton()
        statuses: list[str] = []
        controller._set_status = statuses.append
        results: list[dict] = []
        controller.ttsCacheClearFinished.connect(results.append)
        release_cancelled_worker = threading.Event()

        def cancelled_worker() -> None:
            assert release_cancelled_worker.wait(2.0)
            segment.audio_path.parent.mkdir(parents=True, exist_ok=True)
            segment.audio_path.write_bytes(b"late-segment")

        prior_worker = threading.Thread(target=cancelled_worker, daemon=True)
        prior_worker.start()
        controller._tts_render_thread = prior_worker
        original_question = QtWidgets.QMessageBox.question
        try:
            QtWidgets.QMessageBox.question = staticmethod(
                lambda *_args, **_kwargs: QtWidgets.QMessageBox.No
            )
            controller._clear_tts_cache_requested()
            assert controller._tts_render_job_id == 21
            assert bundle_path.is_file()
            assert controller._tts_ready_segments == {0: ready}

            QtWidgets.QMessageBox.question = staticmethod(
                lambda *_args, **_kwargs: QtWidgets.QMessageBox.Yes
            )
            controller._clear_tts_cache_requested()
            assert controller._tts_render_job_id == 22
            assert getattr(controller, "_tts_cache_clear_in_progress", False)
            assert not controller.audio_story_play_button.isEnabled()
            assert not controller.audio_story_tts_retry_button.isEnabled()
            assert not controller.audio_story_tts_clear_cache_button.isEnabled()
            blocked_job = controller._tts_render_job_id
            blocked_thread = controller._tts_render_thread

            controller._playback_mode_value = lambda: "source"
            controller.imported_audio_path = str(source_path)
            assert controller._active_audio_story_stream_path() == str(source_path)
            controller._play_story()
            assert controller._source_playback_expected
            assert Path(controller.audio_player.sources[-1]) == source_path

            controller._playback_mode_value = lambda: "tts"
            controller._play_story()
            controller._retry_tts_rendering()
            controller._start_tts_render(controller._compute_tts_signature())
            assert controller._tts_render_job_id == blocked_job
            assert controller._tts_render_thread is blocked_thread
            assert not controller._tts_cast_ready()
            controller.audio_story_cast_status_label = _FakeLabel()
            controller._cast_current_visual_to_chromecast()
            assert statuses[-1] == "TTS cache clear is in progress."
            assert controller.audio_story_cast_status_label.text == statuses[-1]
            time.sleep(0.05)
            app.processEvents()
            assert not results
            release_cancelled_worker.set()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and controller._tts_bundle is not None:
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            assert results
            assert results[-1]["file_count"] == 5
            assert results[-1]["directory_count"] == 1
            assert not getattr(controller, "_tts_cache_clear_in_progress", False)
            assert controller._tts_queue_plan is None
            assert controller._tts_ready_segments == {}
            assert controller._tts_bundle is None
            assert controller._tts_signature == ""
            assert not (root / "tts_segments").exists()
            assert not bundle_path.exists()
            assert not bundle_metadata_path.exists()
            assert not bundle_commit_path.exists()
            assert all(path.is_file() for path in (source_path, transcript_path, project_path, image_path))
            assert statuses[-1] == "Cleared 5 TTS cache files and 1 directory."
        finally:
            release_cancelled_worker.set()
            prior_worker.join(timeout=2.0)
            QtWidgets.QMessageBox.question = original_question
            controller.shutdown()


def test_controller_late_tts_cache_clear_result_cannot_mutate_replacement() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, ready = _tts_playback_fixture(
            Path(directory), (10.0,), ready_indices=(0,)
        )
        controller._tts_cache_clear_job_id = 5
        controller._tts_cache_clear_in_progress = True
        old_job = controller._tts_render_job_id
        old_plan = controller._tts_queue_plan
        controller._tts_render_job_id += 1
        replacement_bundle = {
            "audio_path": str(ready[0].plan.audio_path),
            "duration_seconds": 10.0,
        }
        controller._tts_bundle = replacement_bundle
        controller._tts_signature = old_plan.signature
        try:
            controller._on_tts_cache_clear_finished(
                {
                    "clear_job_id": 4,
                    "tts_job_id": old_job,
                    "project_id": old_plan.project_id,
                    "queue_signature": old_plan.signature,
                    "file_count": 2,
                    "directory_count": 1,
                }
            )
            assert controller._tts_queue_plan is old_plan
            assert controller._tts_ready_segments == ready
            assert controller._tts_bundle is replacement_bundle
            assert controller._tts_cache_clear_in_progress
        finally:
            controller.shutdown()


def test_controller_owned_cache_clear_failure_releases_for_retry_only() -> None:
    from PySide6 import QtWidgets

    controller_module = _require_module("addons.audio_story_mode.controller")
    app = _qt_application()
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, ready = _tts_playback_fixture(
            Path(directory), (10.0,), ready_indices=(0,)
        )
        statuses: list[str] = []
        results: list[dict] = []
        controller._set_status = statuses.append
        controller.ttsCacheClearFinished.connect(results.append)
        release_retry = threading.Event()
        calls = 0

        def fail_then_wait(_cache_root):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected clear failure")
            assert release_retry.wait(2.0)
            return 0, 0

        original_clear = controller_module.clear_audio_story_tts_cache
        original_question = QtWidgets.QMessageBox.question
        controller_module.clear_audio_story_tts_cache = fail_then_wait
        QtWidgets.QMessageBox.question = staticmethod(
            lambda *_args, **_kwargs: QtWidgets.QMessageBox.Yes
        )
        try:
            controller._clear_tts_cache_requested()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and getattr(
                controller, "_tts_cache_clear_in_progress", False
            ):
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            assert not getattr(controller, "_tts_cache_clear_in_progress", False)
            assert "injected clear failure" in statuses[-1]
            assert controller._tts_queue_plan is not None
            assert controller._tts_ready_segments == ready

            failed_result = dict(results[-1])
            controller._clear_tts_cache_requested()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and calls < 2:
                time.sleep(0.005)
            assert calls == 2
            assert getattr(controller, "_tts_cache_clear_in_progress", False)
            controller._on_tts_cache_clear_finished(failed_result)
            assert getattr(controller, "_tts_cache_clear_in_progress", False)
            assert controller._tts_queue_plan is not None

            release_retry.set()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and getattr(
                controller, "_tts_cache_clear_in_progress", False
            ):
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            assert not getattr(controller, "_tts_cache_clear_in_progress", False)
            assert controller._tts_queue_plan is None
            assert statuses[-1] == "Cleared 0 TTS cache files and 0 directories."
        finally:
            release_retry.set()
            controller_module.clear_audio_story_tts_cache = original_clear
            QtWidgets.QMessageBox.question = original_question
            controller.shutdown()


def test_controller_tts_cast_waits_for_owned_full_bundle_only() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller_module = _require_module("addons.audio_story_mode.controller")
        controller, _plans, _ready = _tts_playback_fixture(
            root, (10.0,), ready_indices=(0,)
        )
        controller._cache_root = root
        controller.audio_story_cast_status_label = _FakeLabel()
        statuses: list[str] = []
        stream_starts: list[bool] = []
        controller._set_status = statuses.append
        controller._stored_chromecast_device_name = "Fake Cast"
        controller._start_visual_stream = (
            lambda *, silent: stream_starts.append(bool(silent)) or False
        )
        original_audio_from_wav = controller_module.audio_story_runtime.audio_from_wav
        controller_module.audio_story_runtime.audio_from_wav = (
            lambda _path: types.SimpleNamespace(duration_seconds=10.0)
        )
        try:
            assert not controller._tts_cast_ready()
            controller._cast_current_visual_to_chromecast()
            expected = "TTS is still preparing for Chromecast."
            assert statuses[-1] == expected
            assert controller.audio_story_cast_status_label.text == expected
            assert stream_starts == []

            plan = controller._tts_queue_plan
            bundle_path, bundle_identity = _write_committed_tts_bundle(
                root,
                signature=plan.signature,
                project_id=plan.project_id,
                duration_seconds=10.0,
                chunks=[dict(controller.transcript_chunks[0])],
            )
            controller._on_tts_queue_complete(
                {
                    "job_id": controller._tts_render_job_id,
                    "project_id": plan.project_id,
                    "queue_signature": plan.signature,
                    "audio_path": str(bundle_path.resolve()),
                    "duration_seconds": 10.0,
                    "chunks": [dict(controller.transcript_chunks[0])],
                    "signature": plan.signature,
                    "bundle_identity": bundle_identity,
                }
            )
            assert controller._tts_cast_ready()
            assert controller._active_audio_story_stream_path() == str(
                bundle_path.resolve()
            )
            controller._cast_current_visual_to_chromecast()
            app = _qt_application()
            deadline = time.monotonic() + 2.0
            while controller._tts_bundle_validation_pending and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            assert not controller._tts_bundle_validation_pending
            assert stream_starts and all(stream_starts)
            stream_starts.clear()

            commit_path = Path(bundle_identity["commit_path"])
            commit_path.write_text("{}", encoding="utf-8")
            assert controller._tts_cast_ready()
            controller._cast_current_visual_to_chromecast()
            app = _qt_application()
            deadline = time.monotonic() + 2.0
            while controller._tts_bundle_validation_pending and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            assert not controller._tts_bundle_validation_pending
            assert controller._tts_bundle is None
            assert controller._tts_signature == ""
            assert stream_starts == []
            assert statuses[-1].startswith("TTS bundle validation failed:")

            controller._tts_signature = "wrong-signature"
            assert not controller._tts_cast_ready()

            controller._tts_queue_plan = None
            controller._tts_signature = ""
            controller._tts_bundle = {"audio_path": str(bundle_path.resolve())}
            assert not controller._tts_cast_ready()

            source_path = root / "source.wav"
            source_path.write_bytes(b"source")
            controller._playback_mode_value = lambda: "source"
            controller.imported_audio_sources = []
            controller.imported_audio_path = str(source_path)
            assert controller._active_audio_story_stream_path() == str(source_path)
        finally:
            controller_module.audio_story_runtime.audio_from_wav = original_audio_from_wav
            controller.shutdown()


def test_controller_tts_cast_readiness_never_uses_worker_hash_helper_on_gui() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller, _plans, _ready = _tts_playback_fixture(
            root, (10.0,), ready_indices=(0,)
        )
        controller._cache_root = root
        plan = controller._tts_queue_plan
        audio_path, identity = _write_committed_tts_bundle(
            root,
            signature=plan.signature,
            project_id=plan.project_id,
            duration_seconds=10.0,
            chunks=[dict(controller.transcript_chunks[0])],
        )
        try:
            controller._on_tts_queue_complete(
                {
                    "job_id": controller._tts_render_job_id,
                    "project_id": plan.project_id,
                    "queue_signature": plan.signature,
                    "audio_path": str(audio_path.resolve()),
                    "duration_seconds": 10.0,
                    "chunks": [dict(controller.transcript_chunks[0])],
                    "signature": plan.signature,
                    "bundle_identity": identity,
                }
            )
            original_hash = controller._tts_bundle_file_sha256

            def fail_gui_hash(_path):
                raise AssertionError("worker hash helper called on the Qt thread")

            controller._tts_bundle_file_sha256 = fail_gui_hash
            try:
                assert controller._tts_cast_ready()
            finally:
                controller._tts_bundle_file_sha256 = original_hash
        finally:
            controller.shutdown()


def test_controller_tts_same_size_wav_corruption_blocks_cast() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller, _plans, _ready = _tts_playback_fixture(
            root, (10.0,), ready_indices=(0,)
        )
        controller._cache_root = root
        controller.audio_story_cast_status_label = _FakeLabel()
        controller.audio_story_cast_button = _FakeButton()
        statuses: list[str] = []
        stream_starts: list[bool] = []
        controller._set_status = statuses.append
        controller._stored_chromecast_device_name = "Fake Cast"
        controller._start_visual_stream = (
            lambda *, silent: stream_starts.append(bool(silent)) or False
        )
        plan = controller._tts_queue_plan
        audio_path, identity = _write_committed_tts_bundle(
            root,
            signature=plan.signature,
            project_id=plan.project_id,
            duration_seconds=10.0,
            chunks=[dict(controller.transcript_chunks[0])],
        )
        try:
            controller._on_tts_queue_complete(
                {
                    "job_id": controller._tts_render_job_id,
                    "project_id": plan.project_id,
                    "queue_signature": plan.signature,
                    "audio_path": str(audio_path.resolve()),
                    "duration_seconds": 10.0,
                    "chunks": [dict(controller.transcript_chunks[0])],
                    "signature": plan.signature,
                    "bundle_identity": identity,
                }
            )
            assert controller._tts_cast_ready()
            _overwrite_same_size_with_new_mtime(audio_path)
            assert controller._tts_cast_ready()
            validation_started = threading.Event()
            release_validation = threading.Event()
            original_validate = controller._validate_committed_tts_bundle
            controller_thread_id = threading.get_ident()

            def gated_validate(**kwargs):
                assert threading.get_ident() != controller_thread_id
                validation_started.set()
                assert release_validation.wait(timeout=2.0)
                return original_validate(**kwargs)

            controller._validate_committed_tts_bundle = gated_validate
            controller._cast_current_visual_to_chromecast()
            assert validation_started.wait(timeout=1.0)
            assert controller._tts_bundle_validation_pending
            assert not controller.audio_story_cast_button.isEnabled()
            assert statuses[-1] == "Validating the TTS bundle for Chromecast..."
            release_validation.set()
            app = _qt_application()
            deadline = time.monotonic() + 2.0
            while controller._tts_bundle_validation_pending and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            assert not controller._tts_bundle_validation_pending
            assert stream_starts == []
            assert controller._tts_bundle is None
            assert statuses[-1].startswith("TTS bundle validation failed:")
        finally:
            controller.shutdown()


def test_controller_tts_completion_rejects_post_validation_wav_mutation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller, _plans, _ready = _tts_playback_fixture(
            root, (10.0,), ready_indices=(0,)
        )
        controller._cache_root = root
        plan = controller._tts_queue_plan
        audio_path, identity = _write_committed_tts_bundle(
            root,
            signature=plan.signature,
            project_id=plan.project_id,
            duration_seconds=10.0,
            chunks=[dict(controller.transcript_chunks[0])],
        )
        _overwrite_same_size_with_new_mtime(audio_path)
        controller.audio_story_cast_status_label = _FakeLabel()
        statuses: list[str] = []
        stream_starts: list[bool] = []
        controller._set_status = statuses.append
        controller._stored_chromecast_device_name = "Fake Cast"
        controller._start_visual_stream = (
            lambda *, silent: stream_starts.append(bool(silent)) or False
        )
        try:
            controller._on_tts_queue_complete(
                {
                    "job_id": controller._tts_render_job_id,
                    "project_id": plan.project_id,
                    "queue_signature": plan.signature,
                    "audio_path": str(audio_path.resolve()),
                    "duration_seconds": 10.0,
                    "chunks": [dict(controller.transcript_chunks[0])],
                    "signature": plan.signature,
                    "bundle_identity": identity,
                }
            )
            assert controller._tts_bundle is not None
            assert controller._tts_signature == plan.signature
            controller._cast_current_visual_to_chromecast()
            app = _qt_application()
            deadline = time.monotonic() + 2.0
            while controller._tts_bundle_validation_pending and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            assert not controller._tts_bundle_validation_pending
            assert controller._tts_bundle is None
            assert controller._tts_signature == ""
            assert stream_starts == []
            assert statuses[-1].startswith("TTS bundle validation failed:")
        finally:
            controller.shutdown()


def _prime_async_tts_player(
    controller, plan, *, position_ms: int = 2000, player=None
):
    player = player or _AsyncLoadingFakePlayer()
    player.prime_source(plan.audio_path, position_ms=position_ms)
    player.positionChanged.connect(controller._on_player_position_changed)
    player.mediaStatusChanged.connect(controller._on_player_media_status_changed)
    player.seekableChanged.connect(controller._on_player_seekable_changed)
    controller.audio_player = player
    controller._player_source_key = (
        f"tts-segment::{controller._tts_queue_plan.signature}::"
        f"{plan.signature}"
    )
    controller._tts_active_segment_index = int(plan.index)
    controller._tts_active_segment_global_offset = 0.0
    controller._tts_playback_position_seconds = max(
        0.0, float(position_ms) / 1000.0
    )
    return player


def test_controller_tts_segment_switches_preserve_one_global_timeline() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 10.0, 10.0), ready_indices=(0, 1, 2)
        )
        try:
            assert controller._set_tts_segment_for_global_position(12.5)
            assert controller._tts_active_segment_index == 1
            assert controller.audio_player.position() == 2500
            assert controller._player_position_seconds() == 12.5
            assert Path(controller.audio_player.sources[-1]).name == "segment-1.wav"

            controller._tts_resume_after_buffering = True
            controller.audio_player.mediaStatusChanged.emit(_qt_end_of_media())
            assert controller._tts_active_segment_index == 2
            assert controller.audio_player.position() == 0
            assert controller._player_position_seconds() == 20.0
            assert controller.audio_player.play_calls == 1
            assert Path(controller.audio_player.sources[-1]).name == "segment-2.wav"
        finally:
            controller.shutdown()


def test_controller_tts_underrun_waits_for_rebuilt_startup_buffer() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 2.0, 3.0, 4.0), ready_indices=(0,)
        )
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        controller._stored_tts_startup_buffer_seconds = 5
        controller._tts_resume_after_buffering = True
        try:
            assert controller._set_tts_segment_for_global_position(5.0)
            controller.audio_player.mediaStatusChanged.emit(_qt_end_of_media())
            assert controller.audio_player.pause_calls == 1
            assert controller._tts_queue_state == "Buffering"
            assert controller._tts_resume_after_buffering
            assert controller._tts_active_segment_index == 0
            assert controller._tts_active_segment_global_offset == 0.0
            assert controller._tts_render_target_segment_index == 1
            assert controller._tts_buffering_target_seconds == 10.0
            assert controller._tts_playback_position_seconds == 10.0

            segment_one = queue_module.TtsReadySegment(
                plan=plans[1],
                duration_seconds=2.0,
                chunk_offsets=((1, 0.0, 2.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, segment_one)
            )
            assert controller.audio_player.play_calls == 0
            assert controller._tts_queue_state == "Buffering"

            segment_two = queue_module.TtsReadySegment(
                plan=plans[2],
                duration_seconds=3.0,
                chunk_offsets=((2, 0.0, 3.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, segment_two)
            )
            assert controller.audio_player.play_calls == 1
            assert controller._tts_queue_state == "Ready"
            assert controller._tts_active_segment_index == 1
            assert controller._tts_buffering_target_seconds is None
            assert controller.audio_player.position() == 0
            assert controller._player_position_seconds() == 10.0
        finally:
            controller.shutdown()


def test_controller_tts_underrun_resumes_when_all_remaining_audio_is_ready() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 2.0), ready_indices=(0,)
        )
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        controller._stored_tts_startup_buffer_seconds = 30
        controller._tts_resume_after_buffering = True
        controller._start_playback_with_visual_sync = (
            lambda _position, *, status_text: controller.audio_player.play()
        )
        try:
            assert controller._set_tts_segment_for_global_position(5.0)
            controller.audio_player.mediaStatusChanged.emit(_qt_end_of_media())
            final_ready = queue_module.TtsReadySegment(
                plan=plans[1],
                duration_seconds=2.0,
                chunk_offsets=((1, 0.0, 2.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, final_ready)
            )
            assert controller.audio_player.play_calls == 1
            assert controller._tts_queue_state == "Ready"
        finally:
            controller.shutdown()


def test_controller_tts_seek_ready_and_unready_preserves_play_intent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (8.0, 7.0, 6.0, 6.0), ready_indices=(0, 1)
        )
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        controller._stored_tts_startup_buffer_seconds = 5
        controller._tts_resume_after_buffering = True
        controller._start_playback_with_visual_sync = (
            lambda _position, *, status_text: controller.audio_player.play()
        )
        try:
            assert controller._set_tts_segment_for_global_position(2.0)
            controller.audio_player.play()
            controller.audio_player.play_calls = 0
            assert controller._set_player_global_position(10.5)
            assert controller._tts_active_segment_index == 1
            assert controller.audio_player.position() == 2500
            assert controller.audio_player.play_calls == 1

            assert not controller._set_player_global_position(18.0)
            assert controller.audio_player.pause_calls == 1
            assert controller._tts_queue_state == "Buffering"
            assert controller._tts_resume_after_buffering
            assert controller._tts_active_segment_index == 1
            assert controller._tts_active_segment_global_offset == 8.0
            assert controller._tts_render_target_segment_index == 2
            assert controller._tts_render_target_segment_global_offset == 15.0
            assert controller._tts_buffering_target_seconds == 18.0
            assert controller._tts_playback_position_seconds == 18.0

            third_ready = queue_module.TtsReadySegment(
                plan=plans[2],
                duration_seconds=6.0,
                chunk_offsets=((2, 0.0, 6.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, third_ready)
            )
            assert controller.audio_player.play_calls == 1

            fourth_ready = queue_module.TtsReadySegment(
                plan=plans[3],
                duration_seconds=6.0,
                chunk_offsets=((3, 0.0, 6.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, fourth_ready)
            )
            assert controller.audio_player.play_calls == 2
            assert controller.audio_player.position() == 3000
            assert controller._player_position_seconds() == 18.0
            assert controller._tts_buffering_target_seconds is None
        finally:
            controller.shutdown()


def test_controller_tts_buffered_seek_keeps_authoritative_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (8.0, 7.0, 6.0), ready_indices=(0, 1)
        )
        controller_module = _require_module("addons.audio_story_mode.controller")
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        controller.audio_story_position_slider = _FakeSlider()
        controller.audio_story_time_label = _FakeLabel()
        controller._update_slider_range = (
            controller_module.AudioStoryModeController._update_slider_range.__get__(
                controller
            )
        )
        controller._stored_tts_startup_buffer_seconds = 5
        controller._tts_resume_after_buffering = True
        try:
            assert controller._set_tts_segment_for_global_position(2.5)
            controller.audio_player.play()
            controller.audio_player.play_calls = 0
            assert not controller._set_player_global_position(18.0)

            assert controller._tts_buffering_target_seconds == 18.0
            assert controller._tts_active_segment_index == 0
            assert controller._tts_active_segment_global_offset == 0.0
            assert controller._tts_render_target_segment_index == 2
            assert controller.audio_player.position() == 2500
            assert controller._player_position_seconds() == 18.0
            assert controller._tts_playback_position_seconds == 18.0
            assert controller.audio_story_position_slider.current_value == 18000
            assert controller.audio_story_time_label.text.startswith("00:18 / ")

            controller.audio_player.positionChanged.emit(2750)
            assert controller._player_position_seconds() == 18.0
            assert controller._tts_playback_position_seconds == 18.0
            assert controller.audio_story_position_slider.current_value == 18000

            controller._pause_story()
            controller.audio_player.positionChanged.emit(3000)
            assert controller._player_position_seconds() == 18.0
            assert controller._tts_playback_position_seconds == 18.0
            assert controller.audio_story_position_slider.current_value == 18000
            assert not controller._tts_resume_after_buffering

            final_ready = queue_module.TtsReadySegment(
                plan=plans[2],
                duration_seconds=6.0,
                chunk_offsets=((2, 0.0, 6.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, final_ready)
            )
            assert controller._tts_buffering_target_seconds is None
            assert controller._tts_active_segment_index == 2
            assert controller._tts_active_segment_global_offset == 15.0
            assert controller.audio_player.position() == 3000
            assert controller._player_position_seconds() == 18.0
            assert controller.audio_player.play_calls == 0
        finally:
            controller.shutdown()


def test_controller_tts_explicit_seek_supersedes_buffered_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, _plans, _ready = _tts_playback_fixture(
            Path(directory), (8.0, 7.0, 6.0), ready_indices=(0, 1)
        )
        controller_module = _require_module("addons.audio_story_mode.controller")
        controller.audio_story_position_slider = _FakeSlider()
        controller.audio_story_time_label = _FakeLabel()
        controller._update_slider_range = (
            controller_module.AudioStoryModeController._update_slider_range.__get__(
                controller
            )
        )
        visual_positions: list[float] = []
        controller._sync_visual_to_position = (
            lambda position, *_args, **_kwargs: visual_positions.append(
                float(position)
            )
        )
        controller._tts_resume_after_buffering = True
        try:
            assert controller._set_tts_segment_for_global_position(2.5)
            controller.audio_player.play()
            assert not controller._set_player_global_position(18.0)
            assert controller._tts_buffering_target_seconds == 18.0

            visual_positions.clear()
            assert controller._set_player_global_position(2.0)
            assert controller.audio_player.position() == 2000
            assert controller._player_position_seconds() == 2.0
            assert controller._tts_playback_position_seconds == 2.0
            assert controller.audio_story_position_slider.current_value == 2000
            assert visual_positions[-1] == 2.0
            assert controller._tts_buffering_target_seconds is None
            assert controller._tts_queue_state == "Ready"
            assert controller._tts_resume_after_buffering
            assert controller._is_audio_story_currently_playing()

            controller.audio_player.positionChanged.emit(2750)
            assert controller._tts_buffering_target_seconds is None
            assert controller._player_position_seconds() == 2.0
            assert controller._tts_playback_position_seconds != 18.0
            assert controller.audio_story_position_slider.current_value != 18000
            assert visual_positions[-1] != 18.0

            assert controller._set_player_global_position(2.0)
            visual_positions.clear()
            assert not controller._set_player_global_position(18.0)
            assert controller._tts_buffering_target_seconds == 18.0
            assert not controller._set_player_global_position(16.0)
            assert controller._tts_buffering_target_seconds == 16.0
            assert controller._tts_playback_position_seconds == 16.0
            assert controller._tts_render_target_segment_index == 2
            assert controller._tts_render_target_segment_global_offset == 15.0
            assert controller.audio_player.position() == 2000
            assert controller.audio_story_position_slider.current_value == 16000
            assert visual_positions[-1] == 16.0
            assert controller._tts_queue_state == "Buffering"
            assert controller._tts_resume_after_buffering

            controller.audio_player.positionChanged.emit(3000)
            assert controller._tts_buffering_target_seconds == 16.0
            assert controller._tts_playback_position_seconds == 16.0
            assert controller.audio_story_position_slider.current_value == 16000
            assert visual_positions[-1] == 16.0
        finally:
            controller.shutdown()


def test_controller_tts_changed_source_waits_for_owned_media_load() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 5.0), ready_indices=(0, 1)
        )
        controller_module = _require_module("addons.audio_story_mode.controller")
        player = _AsyncLoadingFakePlayer()
        player.prime_source(plans[0].audio_path, position_ms=2000)
        player.positionChanged.connect(controller._on_player_position_changed)
        player.mediaStatusChanged.connect(controller._on_player_media_status_changed)
        seekable_handler = getattr(controller, "_on_player_seekable_changed", None)
        if callable(seekable_handler):
            player.seekableChanged.connect(seekable_handler)
        controller.audio_player = player
        controller._player_source_key = (
            f"tts-segment::{controller._tts_queue_plan.signature}::"
            f"{plans[0].signature}"
        )
        controller._tts_active_segment_index = 0
        controller._tts_active_segment_global_offset = 0.0
        controller._tts_playback_position_seconds = 2.0
        controller._tts_resume_after_buffering = True
        controller.audio_story_position_slider = _FakeSlider()
        controller.audio_story_time_label = _FakeLabel()
        controller._update_slider_range = (
            controller_module.AudioStoryModeController._update_slider_range.__get__(
                controller
            )
        )
        visual_positions: list[float] = []
        controller._sync_visual_to_position = (
            lambda position, *_args, **_kwargs: visual_positions.append(
                float(position)
            )
        )
        try:
            player.play()
            assert not controller._set_player_global_position(12.5)

            pending = controller._tts_pending_media_transition
            assert pending is not None
            assert pending.job_id == controller._tts_render_job_id
            assert pending.project_id == controller._tts_queue_plan.project_id
            assert pending.queue_signature == controller._tts_queue_plan.signature
            assert pending.segment_signature == plans[1].signature
            assert pending.segment_index == 1
            assert pending.audio_path == plans[1].audio_path.resolve()
            assert pending.global_target_seconds == 12.5
            assert pending.local_target_seconds == 2.5
            assert pending.resume_playback
            assert controller._tts_queue_state == "Buffering"
            assert controller._tts_buffering_target_seconds == 12.5
            assert controller._tts_active_segment_index == 0
            assert controller._tts_active_segment_global_offset == 0.0
            assert player.position_attempts[-1] == 2500
            assert player.position() == 0
            assert not controller._is_audio_story_currently_playing()

            player.emit_loaded()

            assert controller._tts_pending_media_transition is None
            assert controller._tts_buffering_target_seconds is None
            assert controller._tts_queue_state == "Ready"
            assert controller._tts_active_segment_index == 1
            assert controller._tts_active_segment_global_offset == 10.0
            assert player.position() == 2500
            assert controller._player_position_seconds() == 12.5
            assert controller._tts_playback_position_seconds == 12.5
            assert controller.audio_story_position_slider.current_value == 12500
            assert visual_positions[-1] == 12.5
            assert controller._is_audio_story_currently_playing()
        finally:
            controller.shutdown()


def test_controller_tts_stale_load_cannot_complete_replaced_queue() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 5.0), ready_indices=(0, 1)
        )
        player = _AsyncLoadingFakePlayer()
        player.prime_source(plans[0].audio_path, position_ms=2000)
        player.positionChanged.connect(controller._on_player_position_changed)
        player.mediaStatusChanged.connect(controller._on_player_media_status_changed)
        player.seekableChanged.connect(controller._on_player_seekable_changed)
        controller.audio_player = player
        controller._player_source_key = (
            f"tts-segment::{controller._tts_queue_plan.signature}::"
            f"{plans[0].signature}"
        )
        controller._tts_active_segment_index = 0
        controller._tts_active_segment_global_offset = 0.0
        controller._tts_playback_position_seconds = 2.0
        controller._tts_resume_after_buffering = True
        try:
            player.play()
            assert not controller._set_player_global_position(12.5)
            assert controller._tts_pending_media_transition is not None
            superseded_job_id = controller._tts_render_job_id
            play_calls = player.play_calls

            controller._invalidate_tts_queue(clear_plan=True)

            assert controller._tts_render_job_id == superseded_job_id + 1
            assert controller._tts_pending_media_transition is None
            assert controller._tts_queue_plan is None
            assert controller._tts_buffering_target_seconds is None
            assert controller._tts_active_segment_index == 0

            player.emit_loaded()
            assert controller._tts_pending_media_transition is None
            assert controller._tts_queue_plan is None
            assert controller._tts_active_segment_index == 0
            assert player.position() == 0
            assert player.play_calls == play_calls
            assert not controller._is_audio_story_currently_playing()
        finally:
            controller.shutdown()


def test_controller_tts_end_waits_for_next_segment_media_load() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 5.0), ready_indices=(0, 1)
        )
        player = _AsyncLoadingFakePlayer()
        player.prime_source(plans[0].audio_path, position_ms=10000)
        player.positionChanged.connect(controller._on_player_position_changed)
        player.mediaStatusChanged.connect(controller._on_player_media_status_changed)
        player.seekableChanged.connect(controller._on_player_seekable_changed)
        controller.audio_player = player
        controller._player_source_key = (
            f"tts-segment::{controller._tts_queue_plan.signature}::"
            f"{plans[0].signature}"
        )
        controller._tts_active_segment_index = 0
        controller._tts_active_segment_global_offset = 0.0
        controller._tts_playback_position_seconds = 10.0
        controller._tts_resume_after_buffering = True
        try:
            player.play()
            play_calls = player.play_calls

            player.mediaStatusChanged.emit(_qt_end_of_media())

            pending = controller._tts_pending_media_transition
            assert pending is not None
            assert pending.segment_index == 1
            assert pending.global_target_seconds == 10.0
            assert pending.local_target_seconds == 0.0
            assert pending.resume_playback
            assert controller._tts_queue_state == "Buffering"
            assert controller._tts_buffering_target_seconds == 10.0
            assert player.play_calls == play_calls
            assert not controller._is_audio_story_currently_playing()

            player.emit_loaded()

            assert controller._tts_pending_media_transition is None
            assert controller._tts_buffering_target_seconds is None
            assert controller._tts_queue_state == "Ready"
            assert controller._tts_active_segment_index == 1
            assert controller._tts_active_segment_global_offset == 10.0
            assert player.position() == 0
            assert controller._player_position_seconds() == 10.0
            assert player.play_calls == play_calls + 1
            assert controller._is_audio_story_currently_playing()
        finally:
            controller.shutdown()


def test_controller_tts_image_ready_waits_for_media_transition() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller, plans, _ready = _tts_playback_fixture(
            root, (10.0, 5.0), ready_indices=(0, 1)
        )
        player = _prime_async_tts_player(controller, plans[0])
        image_path = root / "ready.png"
        image_path.write_bytes(b"ready-image")
        controller._image_generation_token = 41
        controller._tts_resume_after_buffering = True
        controller._pending_play_request = {
            "token": 41,
            "index": 1,
            "position_seconds": 12.5,
            "status_text": "Playing after image ready.",
        }
        controller._visual_reply_set_state = lambda _state: True
        playback_states: list[str] = []
        controller._sync_visual_stream_playback_state = (
            lambda *args, **kwargs: playback_states.append(
                str(args[0])
                if args
                else str(kwargs.get("playback_state", ""))
            )
        )
        try:
            controller._on_image_ready(
                {
                    "token": 41,
                    "index": 1,
                    "image_path": str(image_path),
                    "prompt_text": "Prompt 1",
                    "source_text": "Window 1",
                    "prompt_signature": "ready-signature",
                    "generation_mode": "fresh",
                    "reference_image_paths": [],
                }
            )

            pending = controller._tts_pending_media_transition
            assert pending is not None
            assert pending.global_target_seconds == 12.5
            assert pending.local_target_seconds == 2.5
            assert pending.resume_playback
            assert controller._tts_resume_after_buffering
            assert player.play_calls == 0
            assert not controller._is_audio_story_currently_playing()
            assert not playback_states or playback_states[-1] != "playing"

            player.emit_loaded()

            assert controller._tts_pending_media_transition is None
            assert controller._tts_buffering_target_seconds is None
            assert player.position() == 2500
            assert controller._player_position_seconds() == 12.5
            assert player.play_calls == 1
            assert controller._is_audio_story_currently_playing()
            assert playback_states[-1] == "playing"
        finally:
            controller.shutdown()


def test_controller_tts_image_failure_waits_for_media_transition() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 5.0), ready_indices=(0, 1)
        )
        player = _prime_async_tts_player(controller, plans[0])
        controller._image_generation_token = 42
        controller._tts_resume_after_buffering = True
        controller._pending_play_request = {
            "token": 42,
            "index": 1,
            "position_seconds": 12.5,
            "status_text": "Playing after image failure.",
        }
        controller._visual_reply_generation_info = lambda: {"provider": "xai"}
        controller._visual_reply_current_state = lambda: {"image_path": ""}
        controller._visual_reply_set_state = lambda _state: True
        playback_states: list[str] = []
        controller._sync_visual_stream_playback_state = (
            lambda *args, **kwargs: playback_states.append(
                str(args[0])
                if args
                else str(kwargs.get("playback_state", ""))
            )
        )
        try:
            controller._on_image_failed(
                {
                    "token": 42,
                    "index": 1,
                    "detail": "moderated",
                    "moderated": True,
                }
            )

            pending = controller._tts_pending_media_transition
            assert pending is not None
            assert pending.global_target_seconds == 12.5
            assert pending.local_target_seconds == 2.5
            assert pending.resume_playback
            assert controller._tts_resume_after_buffering
            assert player.play_calls == 0
            assert not controller._is_audio_story_currently_playing()
            assert not playback_states or playback_states[-1] != "playing"

            player.emit_loaded()

            assert controller._tts_pending_media_transition is None
            assert controller._tts_buffering_target_seconds is None
            assert player.position() == 2500
            assert controller._player_position_seconds() == 12.5
            assert player.play_calls == 1
            assert controller._is_audio_story_currently_playing()
            assert playback_states[-1] == "playing"
        finally:
            controller.shutdown()


def test_controller_tts_position_callback_completes_delayed_seek() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 5.0), ready_indices=(0, 1)
        )
        delayed_player = _DelayedSeekFakePlayer()
        player = _prime_async_tts_player(
            controller, plans[0], player=delayed_player
        )
        controller._tts_resume_after_buffering = True
        try:
            assert not controller._set_player_global_position(12.5)
            player.emit_loaded_without_applying_seek()
            assert controller._tts_pending_media_transition is not None
            assert controller._tts_buffering_target_seconds == 12.5
            assert player.position() == 0
            assert player.play_calls == 0
            attempts_after_load = len(player.position_attempts)

            expected_source = player.source()
            controller_module = _require_module(
                "addons.audio_story_mode.controller"
            )
            player._source = controller_module.QtCore.QUrl.fromLocalFile(
                str(plans[0].audio_path.resolve())
            )
            player.apply_delayed_position(2500)
            assert controller._tts_pending_media_transition is not None
            assert controller._tts_buffering_target_seconds == 12.5
            assert player.play_calls == 0

            player._source = expected_source
            player.positionChanged.emit(2500)

            assert controller._tts_pending_media_transition is None
            assert controller._tts_buffering_target_seconds is None
            assert controller._tts_queue_state == "Ready"
            assert controller._tts_active_segment_index == 1
            assert controller._tts_active_segment_global_offset == 10.0
            assert player.position() == 2500
            assert controller._player_position_seconds() == 12.5
            assert controller._tts_playback_position_seconds == 12.5
            assert len(player.position_attempts) == attempts_after_load
            assert player.play_calls == 1
            assert controller._is_audio_story_currently_playing()
        finally:
            controller.shutdown()


def test_controller_tts_synchronous_position_callback_is_reentrant_safe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (10.0, 5.0), ready_indices=(0, 1)
        )
        player = _prime_async_tts_player(controller, plans[0])
        controller._tts_resume_after_buffering = True
        try:
            assert not controller._set_player_global_position(12.5)
            assert player.position_attempts == [2500]

            player.emit_loaded()

            assert controller._tts_pending_media_transition is None
            assert controller._tts_buffering_target_seconds is None
            assert player.position() == 2500
            assert controller._player_position_seconds() == 12.5
            assert player.position_attempts == [2500, 2500]
            assert player.play_calls == 1
            assert controller._is_audio_story_currently_playing()
        finally:
            controller.shutdown()


def test_controller_tts_seek_unready_preserves_pause_intent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (8.0, 7.0, 6.0), ready_indices=(0, 1)
        )
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        controller._stored_tts_startup_buffer_seconds = 5
        controller._tts_resume_after_buffering = False
        try:
            assert not controller._set_player_global_position(18.0)
            final_ready = queue_module.TtsReadySegment(
                plan=plans[2],
                duration_seconds=6.0,
                chunk_offsets=((2, 0.0, 6.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, final_ready)
            )
            assert controller._tts_queue_state == "Ready"
            assert controller.audio_player.play_calls == 0
            assert controller.audio_player.position() == 3000
            assert not controller._tts_resume_after_buffering
            assert controller._tts_buffering_target_seconds is None
        finally:
            controller.shutdown()


def test_controller_tts_unready_seek_retargets_from_actual_ready_durations() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (5.0, 5.0, 5.0), ready_indices=(0,)
        )
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        estimated_plans = tuple(
            queue_module.TtsSegmentPlan(
                index=plan.index,
                signature=plan.signature,
                text=plan.text,
                window_indices=plan.window_indices,
                estimated_seconds=10.0,
                audio_path=plan.audio_path,
                metadata_path=plan.metadata_path,
            )
            for plan in plans
        )
        controller._tts_queue_plan = queue_module.TtsQueuePlan(
            signature=controller._tts_queue_plan.signature,
            project_id=controller._tts_queue_plan.project_id,
            segments=estimated_plans,
        )
        try:
            assert not controller._set_player_global_position(12.0)
            assert controller._tts_active_segment_index == 0
            assert controller._tts_active_segment_global_offset == 0.0
            assert controller._tts_render_target_segment_index == 1
            assert controller._tts_render_target_segment_global_offset == 5.0

            second_ready = queue_module.TtsReadySegment(
                plan=estimated_plans[1],
                duration_seconds=5.0,
                chunk_offsets=((1, 0.0, 5.0),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, second_ready)
            )
            assert controller._tts_queue_state == "Buffering"
            assert controller._tts_active_segment_index == 0
            assert controller._tts_active_segment_global_offset == 0.0
            assert controller._tts_render_target_segment_index == 2
            assert controller._tts_render_target_segment_global_offset == 10.0
            assert controller._tts_buffering_target_seconds == 12.0
            assert controller._tts_playback_position_seconds == 12.0
        finally:
            controller.shutdown()


def test_controller_tts_buffered_seek_uses_planned_visual_window() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controller, fixture_plans, _ready = _tts_playback_fixture(
            root, (4.0, 10.0), ready_indices=()
        )
        controller_module = _require_module("addons.audio_story_mode.controller")
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        controller.transcript_chunks = [
            {
                "index": 0,
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "text": "Rendered opening",
                "prompt": "Opening",
                "tts_start_seconds": None,
                "tts_end_seconds": None,
            },
            {
                "index": 1,
                "start_seconds": 5.0,
                "end_seconds": 6.5,
                "text": "Short unrendered window",
                "prompt": "Short",
                "tts_start_seconds": None,
                "tts_end_seconds": None,
            },
            {
                "index": 2,
                "start_seconds": 6.5,
                "end_seconds": 15.5,
                "text": "Long unrendered window",
                "prompt": "Long",
                "tts_start_seconds": None,
                "tts_end_seconds": None,
            },
        ]
        planned_segments = (
            queue_module.TtsSegmentPlan(
                index=0,
                signature=fixture_plans[0].signature,
                text="Rendered opening",
                window_indices=(0,),
                estimated_seconds=5.0,
                audio_path=fixture_plans[0].audio_path,
                metadata_path=fixture_plans[0].metadata_path,
            ),
            queue_module.TtsSegmentPlan(
                index=1,
                signature=fixture_plans[1].signature,
                text="Short unrendered window\nLong unrendered window",
                window_indices=(1, 2),
                estimated_seconds=10.0,
                audio_path=fixture_plans[1].audio_path,
                metadata_path=fixture_plans[1].metadata_path,
            ),
        )
        controller._tts_queue_plan = queue_module.TtsQueuePlan(
            signature="planned-visual-queue",
            project_id="",
            segments=planned_segments,
        )
        first_ready = queue_module.TtsReadySegment(
            plan=planned_segments[0],
            duration_seconds=4.0,
            chunk_offsets=((0, 0.0, 4.0),),
        )
        controller._tts_ready_segments = {0: first_ready}
        controller._rebuild_tts_transcript_timing()
        published_indices = []
        controller._sync_visual_to_position = (
            controller_module.AudioStoryModeController._sync_visual_to_position.__get__(
                controller
            )
        )
        controller._publish_visual_for_index = (
            lambda index, *, keep_current_image: published_indices.append(int(index))
        )
        controller._refresh_scene_override_controls = lambda: None
        controller._current_chunk_index = -1
        try:
            assert controller._set_tts_segment_for_global_position(1.0)
            assert not controller._set_player_global_position(6.0)
            assert published_indices[-1] == 2
            assert controller._current_chunk_index == 2
            assert controller.transcript_chunks[1]["tts_start_seconds"] is None
            assert controller.transcript_chunks[1]["tts_end_seconds"] is None
            assert controller.transcript_chunks[2]["tts_start_seconds"] is None
            assert controller.transcript_chunks[2]["tts_end_seconds"] is None
        finally:
            controller.shutdown()


def test_controller_tts_ready_offsets_require_current_owned_segments() -> None:
    with tempfile.TemporaryDirectory() as directory:
        controller, plans, _ready = _tts_playback_fixture(
            Path(directory), (8.0, 7.0, 6.0), ready_indices=()
        )
        queue_module = _require_module("addons.audio_story_mode.tts_segment_queue")
        original_chunks = tuple(controller.transcript_chunks)
        first_ready = queue_module.TtsReadySegment(
            plan=plans[0],
            duration_seconds=8.0,
            chunk_offsets=((0, 0.5, 7.5),),
        )
        try:
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, first_ready)
            )
            assert controller.transcript_chunks[0] is not original_chunks[0]
            assert controller.transcript_chunks[0]["tts_start_seconds"] == 0.5
            assert controller.transcript_chunks[0]["tts_end_seconds"] == 7.5
            assert controller.transcript_chunks[1]["tts_start_seconds"] is None

            stale_ready = queue_module.TtsReadySegment(
                plan=plans[1],
                duration_seconds=7.0,
                chunk_offsets=((1, 0.25, 6.5),),
            )
            stale_payload = _ready_tts_payload(controller, stale_ready)
            stale_payload["job_id"] -= 1
            controller._on_tts_segment_ready(stale_payload)
            assert controller.transcript_chunks[1]["tts_start_seconds"] is None

            wrong_path_plan = queue_module.TtsSegmentPlan(
                index=plans[1].index,
                signature=plans[1].signature,
                text=plans[1].text,
                window_indices=plans[1].window_indices,
                estimated_seconds=plans[1].estimated_seconds,
                audio_path=Path(directory) / "wrong-owned-segment.wav",
                metadata_path=plans[1].metadata_path,
            )
            wrong_path_ready = queue_module.TtsReadySegment(
                plan=wrong_path_plan,
                duration_seconds=7.0,
                chunk_offsets=((1, 0.25, 6.5),),
            )
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, wrong_path_ready)
            )
            assert 1 not in controller._tts_ready_segments
            assert controller.transcript_chunks[1]["tts_start_seconds"] is None

            mismatched_plan = queue_module.TtsSegmentPlan(
                index=1,
                signature="stale-segment-signature",
                text=plans[1].text,
                window_indices=plans[1].window_indices,
                estimated_seconds=plans[1].estimated_seconds,
                audio_path=plans[1].audio_path,
                metadata_path=plans[1].metadata_path,
            )
            mismatched_ready = queue_module.TtsReadySegment(
                plan=mismatched_plan,
                duration_seconds=7.0,
                chunk_offsets=((1, 0.25, 6.5),),
            )
            controller._tts_ready_segments[1] = mismatched_ready
            assert not controller._set_tts_segment_for_global_position(9.0)
            controller._stored_tts_startup_buffer_seconds = 5
            controller._tts_queue_state = "Buffering"
            controller._tts_active_segment_index = 0
            controller._tts_active_segment_global_offset = 0.0
            controller._tts_playback_position_seconds = 7.0
            controller._tts_resume_after_buffering = True
            assert not controller._finish_tts_buffering_if_ready()
            assert controller.audio_player.play_calls == 0
            assert controller._tts_queue_state == "Buffering"

            controller._tts_ready_segments.pop(1)
            controller._on_tts_segment_ready(
                _ready_tts_payload(controller, stale_ready)
            )
            assert controller.transcript_chunks[1]["tts_start_seconds"] == 8.25
            assert controller.transcript_chunks[1]["tts_end_seconds"] == 14.5
            assert controller.transcript_chunks[2]["tts_start_seconds"] is None
        finally:
            controller.shutdown()


def test_controller_player_position_uses_combined_story_timeline() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller.imported_audio_sources = _sample_sources(10.0, 7.5)
    controller._active_source_index = 1
    controller._active_source_global_offset = 10.0
    controller.audio_player = _FakePlayer(position_ms=3000)
    assert controller._player_position_seconds() == 13.0


def test_controller_global_seek_selects_chapter_and_local_position() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller.imported_audio_sources = _sample_sources(10.0, 7.5)
    controller.imported_audio_paths = [item.path for item in controller.imported_audio_sources]
    controller.imported_audio_path = controller.imported_audio_paths[0]
    controller.audio_player = _FakePlayer()
    assert controller._set_source_for_global_position(12.25)
    assert controller._active_source_index == 1
    assert controller.audio_player.position() == 2250
    assert Path(controller.audio_player.sources[-1]).name == "chapter_2.wav"


def test_controller_source_media_end_behavior_remains_unchanged() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller.imported_audio_sources = _sample_sources(10.0, 7.5)
    controller.imported_audio_paths = [
        item.path for item in controller.imported_audio_sources
    ]
    controller.imported_audio_path = controller.imported_audio_paths[0]
    controller.imported_audio_duration_seconds = 17.5
    controller.audio_player = _FakePlayer()
    controller.audio_player.mediaStatusChanged.connect(
        controller._on_player_media_status_changed
    )
    controller._sync_visual_stream_playback_state = lambda *_args, **_kwargs: None
    controller._set_status = lambda _message: None
    controller._source_playback_expected = True
    try:
        controller.audio_player.mediaStatusChanged.emit(_qt_end_of_media())
        assert controller._active_source_index == 1
        assert controller._active_source_global_offset == 10.0
        assert controller.audio_player.position() == 0
        assert controller.audio_player.play_calls == 1
        assert Path(controller.audio_player.sources[-1]).name == "chapter_2.wav"

        controller.audio_player.mediaStatusChanged.emit(_qt_end_of_media())
        assert not controller._source_playback_expected
        assert controller.audio_player.play_calls == 1
    finally:
        controller.shutdown()


def test_controller_disables_stale_sources_while_queue_is_reprobed() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller.imported_audio_sources = _sample_sources(10.0)
    controller.imported_audio_paths = [controller.imported_audio_sources[0].path]
    controller.imported_audio_path = controller.imported_audio_paths[0]
    controller._set_imported_audio_paths([], clear_story=True)
    assert controller.imported_audio_sources == []
    assert controller.imported_audio_path == ""


def test_structured_story_beats_convert_to_existing_scene_shape() -> None:
    models = _require_module("addons.audio_story_mode.structured_models")
    assert models.PYDANTIC_AVAILABLE
    response = models.StoryBeatAnalysis.model_validate(
        {
            "story_summary": "A traveler reaches a storm-lit station.",
            "global_visual_style": "cinematic illustrated realism",
            "world_anchor": "rainy modern rail station",
            "beats": [
                {
                    "beat_id": "beat_arrival",
                    "chunk_index": 0,
                    "start_seconds": 0.0,
                    "end_seconds": 8.0,
                    "story_event": "The traveler enters the station.",
                    "visible_action": "A traveler steps through the station doors.",
                    "location_id": "loc_station",
                    "mood": "uneasy",
                    "lighting": "cold blue lightning",
                    "camera": "wide establishing shot",
                    "continuity_anchors": ["dark raincoat"],
                    "visual_change_score": 0.9,
                    "image_worthy": True,
                    "source_evidence": "The station doors opened as thunder rolled.",
                    "confidence": 0.8,
                    "avoid": ["extra travelers"],
                }
            ],
        }
    )
    converted = models.story_beat_payload_to_existing_analysis(response.model_dump())
    assert converted["story_bible"]["summary"].startswith("A traveler")
    assert converted["scenes"][0]["scene_id"] == "beat_arrival"
    assert converted["scenes"][0]["key_action"].startswith("A traveler steps")
    assert "cold blue lightning" in converted["scenes"][0]["image_prompt"]


def test_instructor_adapter_wraps_isolated_client_and_strips_incompatible_params() -> None:
    models = _require_module("addons.audio_story_mode.structured_models")
    calls: dict[str, object] = {}

    class FakeMode:
        JSON = "json"
        MD_JSON = "md_json"

    class FakeWrapped:
        def create(self, **kwargs):
            calls["kwargs"] = kwargs
            return kwargs["response_model"].model_validate(
                {
                    "story_summary": "Structured",
                    "beats": [
                        {
                            "beat_id": "beat_1",
                            "chunk_index": 0,
                            "start_seconds": 0,
                            "end_seconds": 2,
                            "story_event": "Arrival",
                            "visible_action": "A figure arrives.",
                        }
                    ],
                }
            )

    fake_instructor = types.SimpleNamespace(
        __version__="test",
        Mode=FakeMode,
        from_openai=lambda client, mode: (
            calls.update({"base_client": client, "mode": mode}) or FakeWrapped()
        ),
    )
    previous = sys.modules.get("instructor")
    sys.modules["instructor"] = fake_instructor
    try:
        adapter = _require_module("addons.audio_story_mode.instructor_adapter")
        base_client = object()
        result = adapter.generate_story_beats(
            provider="lmstudio",
            params={
                "model": "local-model",
                "messages": [{"role": "user", "content": "beats"}],
                "response_format": {"type": "json_object"},
                "stream": False,
            },
            client_factory=lambda provider: (
                calls.update({"provider": provider}) or base_client
            ),
        )
    finally:
        if previous is None:
            sys.modules.pop("instructor", None)
        else:
            sys.modules["instructor"] = previous
    assert result["story_summary"] == "Structured"
    assert calls["provider"] == "lmstudio"
    assert calls["base_client"] is base_client
    assert calls["mode"] == FakeMode.JSON
    request = dict(calls["kwargs"])
    assert request["response_model"] is models.StoryBeatAnalysis
    assert request["max_retries"] == 2
    assert "response_format" not in request
    assert "stream" not in request


def test_designer_ui_exposes_instructor_controls() -> None:
    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    root = ET.parse(ui_path).getroot()
    names = {str(node.attrib.get("name") or "") for node in root.iter("widget")}
    assert "audio_story_instructor_beats_checkbox" in names
    assert "audio_story_instructor_status_label" in names


def test_designer_ui_exposes_transcription_console() -> None:
    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    root = ET.parse(ui_path).getroot()
    names = {str(node.attrib.get("name") or "") for node in root.iter("widget")}
    required = {
        "audio_story_transcription_console_group",
        "audio_story_transcription_console",
        "audio_story_transcription_console_copy_button",
        "audio_story_transcription_console_clear_button",
    }
    assert required.issubset(names), sorted(required - names)


def _qt_application():
    from PySide6 import QtWidgets

    global _QT_APP
    _QT_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _QT_APP


def test_mprc_style_tab_navigation_has_expected_geometry_and_order() -> None:
    _qt_application()
    from PySide6 import QtCore, QtWidgets

    tabs_module = _require_module("addons.audio_story_mode.tab_navigation")
    navigation = tabs_module.AudioStoryTabNavigation()
    specs = (
        ("project", "Project", "#f59e0b"),
        ("audio", "Audio", "#38bdf8"),
        ("story", "Story", "#a78bfa"),
        ("images", "Images", "#fb7185"),
        ("review", "Review", "#facc15"),
        ("play", "Play / Cast", "#22c55e"),
    )
    for key, title, color in specs:
        navigation.add_page(key, QtWidgets.QWidget(), title, f"{title} page", color)
    assert navigation.page_keys() == ["project", "audio", "story", "images", "review", "play"]
    assert len(navigation.buttons) == 6
    icon_signatures = set()
    for button, (key, _title, color) in zip(navigation.buttons, specs):
        assert button.minimumWidth() == 80
        assert button.maximumWidth() == 96
        assert button.height() == 68
        assert button.icon_pixmap_size() == (36, 36)
        style = button.styleSheet().lower()
        assert "border-radius: 9px" in style
        assert "border-bottom: 3px" not in style
        assert f"color: {color}" in style
        assert button.property("audio_story_icon_key") == key
        buffer = QtCore.QBuffer()
        assert buffer.open(QtCore.QIODevice.WriteOnly)
        assert button.icon_label.pixmap().save(buffer, "PNG")
        icon_signatures.add(hashlib.sha256(bytes(buffer.data())).hexdigest())
    assert len(icon_signatures) == len(specs)
    navigation.select_key("review")
    assert navigation.current_key() == "review"
    navigation.move_button(0, 2)
    assert navigation.page_keys() == ["audio", "story", "project", "images", "review", "play"]
    assert navigation.current_key() == "review"


def test_audio_story_tab_navigation_matches_mprc_overflow_controls() -> None:
    app = _qt_application()
    from PySide6 import QtWidgets

    tabs_module = _require_module("addons.audio_story_mode.tab_navigation")
    navigation = tabs_module.AudioStoryTabNavigation()
    for key, title, color in (
        ("project", "Project", "#f59e0b"),
        ("audio", "Audio", "#38bdf8"),
        ("story", "Story", "#a78bfa"),
        ("images", "Images", "#fb7185"),
        ("review", "Review", "#facc15"),
        ("play", "Play / Cast", "#22c55e"),
    ):
        navigation.add_page(key, QtWidgets.QWidget(), title, title, color)
    navigation.resize(620, 500)
    navigation.show()
    app.processEvents()
    navigation._update_navigation_buttons()
    assert not navigation.previous_button.isVisible()
    assert not navigation.next_button.isVisible()

    navigation.resize(260, 500)
    app.processEvents()
    navigation._update_navigation_buttons()
    assert navigation.previous_button.isVisible()
    assert navigation.next_button.isVisible()
    assert not navigation.previous_button.isEnabled()
    assert navigation.next_button.isEnabled()

    navigation.select_key("play")
    app.processEvents()
    assert navigation.nav_scroll.horizontalScrollBar().value() > 0
    assert navigation.previous_button.isEnabled()
    navigation.close()


def test_transcription_console_reports_progress_and_errors() -> None:
    app = _qt_application()
    from PySide6 import QtCore, QtUiTools, QtWidgets

    controller_module = _require_module("addons.audio_story_mode.controller")
    audio_sources = _require_module("addons.audio_story_mode.audio_sources")
    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    ui_file = QtCore.QFile(str(ui_path))
    assert ui_file.open(QtCore.QIODevice.ReadOnly), ui_file.errorString()
    try:
        root = QtUiTools.QUiLoader().load(ui_file)
    finally:
        ui_file.close()
    assert root is not None, "Designer UI did not load"
    controller = controller_module.AudioStoryModeController(context=None)
    assert controller._bind_designer_runtime_widget(root) is root
    console = root.findChild(
        QtWidgets.QPlainTextEdit, "audio_story_transcription_console"
    )
    assert console is not None
    assert console.isReadOnly()
    assert console.document().maximumBlockCount() == 250
    ancestors = set()
    widget = console
    while widget is not None:
        ancestors.add(str(widget.objectName() or ""))
        widget = widget.parent()
    assert "audio_story_audio_inner_page" in ancestors

    controller._clear_transcription_console()
    controller._append_transcription_console("INFO", "Preparing transcription")
    controller._append_transcription_console("INFO", "Preparing transcription")
    lines = console.toPlainText().splitlines()
    assert len(lines) == 1
    assert re.match(
        r"^\[\d{2}:\d{2}:\d{2}\] \[INFO\] Preparing transcription$",
        lines[0],
    )
    controller._append_transcription_console(
        "ERROR", "Provider failed with api_key=super-secret-value"
    )
    assert "super-secret-value" not in console.toPlainText()
    assert "[redacted]" in console.toPlainText()
    for index in range(260):
        controller._append_transcription_console("PROGRESS", f"stage {index}")
    assert console.document().blockCount() == 250

    controller._clear_transcription_console()
    source = audio_sources.AudioSource(
        index=0,
        path=str(Path(__file__).resolve()),
        display_name="sample.wav",
        duration_seconds=10.0,
        global_start_seconds=0.0,
        global_end_seconds=10.0,
    )
    controller.imported_audio_sources = [source]
    controller.imported_audio_paths = [source.path]
    controller.imported_audio_path = source.path
    controller.imported_audio_duration_seconds = 10.0
    controller._sync_transcription_range_controls()

    class DeferredThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            return None

    previous_thread = controller_module.threading.Thread
    controller_module.threading.Thread = DeferredThread
    try:
        controller._start_transcription()
    finally:
        controller_module.threading.Thread = previous_thread
    assert (
        "[INFO] Starting whole-project transcription for 1 files."
        in console.toPlainText()
    )

    controller._on_transcription_progress(
        {
            "job_id": controller._transcription_job_id,
            "percent": 25,
            "message": "Transcribing file 1 of 1: sample.wav",
        }
    )
    assert (
        "[PROGRESS] Transcribing file 1 of 1: sample.wav"
        in console.toPlainText()
    )
    controller._on_transcription_failed("STT is unavailable for sample.wav.")
    assert "[ERROR] STT is unavailable for sample.wav." in console.toPlainText()
    assert "audio_story_transcription_console" not in json.dumps(
        controller.export_session_state(), ensure_ascii=True
    )

    controller.shutdown()
    root.close()
    root.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def test_controller_requires_project_before_audio_chooser() -> None:
    _qt_application()
    from PySide6 import QtWidgets

    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    calls = []
    imported = []
    previous_dialog = QtWidgets.QFileDialog.getOpenFileNames
    QtWidgets.QFileDialog.getOpenFileNames = lambda *_args, **_kwargs: (
        calls.append("opened") or (["chapter.wav"], "Audio Files")
    )
    controller._import_story_project_audio_paths = lambda paths: imported.extend(paths)
    try:
        controller._choose_audio_files()
        assert not calls, "audio chooser opened without an explicit project"
        controller.current_story_project_id = "project-1"
        controller._choose_audio_files()
    finally:
        QtWidgets.QFileDialog.getOpenFileNames = previous_dialog
        controller.shutdown()
    assert calls == ["opened"]
    assert imported == ["chapter.wav"]


def test_controller_applies_owned_project_list_worker_result() -> None:
    _qt_application()
    controller_module = _require_module("addons.audio_story_mode.controller")
    project_models = _require_module("addons.audio_story_mode.project_models")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._story_project_generation = 7
    controller._story_project_input_fingerprint = "owned-input"
    project = project_models.new_project_manifest(
        "Listed Project", project_id="listed-project", now=100.0
    )
    controller._on_story_project_job_finished(
        {
            "operation": "list",
            "project_id": "__project_index__",
            "generation_id": 7,
            "input_fingerprint": "owned-input",
            "result": [project],
        }
    )
    try:
        assert [item["project_id"] for item in controller._story_projects] == [
            "listed-project"
        ]
    finally:
        controller.shutdown()


def test_controller_rejects_stale_project_results_and_invalidates_pipeline_tokens() -> None:
    _qt_application()
    controller_module = _require_module("addons.audio_story_mode.controller")
    project_models = _require_module("addons.audio_story_mode.project_models")
    controller = controller_module.AudioStoryModeController(context=None)
    current = project_models.new_project_manifest(
        "Current", project_id="current-project", now=100.0
    )
    other = project_models.new_project_manifest(
        "Other", project_id="other-project", now=101.0
    )
    controller.current_story_project_id = "current-project"
    controller._current_story_project = current
    controller._story_projects = [current]
    controller._story_project_generation = 3
    controller._story_project_input_fingerprint = "current-input"
    stale_payloads = (
        {
            "operation": "rename",
            "project_id": "current-project",
            "generation_id": 2,
            "input_fingerprint": "current-input",
            "result": {"project": other},
        },
        {
            "operation": "rename",
            "project_id": "current-project",
            "generation_id": 3,
            "input_fingerprint": "stale-input",
            "result": {"project": other},
        },
        {
            "operation": "rename",
            "project_id": "other-project",
            "generation_id": 3,
            "input_fingerprint": "current-input",
            "result": {"project": other},
        },
    )
    for payload in stale_payloads:
        controller._on_story_project_job_finished(payload)
        assert controller.current_story_project_id == "current-project"
        assert controller._current_story_project["name"] == "Current"
    generation = controller._story_project_generation
    transcription_token = controller._transcription_job_id
    image_token = controller._image_generation_token
    controller._invalidate_story_project_work()
    try:
        assert controller._story_project_generation == generation + 1
        assert controller._transcription_job_id == transcription_token + 1
        assert controller._image_generation_token == image_token + 1
    finally:
        controller.shutdown()


def test_controller_project_lifecycle_runs_after_ui_binding() -> None:
    app = _qt_application()
    from PySide6 import QtCore, QtUiTools, QtWidgets

    class Storage:
        def __init__(self, root: Path):
            self.root = root

        def resolve(self, relative_path: str = "") -> Path:
            return self.root / str(relative_path or "")

    class Context:
        def __init__(self, root: Path):
            self.storage = Storage(root)

        @staticmethod
        def get_service(_name: str):
            return None

    def wait_until(predicate, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 20)
            time.sleep(0.005)
        assert predicate(), "timed out waiting for project worker callback"

    controller_module = _require_module("addons.audio_story_mode.controller")
    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    with tempfile.TemporaryDirectory() as temporary:
        ui_file = QtCore.QFile(str(ui_path))
        assert ui_file.open(QtCore.QIODevice.ReadOnly), ui_file.errorString()
        try:
            root = QtUiTools.QUiLoader().load(ui_file)
        finally:
            ui_file.close()
        assert root is not None
        controller = controller_module.AudioStoryModeController(
            context=Context(Path(temporary))
        )
        provider_calls = []
        runtime_boundaries = (
            "ensure_stt_ready",
            "transcribe_audio",
            "ensure_chat_provider_model_ready",
            "init_tts",
            "generate_tts",
        )
        previous_runtime = {
            name: getattr(controller_module.audio_story_runtime, name)
            for name in runtime_boundaries
            if hasattr(controller_module.audio_story_runtime, name)
        }

        def provider_sentinel(name):
            return lambda *_args, **_kwargs: provider_calls.append(name)

        for name in previous_runtime:
            setattr(
                controller_module.audio_story_runtime,
                name,
                provider_sentinel(name),
            )
        chat_provider_module = controller_module.chat_providers._resolve()
        chat_boundaries = (
            "list_models",
            "create_client",
            "complete_chat",
            "stream_chat",
            "check_connection",
        )
        previous_chat = {
            name: getattr(chat_provider_module, name) for name in chat_boundaries
        }
        for name in chat_boundaries:
            setattr(chat_provider_module, name, provider_sentinel(f"chat_{name}"))
        controller._visual_reply_capability = provider_sentinel(
            "visual_reply_capability"
        )
        controller._get_visual_client = provider_sentinel("visual_client")
        controller._start_transcription = lambda: provider_calls.append("transcription")
        controller._restart_missing_visual_generation_from_position = (
            lambda *_args, **_kwargs: provider_calls.append("images")
        )
        previous_input = QtWidgets.QInputDialog.getText
        QtWidgets.QInputDialog.getText = lambda *_args, **_kwargs: (
            "Worker Project",
            True,
        )
        generation = controller._story_project_generation
        try:
            assert controller._bind_designer_runtime_widget(root) is root
            assert provider_calls == []
            controller._create_story_project()
            wait_until(lambda: bool(controller.current_story_project_id))
            assert controller._story_project_generation == generation + 1
            project_id = controller.current_story_project_id
            assert provider_calls == []
            assert controller.audio_story_project_name_label.text() == (
                "Project: Worker Project"
            )
            controller._close_story_project()
            wait_until(lambda: not controller.current_story_project_id)
            assert not controller.audio_story_import_button.isEnabled()
            project_list = controller.audio_story_project_list
            matching_row = next(
                row
                for row in range(project_list.count())
                if project_list.item(row).data(QtCore.Qt.UserRole) == project_id
            )
            project_list.setCurrentRow(matching_row)
            controller._open_story_project()
            wait_until(lambda: controller.current_story_project_id == project_id)
            assert provider_calls == []
        finally:
            QtWidgets.QInputDialog.getText = previous_input
            for name, boundary in previous_chat.items():
                setattr(chat_provider_module, name, boundary)
            for name, boundary in previous_runtime.items():
                setattr(controller_module.audio_story_runtime, name, boundary)
            controller.shutdown()
            root.close()
            root.deleteLater()
            app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            app.processEvents()


def test_designer_ui_exposes_story_project_controls() -> None:
    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    root = ET.parse(ui_path).getroot()
    names = {str(node.attrib.get("name") or "") for node in root.iter("widget")}
    required = {
        "audio_story_project_header_frame",
        "audio_story_project_name_label",
        "audio_story_project_autosave_label",
        "audio_story_project_page_frame",
        "audio_story_project_list",
        "audio_story_project_new_button",
        "audio_story_project_open_button",
        "audio_story_project_rename_button",
        "audio_story_project_close_button",
        "audio_story_project_delete_button",
        "audio_story_project_add_audio_button",
        "audio_story_project_relink_button",
        "audio_story_project_resume_all_button",
        "audio_story_project_retry_button",
    }
    assert required <= names, sorted(required - names)


def test_designer_ui_exposes_range_and_tts_buffer_controls() -> None:
    app = _qt_application()
    from PySide6 import QtCore, QtUiTools, QtWidgets

    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    ui_file = QtCore.QFile(str(ui_path))
    assert ui_file.open(QtCore.QIODevice.ReadOnly), ui_file.errorString()
    try:
        root = QtUiTools.QUiLoader().load(ui_file)
    finally:
        ui_file.close()
    assert root is not None, "Designer UI did not load"

    required = {
        "audio_story_selected_range_checkbox",
        "audio_story_play_cast_tabs",
        "audio_story_playback_subpage",
        "audio_story_tts_buffer_subpage",
        "audio_story_tts_startup_buffer_spin",
        "audio_story_tts_render_ahead_spin",
        "audio_story_tts_buffered_label",
        "audio_story_tts_segment_label",
        "audio_story_tts_state_label",
        "audio_story_tts_retry_button",
        "audio_story_tts_clear_cache_button",
    }
    widgets = {
        name: root.findChild(QtCore.QObject, name)
        for name in required
    }
    assert all(widgets.values()), sorted(
        name for name, widget in widgets.items() if widget is None
    )

    def ancestor_names(widget) -> set[str]:
        names = set()
        while widget is not None:
            names.add(str(widget.objectName() or ""))
            widget = widget.parent()
        return names

    playback_controls = {
        "audio_story_playback_title",
        "audio_story_play_button",
        "audio_story_pause_button",
        "audio_story_stop_button",
        "audio_story_time_label",
        "audio_story_position_slider",
        "audio_story_status_label",
        "audio_story_stream_enabled_checkbox",
        "audio_story_stream_port_spin",
        "audio_story_stream_url_label",
        "audio_story_cast_device_combo",
        "audio_story_cast_refresh_button",
        "audio_story_cast_button",
        "audio_story_cast_stop_button",
        "audio_story_cast_prompt_checkbox",
        "audio_story_cast_status_label",
    }
    for name in playback_controls:
        widget = root.findChild(QtCore.QObject, name)
        assert widget is not None, name
        assert "audio_story_playback_subpage" in ancestor_names(widget), name
    for name in required - {
        "audio_story_selected_range_checkbox",
        "audio_story_play_cast_tabs",
        "audio_story_playback_subpage",
        "audio_story_tts_buffer_subpage",
    }:
        assert "audio_story_tts_buffer_subpage" in ancestor_names(widgets[name]), name

    tabs = widgets["audio_story_play_cast_tabs"]
    assert isinstance(tabs, QtWidgets.QTabWidget)
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Playback",
        "TTS Buffer",
    ]
    startup_spin = widgets["audio_story_tts_startup_buffer_spin"]
    ahead_spin = widgets["audio_story_tts_render_ahead_spin"]
    assert (startup_spin.minimum(), startup_spin.maximum(), startup_spin.suffix()) == (
        5,
        120,
        " s",
    )
    assert (ahead_spin.minimum(), ahead_spin.maximum(), ahead_spin.suffix()) == (
        30,
        600,
        " s",
    )
    selected_range = widgets["audio_story_selected_range_checkbox"]
    assert not selected_range.isChecked()
    assert not root.findChild(QtWidgets.QSpinBox, "audio_story_transcription_start_spin").isEnabled()
    assert not root.findChild(QtWidgets.QSpinBox, "audio_story_transcription_end_spin").isEnabled()
    assert app is not None
    root.close()
    root.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def test_controller_normalizes_and_round_trips_range_and_buffer_settings() -> None:
    controller_module = _require_module("addons.audio_story_mode.controller")
    session_schema = _require_module("addons.audio_story_mode.session_schema")
    controller = controller_module.AudioStoryModeController(context=None)
    try:
        assert controller._stored_selected_range_enabled is False
        assert controller._stored_tts_startup_buffer_seconds == 30
        assert controller._stored_tts_render_ahead_seconds == 120
        assert controller._normalize_tts_buffer_settings(4, 1) == (5, 30)
        assert controller._normalize_tts_buffer_settings(121, 601) == (120, 600)
        assert controller._normalize_tts_buffer_settings(90, 60) == (90, 90)

        controller.import_session_state(
            {
                "audio_story_mode": {
                    "audio": {
                        "selected_range_enabled": True,
                        "tts_startup_buffer_seconds": 500,
                        "tts_render_ahead_seconds": 20,
                    }
                }
            }
        )
        assert controller._stored_selected_range_enabled is True
        assert controller._stored_tts_startup_buffer_seconds == 120
        assert controller._stored_tts_render_ahead_seconds == 120
        flat = session_schema.flatten_audio_story_mode_settings(
            controller.export_session_state()
        )
        assert flat["audio_story_mode_selected_range_enabled"] is True
        assert flat["audio_story_mode_tts_startup_buffer_seconds"] == 120
        assert flat["audio_story_mode_tts_render_ahead_seconds"] == 120

        controller.import_session_state({"audio_story_mode": {"audio": {}}})
        assert controller._stored_selected_range_enabled is False
        assert controller._stored_tts_startup_buffer_seconds == 30
        assert controller._stored_tts_render_ahead_seconds == 120
    finally:
        controller.shutdown()


def test_designer_runtime_assembles_six_audio_story_categories() -> None:
    app = _qt_application()
    from PySide6 import QtCore, QtUiTools

    controller_module = _require_module("addons.audio_story_mode.controller")
    ui_path = Path(__file__).resolve().parent / "ui" / "audio_story_mode.ui"
    ui_file = QtCore.QFile(str(ui_path))
    assert ui_file.open(QtCore.QIODevice.ReadOnly), ui_file.errorString()
    try:
        root = QtUiTools.QUiLoader().load(ui_file)
    finally:
        ui_file.close()
    assert root is not None, "Designer UI did not load"
    controller = controller_module.AudioStoryModeController(context=None)
    assert controller._bind_designer_runtime_widget(root) is root, "controller did not bind the Designer root"
    assert controller.audio_story_tts_state_label.text() == "Idle"
    assert controller.audio_story_tts_buffered_label.text() == "Buffered: 00:00 / 00:30"
    assert controller.audio_story_tts_segment_label.text() == "Segment: 0 / 0"
    assert not controller.audio_story_selected_range_checkbox.isChecked()
    assert not controller.audio_story_transcription_start_spin.isEnabled()
    assert not controller.audio_story_transcription_end_spin.isEnabled()
    controller.audio_story_selected_range_checkbox.setChecked(True)
    assert controller._stored_selected_range_enabled is True
    assert controller.audio_story_transcription_start_spin.isEnabled()
    assert controller.audio_story_transcription_end_spin.isEnabled()
    controller.import_session_state({"audio_story_mode": {"audio": {}}})
    assert not controller.audio_story_selected_range_checkbox.isChecked()
    assert not controller.audio_story_transcription_start_spin.isEnabled()
    assert not controller.audio_story_transcription_end_spin.isEnabled()
    controller.audio_story_tts_render_ahead_spin.setValue(60)
    controller.audio_story_tts_startup_buffer_spin.setValue(90)
    assert controller._stored_tts_startup_buffer_seconds == 90
    assert controller._stored_tts_render_ahead_seconds == 90
    assert controller.audio_story_tts_render_ahead_spin.value() == 90
    render_job_id = controller._tts_render_job_id
    render_in_progress = controller._tts_render_in_progress
    tts_bundle = controller._tts_bundle
    controller.audio_story_tts_retry_button.click()
    controller.audio_story_tts_clear_cache_button.click()
    assert controller._tts_render_job_id == render_job_id
    assert controller._tts_render_in_progress is render_in_progress
    assert controller._tts_bundle is tts_bundle
    navigation = controller.audio_story_inner_tabs
    assert navigation.page_keys() == ["project", "audio", "story", "images", "review", "play"], navigation.page_keys()
    assert navigation.current_key() == "project", navigation.current_key()
    assert not controller.audio_story_import_button.isEnabled()
    assert not controller.audio_story_transcribe_button.isEnabled()
    navigation.select_key("audio")
    project_models = _require_module("addons.audio_story_mode.project_models")
    project = project_models.new_project_manifest(
        "Smoke Project", project_id="smoke-project", now=100.0
    )
    controller._apply_open_story_project(project)
    assert controller.current_story_project_id == "smoke-project"
    assert controller.audio_story_import_button.isEnabled()
    assert not controller.audio_story_transcribe_button.isEnabled()
    assert controller.audio_story_project_autosave_label.text() == "Project ready"
    assert navigation.current_key() == "audio"
    controller.transcript_chunks = [{"text": "Retained after rename"}]
    renamed_project = dict(project)
    renamed_project["name"] = "Renamed Smoke Project"
    controller._apply_open_story_project(renamed_project)
    assert controller.transcript_chunks == [{"text": "Retained after rename"}]
    controller.transcript_chunks = []
    source = _require_module("addons.audio_story_mode.audio_sources").AudioSource(
        index=0,
        path=str(Path(__file__).resolve()),
        display_name="sample.wav",
        duration_seconds=10.0,
        global_start_seconds=0.0,
        global_end_seconds=10.0,
    )
    controller.imported_audio_sources = [source]
    controller.imported_audio_paths = [source.path]
    controller.imported_audio_path = source.path
    controller._refresh_controls()
    assert controller.audio_story_transcribe_button.isEnabled()

    class CapturingAutosaveQueue:
        def __init__(self):
            self.requests = []

        def request(self, request):
            self.requests.append(request)

        @staticmethod
        def shutdown(timeout=0.0):
            return None

    controller._story_project_autosave_queue.shutdown(timeout=0.0)
    capturing_queue = CapturingAutosaveQueue()
    controller._story_project_autosave_queue = capturing_queue
    controller._queue_story_project_autosave(renamed_project)
    assert len(capturing_queue.requests) == 1
    request = capturing_queue.requests[0]
    assert request.project_id == "smoke-project"
    assert request.revision == 1
    assert controller.audio_story_project_autosave_label.text() == (
        "Saving recovery state..."
    )
    assert not controller.audio_story_import_button.isEnabled()
    assert not controller.audio_story_transcribe_button.isEnabled()
    pending = controller._story_project_pending_autosave
    stale = {
        "project_id": pending[0],
        "revision": pending[1] + 1,
        "generation_id": pending[2],
        "input_fingerprint": pending[3],
        "project": dict(request.snapshot),
    }
    controller._on_story_project_autosave_saved(stale)
    assert controller.audio_story_project_autosave_label.text() == (
        "Saving recovery state..."
    )
    matching = dict(stale)
    matching["revision"] = pending[1]
    controller._on_story_project_autosave_saved(matching)
    assert controller.audio_story_project_autosave_label.text() == "Saved"
    assert controller.audio_story_import_button.isEnabled()
    controller._queue_story_project_autosave(renamed_project)
    pending = controller._story_project_pending_autosave
    controller._on_story_project_autosave_failed(
        {
            "project_id": pending[0],
            "revision": pending[1],
            "generation_id": pending[2],
            "input_fingerprint": pending[3],
            "error": "disk full",
        }
    )
    assert controller.audio_story_project_autosave_label.text() == (
        "Autosave failed: disk full"
    )
    for button in navigation.buttons:
        title_style = button.title_label.styleSheet().lower()
        assert f"color: {button._color}" in title_style, title_style
        assert "font-weight: 800" in title_style, title_style
    required_controls = (
        "audio_story_source_list",
        "audio_story_llm_analysis_checkbox",
        "audio_story_xai_aspect_ratio_combo",
        "audio_story_scene_anchor_edit",
        "audio_story_play_button",
    )
    for name in required_controls:
        assert root.findChild(QtCore.QObject, name) is not None, name
    category_expectations = {
        "audio_story_project_list": "audio_story_project_inner_page",
        "audio_story_source_list": "audio_story_audio_inner_page",
        "audio_story_master_prompt_button": "audio_story_story_inner_page",
        "audio_story_style_live_checkbox": "audio_story_images_inner_page",
        "audio_story_scene_anchor_edit": "audio_story_review_inner_page",
        "audio_story_play_button": "audio_story_play_inner_page",
    }
    for control_name, page_name in category_expectations.items():
        widget = root.findChild(QtCore.QObject, control_name)
        ancestors = set()
        while widget is not None:
            ancestors.add(str(widget.objectName() or ""))
            widget = widget.parent()
        assert page_name in ancestors, f"{control_name} is not in {page_name}"
    assert app is not None, "QApplication is unavailable"
    controller.shutdown()
    root.close()
    root.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def main() -> int:
    _qt_application()
    tests = [
        test_audio_sources_keep_order_deduplicate_and_offset,
        test_audio_sources_retain_invalid_entries_without_advancing_offset,
        test_range_and_seek_cross_chapter_boundary,
        test_exact_boundary_resolves_to_next_chapter,
        test_normalize_segmented_stt_offsets_to_global_timeline,
        test_normalize_transcript_only_stt_preserves_valid_text,
        test_unavailable_and_empty_stt_are_failures,
        test_transcribe_slices_runs_in_order_and_cleans_extracted_files,
        test_transcribe_slice_preserves_mapping_result_offsets_and_cleanup,
        test_project_default_transcription_ignores_stale_range_and_reuses_completed,
        test_project_selected_range_remains_explicit_and_limited,
        test_project_default_transcription_regenerates_partial_legacy_checkpoint,
        test_project_switch_resets_selected_range_before_new_audio_hydration,
        test_project_transcription_missing_or_unreadable_middle_chapter_recovers_in_order,
        test_project_transcription_resumes_only_interrupted_chapter,
        test_project_transcription_failure_preserves_last_valid_output,
        test_project_switch_leaves_only_active_transcription_interrupted,
        test_stale_project_transcription_token_does_no_work_or_publication,
        test_project_transcription_uses_frozen_launch_range_and_chunk,
        test_project_transcription_original_helper_signature_remains_supported,
        test_project_images_persist_retry_exact_scene_and_restore_without_provider_calls,
        test_real_project_image_worker_failures_checkpoint_exact_resume_work,
        test_stale_project_provider_output_is_not_cached_or_reused,
        test_project_image_persistence_failure_is_failed_not_durable,
        test_legacy_visual_reply_generation_contract_remains_unchanged,
        test_project_image_copy_hash_runs_off_gui_and_rechecks_exact_ownership,
        test_failed_image_replacement_restores_previous_durable_checkpoint,
        test_recovery_actions_are_explicit_and_dispatch_selected_work_items,
        test_retry_preserves_chapter_identity_for_duplicate_scene_ids,
        test_project_analysis_runs_in_project_order_and_seeds_following_chapter,
        test_failed_project_analysis_keeps_committed_story_bible_pointer,
        test_switched_project_analysis_does_not_commit_stale_provider_result,
        test_project_analysis_publication_does_not_need_a_final_manifest_save,
        test_reanalyzing_earlier_chapter_stales_only_downstream_continuity,
        test_project_story_memory_seed_bypasses_legacy_audio_path_store,
        test_named_project_cached_rebuilds_use_committed_memory_and_forbid_legacy_store,
        test_instructor_failure_falls_back_to_llm_with_committed_seed,
        test_normal_llm_generated_entity_id_resolves_to_committed_id,
        test_instructor_generated_entity_id_resolves_to_committed_id,
        test_designer_ui_exposes_ordered_audio_queue_controls,
        test_controller_player_position_uses_combined_story_timeline,
        test_controller_global_seek_selects_chapter_and_local_position,
        test_controller_source_media_end_behavior_remains_unchanged,
        test_controller_tts_buffer_ui_uses_exact_states_and_actual_progress,
        test_controller_tts_slider_ui_path_stays_live_for_progressive_queue,
        test_refresh_controls_keeps_range_spins_disabled_without_selected_range,
        test_controller_tts_buffer_setting_change_clamps_wakes_and_persists_only,
        test_controller_tts_play_and_stop_stay_available_during_active_render,
        test_controller_tts_pause_keeps_render_owner_while_stop_cancels_and_keeps_cache,
        test_controller_transcript_replacement_cancels_tts_before_clearing_memory,
        test_controller_tts_cache_clear_confirms_scopes_and_reports_owned_counts,
        test_controller_late_tts_cache_clear_result_cannot_mutate_replacement,
        test_controller_owned_cache_clear_failure_releases_for_retry_only,
        test_controller_tts_cast_waits_for_owned_full_bundle_only,
        test_controller_tts_cast_readiness_never_uses_worker_hash_helper_on_gui,
        test_controller_tts_same_size_wav_corruption_blocks_cast,
        test_controller_tts_completion_rejects_post_validation_wav_mutation,
        test_controller_tts_segment_switches_preserve_one_global_timeline,
        test_controller_tts_underrun_waits_for_rebuilt_startup_buffer,
        test_controller_tts_underrun_resumes_when_all_remaining_audio_is_ready,
        test_controller_tts_seek_ready_and_unready_preserves_play_intent,
        test_controller_tts_buffered_seek_keeps_authoritative_target,
        test_controller_tts_explicit_seek_supersedes_buffered_target,
        test_controller_tts_changed_source_waits_for_owned_media_load,
        test_controller_tts_stale_load_cannot_complete_replaced_queue,
        test_controller_tts_end_waits_for_next_segment_media_load,
        test_controller_tts_image_ready_waits_for_media_transition,
        test_controller_tts_image_failure_waits_for_media_transition,
        test_controller_tts_position_callback_completes_delayed_seek,
        test_controller_tts_synchronous_position_callback_is_reentrant_safe,
        test_controller_tts_seek_unready_preserves_pause_intent,
        test_controller_tts_unready_seek_retargets_from_actual_ready_durations,
        test_controller_tts_buffered_seek_uses_planned_visual_window,
        test_controller_tts_ready_offsets_require_current_owned_segments,
        test_controller_disables_stale_sources_while_queue_is_reprobed,
        test_structured_story_beats_convert_to_existing_scene_shape,
        test_instructor_adapter_wraps_isolated_client_and_strips_incompatible_params,
        test_designer_ui_exposes_instructor_controls,
        test_designer_ui_exposes_transcription_console,
        test_designer_ui_exposes_story_project_controls,
        test_designer_ui_exposes_range_and_tts_buffer_controls,
        test_controller_normalizes_and_round_trips_range_and_buffer_settings,
        test_mprc_style_tab_navigation_has_expected_geometry_and_order,
        test_audio_story_tab_navigation_matches_mprc_overflow_controls,
        test_transcription_console_reports_progress_and_errors,
        test_controller_requires_project_before_audio_chooser,
        test_controller_applies_owned_project_list_worker_result,
        test_controller_rejects_stale_project_results_and_invalidates_pipeline_tokens,
        test_controller_project_lifecycle_runs_after_ui_binding,
        test_designer_runtime_assembles_six_audio_story_categories,
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
