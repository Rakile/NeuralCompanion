from __future__ import annotations

import inspect
import json
import copy
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from addons.audio_story_mode import project_store


@contextmanager
def _raises(expected_type):
    try:
        yield
    except expected_type:
        return
    raise AssertionError(f"Expected {expected_type.__name__}")


def test_novel_artifacts_are_atomic_and_confined_to_project(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Novel", source_kind="chatlog_json")

    reference = store.save_project_json_artifact(
        project["project_id"],
        "novel/story_map.json",
        {"characters": []},
    )
    store.save_project_text_artifact(
        project["project_id"],
        "novel/scenes/scene-1.md",
        "Scene prose.",
    )

    assert reference == "novel/story_map.json"
    assert store.load_project_json_artifact(project["project_id"], reference) == {
        "characters": []
    }
    assert (
        store.load_project_text_artifact(
            project["project_id"], "novel/scenes/scene-1.md"
        )
        == "Scene prose."
    )
    with _raises(project_store.ProjectStoreError):
        store.save_project_text_artifact(
            project["project_id"], "../escape.md", "bad"
        )
    with _raises(project_store.ProjectStoreError):
        store.save_project_json_artifact(
            project["project_id"], "chapters/not-owned.json", {}
        )


def test_markdown_copy_preserves_source_bytes(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path / "projects")
    project = store.create_project("Markdown", source_kind="markdown")
    source = tmp_path / "source.md"
    source.write_bytes(b"\xef\xbb\xbf# One\r\n\r\nExact bytes.\r\n")

    store.copy_project_artifact_from_path(
        project["project_id"], "novel/imported.md", source
    )
    copied = store.resolve_project_artifact(
        project["project_id"], "novel/imported.md"
    )

    assert copied.read_bytes() == source.read_bytes()


def test_artifact_signature_is_stable_and_sensitive() -> None:
    from addons.audio_story_mode import novel_generation

    first = novel_generation.artifact_signature({"b": 2, "a": [1]})
    reordered = novel_generation.artifact_signature({"a": [1], "b": 2})
    changed = novel_generation.artifact_signature({"a": [1], "b": 3})

    assert first == reordered
    assert first != changed


def test_scene_plan_change_invalidates_only_scene_prose_and_assembly() -> None:
    from addons.audio_story_mode import novel_generation

    state = novel_generation.new_generation_state()
    state["scenes"] = {
        "s1": {
            "chapter_id": "c1",
            "plan": novel_generation.generation_checkpoint("complete"),
            "prose": novel_generation.generation_checkpoint("complete"),
        },
        "s2": {
            "chapter_id": "c1",
            "plan": novel_generation.generation_checkpoint("complete"),
            "prose": novel_generation.generation_checkpoint("complete"),
        },
    }
    state["chapters"] = {
        "c1": novel_generation.generation_checkpoint("complete")
    }
    state["assembly"] = novel_generation.generation_checkpoint("complete")

    updated = novel_generation.invalidate_generation_state(
        state, "scene_plan", ["s1"]
    )

    assert updated["scenes"]["s1"]["plan"]["status"] == "complete"
    assert updated["scenes"]["s1"]["prose"]["status"] == "stale"
    assert updated["scenes"]["s2"]["prose"]["status"] == "complete"
    assert updated["chapters"]["c1"]["status"] == "stale"
    assert updated["assembly"]["status"] == "stale"
    assert state["scenes"]["s1"]["prose"]["status"] == "complete"


def test_partial_story_maps_merge_character_aliases_and_keep_contradictions() -> None:
    from addons.audio_story_mode import novel_generation

    merged = novel_generation.merge_partial_story_maps(
        [
            {
                "characters": [
                    {
                        "name": "Alexandra",
                        "aliases": ["Alex"],
                        "summary": "First description",
                        "source_record_ids": ["r1"],
                    }
                ],
                "contradictions": [{"fact": "door open", "source_record_ids": ["r1"]}],
            },
            {
                "characters": [
                    {
                        "name": "Alex",
                        "aliases": [],
                        "source_record_ids": ["r2"],
                    }
                ],
                "contradictions": [{"fact": "door closed", "source_record_ids": ["r2"]}],
            },
        ]
    )

    assert len(merged["characters"]) == 1
    assert merged["characters"][0]["source_record_ids"] == ["r1", "r2"]
    assert len(merged["contradictions"]) == 2


def _chatlog_pipeline_fixture(tmp_path: Path, messages: int = 620):
    from addons.audio_story_mode import chatlog_source, novel_pipeline

    store = project_store.StoryProjectStore(tmp_path / "projects")
    project = store.create_project("Novel", source_kind="chatlog_json")
    path = tmp_path / "chat.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "author": "Ada" if index % 2 == 0 else "Nova",
                    "content": f"Message {index}",
                    "timestamp": index,
                }
            )
            for index in range(messages)
        ),
        encoding="utf-8",
    )
    preview = chatlog_source.ChatlogSourceAdapter().inspect(path)
    return store, project, novel_pipeline.NovelPipeline(store), path, preview


