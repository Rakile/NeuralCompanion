from __future__ import annotations

import copy
import hashlib
import math
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from addons.audio_story_mode import (
    chatlog_source,
    markdown_source,
    novel_generation,
    novel_models,
    novel_prompt_builder,
    project_models,
    project_store,
)


ProgressCallback = Callable[[int, str], None]
CancelCheck = Callable[[], bool]


class NovelPipelineError(RuntimeError):
    pass


class NovelPipelineCancelled(NovelPipelineError):
    pass


class NovelOutlineNotApproved(NovelPipelineError):
    pass


class IncompleteNovelError(NovelPipelineError):
    pass


class NovelStructuredOutputError(NovelPipelineError):
    def __init__(self, message: str, raw_response: Any = "") -> None:
        super().__init__(message)
        self.raw_response = str(raw_response or "")


class NovelPipeline:
    def __init__(
        self,
        store: project_store.StoryProjectStore,
        llm_client: novel_models.NovelLlmClient | None = None,
    ) -> None:
        self.store = store
        self.llm_client = llm_client
        self._chatlog_adapter = chatlog_source.ChatlogSourceAdapter()
        self._markdown_adapter = markdown_source.MarkdownSourceAdapter()

    def import_chatlog(
        self,
        project_id: str,
        path: str | Path,
        preview: novel_models.SourcePreview,
        *,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> novel_models.ImportResult:
        project = self._require_project_kind(
            project_id, novel_models.SOURCE_KIND_CHATLOG_JSON
        )
        self._require_preview(preview, path, novel_models.SOURCE_KIND_CHATLOG_JSON)
        existing_manifest = self._load_optional_json(project_id, "source_manifest.json")
        same_source = self._same_source(existing_manifest, preview)
        if same_source and existing_manifest.get("status") == "complete":
            chunk_refs = tuple(existing_manifest.get("chunk_refs") or ())
            self._progress(progress, 100, "Chatlog import already complete")
            return novel_models.ImportResult(
                project_id=project_id,
                source_fingerprint=preview.fingerprint,
                chunk_count=len(chunk_refs),
                record_count=preview.record_count,
                skipped_count=preview.skipped_count,
            )
        preserve_previous = bool(
            existing_manifest.get("status") == "complete" and not same_source
        )
        previous_revision = self._positive_int(existing_manifest.get("import_revision"))
        import_revision = previous_revision if same_source and previous_revision else previous_revision + 1
        completed_refs = (
            [str(item) for item in existing_manifest.get("chunk_refs") or ()]
            if same_source
            else []
        )
        previous_reference = copy.deepcopy(dict(project.get("source_reference") or {}))
        state = self._load_generation_state(project_id)
        if existing_manifest and not same_source:
            state = novel_generation.invalidate_generation_state(state, "source")
        state["import"] = self._running_checkpoint(
            novel_generation.artifact_signature(
                {
                    "fingerprint": preview.fingerprint,
                    "parser_id": preview.parser_id,
                    "field_map": preview.field_map.to_dict(),
                    "import_revision": import_revision,
                }
            )
        )
        if not preserve_previous:
            self._save_generation_state(project_id, state)
        replacement_reference = novel_models.SourceReference(
            kind=novel_models.SOURCE_KIND_CHATLOG_JSON,
            original_path=str(Path(path).resolve()),
            fingerprint=preview.fingerprint,
            import_revision=import_revision,
        ).to_dict()
        if not preserve_previous:
            project["source_kind"] = novel_models.SOURCE_KIND_CHATLOG_JSON
            project["source_reference"] = replacement_reference
            self.store.save_project(project)

        chunk_refs: list[str] = []
        expected_chunks = max(1, int(preview.estimated_chunks or 1))
        staging_manifest_ref = self._staging_manifest_ref(import_revision)
        try:
            for index, records in enumerate(
                self._chatlog_adapter.iter_batches(
                    path, preview, cancel_check=cancel_check
                ),
                1,
            ):
                self._require_not_cancelled(cancel_check)
                self._require_current_import_owner(
                    project_id,
                    replacement_reference if not preserve_previous else previous_reference,
                )
                reference = self._source_chunk_ref(import_revision, index)
                records_payload = [record.to_dict() for record in records]
                input_signature = novel_generation.artifact_signature(
                    {
                        "source_fingerprint": preview.fingerprint,
                        "index": index,
                        "records": records_payload,
                    }
                )
                reusable = False
                if reference in completed_refs:
                    existing_chunk = self._load_optional_json(project_id, reference)
                    reusable = (
                        existing_chunk.get("source_fingerprint") == preview.fingerprint
                        and existing_chunk.get("input_signature") == input_signature
                    )
                if not reusable:
                    self.store.save_project_json_artifact(
                        project_id,
                        reference,
                        {
                            "schema_version": 1,
                            "source_fingerprint": preview.fingerprint,
                            "import_revision": import_revision,
                            "index": index,
                            "input_signature": input_signature,
                            "records": records_payload,
                        },
                    )
                chunk_refs.append(reference)
                self._save_source_manifest(
                    project_id,
                    preview,
                    import_revision,
                    chunk_refs,
                    status="running",
                    reference=(
                        staging_manifest_ref
                        if preserve_previous
                        else "source_manifest.json"
                    ),
                )
                self._progress(
                    progress,
                    min(99, int(index * 100 / expected_chunks)),
                    f"Normalizing chatlog - chunk {index} of {expected_chunks}",
                )
            self._require_not_cancelled(cancel_check)
        except (chatlog_source.SourceImportCancelled, NovelPipelineCancelled) as exc:
            if not preserve_previous:
                state["import"] = self._terminal_checkpoint(
                    state.get("import"), "cancelled", error=str(exc)
                )
                self._save_generation_state(project_id, state)
            self._save_source_manifest(
                project_id,
                preview,
                import_revision,
                chunk_refs,
                status="cancelled",
                reference=(
                    staging_manifest_ref
                    if preserve_previous
                    else "source_manifest.json"
                ),
            )
            raise NovelPipelineCancelled(str(exc)) from exc
        except Exception as exc:
            if not preserve_previous:
                state["import"] = self._terminal_checkpoint(
                    state.get("import"), "failed", error=str(exc)
                )
                self._save_generation_state(project_id, state)
            self._save_source_manifest(
                project_id,
                preview,
                import_revision,
                chunk_refs,
                status="failed",
                reference=(
                    staging_manifest_ref
                    if preserve_previous
                    else "source_manifest.json"
                ),
            )
            raise

        state["import"] = self._terminal_checkpoint(
            state.get("import"),
            "complete",
            output_signature=novel_generation.artifact_signature(chunk_refs),
            artifact_ref="source_manifest.json",
        )
        self._save_source_manifest(
            project_id,
            preview,
            import_revision,
            chunk_refs,
            status="complete",
        )
        project = self.store.load_project(project_id)
        project["source_kind"] = novel_models.SOURCE_KIND_CHATLOG_JSON
        project["source_reference"] = replacement_reference
        self.store.save_project(project)
        self._save_generation_state(project_id, state)
        self._progress(progress, 100, "Chatlog import complete")
        return novel_models.ImportResult(
            project_id=project_id,
            source_fingerprint=preview.fingerprint,
            chunk_count=len(chunk_refs),
            record_count=preview.record_count,
            skipped_count=preview.skipped_count,
        )

    def import_markdown(
        self,
        project_id: str,
        path: str | Path,
        preview: novel_models.SourcePreview,
        *,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> novel_models.ImportResult:
        project = self._require_project_kind(
            project_id, novel_models.SOURCE_KIND_MARKDOWN
        )
        self._require_preview(preview, path, novel_models.SOURCE_KIND_MARKDOWN)
        self._require_not_cancelled(cancel_check)
        current_fingerprint = chatlog_source.fingerprint_path(path, cancel_check)
        if current_fingerprint != preview.fingerprint:
            raise NovelPipelineError("Markdown changed after it was inspected.")
        existing_manifest = self._load_optional_json(project_id, "source_manifest.json")
        previous_revision = self._positive_int(existing_manifest.get("import_revision"))
        same_source = self._same_source(existing_manifest, preview)
        if same_source and existing_manifest.get("status") == "complete":
            chunk_refs = tuple(existing_manifest.get("chunk_refs") or ())
            self._progress(progress, 100, "Markdown import already complete")
            return novel_models.ImportResult(
                project_id=project_id,
                source_fingerprint=preview.fingerprint,
                chunk_count=len(chunk_refs),
                record_count=preview.record_count,
                skipped_count=preview.skipped_count,
            )
        preserve_previous = bool(
            existing_manifest.get("status") == "complete" and not same_source
        )
        import_revision = previous_revision if same_source and previous_revision else previous_revision + 1
        previous_reference = copy.deepcopy(dict(project.get("source_reference") or {}))
        state = self._load_generation_state(project_id)
        if existing_manifest and not same_source:
            state = novel_generation.invalidate_generation_state(state, "source")
        state["import"] = self._running_checkpoint(preview.fingerprint)
        if not preserve_previous:
            self._save_generation_state(project_id, state)
        replacement_reference = novel_models.SourceReference(
            kind=novel_models.SOURCE_KIND_MARKDOWN,
            original_path=str(Path(path).resolve()),
            fingerprint=preview.fingerprint,
            import_revision=import_revision,
        ).to_dict()
        if not preserve_previous:
            project["source_reference"] = replacement_reference
            self.store.save_project(project)
        chunk_refs: list[str] = []
        chapter_order: list[str] = []
        chapters: dict[str, dict] = {}
        markdown_ref = f"novel/imports/imported-rev-{import_revision:06d}.md"
        staging_manifest_ref = self._staging_manifest_ref(import_revision)
        try:
            self.store.copy_project_artifact_from_path(
                project_id,
                markdown_ref,
                path,
                cancel_check=cancel_check,
            )
            expected = max(1, int(preview.record_count or 1))
            for index, (title, chunks) in enumerate(
                self._markdown_adapter.iter_narration_chapters(
                    path, cancel_check=cancel_check
                ),
                1,
            ):
                self._require_not_cancelled(cancel_check)
                self._require_current_import_owner(
                    project_id,
                    replacement_reference if not preserve_previous else previous_reference,
                )
                reference = self._source_chunk_ref(import_revision, index)
                self.store.save_project_json_artifact(
                    project_id,
                    reference,
                    {
                        "schema_version": 1,
                        "source_fingerprint": preview.fingerprint,
                        "import_revision": import_revision,
                        "index": index,
                        "title": title,
                        "narration_chunks": [chunk.to_dict() for chunk in chunks],
                    },
                )
                chunk_refs.append(reference)
                chapter_id = self._markdown_chapter_id(preview.fingerprint, index)
                chapter_order.append(chapter_id)
                chapters[chapter_id] = project_models.new_chapter_manifest(
                    title,
                    source_reference={
                        "kind": novel_models.SOURCE_KIND_MARKDOWN,
                        "artifact_ref": reference,
                        "source_fingerprint": preview.fingerprint,
                        "import_revision": import_revision,
                    },
                    chapter_id=chapter_id,
                )
                self._save_source_manifest(
                    project_id,
                    preview,
                    import_revision,
                    chunk_refs,
                    status="running",
                    extra={
                        "markdown_ref": markdown_ref,
                        "chapter_order": chapter_order,
                    },
                    reference=(
                        staging_manifest_ref
                        if preserve_previous
                        else "source_manifest.json"
                    ),
                )
                self._progress(
                    progress,
                    min(99, int(index * 100 / expected)),
                    f"Indexing Markdown - chapter {index} of {expected}",
                )
            self._require_not_cancelled(cancel_check)
            self.store.copy_project_artifact_from_path(
                project_id,
                "novel/imported.md",
                path,
                cancel_check=cancel_check,
            )
        except (chatlog_source.SourceImportCancelled, NovelPipelineCancelled, project_store.ProjectStoreError) as exc:
            cancelled = "cancel" in str(exc).casefold()
            if not preserve_previous:
                state["import"] = self._terminal_checkpoint(
                    state.get("import"),
                    "cancelled" if cancelled else "failed",
                    error=str(exc),
                )
                self._save_generation_state(project_id, state)
            self._save_source_manifest(
                project_id,
                preview,
                import_revision,
                chunk_refs,
                status="cancelled" if cancelled else "failed",
                extra={
                    "markdown_ref": markdown_ref,
                    "chapter_order": chapter_order,
                },
                reference=(
                    staging_manifest_ref
                    if preserve_previous
                    else "source_manifest.json"
                ),
            )
            if cancelled:
                raise NovelPipelineCancelled(str(exc)) from exc
            raise

        project = self.store.load_project(project_id)
        project["source_reference"] = replacement_reference
        project["chapters"] = chapters
        project["chapter_order"] = chapter_order
        project["archived_chapter_ids"] = []
        self.store.save_project(project)
        self._save_source_manifest(
            project_id,
            preview,
            import_revision,
            chunk_refs,
            status="complete",
            extra={"markdown_ref": markdown_ref, "chapter_order": chapter_order},
        )
        state["import"] = self._terminal_checkpoint(
            state.get("import"),
            "complete",
            output_signature=novel_generation.artifact_signature(chunk_refs),
            artifact_ref="source_manifest.json",
        )
        self._save_generation_state(project_id, state)
        self._progress(progress, 100, "Markdown import complete")
        return novel_models.ImportResult(
            project_id=project_id,
            source_fingerprint=preview.fingerprint,
            chunk_count=len(chunk_refs),
            record_count=preview.record_count,
            skipped_count=preview.skipped_count,
        )

    def restore_state(self, project_id: str) -> novel_models.NovelProjectState:
        self.store.load_project(project_id)
        source_manifest = self._load_optional_json(project_id, "source_manifest.json")
        state = self._load_generation_state(project_id)
        chunk_refs = tuple(
            str(item) for item in source_manifest.get("chunk_refs") or () if str(item)
        )
        return novel_models.NovelProjectState(
            project_id=project_id,
            source_fingerprint=str(source_manifest.get("fingerprint") or ""),
            import_status=str(
                dict(state.get("import") or {}).get("status") or "pending"
            ),
            completed_chunk_refs=chunk_refs,
            story_map_status=str(
                dict(state.get("story_map") or {}).get("status") or "pending"
            ),
            outline_status=str(
                dict(state.get("outline") or {}).get("status") or "pending"
            ),
            assembly_status=str(
                dict(state.get("assembly") or {}).get("status") or "pending"
            ),
        )

    def build_story_map(
        self,
        project_id: str,
        settings: novel_models.FrozenNovelSettings,
        *,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        llm = self._require_llm()
        source_manifest = self._require_completed_import(project_id, settings)
        chunk_refs = [str(item) for item in source_manifest.get("chunk_refs") or ()]
        state = self._load_generation_state(project_id)
        stage_signature = novel_generation.artifact_signature(
            {
                "source_fingerprint": source_manifest.get("fingerprint"),
                "import_revision": source_manifest.get("import_revision"),
                "chunk_refs": chunk_refs,
                "settings": settings.to_dict(),
                "prompt_schema": novel_prompt_builder.PROMPT_SCHEMA_VERSION,
            }
        )
        checkpoint = dict(state.get("story_map") or {})
        if (
            checkpoint.get("status") == "complete"
            and checkpoint.get("input_signature") == stage_signature
        ):
            cached = self._load_optional_json(project_id, "novel/story_map.json")
            if cached:
                return cached
        state["story_map"] = self._running_checkpoint(stage_signature)
        self._save_generation_state(project_id, state)
        partials: list[dict] = []
        continuity: dict = {}
        total = max(1, len(chunk_refs))
        try:
            for batch_index, chunk_ref in enumerate(chunk_refs, 1):
                self._require_not_cancelled(cancel_check)
                chunk = self.store.load_project_json_artifact(project_id, chunk_ref)
                records = list(dict(chunk).get("records") or ())
                batch_signature = novel_generation.artifact_signature(
                    {
                        "chunk_signature": dict(chunk).get("input_signature"),
                        "settings": settings.to_dict(),
                        "prompt_schema": novel_prompt_builder.PROMPT_SCHEMA_VERSION,
                    }
                )
                partial_ref = (
                    f"novel/story_map_batches/batch-{batch_index:06d}.json"
                )
                saved_partial = self._load_optional_json(project_id, partial_ref)
                if saved_partial.get("input_signature") == batch_signature and isinstance(
                    saved_partial.get("result"), Mapping
                ):
                    partial = copy.deepcopy(dict(saved_partial["result"]))
                else:
                    payload = novel_prompt_builder.build_story_map_batch_payload(
                        records=[dict(item) for item in records if isinstance(item, Mapping)],
                        continuity=continuity,
                        settings=settings,
                    )
                    partial = dict(
                        llm.request_json(
                            "story_map_batch",
                            payload,
                            settings,
                            cancel_check=cancel_check,
                        )
                        or {}
                    )
                    self._require_not_cancelled(cancel_check)
                    self.store.save_project_json_artifact(
                        project_id,
                        partial_ref,
                        {
                            "schema_version": 1,
                            "batch_index": batch_index,
                            "input_signature": batch_signature,
                            "result": partial,
                        },
                    )
                partials.append(partial)
                continuity = novel_generation.merge_partial_story_maps(partials)
                self._progress(
                    progress,
                    int(batch_index * 100 / total),
                    f"Extracting story map - batch {batch_index} of {total}",
                )
        except (NovelPipelineCancelled, chatlog_source.SourceImportCancelled) as exc:
            state["story_map"] = self._terminal_checkpoint(
                state.get("story_map"), "cancelled", error=str(exc)
            )
            self._save_generation_state(project_id, state)
            raise NovelPipelineCancelled(str(exc)) from exc
        except Exception as exc:
            state["story_map"] = self._terminal_checkpoint(
                state.get("story_map"), "failed", error=str(exc)
            )
            self._save_generation_state(project_id, state)
            raise
        story_map = novel_generation.merge_partial_story_maps(partials)
        story_map.update(
            {
                "source_fingerprint": source_manifest.get("fingerprint"),
                "source_revision": settings.source_revision,
                "adaptation_style": settings.adaptation_style,
                "input_signature": stage_signature,
            }
        )
        self.store.save_project_json_artifact(
            project_id, "novel/story_map.json", story_map
        )
        state["story_map"] = self._terminal_checkpoint(
            state.get("story_map"),
            "complete",
            output_signature=novel_generation.artifact_signature(story_map),
            artifact_ref="novel/story_map.json",
        )
        self._save_generation_state(project_id, state)
        return story_map

    def build_outline(
        self,
        project_id: str,
        settings: novel_models.FrozenNovelSettings,
        *,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        llm = self._require_llm()
        self._require_completed_import(project_id, settings)
        story_map = self._load_optional_json(project_id, "novel/story_map.json")
        if not story_map:
            raise NovelPipelineError("Build the story map before creating an outline.")
        stage_signature = novel_generation.artifact_signature(
            {
                "story_map": story_map.get("input_signature"),
                "settings": settings.to_dict(),
                "prompt_schema": novel_prompt_builder.PROMPT_SCHEMA_VERSION,
            }
        )
        state = self._load_generation_state(project_id)
        state["outline"] = self._running_checkpoint(stage_signature)
        self._save_generation_state(project_id, state)
        try:
            self._require_not_cancelled(cancel_check)
            payload = novel_prompt_builder.build_outline_payload(
                story_map=story_map,
                settings=settings,
            )
            self._progress(progress, 10, "Building chapter outline")
            raw_outline = llm.request_json(
                "outline", payload, settings, cancel_check=cancel_check
            )
            self._require_not_cancelled(cancel_check)
            outline = novel_generation.normalize_outline(raw_outline or {}, revision=0)
        except (NovelPipelineCancelled, chatlog_source.SourceImportCancelled) as exc:
            state["outline"] = self._terminal_checkpoint(
                state.get("outline"), "cancelled", error=str(exc)
            )
            self._save_generation_state(project_id, state)
            raise NovelPipelineCancelled(str(exc)) from exc
        except Exception as exc:
            state["outline"] = self._terminal_checkpoint(
                state.get("outline"), "failed", error=str(exc)
            )
            self._save_generation_state(project_id, state)
            raise
        outline["approval_status"] = "draft"
        outline["input_signature"] = stage_signature
        self.store.save_project_json_artifact(
            project_id, "novel/novel_outline.proposed.json", outline
        )
        state["outline"] = self._terminal_checkpoint(
            state.get("outline"),
            "complete",
            output_signature=novel_generation.artifact_signature(outline),
            artifact_ref="novel/novel_outline.proposed.json",
        )
        self._save_generation_state(project_id, state)
        self._progress(progress, 100, "Draft outline ready for review")
        return outline

    def save_outline(self, project_id: str, outline: Mapping) -> dict:
        self.store.load_project(project_id)
        current = self._load_optional_json(project_id, "novel/novel_outline.json")
        revision = self._positive_int(current.get("revision")) + 1
        normalized = novel_generation.normalize_outline(outline, revision=revision)
        normalized["approval_status"] = "draft"
        self.store.save_project_json_artifact(
            project_id, "novel/novel_outline.json", normalized
        )
        state = self._load_generation_state(project_id)
        if current:
            state = novel_generation.invalidate_generation_state(state, "outline")
        state["outline"] = self._terminal_checkpoint(
            state.get("outline"),
            "complete",
            output_signature=novel_generation.artifact_signature(normalized),
            artifact_ref="novel/novel_outline.json",
        )
        self._save_generation_state(project_id, state)
        return normalized

    def approve_outline(self, project_id: str, outline_revision: int) -> dict:
        outline = self._load_optional_json(project_id, "novel/novel_outline.json")
        if not outline:
            raise NovelPipelineError("Save the draft outline before approving it.")
        if self._positive_int(outline.get("revision")) != int(outline_revision):
            raise NovelPipelineError("Outline changed; review the latest revision.")
        approved = novel_generation.normalize_outline(
            outline, revision=int(outline_revision)
        )
        approved["approval_status"] = "approved"
        self.store.save_project_json_artifact(
            project_id, "novel/novel_outline.json", approved
        )
        project = self.store.load_project(project_id)
        chapters: dict[str, dict] = {}
        chapter_order: list[str] = []
        state = self._load_generation_state(project_id)
        state["scenes"] = {}
        state["chapters"] = {}
        for chapter in approved["chapters"]:
            if not chapter.get("enabled", True):
                continue
            chapter_id = str(chapter["chapter_id"])
            chapter_order.append(chapter_id)
            chapters[chapter_id] = project_models.new_chapter_manifest(
                str(chapter.get("title") or "Untitled Chapter"),
                source_reference={
                    "kind": novel_models.SOURCE_KIND_CHATLOG_JSON,
                    "outline_revision": int(outline_revision),
                    "outline_chapter_id": chapter_id,
                },
                chapter_id=chapter_id,
            )
            state["chapters"][chapter_id] = novel_generation.generation_checkpoint(
                "pending"
            )
            for scene in chapter.get("scenes") or ():
                if not scene.get("enabled", True):
                    continue
                state["scenes"][str(scene["scene_id"])] = {
                    "chapter_id": chapter_id,
                    "plan": novel_generation.generation_checkpoint("pending"),
                    "prose": novel_generation.generation_checkpoint("pending"),
                }
        state["outline"] = self._terminal_checkpoint(
            state.get("outline"),
            "complete",
            output_signature=novel_generation.artifact_signature(approved),
            artifact_ref="novel/novel_outline.json",
        )
        state["assembly"] = novel_generation.generation_checkpoint("stale")
        project["chapters"] = chapters
        project["chapter_order"] = chapter_order
        project["archived_chapter_ids"] = []
        self.store.save_project(project)
        self._save_generation_state(project_id, state)
        return approved

    def generate(
        self,
        project_id: str,
        settings: novel_models.FrozenNovelSettings,
        *,
        scene_ids: tuple[str, ...] | list[str] | None = None,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> novel_models.GenerationResult:
        return self._generate(
            project_id,
            settings,
            scene_ids=tuple(scene_ids) if scene_ids is not None else None,
            force_scene_ids=frozenset(),
            progress=progress,
            cancel_check=cancel_check,
        )

    def retry_scene(
        self,
        project_id: str,
        scene_id: str,
        settings: novel_models.FrozenNovelSettings,
        *,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> novel_models.GenerationResult:
        normalized_id = str(scene_id or "").strip()
        if not normalized_id:
            raise ValueError("scene_id is required")
        return self._generate(
            project_id,
            settings,
            scene_ids=(normalized_id,),
            force_scene_ids=frozenset({normalized_id}),
            progress=progress,
            cancel_check=cancel_check,
        )

    def _generate(
        self,
        project_id: str,
        settings: novel_models.FrozenNovelSettings,
        *,
        scene_ids: tuple[str, ...] | None,
        force_scene_ids: frozenset[str],
        progress: ProgressCallback | None,
        cancel_check: CancelCheck | None,
    ) -> novel_models.GenerationResult:
        llm = self._require_llm()
        source_manifest = self._require_completed_import(project_id, settings)
        outline = self._require_approved_outline(project_id)
        story_map = self._load_optional_json(project_id, "novel/story_map.json")
        ordered = self._ordered_enabled_scenes(outline)
        selected = set(scene_ids) if scene_ids is not None else None
        work = [item for item in ordered if selected is None or item[1]["scene_id"] in selected]
        if selected is not None and {item[1]["scene_id"] for item in work} != selected:
            raise NovelPipelineError("One or more selected scenes are not enabled in the outline.")
        state = self._load_generation_state(project_id)
        ledger = self._load_optional_json(project_id, "novel/continuity_ledger.json")
        if not ledger:
            ledger = novel_generation.new_continuity_ledger()
        completed: list[str] = []
        failed: list[str] = []
        total = max(1, len(work))
        chapter_progress = {}
        for chapter in outline.get("chapters") or ():
            if not isinstance(chapter, Mapping) or not chapter.get("enabled", True):
                continue
            enabled_scene_ids = [
                str(scene.get("scene_id") or "")
                for scene in chapter.get("scenes") or ()
                if isinstance(scene, Mapping) and scene.get("enabled", True)
            ]
            for scene_index, scene_id in enumerate(enabled_scene_ids, 1):
                chapter_progress[scene_id] = (
                    str(chapter.get("title") or "Untitled Chapter"),
                    scene_index,
                    len(enabled_scene_ids),
                )
        for work_index, (chapter_id, scene, next_intent) in enumerate(work, 1):
            scene_id = str(scene["scene_id"])
            self._require_not_cancelled(cancel_check)
            scene_state = copy.deepcopy(
                dict(state.get("scenes", {}).get(scene_id) or {})
            )
            input_signature = novel_generation.artifact_signature(
                {
                    "outline_revision": outline.get("revision"),
                    "scene": scene,
                    "story_map": story_map.get("input_signature"),
                    "source_revision": source_manifest.get("import_revision"),
                    "settings": settings.to_dict(),
                    "prompt_schema": novel_prompt_builder.PROMPT_SCHEMA_VERSION,
                }
            )
            prose_checkpoint = dict(scene_state.get("prose") or {})
            if (
                scene_id not in force_scene_ids
                and prose_checkpoint.get("status") == "complete"
                and prose_checkpoint.get("input_signature") == input_signature
            ):
                try:
                    self.store.load_project_text_artifact(
                        project_id, f"novel/scenes/{scene_id}.md"
                    )
                except project_store.ProjectStoreError:
                    pass
                else:
                    completed.append(scene_id)
                    continue
            raw_response: Any = ""
            try:
                source_records = self._source_records_by_ids(
                    project_id,
                    source_manifest,
                    scene.get("source_record_ids") or (),
                )
                scene_with_chapter = {**scene, "chapter_id": chapter_id}
                plan_payload = novel_prompt_builder.build_scene_plan_payload(
                    scene=scene_with_chapter,
                    source_records=source_records,
                    story_map=story_map,
                    continuity=ledger,
                    next_intent=next_intent,
                    settings=settings,
                )
                raw_response = llm.request_json(
                    "scene_plan",
                    plan_payload,
                    settings,
                    cancel_check=cancel_check,
                )
                scene_plan = None
                if isinstance(raw_response, Mapping):
                    try:
                        scene_plan = novel_generation.normalize_scene_plan(
                            raw_response,
                            chapter_id=chapter_id,
                            scene=scene,
                            previous_continuity=ledger,
                            next_intent=next_intent,
                        )
                    except (TypeError, ValueError):
                        scene_plan = None
                if scene_plan is None:
                    repair_payload = novel_prompt_builder.build_json_repair_payload(
                        raw_response=raw_response,
                        contract=novel_prompt_builder.SCENE_PLAN_CONTRACT,
                    )
                    raw_response = llm.request_json(
                        "json_repair",
                        repair_payload,
                        settings,
                        cancel_check=cancel_check,
                    )
                    if not isinstance(raw_response, Mapping):
                        raise NovelStructuredOutputError(
                            f"Scene {scene_id} did not return valid structured JSON.",
                            raw_response,
                        )
                    try:
                        scene_plan = novel_generation.normalize_scene_plan(
                            raw_response,
                            chapter_id=chapter_id,
                            scene=scene,
                            previous_continuity=ledger,
                            next_intent=next_intent,
                        )
                    except (TypeError, ValueError) as exc:
                        raise NovelStructuredOutputError(
                            f"Scene {scene_id} returned invalid structured JSON: {exc}",
                            raw_response,
                        ) from exc
                scene_plan["input_signature"] = input_signature
                self.store.save_project_json_artifact(
                    project_id,
                    f"novel/scenes/{scene_id}.plan.json",
                    scene_plan,
                )
                scene_state["plan"] = self._terminal_checkpoint(
                    self._running_checkpoint(input_signature),
                    "complete",
                    output_signature=novel_generation.artifact_signature(scene_plan),
                    artifact_ref=f"novel/scenes/{scene_id}.plan.json",
                )
                prose_payload = novel_prompt_builder.build_prose_payload(
                    scene_plan=scene_plan,
                    settings=settings,
                )
                prose = str(
                    llm.request_text(
                        "scene_prose",
                        prose_payload,
                        settings,
                        cancel_check=cancel_check,
                    )
                    or ""
                ).strip()
                if not prose:
                    raise NovelPipelineError(f"Scene {scene_id} returned empty prose.")
                self._require_not_cancelled(cancel_check)
                prose_ref = f"novel/scenes/{scene_id}.md"
                self.store.save_project_text_artifact(project_id, prose_ref, prose)
                scene_state["prose"] = self._terminal_checkpoint(
                    self._running_checkpoint(input_signature),
                    "complete",
                    output_signature=novel_generation.artifact_signature(prose),
                    artifact_ref=prose_ref,
                )
                ledger = novel_generation.update_continuity_ledger(
                    ledger, scene_plan, prose[:600]
                )
                self.store.save_project_json_artifact(
                    project_id, "novel/continuity_ledger.json", ledger
                )
                state.setdefault("scenes", {})[scene_id] = scene_state
                self._save_generation_state(project_id, state)
                completed.append(scene_id)
            except NovelPipelineCancelled:
                scene_state["prose"] = self._terminal_checkpoint(
                    scene_state.get("prose"), "cancelled", error="Generation cancelled"
                )
                state.setdefault("scenes", {})[scene_id] = scene_state
                self._save_generation_state(project_id, state)
                raise
            except Exception as exc:
                preserved = (
                    exc.raw_response
                    if isinstance(exc, NovelStructuredOutputError)
                    else raw_response
                )
                self.store.save_project_json_artifact(
                    project_id,
                    f"novel/scenes/{scene_id}.failure.json",
                    {
                        "schema_version": 1,
                        "scene_id": scene_id,
                        "stage": "scene_generation",
                        "provider": settings.provider_id,
                        "model": settings.model,
                        "error": str(exc)[:2_000],
                        "raw_response": self._sanitized_raw_response(preserved),
                        "failed_at": time.time(),
                    },
                )
                scene_state["prose"] = self._terminal_checkpoint(
                    scene_state.get("prose"), "failed", error=str(exc)[:2_000]
                )
                state.setdefault("scenes", {})[scene_id] = scene_state
                self._save_generation_state(project_id, state)
                failed.append(scene_id)
            chapter_title, chapter_scene_index, chapter_scene_count = (
                chapter_progress.get(
                    scene_id,
                    ("Untitled Chapter", work_index, total),
                )
            )
            self._progress(
                progress,
                int(work_index * 100 / total),
                f"Writing {chapter_title} - scene {chapter_scene_index} "
                f"of {chapter_scene_count}",
            )
        return novel_models.GenerationResult(
            project_id=project_id,
            completed_scene_ids=tuple(completed),
            failed_scene_ids=tuple(failed),
            cancelled=False,
        )

    def assemble(
        self,
        project_id: str,
        *,
        allow_partial: bool = False,
    ) -> novel_models.AssemblyResult:
        outline = self._require_approved_outline(project_id)
        chapter_refs: list[str] = []
        novel_parts = [f"# {outline.get('title') or 'Untitled Novel'}"]
        missing: list[str] = []
        state = self._load_generation_state(project_id)
        prose_by_scene: dict[str, str] = {}
        for _chapter_id, scene, _next_intent in self._ordered_enabled_scenes(outline):
            scene_id = str(scene["scene_id"])
            try:
                prose_by_scene[scene_id] = self._load_current_scene_prose(
                    project_id, scene_id, state
                )
            except IncompleteNovelError:
                missing.append(scene_id)
        if missing and not allow_partial:
            raise IncompleteNovelError(
                "Enabled scenes are missing or stale: " + ", ".join(missing)
            )
        for chapter in outline.get("chapters") or ():
            if not chapter.get("enabled", True):
                continue
            chapter_id = str(chapter["chapter_id"])
            chapter_parts = [f"# {chapter.get('title') or 'Untitled Chapter'}"]
            chapter_missing = False
            for scene in chapter.get("scenes") or ():
                if not scene.get("enabled", True):
                    continue
                scene_id = str(scene["scene_id"])
                prose = prose_by_scene.get(scene_id)
                if prose is None:
                    chapter_missing = True
                    chapter_parts.append(
                        f"## {scene.get('title') or 'Missing Scene'}\n\n"
                        f"_[INCOMPLETE: scene {scene_id} is unavailable or stale.]_"
                    )
                    continue
                chapter_parts.append(
                    f"## {scene.get('title') or 'Scene'}\n\n{prose.strip()}"
                )
            chapter_text = "\n\n".join(chapter_parts).rstrip() + "\n"
            if not chapter_missing or allow_partial:
                chapter_ref = f"novel/chapters/{chapter_id}.md"
                self.store.save_project_text_artifact(
                    project_id, chapter_ref, chapter_text
                )
                chapter_refs.append(chapter_ref)
                novel_parts.append(chapter_text.rstrip())
                if chapter_id in state.get("chapters", {}):
                    state["chapters"][chapter_id] = self._terminal_checkpoint(
                        state["chapters"][chapter_id],
                        "complete" if not chapter_missing else "stale",
                        output_signature=novel_generation.artifact_signature(
                            chapter_text
                        ),
                        artifact_ref=chapter_ref,
                    )
        novel_text = "\n\n".join(novel_parts).rstrip() + "\n"
        if missing:
            novel_text = (
                "> **INCOMPLETE NOVEL PREVIEW** — one or more enabled scenes are missing.\n\n"
                + novel_text
            )
            novel_ref = "novel/novel.partial.md"
        else:
            novel_ref = "novel/novel.md"
        self.store.save_project_text_artifact(project_id, novel_ref, novel_text)
        if not missing:
            state["assembly"] = self._terminal_checkpoint(
                state.get("assembly"),
                "complete",
                output_signature=novel_generation.artifact_signature(novel_text),
                artifact_ref=novel_ref,
            )
            self._save_generation_state(project_id, state)
        return novel_models.AssemblyResult(
            project_id=project_id,
            novel_ref=novel_ref,
            chapter_refs=tuple(chapter_refs),
            novel_text=novel_text,
            partial=bool(missing),
        )

    def narration_chunks(
        self, project_id: str, chapter_id: str
    ) -> tuple[dict, ...]:
        """Load narration windows for one chapter and no other chapter prose."""
        project = self.store.load_project(project_id)
        normalized_chapter_id = str(chapter_id or "").strip()
        chapter = dict(
            dict(project.get("chapters") or {}).get(normalized_chapter_id) or {}
        )
        if not normalized_chapter_id or not chapter:
            raise NovelPipelineError("Select an available novel chapter first.")
        source_kind = novel_models.normalize_source_kind(project.get("source_kind"))
        if source_kind == novel_models.SOURCE_KIND_MARKDOWN:
            reference = str(
                dict(chapter.get("source_reference") or {}).get("artifact_ref")
                or ""
            )
            if not reference:
                raise NovelPipelineError("The Markdown chapter source is unavailable.")
            artifact = self.store.load_project_json_artifact(project_id, reference)
            values = list(dict(artifact or {}).get("narration_chunks") or ())
            chunks: list[dict] = []
            for index, value in enumerate(values):
                if not isinstance(value, Mapping):
                    continue
                text = str(value.get("text") or "").strip()
                if not text:
                    continue
                start = max(0.0, float(value.get("start_seconds", 0.0) or 0.0))
                end = max(
                    start,
                    float(value.get("end_seconds", start) or start),
                )
                chunks.append(
                    {
                        "chunk_index": index,
                        "chapter_id": normalized_chapter_id,
                        "scene_id": f"markdown-{normalized_chapter_id}-{index + 1}",
                        "text": text,
                        "start_seconds": start,
                        "end_seconds": end,
                    }
                )
            if not chunks:
                raise NovelPipelineError("The selected Markdown chapter is empty.")
            return tuple(chunks)

        outline = self._require_approved_outline(project_id)
        outline_chapter = next(
            (
                dict(value)
                for value in outline.get("chapters") or ()
                if isinstance(value, Mapping)
                and str(value.get("chapter_id") or "") == normalized_chapter_id
                and value.get("enabled", True)
            ),
            None,
        )
        if outline_chapter is None:
            raise NovelPipelineError("The selected chapter is not enabled.")
        state = self._load_generation_state(project_id)
        chunks = []
        cursor = 0.0
        for scene in outline_chapter.get("scenes") or ():
            if not isinstance(scene, Mapping) or not scene.get("enabled", True):
                continue
            scene_id = str(scene.get("scene_id") or "")
            prose = self._load_current_scene_prose(project_id, scene_id, state)
            for part in markdown_source.split_narration_text(prose):
                duration = max(0.25, len(part.split()) / 2.6)
                chunks.append(
                    {
                        "chunk_index": len(chunks),
                        "chapter_id": normalized_chapter_id,
                        "scene_id": scene_id,
                        "text": part,
                        "start_seconds": cursor,
                        "end_seconds": cursor + duration,
                    }
                )
                cursor += duration
        if not chunks:
            raise IncompleteNovelError("The selected chapter has no generated prose.")
        return tuple(chunks)

    def story_handoff(self, project_id: str, chapter_id: str) -> dict:
        """Create a copied, deterministic Story/Images payload for one chapter."""
        project = self.store.load_project(project_id)
        source_kind = novel_models.normalize_source_kind(project.get("source_kind"))
        normalized_chapter_id = str(chapter_id or "").strip()
        chunks = [dict(item) for item in self.narration_chunks(project_id, chapter_id)]
        if source_kind == novel_models.SOURCE_KIND_MARKDOWN:
            scene_order: list[str] = []
            for chunk in chunks:
                scene_id = str(chunk.get("scene_id") or "")
                if scene_id and scene_id not in scene_order:
                    scene_order.append(scene_id)
            scene_plan = []
            for scene_index, scene_id in enumerate(scene_order):
                scene_chunks = [
                    item for item in chunks if item.get("scene_id") == scene_id
                ]
                scene_plan.append(
                    {
                        "scene_id": scene_id,
                        "scene_index": scene_index + 1,
                        "title": str(project["chapters"][normalized_chapter_id].get("display_name") or "Chapter"),
                        "summary": " ".join(item["text"] for item in scene_chunks)[:600],
                        "start_seconds": scene_chunks[0]["start_seconds"],
                        "end_seconds": scene_chunks[-1]["end_seconds"],
                        "is_new_scene": True,
                    }
                )
            story_bible = {}
        else:
            outline = self._require_approved_outline(project_id)
            outline_chapter = next(
                (
                    dict(value)
                    for value in outline.get("chapters") or ()
                    if isinstance(value, Mapping)
                    and str(value.get("chapter_id") or "")
                    == normalized_chapter_id
                ),
                {},
            )
            scene_plan = []
            for scene_index, scene in enumerate(
                value
                for value in outline_chapter.get("scenes") or ()
                if isinstance(value, Mapping) and value.get("enabled", True)
            ):
                scene_id = str(scene.get("scene_id") or "")
                scene_chunks = [
                    item for item in chunks if item.get("scene_id") == scene_id
                ]
                if not scene_chunks:
                    continue
                saved_plan = self._load_optional_json(
                    project_id, f"novel/scenes/{scene_id}.plan.json"
                )
                plan = copy.deepcopy(dict(saved_plan or scene))
                plan.update(
                    {
                        "scene_id": scene_id,
                        "scene_index": scene_index + 1,
                        "start_seconds": scene_chunks[0]["start_seconds"],
                        "end_seconds": scene_chunks[-1]["end_seconds"],
                        "is_new_scene": True,
                        "summary": str(
                            scene.get("summary")
                            or plan.get("purpose")
                            or scene_chunks[0]["text"][:600]
                        ),
                    }
                )
                scene_plan.append(plan)
            story_bible = self._load_optional_json(
                project_id, "novel/story_map.json"
            )
        reference = dict(project.get("source_reference") or {})
        duration = max(float(item["end_seconds"]) for item in chunks)
        transcript_chunks = []
        for index, item in enumerate(chunks):
            copied = copy.deepcopy(item)
            copied["index"] = index
            copied["chunk_index"] = index
            transcript_chunks.append(copied)
        return {
            "project_id": project_id,
            "chapter_id": normalized_chapter_id,
            "source_kind": source_kind,
            "novel_source_revision": int(reference.get("import_revision", 0) or 0),
            "transcript_chunks": transcript_chunks,
            "raw_segments": copy.deepcopy(transcript_chunks),
            "scene_plan": scene_plan,
            "story_bible": story_bible,
            "full_text": "\n\n".join(item["text"] for item in transcript_chunks),
            "audio_duration_seconds": duration,
        }

    def _require_project_kind(self, project_id: str, expected: str) -> dict:
        project = self.store.load_project(project_id)
        actual = novel_models.normalize_source_kind(project.get("source_kind"))
        if actual != expected:
            raise NovelPipelineError(
                f"Project source is {actual}; expected {expected}."
            )
        return project

    def _require_current_import_owner(
        self,
        project_id: str,
        expected_reference: Mapping,
    ) -> None:
        project = self.store.load_project(project_id)
        reference = dict(project.get("source_reference") or {})
        if reference != dict(expected_reference or {}):
            raise NovelPipelineError(
                "The project source changed while this import was running."
            )

    def _require_approved_outline(self, project_id: str) -> dict:
        outline = self._load_optional_json(project_id, "novel/novel_outline.json")
        if not outline or outline.get("approval_status") != "approved":
            raise NovelOutlineNotApproved(
                "Approve the current outline before generating prose."
            )
        return outline

    def _load_current_scene_prose(
        self,
        project_id: str,
        scene_id: str,
        state: Mapping,
    ) -> str:
        prose_ref = f"novel/scenes/{scene_id}.md"
        scene_state = dict(dict(state.get("scenes") or {}).get(scene_id) or {})
        checkpoint = dict(scene_state.get("prose") or {})
        if (
            checkpoint.get("status") != "complete"
            or str(checkpoint.get("artifact_ref") or "") != prose_ref
        ):
            raise IncompleteNovelError(
                f"Scene {scene_id} has not been generated for the current outline."
            )
        try:
            prose = self.store.load_project_text_artifact(project_id, prose_ref)
        except project_store.ProjectStoreError as exc:
            raise IncompleteNovelError(
                f"Scene {scene_id} has not been generated yet."
            ) from exc
        if str(checkpoint.get("output_signature") or "") != (
            novel_generation.artifact_signature(prose)
        ):
            raise IncompleteNovelError(
                f"Scene {scene_id} prose no longer matches its generation checkpoint."
            )
        return prose

    @staticmethod
    def _ordered_enabled_scenes(outline: Mapping) -> list[tuple[str, dict, str]]:
        flattened: list[tuple[str, dict]] = []
        for chapter in outline.get("chapters") or ():
            if not isinstance(chapter, Mapping) or not chapter.get("enabled", True):
                continue
            chapter_id = str(chapter.get("chapter_id") or "")
            for scene in chapter.get("scenes") or ():
                if isinstance(scene, Mapping) and scene.get("enabled", True):
                    flattened.append((chapter_id, copy.deepcopy(dict(scene))))
        result: list[tuple[str, dict, str]] = []
        for index, (chapter_id, scene) in enumerate(flattened):
            next_intent = ""
            if index + 1 < len(flattened):
                following = flattened[index + 1][1]
                next_intent = str(
                    following.get("purpose") or following.get("summary") or ""
                ).strip()
            result.append((chapter_id, scene, next_intent))
        return result

    def _source_records_by_ids(
        self,
        project_id: str,
        source_manifest: Mapping,
        source_record_ids,
    ) -> list[dict]:
        wanted = {str(item) for item in source_record_ids if str(item)}
        if not wanted:
            return []
        found: dict[str, dict] = {}
        for reference in source_manifest.get("chunk_refs") or ():
            chunk = self.store.load_project_json_artifact(project_id, str(reference))
            for raw in dict(chunk).get("records") or ():
                if not isinstance(raw, Mapping):
                    continue
                record_id = str(raw.get("source_record_id") or "")
                if record_id in wanted and record_id not in found:
                    found[record_id] = copy.deepcopy(dict(raw))
            if wanted.issubset(found):
                break
        return [found[item] for item in source_record_ids if str(item) in found]

    @staticmethod
    def _sanitized_raw_response(value: Any) -> str:
        if isinstance(value, Mapping):
            text = str(dict(value))
        else:
            text = str(value or "")
        return text.replace("\x00", "")[:20_000]

    def _require_llm(self) -> novel_models.NovelLlmClient:
        if self.llm_client is None:
            raise NovelPipelineError("No LLM client is available for Novel Workshop.")
        return self.llm_client

    def _require_completed_import(
        self,
        project_id: str,
        settings: novel_models.FrozenNovelSettings,
    ) -> dict:
        manifest = self._load_optional_json(project_id, "source_manifest.json")
        if manifest.get("status") != "complete":
            raise NovelPipelineError("Import the source before starting novel analysis.")
        revision = self._positive_int(manifest.get("import_revision"))
        if settings.source_revision != revision:
            raise NovelPipelineError(
                "Novel settings belong to another source revision; apply them again."
            )
        return manifest

    @staticmethod
    def _require_preview(
        preview: novel_models.SourcePreview,
        path: str | Path,
        expected_kind: str,
    ) -> None:
        if novel_models.normalize_source_kind(preview.source_kind) != expected_kind:
            raise NovelPipelineError("Source preview belongs to another source type.")
        if Path(preview.source_path).resolve() != Path(path).resolve():
            raise NovelPipelineError("Source preview belongs to another file.")
        if preview.ambiguities:
            raise NovelPipelineError("Confirm the source field mapping before import.")

    @staticmethod
    def _same_source(manifest: Mapping, preview: novel_models.SourcePreview) -> bool:
        return bool(
            manifest
            and str(manifest.get("fingerprint") or "") == preview.fingerprint
            and str(manifest.get("parser_id") or "") == preview.parser_id
            and dict(manifest.get("field_map") or {}) == preview.field_map.to_dict()
        )

    def _save_source_manifest(
        self,
        project_id: str,
        preview: novel_models.SourcePreview,
        import_revision: int,
        chunk_refs: list[str],
        *,
        status: str,
        extra: Mapping[str, Any] | None = None,
        reference: str = "source_manifest.json",
    ) -> None:
        payload = {
            "schema_version": 1,
            "source_kind": preview.source_kind,
            "original_path": preview.source_path,
            "fingerprint": preview.fingerprint,
            "parser_id": preview.parser_id,
            "field_map": preview.field_map.to_dict(),
            "record_count": preview.record_count,
            "source_size_bytes": preview.source_size_bytes,
            "participant_count": preview.participant_count,
            "participants": list(preview.participants),
            "participants_truncated": preview.participants_truncated,
            "skipped_count": preview.skipped_count,
            "date_start": preview.date_start,
            "date_end": preview.date_end,
            "import_revision": import_revision,
            "chunk_refs": list(chunk_refs),
            "status": status,
            "updated_at": time.time(),
        }
        payload.update(copy.deepcopy(dict(extra or {})))
        self.store.save_project_json_artifact(
            project_id, reference, payload
        )

    def _load_generation_state(self, project_id: str) -> dict:
        state = self._load_optional_json(project_id, "novel/generation_state.json")
        return state or novel_generation.new_generation_state()

    def _save_generation_state(self, project_id: str, state: Mapping) -> None:
        self.store.save_project_json_artifact(
            project_id,
            "novel/generation_state.json",
            state,
        )

    def _load_optional_json(self, project_id: str, reference: str) -> dict:
        try:
            payload = self.store.load_project_json_artifact(project_id, reference)
        except (project_store.ProjectCorruptError, FileNotFoundError, ValueError):
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    @staticmethod
    def _positive_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _markdown_chapter_id(fingerprint: str, index: int) -> str:
        digest = hashlib.sha256(
            f"{fingerprint}:{index}".encode("utf-8")
        ).hexdigest()[:12]
        return f"markdown-{index:04d}-{digest}"

    @staticmethod
    def _source_chunk_ref(import_revision: int, index: int) -> str:
        return (
            f"source_chunks/rev-{int(import_revision):06d}-"
            f"chunk-{int(index):06d}.json"
        )

    @staticmethod
    def _staging_manifest_ref(import_revision: int) -> str:
        return f"novel/imports/source-manifest-rev-{int(import_revision):06d}.json"

    @staticmethod
    def _running_checkpoint(input_signature: str) -> dict:
        checkpoint = novel_generation.generation_checkpoint("running")
        checkpoint["input_signature"] = str(input_signature)
        checkpoint["attempt_count"] = 1
        checkpoint["started_at"] = time.time()
        return checkpoint

    @staticmethod
    def _terminal_checkpoint(
        checkpoint: Mapping | None,
        status: str,
        *,
        output_signature: str = "",
        artifact_ref: str = "",
        error: str = "",
    ) -> dict:
        result = copy.deepcopy(dict(checkpoint or novel_generation.generation_checkpoint()))
        result["status"] = status
        result["output_signature"] = str(output_signature)
        result["artifact_ref"] = str(artifact_ref)
        result["error"] = str(error)
        result["completed_at"] = time.time()
        result["updated_at"] = result["completed_at"]
        return result

    @staticmethod
    def _require_not_cancelled(cancel_check: CancelCheck | None) -> None:
        if callable(cancel_check) and bool(cancel_check()):
            raise NovelPipelineCancelled("Novel import was cancelled.")

    @staticmethod
    def _progress(
        callback: ProgressCallback | None,
        percent: int,
        message: str,
    ) -> None:
        if callable(callback):
            callback(max(0, min(100, int(percent))), str(message))
