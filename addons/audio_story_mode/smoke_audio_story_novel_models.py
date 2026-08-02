from __future__ import annotations

import inspect
import sys
import tempfile
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from addons.audio_story_mode import project_models, project_store, story_projects


def test_version_one_audio_project_normalizes_without_losing_audio_reference() -> None:
    chapter_id = "legacy-chapter"
    legacy = {
        "schema_version": 1,
        "project_id": "legacy-project",
        "name": "Legacy",
        "created_at": 1.0,
        "updated_at": 1.0,
        "story_bible_revision": 0,
        "autosave_revision": 0,
        "chapter_order": [chapter_id],
        "chapters": {
            chapter_id: {
                "schema_version": 1,
                "chapter_id": chapter_id,
                "display_name": "Chapter",
                "audio_reference": {
                    "path": "chapter.wav",
                    "fingerprint": {"digest": "abc"},
                },
                "created_at": 1.0,
                "updated_at": 1.0,
                "stages": {},
            }
        },
        "archived_chapter_ids": [],
    }

    normalized = project_models.normalize_project_manifest(legacy)

    assert normalized["schema_version"] == 2
    assert normalized["source_kind"] == "audio"
    assert normalized["source_reference"] == {}
    assert normalized["chapters"][chapter_id]["audio_reference"]["path"] == "chapter.wav"


def test_novel_project_uses_source_reference_without_synthetic_audio() -> None:
    project = project_models.new_project_manifest(
        "Novel",
        source_kind="chatlog_json",
        source_reference={"original_path": "chat.json"},
    )
    chapter = project_models.new_chapter_manifest(
        "Chapter One",
        source_reference={"outline_chapter_id": "chapter-1"},
    )

    assert project["source_kind"] == "chatlog_json"
    assert project["source_reference"]["original_path"] == "chat.json"
    assert chapter["audio_reference"] == {}
    assert chapter["source_reference"]["outline_chapter_id"] == "chapter-1"


def test_invalid_project_source_kind_falls_back_to_audio() -> None:
    project = project_models.new_project_manifest("Fallback", source_kind="unknown")
    assert project["source_kind"] == "audio"


def test_project_store_and_manager_create_source_aware_project(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    manager = story_projects.StoryProjectManager(store, duration_reader=lambda _path: 1.0)

    project = manager.create(
        "Imported Chat",
        source_kind="chatlog_json",
        source_reference={"original_path": "chat.json"},
    )
    reloaded = store.load_project(project["project_id"])

    assert reloaded["source_kind"] == "chatlog_json"
    assert reloaded["source_reference"]["original_path"] == "chat.json"


def main() -> int:
    tests = [
        test
        for name, test in sorted(globals().items())
        if name.startswith("test_") and callable(test)
    ]
    failures = 0
    for test in tests:
        try:
            parameters = tuple(inspect.signature(test).parameters)
            if parameters == ("tmp_path",):
                with tempfile.TemporaryDirectory() as directory:
                    test(Path(directory))
            elif not parameters:
                test()
            else:
                raise AssertionError(
                    f"Unsupported smoke fixture(s): {', '.join(parameters)}"
                )
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