def test_confirmed_chatlog_import_persists_chunks_and_restores(tmp_path: Path) -> None:
    store, project, pipeline, path, preview = _chatlog_pipeline_fixture(tmp_path)

    result = pipeline.import_chatlog(project["project_id"], path, preview)

    assert result.chunk_count >= 3
    assert result.record_count == 620
    manifest = store.load_project_json_artifact(
        project["project_id"], "source_manifest.json"
    )
    assert len(manifest["chunk_refs"]) == result.chunk_count
    assert all(
        store.load_project_json_artifact(project["project_id"], reference)[
            "source_fingerprint"
        ]
        == preview.fingerprint
        for reference in manifest["chunk_refs"]
    )
    restored = pipeline.restore_state(project["project_id"])
    assert restored.source_fingerprint == preview.fingerprint
    assert restored.import_status == "complete"
    assert restored.completed_chunk_refs == tuple(manifest["chunk_refs"])


def test_cancelled_import_keeps_completed_chunks_and_marks_cancelled(
    tmp_path: Path,
) -> None:
    from addons.audio_story_mode import novel_pipeline

    _store, project, pipeline, path, preview = _chatlog_pipeline_fixture(tmp_path)
    cancel = False

    def progress(_percent: int, message: str) -> None:
        nonlocal cancel
        if "chunk 1" in message:
            cancel = True

    try:
        pipeline.import_chatlog(
            project["project_id"],
            path,
            preview,
            progress=progress,
            cancel_check=lambda: cancel,
        )
    except novel_pipeline.NovelPipelineCancelled:
        pass
    else:
        raise AssertionError("Import should stop after the first completed chunk")

    restored = pipeline.restore_state(project["project_id"])
    assert restored.import_status == "cancelled"
    assert len(restored.completed_chunk_refs) == 1


def test_chatlog_cancel_after_final_progress_does_not_publish_complete(
    tmp_path: Path,
) -> None:
    from addons.audio_story_mode import novel_pipeline

    store, project, pipeline, path, preview = _chatlog_pipeline_fixture(
        tmp_path, messages=10
    )
    cancel = False

    def progress(_percent: int, message: str) -> None:
        nonlocal cancel
        if "chunk 1" in message:
            cancel = True

    with _raises(novel_pipeline.NovelPipelineCancelled):
        pipeline.import_chatlog(
            project["project_id"],
            path,
            preview,
            progress=progress,
            cancel_check=lambda: cancel,
        )

    manifest = store.load_project_json_artifact(
        project["project_id"], "source_manifest.json"
    )
    state = store.load_project_json_artifact(
        project["project_id"], "novel/generation_state.json"
    )
    assert manifest["status"] == "cancelled"
    assert state["import"]["status"] == "cancelled"


def test_markdown_import_copies_exact_source_and_creates_source_chapters(
    tmp_path: Path,
) -> None:
    from addons.audio_story_mode import markdown_source, novel_pipeline

    store = project_store.StoryProjectStore(tmp_path / "projects")
    project = store.create_project("Markdown", source_kind="markdown")
    path = tmp_path / "book.md"
    path.write_bytes(
        b"\xef\xbb\xbf# One\r\n\r\nFirst paragraph.\r\n\r\n# Two\r\n\r\nSecond paragraph.\r\n"
    )
    preview = markdown_source.MarkdownSourceAdapter().inspect(path)
    pipeline = novel_pipeline.NovelPipeline(store)

    result = pipeline.import_markdown(project["project_id"], path, preview)
    reloaded = store.load_project(project["project_id"])
    copied = store.resolve_project_artifact(
        project["project_id"], "novel/imported.md"
    )

    assert result.chunk_count == 2
    assert copied.read_bytes() == path.read_bytes()
    assert len(reloaded["chapter_order"]) == 2
    assert all(
        not reloaded["chapters"][chapter_id]["audio_reference"]
        for chapter_id in reloaded["chapter_order"]
    )
    assert [
        reloaded["chapters"][chapter_id]["display_name"]
        for chapter_id in reloaded["chapter_order"]
    ] == ["One", "Two"]


def test_cancelled_changed_markdown_import_preserves_last_complete_source(
    tmp_path: Path,
) -> None:
    from addons.audio_story_mode import markdown_source, novel_pipeline

    store = project_store.StoryProjectStore(tmp_path / "projects")
    project = store.create_project("Markdown", source_kind="markdown")
    source = tmp_path / "book.md"
    source.write_text("# Old One\n\nOld first.\n\n# Old Two\n\nOld second.", encoding="utf-8")
    pipeline = novel_pipeline.NovelPipeline(store)
    first_preview = markdown_source.MarkdownSourceAdapter().inspect(source)
    pipeline.import_markdown(project["project_id"], source, first_preview)
    before_project = store.load_project(project["project_id"])
    before_manifest = store.load_project_json_artifact(
        project["project_id"], "source_manifest.json"
    )
    before_state = store.load_project_json_artifact(
        project["project_id"], "novel/generation_state.json"
    )
    before_chapter = before_project["chapter_order"][0]
    before_narration = pipeline.narration_chunks(
        project["project_id"], before_chapter
    )

    source.write_text("# New One\n\nNew first.\n\n# New Two\n\nNew second.", encoding="utf-8")
    changed_preview = markdown_source.MarkdownSourceAdapter().inspect(source)
    cancelled = False

    def progress(_percent: int, message: str) -> None:
        nonlocal cancelled
        if "chapter 1" in message:
            cancelled = True

    with _raises(novel_pipeline.NovelPipelineCancelled):
        pipeline.import_markdown(
            project["project_id"],
            source,
            changed_preview,
            progress=progress,
            cancel_check=lambda: cancelled,
        )

    after_project = store.load_project(project["project_id"])
    after_manifest = store.load_project_json_artifact(
        project["project_id"], "source_manifest.json"
    )
    after_state = store.load_project_json_artifact(
        project["project_id"], "novel/generation_state.json"
    )
    after_narration = pipeline.narration_chunks(
        project["project_id"], before_chapter
    )

    assert after_project["source_reference"] == before_project["source_reference"]
    assert after_project["chapter_order"] == before_project["chapter_order"]
    assert after_manifest == before_manifest
    assert after_state == before_state
    assert after_narration == before_narration

    pipeline.import_markdown(project["project_id"], source, changed_preview)
    completed = store.load_project(project["project_id"])
    assert completed["source_reference"]["fingerprint"] == changed_preview.fingerprint
    assert "New first" in pipeline.narration_chunks(
        project["project_id"], completed["chapter_order"][0]
    )[0]["text"]


def test_changed_chatlog_revision_stales_completed_story_work(tmp_path: Path) -> None:
    from addons.audio_story_mode import chatlog_source, novel_generation

    store, project, pipeline, path, preview = _chatlog_pipeline_fixture(
        tmp_path, messages=20
    )
    pipeline.import_chatlog(project["project_id"], path, preview)
    state = novel_generation.new_generation_state()
    state["import"] = novel_generation.generation_checkpoint("complete")
    state["story_map"] = novel_generation.generation_checkpoint("complete")
    store.save_project_json_artifact(
        project["project_id"], "novel/generation_state.json", state
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps({"author": "Ada", "content": "Changed"}))
    changed_preview = chatlog_source.ChatlogSourceAdapter().inspect(path)

    pipeline.import_chatlog(project["project_id"], path, changed_preview)
    restored_state = store.load_project_json_artifact(
        project["project_id"], "novel/generation_state.json"
    )
    manifest = store.load_project_json_artifact(
        project["project_id"], "source_manifest.json"
    )

    assert manifest["import_revision"] == 2
    assert restored_state["story_map"]["status"] == "stale"


class _RecordingNovelLlm:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.scene_plan_calls: dict[str, int] = {}
        self.prose_calls: dict[str, int] = {}
        self.fail_scene_plan_once: set[str] = set()
        self.return_structurally_invalid_plan_once: set[str] = set()
        self.repair_with_valid_plan = False
        self.fail_outline = False

    def request_json(self, stage, payload, settings, cancel_check=None):
        self.calls.append((stage, copy.deepcopy(dict(payload))))
        if stage == "story_map_batch":
            records = list(payload.get("source_records") or [])
            first = records[0]
            return {
                "characters": [
                    {
                        "name": first["speaker"],
                        "aliases": [],
                        "summary": "A chat participant.",
                        "source_record_ids": [first["source_record_id"]],
                    }
                ],
                "relationships": [],
                "events": [],
                "locations": [],
                "themes": ["connection"],
                "candidate_scenes": [],
                "contradictions": [],
            }
        if stage == "outline":
            if self.fail_outline:
                raise RuntimeError("outline provider failed")
            return {
                "title": "The Connected Archive",
                "chapters": [
                    {
                        "title": "Beginnings",
                        "summary": "The conversation begins.",
                        "scenes": [
                            {
                                "title": "First Contact",
                                "summary": "Ada and Nova begin speaking.",
                                "purpose": "Introduce the participants.",
                                "characters": ["Ada", "Nova"],
                                "source_record_ids": ["record-1"],
                            }
                        ],
                    }
                ],
            }
        if stage == "scene_plan":
            scene = dict(payload.get("scene") or {})
            scene_id = str(scene.get("scene_id") or "")
            self.scene_plan_calls[scene_id] = self.scene_plan_calls.get(scene_id, 0) + 1
            if (
                scene_id in self.fail_scene_plan_once
                and self.scene_plan_calls[scene_id] == 1
            ):
                return "{broken"
            if (
                scene_id in self.return_structurally_invalid_plan_once
                and self.scene_plan_calls[scene_id] == 1
            ):
                return {"scene_id": scene_id, "title": "Missing beats"}
            return {
                "scene_id": scene_id,
                "chapter_id": scene.get("chapter_id"),
                "title": scene.get("title"),
                "purpose": scene.get("purpose"),
                "pov": scene.get("pov"),
                "tense": scene.get("tense"),
                "characters": scene.get("characters") or [],
                "location": scene.get("location"),
                "beats": [scene.get("summary") or "Advance the scene."],
                "source_record_ids": scene.get("source_record_ids") or [],
                "locked_canon": [],
                "continuity_updates": {
                    "unresolved_threads": [f"thread-{scene_id}"]
                },
            }
        if stage == "json_repair":
            if self.repair_with_valid_plan:
                return {
                    "scene_id": "repaired",
                    "beats": ["Advance the repaired scene."],
                    "source_record_ids": [],
                    "locked_canon": [],
                    "continuity_updates": {},
                }
            return "{still broken"
        raise AssertionError(f"Unexpected LLM stage: {stage}")

    def request_text(self, stage, payload, settings, cancel_check=None):
        if stage != "scene_prose":
            raise AssertionError(f"Unexpected text stage: {stage}")
        plan = dict(payload.get("scene_plan") or {})
        scene_id = str(plan.get("scene_id") or "")
        self.prose_calls[scene_id] = self.prose_calls.get(scene_id, 0) + 1
        return f"Prose for {scene_id}. The scene reaches its intended transition."


def _mapped_pipeline_fixture(tmp_path: Path, messages: int = 160):
    from addons.audio_story_mode import novel_models, novel_pipeline

    store, project, _pipeline, path, preview = _chatlog_pipeline_fixture(
        tmp_path, messages=messages
    )
    llm = _RecordingNovelLlm()
    pipeline = novel_pipeline.NovelPipeline(store, llm_client=llm)
    pipeline.import_chatlog(project["project_id"], path, preview)
    settings = novel_models.FrozenNovelSettings(
        provider_id="lmstudio",
        model="local-model",
        adaptation_style="faithful",
        novel_instructions="Preserve the source facts.",
        prompt_additions={"story_map": "Track relationship changes."},
        source_revision=1,
    )
    return store, project["project_id"], pipeline, llm, settings


def test_story_map_is_bounded_evidenced_and_resumable(tmp_path: Path) -> None:
    _store, project_id, pipeline, llm, settings = _mapped_pipeline_fixture(tmp_path)

    story_map = pipeline.build_story_map(project_id, settings)
    first_call_count = len(llm.calls)
    restored = pipeline.build_story_map(project_id, settings)

    batch_payloads = [payload for stage, payload in llm.calls if stage == "story_map_batch"]
    assert len(batch_payloads) > 1
    assert all(len(json.dumps(payload, ensure_ascii=False)) < 24_000 for payload in batch_payloads)
    assert story_map["characters"][0]["source_record_ids"]
    assert restored == story_map
    assert len(llm.calls) == first_call_count


def test_outline_is_draft_with_stable_chapter_and_scene_ids(tmp_path: Path) -> None:
    store, project_id, pipeline, _llm, settings = _mapped_pipeline_fixture(tmp_path)
    pipeline.build_story_map(project_id, settings)

    proposal = pipeline.build_outline(project_id, settings)
    saved = pipeline.save_outline(project_id, proposal)

    assert proposal["approval_status"] == "draft"
    assert proposal["chapters"][0]["chapter_id"]
    assert proposal["chapters"][0]["scenes"][0]["scene_id"]
    assert saved["revision"] == 1
    assert store.load_project_json_artifact(
        project_id, "novel/novel_outline.json"
    )["approval_status"] == "draft"


def test_outline_failure_is_checkpointed(tmp_path: Path) -> None:
    store, project_id, pipeline, llm, settings = _mapped_pipeline_fixture(tmp_path)
    pipeline.build_story_map(project_id, settings)
    llm.fail_outline = True

    with _raises(RuntimeError):
        pipeline.build_outline(project_id, settings)

    state = store.load_project_json_artifact(
        project_id, "novel/generation_state.json"
    )
    assert state["outline"]["status"] == "failed"
    assert "outline provider failed" in state["outline"]["error"]


def test_frozen_novel_settings_copy_prompt_additions() -> None:
    from addons.audio_story_mode import novel_models

    additions = {"story_map": "Original"}
    settings = novel_models.FrozenNovelSettings(
        provider_id="lmstudio",
        model="model",
        adaptation_style="lightly_novelized",
        novel_instructions="Instructions",
        prompt_additions=additions,
        source_revision=2,
    )
    additions["story_map"] = "Changed"

    assert settings.prompt_additions["story_map"] == "Original"
    with _raises(TypeError):
        settings.prompt_additions["story_map"] = "Blocked"


def _approved_generation_fixture(tmp_path: Path, *, two_scenes: bool = True):
    store, project_id, pipeline, llm, settings = _mapped_pipeline_fixture(tmp_path)
    story_map = pipeline.build_story_map(project_id, settings)
    proposal = pipeline.build_outline(project_id, settings)
    if two_scenes:
        source_id = story_map["characters"][0]["source_record_ids"][0]
        proposal["chapters"][0]["scenes"].append(
            {
                "title": "A Deeper Exchange",
                "summary": "The conversation becomes more meaningful.",
                "purpose": "Develop the relationship.",
                "characters": ["Ada", "Nova"],
                "source_record_ids": [source_id],
                "enabled": True,
            }
        )
    saved = pipeline.save_outline(project_id, proposal)
    approved = pipeline.approve_outline(project_id, saved["revision"])
    return store, project_id, pipeline, llm, settings, approved


def test_generation_requires_approved_outline(tmp_path: Path) -> None:
    _store, project_id, pipeline, _llm, settings = _mapped_pipeline_fixture(tmp_path)
    pipeline.build_story_map(project_id, settings)
    proposal = pipeline.build_outline(project_id, settings)
    pipeline.save_outline(project_id, proposal)

    from addons.audio_story_mode import novel_pipeline

    with _raises(novel_pipeline.NovelOutlineNotApproved):
        pipeline.generate(project_id, settings)


def test_generation_saves_scene_plans_prose_and_continuity(tmp_path: Path) -> None:
    store, project_id, pipeline, _llm, settings, approved = (
        _approved_generation_fixture(tmp_path)
    )
    scene_ids = tuple(
        scene["scene_id"]
        for chapter in approved["chapters"]
        for scene in chapter["scenes"]
    )

    result = pipeline.generate(project_id, settings)

    assert result.completed_scene_ids == scene_ids
    assert result.failed_scene_ids == ()
    assert all(
        store.load_project_json_artifact(
            project_id, f"novel/scenes/{scene_id}.plan.json"
        )["scene_id"]
        == scene_id
        for scene_id in scene_ids
    )
    assert all(
        store.load_project_text_artifact(
            project_id, f"novel/scenes/{scene_id}.md"
        ).startswith("Prose for")
        for scene_id in scene_ids
    )
    ledger = store.load_project_json_artifact(
        project_id, "novel/continuity_ledger.json"
    )
    assert len(ledger["recent_scenes"]) == len(scene_ids)


def test_failed_scene_is_preserved_and_retry_does_not_repeat_sibling(
    tmp_path: Path,
) -> None:
    store, project_id, pipeline, llm, settings, approved = (
        _approved_generation_fixture(tmp_path)
    )
    first_scene = approved["chapters"][0]["scenes"][0]["scene_id"]
    second_scene = approved["chapters"][0]["scenes"][1]["scene_id"]
    llm.fail_scene_plan_once.add(first_scene)

    result = pipeline.generate(project_id, settings)

    assert result.failed_scene_ids == (first_scene,)
    assert result.completed_scene_ids == (second_scene,)
    failure = store.load_project_json_artifact(
        project_id, f"novel/scenes/{first_scene}.failure.json"
    )
    assert failure["raw_response"] == "{still broken"
    sibling_calls = llm.prose_calls[second_scene]

    retried = pipeline.retry_scene(project_id, first_scene, settings)

    assert retried.completed_scene_ids == (first_scene,)
    assert llm.prose_calls[second_scene] == sibling_calls


def test_structurally_invalid_scene_plan_gets_one_repair_attempt(
    tmp_path: Path,
) -> None:
    _store, project_id, pipeline, llm, settings, approved = (
        _approved_generation_fixture(tmp_path, two_scenes=False)
    )
    scene_id = approved["chapters"][0]["scenes"][0]["scene_id"]
    llm.return_structurally_invalid_plan_once.add(scene_id)
    llm.repair_with_valid_plan = True

    result = pipeline.generate(project_id, settings)

    assert result.completed_scene_ids == (scene_id,)
    assert result.failed_scene_ids == ()
    assert [stage for stage, _payload in llm.calls].count("json_repair") == 1


def test_assembly_is_deterministic_and_refuses_missing_enabled_scene(
    tmp_path: Path,
) -> None:
    store, project_id, pipeline, _llm, settings, approved = (
        _approved_generation_fixture(tmp_path)
    )
    pipeline.generate(project_id, settings)

    first = pipeline.assemble(project_id)
    second = pipeline.assemble(project_id)

    assert first.novel_text == second.novel_text
    assert not first.partial
    assert store.load_project_text_artifact(project_id, first.novel_ref) == first.novel_text

    missing_scene = approved["chapters"][0]["scenes"][1]["scene_id"]
    store.resolve_project_artifact(
        project_id, f"novel/scenes/{missing_scene}.md"
    ).unlink()
    from addons.audio_story_mode import novel_pipeline

    with _raises(novel_pipeline.IncompleteNovelError):
        pipeline.assemble(project_id)
    partial = pipeline.assemble(project_id, allow_partial=True)
    assert partial.partial
    assert "INCOMPLETE" in partial.novel_text


def test_outline_reapproval_blocks_stale_scene_prose_and_preserves_assembly(
    tmp_path: Path,
) -> None:
    store, project_id, pipeline, _llm, settings, approved = (
        _approved_generation_fixture(tmp_path, two_scenes=False)
    )
    pipeline.generate(project_id, settings)
    assembled = pipeline.assemble(project_id)
    old_novel = store.load_project_text_artifact(project_id, assembled.novel_ref)
    chapter_id = approved["chapters"][0]["chapter_id"]

    changed = copy.deepcopy(approved)
    changed["chapters"][0]["scenes"][0]["summary"] = "A changed intent."
    saved = pipeline.save_outline(project_id, changed)
    pipeline.approve_outline(project_id, saved["revision"])

    from addons.audio_story_mode import novel_pipeline

    with _raises(novel_pipeline.IncompleteNovelError):
        pipeline.assemble(project_id)
    with _raises(novel_pipeline.IncompleteNovelError):
        pipeline.narration_chunks(project_id, chapter_id)
    assert store.load_project_text_artifact(project_id, assembled.novel_ref) == old_novel


def test_generated_novel_narration_loads_only_selected_chapter(
    tmp_path: Path,
) -> None:
    _store, project_id, pipeline, _llm, settings, approved = (
        _approved_generation_fixture(tmp_path)
    )
    pipeline.generate(project_id, settings)
    chapter_id = approved["chapters"][0]["chapter_id"]

    chunks = pipeline.narration_chunks(project_id, chapter_id)

    assert chunks
    assert all(chunk["chapter_id"] == chapter_id for chunk in chunks)
    assert all(chunk["text"].strip() for chunk in chunks)
    assert chunks[0]["start_seconds"] == 0.0
    assert all(
        left["end_seconds"] <= right["start_seconds"]
        for left, right in zip(chunks, chunks[1:])
    )


def test_markdown_narration_uses_saved_selected_chapter_chunks(
    tmp_path: Path,
) -> None:
    from addons.audio_story_mode import markdown_source, novel_pipeline

    store = project_store.StoryProjectStore(tmp_path / "projects")
    project = store.create_project("Markdown", source_kind="markdown")
    source = tmp_path / "book.md"
    source.write_text(
        "# One\n\nFirst chapter text.\n\n# Two\n\nSecond chapter only.",
        encoding="utf-8",
    )
    pipeline = novel_pipeline.NovelPipeline(store)
    preview = markdown_source.MarkdownSourceAdapter().inspect(source)
    pipeline.import_markdown(project["project_id"], source, preview)
    reopened = store.load_project(project["project_id"])
    chapter_id = reopened["chapter_order"][1]

    chunks = pipeline.narration_chunks(project["project_id"], chapter_id)

    assert chunks
    assert all(chunk["chapter_id"] == chapter_id for chunk in chunks)
    assert "Second chapter only" in " ".join(chunk["text"] for chunk in chunks)
    assert "First chapter text" not in " ".join(chunk["text"] for chunk in chunks)


def test_story_handoff_uses_enabled_scenes_and_stable_windows(
    tmp_path: Path,
) -> None:
    _store, project_id, pipeline, _llm, settings, approved = (
        _approved_generation_fixture(tmp_path)
    )
    pipeline.generate(project_id, settings)
    chapter = approved["chapters"][0]

    payload = pipeline.story_handoff(project_id, chapter["chapter_id"])

    expected_scene_ids = [scene["scene_id"] for scene in chapter["scenes"]]
    assert [item["scene_id"] for item in payload["scene_plan"]] == expected_scene_ids
    assert payload["transcript_chunks"]
    assert {
        item["scene_id"] for item in payload["transcript_chunks"]
    } == set(expected_scene_ids)
    assert all(
        left["end_seconds"] <= right["start_seconds"]
        for left, right in zip(
            payload["transcript_chunks"], payload["transcript_chunks"][1:]
        )
    )


def test_completed_novel_reopens_without_repeating_llm_work(tmp_path: Path) -> None:
    from addons.audio_story_mode import novel_pipeline

    store, project_id, pipeline, llm, settings, approved = (
        _approved_generation_fixture(tmp_path)
    )
    pipeline.generate(project_id, settings)
    pipeline.assemble(project_id)
    initial_calls = tuple(llm.calls)
    reopened = novel_pipeline.NovelPipeline(store, llm_client=llm)

    restored = reopened.restore_state(project_id)
    chunks = reopened.narration_chunks(
        project_id, approved["chapters"][0]["chapter_id"]
    )

    assert restored.assembly_status == "complete"
    assert chunks
    assert tuple(llm.calls) == initial_calls


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
