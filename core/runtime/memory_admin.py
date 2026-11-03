"""Session-bound administration for Long-Term Memory stores."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any

from core import (
    continuity_memory,
    long_term_memory,
    long_term_memory_archive_rebuild,
    session_memory_report,
)
from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.lifecycle import WorkerHandle
from core.runtime.memory import MemoryService, MemorySessionBinding, MemoryWorkContext
from core.runtime.memory_embeddings import (
    EmbeddingProviderCapability,
    JsonRequest,
    MemoryEmbeddingConfig,
    MemoryEmbeddingService,
)
from core.runtime.session_resources import SessionResourceGuard


Logger = Callable[[str], None]
EmbeddingBaselineWriter = Callable[[str, int], object]
AssetRefresher = Callable[[MemoryWorkContext], object]
OperationCompletion = Callable[
    [MemoryWorkContext, object | None, BaseException | None],
    None,
]
TurnTimestampFormatter = Callable[[Mapping[str, object]], str]
Strftime = Callable[[str], str]

_STALE = object()


@dataclass(frozen=True, slots=True)
class SessionMemoryReportRequest:
    """Explicit non-database inputs for one session memory report."""

    continuity: Mapping[str, object] = field(default_factory=dict)
    history: Sequence[Mapping[str, object]] = ()
    chat_context_name: str = ""
    chat_context_path: str = ""
    memory_id: str = ""
    exported_at: str = ""
    path_timestamp: str = ""


class MemoryAdminService:
    """Own manual memory administration without selecting a global store."""

    name = "memory_admin"

    def __init__(
        self,
        *,
        memory_service: MemoryService,
        session_guard: SessionResourceGuard,
        runtime_dir: str | Path,
        baseline_writer: EmbeddingBaselineWriter,
        format_turn_timestamp: TurnTimestampFormatter,
        request_json: JsonRequest | None = None,
        refresh_assets: AssetRefresher | None = None,
        blocked_notifier: Callable[[Mapping[str, object]], object] | None = None,
        logger: Logger | None = print,
        strftime: Strftime = time.strftime,
    ) -> None:
        if not isinstance(memory_service, MemoryService):
            raise TypeError("Memory administration requires a MemoryService.")
        if not isinstance(session_guard, SessionResourceGuard):
            raise TypeError("Memory administration requires a SessionResourceGuard.")
        if memory_service.session_guard is not session_guard:
            raise ValueError(
                "Memory administration and MemoryService must share one session guard."
            )
        if not callable(baseline_writer):
            raise TypeError("Memory embedding baseline writer must be callable.")
        if not callable(format_turn_timestamp):
            raise TypeError("Memory report timestamp formatter must be callable.")
        if refresh_assets is not None and not callable(refresh_assets):
            raise TypeError("Memory asset refresher must be callable.")
        self._memory = memory_service
        self._session_guard = session_guard
        self._runtime_dir = Path(runtime_dir)
        self._baseline_writer = baseline_writer
        self._format_turn_timestamp = format_turn_timestamp
        self._refresh_assets = refresh_assets
        self._logger = logger
        self._strftime = strftime
        self._embeddings = MemoryEmbeddingService(
            session_guard=session_guard,
            request_json=request_json,
            work_context_is_current=memory_service.work_context_is_current,
            blocked_notifier=blocked_notifier,
            logger=logger,
        )

    @property
    def embeddings(self) -> MemoryEmbeddingService:
        return self._embeddings

    def start(self) -> CommandResult[None]:
        return self._embeddings.start()

    def stop(self) -> CommandResult[None]:
        return self._embeddings.stop()

    def provider_capability(self) -> EmbeddingProviderCapability:
        return self._embeddings.provider_capability()

    def document_capability(self):
        return self._embeddings.document_capability()

    def embedding_config(
        self,
        context: MemoryWorkContext,
    ) -> MemoryEmbeddingConfig | None:
        if not self._is_current(context):
            return None
        return self._embeddings.config(context.config.values)

    def embedding_session_mismatch(
        self,
        context: MemoryWorkContext,
    ) -> dict[str, object]:
        if not self._is_current(context):
            return {}
        return self._embeddings.session_mismatch(context.config.values)

    def embedding_write_blocked(self, context: MemoryWorkContext) -> bool:
        return bool(
            self._is_current(context)
            and self._embeddings.write_blocked(context.config.values)
        )

    def list_embedding_models(
        self,
        context: MemoryWorkContext,
        *,
        base_url: str = "",
        quiet: bool = True,
    ) -> list[str]:
        if not self._is_current(context):
            return []
        config = self._embeddings.config(context.config.values)
        return self._embeddings.list_models(
            base_url=base_url or config.base_url,
            quiet=quiet,
            provider=config.provider,
        )

    def embedding_model_status(
        self,
        context: MemoryWorkContext,
    ) -> dict[str, object]:
        if not self._is_current(context):
            return {"available": False, "stale_session": True}
        return self._embeddings.model_status(context.config.values)

    def ensure_embedding_model_loaded(
        self,
        context: MemoryWorkContext,
        *,
        force: bool = False,
    ) -> dict[str, object]:
        if not self._is_current(context):
            return {"ok": False, "stale_session": True}
        result = self._embeddings.ensure_model_loaded(
            context.config.values,
            force=force,
        )
        if not self._is_current(context):
            return {"ok": False, "stale_session": True}
        return result

    def embedding_status(
        self,
        context: MemoryWorkContext,
        *,
        include_lmstudio: bool = False,
    ) -> dict[str, object]:
        if not self._is_current(context):
            return {"stale_session": True}
        return self._embeddings.status(
            context.binding,
            include_lmstudio=include_lmstudio,
            runtime_config=context.config.values,
        )

    def record_embedding_blocked_attempt(
        self,
        context: MemoryWorkContext,
        reason: str = "long_term_memory_archive",
    ) -> dict[str, object]:
        if not self._is_current(context):
            return {}
        return self._embeddings.record_blocked_attempt(
            context,
            reason,
            runtime_config=context.config.values,
        )

    def embedding_blocked_event(
        self,
        context: MemoryWorkContext,
    ) -> dict[str, object]:
        if not self._is_current(context):
            return {}
        return self._embeddings.blocked_event()

    def set_embedding_baseline(
        self,
        context: MemoryWorkContext,
        model: object = "",
        context_length: object | None = None,
    ) -> bool:
        if not self._is_current(context):
            return False
        config = self._embeddings.config(context.config.values)
        baseline_model = str(model or config.model).strip() or config.model
        from core.runtime.embedding_provider import baseline_model as provider_baseline
        baseline_model = provider_baseline(config.provider, baseline_model)
        baseline_context = long_term_memory.embedding_context_length(
            config.context_length if context_length is None else context_length
        )
        result = self._state_effect(
            context,
            lambda: self._baseline_writer(baseline_model, baseline_context),
        )
        return result is not _STALE and result is not False

    def embed_target(
        self,
        context: MemoryWorkContext,
        target: Mapping[str, object],
        *,
        allow_session_mismatch: bool = False,
    ) -> Mapping[str, Any] | None:
        if not self._is_current(context):
            return None
        return self._embeddings.embed_target(
            context,
            target,
            allow_session_mismatch=allow_session_mismatch,
            runtime_config=context.config.values,
        )

    def embed_record(
        self,
        context: MemoryWorkContext,
        record: Mapping[str, object] | None,
    ) -> Mapping[str, Any] | None:
        if not self._is_current(context):
            return None
        return self._embeddings.embed_record(
            context,
            record,
            runtime_config=context.config.values,
        )

    def embed_chunk(
        self,
        context: MemoryWorkContext,
        chunk: Mapping[str, object] | None,
    ) -> list[Mapping[str, Any]]:
        if not self._is_current(context):
            return []
        return self._embeddings.embed_chunk(
            context,
            chunk,
            runtime_config=context.config.values,
        )

    def create_record(
        self,
        context: MemoryWorkContext,
        *,
        memory_type: object = "note",
        title: object = "",
        summary: object = "",
        content: object = "",
        tags: object = None,
        source_chat_id: object = "",
        source_message_start: object = None,
        source_message_end: object = None,
        importance: object = 0.5,
        confidence: object = 0.8,
    ) -> dict[str, Any] | None:
        path = self._database_path(context)
        if path is None:
            return None
        record = self._database_effect(
            context,
            lambda: long_term_memory.create_memory(
                memory_type=memory_type,
                title=title,
                summary=summary,
                content=content,
                tags=tags,
                source_chat_id=source_chat_id,
                source_message_start=source_message_start,
                source_message_end=source_message_end,
                importance=importance,
                confidence=confidence,
                path=path,
            ),
        )
        if record is _STALE or not isinstance(record, Mapping):
            return None
        stored = dict(record)
        self.embed_record(context, stored)
        if self._logger is not None:
            self._logger(
                "\U0001f9e0 [Memory] Long-Term Memory record stored: "
                f"{stored.get('id', '')} ({stored.get('type', '')})"
            )
        return stored

    def list_records(
        self,
        context: MemoryWorkContext,
        *,
        status: object = "active",
        memory_type: object = "",
        source_chat_id: object = "",
        include_deleted: bool = False,
        limit: object = 100,
        offset: object = 0,
    ) -> list[dict[str, Any]]:
        result = self._existing_store_effect(
            context,
            [],
            lambda path: long_term_memory.list_memories(
                status=status,
                memory_type=memory_type,
                source_chat_id=source_chat_id,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
                path=path,
            ),
        )
        return list(result) if isinstance(result, list) else []

    def search_records(
        self,
        context: MemoryWorkContext,
        query: object,
        *,
        status: object = "active",
        memory_type: object = "",
        source_chat_id: object = "",
        include_deleted: bool = False,
        limit: object = 100,
        offset: object = 0,
    ) -> list[dict[str, Any]]:
        result = self._existing_store_effect(
            context,
            [],
            lambda path: long_term_memory.search_memories(
                query,
                status=status,
                memory_type=memory_type,
                source_chat_id=source_chat_id,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
                path=path,
            ),
        )
        return list(result) if isinstance(result, list) else []

    def get_record(
        self,
        context: MemoryWorkContext,
        memory_id: object,
    ) -> dict[str, Any] | None:
        result = self._existing_store_effect(
            context,
            None,
            lambda path: long_term_memory.get_memory(memory_id, path=path),
        )
        return dict(result) if isinstance(result, Mapping) else None

    def update_record(
        self,
        context: MemoryWorkContext,
        memory_id: object,
        **fields: Any,
    ) -> dict[str, Any] | None:
        path = self._database_path(context)
        if path is None:
            return None
        result = self._database_effect(
            context,
            lambda: long_term_memory.update_memory(memory_id, path=path, **fields),
        )
        return dict(result) if isinstance(result, Mapping) else None

    def set_record_status(
        self,
        context: MemoryWorkContext,
        memory_id: object,
        status: object,
    ) -> dict[str, Any] | None:
        path = self._database_path(context)
        if path is None:
            return None
        result = self._database_effect(
            context,
            lambda: long_term_memory.set_memory_status(
                memory_id,
                status,
                path=path,
            ),
        )
        return dict(result) if isinstance(result, Mapping) else None

    def delete_record(
        self,
        context: MemoryWorkContext,
        memory_id: object,
        *,
        hard: bool = False,
    ) -> bool:
        path = self._database_path(context)
        if path is None:
            return False
        result = self._database_effect(
            context,
            lambda: long_term_memory.delete_memory(memory_id, hard=hard, path=path),
        )
        deleted = result is not _STALE and bool(result)
        if deleted and self._logger is not None:
            mode = "deleted" if hard else "marked deleted"
            self._logger(
                f"\U0001f9e0 [Memory] Long-Term Memory record {mode}: {memory_id}"
            )
        return deleted

    def list_chunks(
        self,
        context: MemoryWorkContext,
        *,
        status: object = "active",
        source_chat_id: object = "",
        include_deleted: bool = False,
        limit: object = 100,
        offset: object = 0,
    ) -> list[dict[str, Any]]:
        result = self._existing_store_effect(
            context,
            [],
            lambda path: long_term_memory.list_archived_chunks(
                status=status,
                source_chat_id=source_chat_id,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
                path=path,
            ),
        )
        return list(result) if isinstance(result, list) else []

    def search_chunks(
        self,
        context: MemoryWorkContext,
        query: object,
        *,
        status: object = "active",
        source_chat_id: object = "",
        include_deleted: bool = False,
        limit: object = 100,
        offset: object = 0,
    ) -> list[dict[str, Any]]:
        result = self._existing_store_effect(
            context,
            [],
            lambda path: long_term_memory.search_archived_chunks(
                query,
                status=status,
                source_chat_id=source_chat_id,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
                path=path,
            ),
        )
        return list(result) if isinstance(result, list) else []

    def get_chunk(
        self,
        context: MemoryWorkContext,
        chunk_id: object,
    ) -> dict[str, Any] | None:
        result = self._existing_store_effect(
            context,
            None,
            lambda path: long_term_memory.get_archived_chunk(chunk_id, path=path),
        )
        return dict(result) if isinstance(result, Mapping) else None

    def delete_chunk(
        self,
        context: MemoryWorkContext,
        chunk_id: object,
        *,
        hard: bool = False,
    ) -> bool:
        path = self._database_path(context)
        if path is None:
            return False
        result = self._database_effect(
            context,
            lambda: long_term_memory.delete_archived_chunk(
                chunk_id,
                hard=hard,
                path=path,
            ),
        )
        deleted = result is not _STALE and bool(result)
        if deleted and self._logger is not None:
            mode = "deleted" if hard else "marked deleted"
            self._logger(
                f"\U0001f9e0 [Memory] Long-Term Memory chunk {mode}: {chunk_id}"
            )
        return deleted

    def rebuild_embeddings(
        self,
        context: MemoryWorkContext,
        *,
        limit: object = 200,
        clear_existing: bool = False,
    ) -> dict[str, object]:
        config = self._embeddings.config(
            context.config.values if isinstance(context, MemoryWorkContext) else {}
        )
        stale = self._stale_rebuild_result(config)
        if not self._is_current(context):
            return stale
        if not self._embeddings.embedding_enabled(context.config.values):
            raise RuntimeError(
                "Enable Long-Term Memory embeddings and choose an embedding model first."
            )
        load_result = self.ensure_embedding_model_loaded(context, force=True)
        if load_result.get("stale_session"):
            return stale
        warning = str(load_result.get("warning") or "")
        if warning and self._logger is not None:
            self._logger(f"\U0001f9e0 [Memory] Embedding model warning: {warning}")

        refreshed_assets = 0
        if self._refresh_assets is not None:
            refreshed = self._database_effect(
                context,
                lambda: self._refresh_assets(context),
            )
            if refreshed is _STALE:
                return stale
            refreshed_assets = int(refreshed or 0)
            stale["refreshed_assets"] = refreshed_assets
            if refreshed_assets and self._logger is not None:
                self._logger(
                    "\U0001f9e0 [Memory] Refreshed "
                    f"{refreshed_assets} linked image asset(s) from the loaded chat "
                    "before rebuilding embeddings."
                )

        path = context.binding.database_path
        recovered = self._database_effect(
            context,
            lambda: long_term_memory.backfill_all_visualization_prompts_from_original_paths(
                path=path
            ),
        )
        if recovered is _STALE:
            return stale
        recovered_image_prompts = int(recovered or 0)
        stale["recovered_image_prompts"] = recovered_image_prompts
        if recovered_image_prompts and self._logger is not None:
            self._logger(
                "\U0001f9e0 [Memory] Recovered visualization prompts from "
                f"{recovered_image_prompts} original image file comment(s)."
            )

        cleared = 0
        if clear_existing:
            marked = self._database_effect(context, lambda: long_term_memory.mark_archive_batch_states(
                batch_size=int(context.config.values.get('long_term_memory_archive_batch_turns', 8) or 8), path=path))
            if marked is _STALE:
                return stale
            deleted = self._database_effect(
                context,
                lambda: long_term_memory.delete_all_embeddings(path=path),
            )
            if deleted is _STALE:
                return stale
            cleared = int(deleted or 0)
            stale["cleared_embeddings"] = cleared

        targets = self._memory_effect(
            context,
            lambda: long_term_memory.list_embedding_targets(
                model=config.index_model,
                context_length=config.context_length,
                batch_size=int(context.config.values.get('long_term_memory_archive_batch_turns', 8) or 8),
                limit=limit,
                path=path,
            ),
        )
        if targets is _STALE:
            return stale
        selected = list(targets or ())
        embedded: list[Mapping[str, Any]] = []
        failed: list[Mapping[str, object]] = []
        for target in selected:
            try:
                result = self.embed_target(
                    context,
                    target,
                    allow_session_mismatch=bool(clear_existing),
                )
                if result:
                    embedded.append(result)
                else:
                    failed.append(dict(target))
            except Exception as exc:  # noqa: BLE001 - one bad target must not abort rebuild
                failed.append({**dict(target), "error": str(exc)})
            if not self._is_current(context):
                stale.update(
                    {
                        "selected": len(selected),
                        "embedded": len(embedded),
                        "failed": len(failed),
                        "failures": failed[:10],
                    }
                )
                return stale

        if self._logger is not None:
            self._logger(
                f"\U0001f9e0 [Memory] Embedded {len(embedded)} Long-Term Memory "
                f"item(s); failed {len(failed)}."
            )
        if clear_existing and not self.set_embedding_baseline(
            context,
            config.model,
            config.context_length,
        ):
            stale.update(
                {
                    "selected": len(selected),
                    "embedded": len(embedded),
                    "failed": len(failed),
                    "failures": failed[:10],
                }
            )
            return stale
        if not self._is_current(context):
            return stale
        return {
            "model": config.model,
            "index_model": config.index_model,
            "context_length": config.context_length,
            "base_url": config.base_url,
            "cleared_embeddings": cleared,
            "refreshed_assets": refreshed_assets,
            "recovered_image_prompts": recovered_image_prompts,
            "selected": len(selected),
            "embedded": len(embedded),
            "failed": len(failed),
            "failures": failed[:10],
            "status": self.embedding_status(context),
        }

    def schedule_embedding_rebuild(
        self,
        context: MemoryWorkContext,
        *,
        on_complete: OperationCompletion,
        limit: object = 500,
        clear_existing: bool = True,
    ) -> CommandResult[WorkerHandle]:
        stale = self._reject_stale(context)
        if stale is not None:
            return stale
        return self._memory.schedule_operation(
            name="nc-long-term-memory-embeddings",
            work_context=context,
            payload={"limit": limit, "clear_existing": clear_existing},
            operation=self._run_embedding_rebuild,
            on_complete=on_complete,
        )

    def schedule_archive_candidate(
        self,
        context: MemoryWorkContext,
        prepared: long_term_memory_archive_rebuild.PreparedArchiveRebuild,
        *,
        on_complete: OperationCompletion,
    ) -> CommandResult[WorkerHandle]:
        stale = self._reject_stale(context)
        if stale is not None:
            return stale
        if not isinstance(
            prepared,
            long_term_memory_archive_rebuild.PreparedArchiveRebuild,
        ):
            raise TypeError("A prepared archive rebuild is required.")
        frozen = long_term_memory_archive_rebuild.prepare_archive_rebuild(
            prepared.context_path,
            source_db_path=prepared.source_db_path,
            output_dir=prepared.output_dir,
            chunk_size=prepared.chunk_size,
            session_generation=context.binding.session_generation,
            lease=context.lease,
        )
        return self._memory.schedule_operation(
            name="nc-long-term-memory-archive-candidate",
            work_context=context,
            payload=frozen,
            operation=self._run_archive_candidate,
            on_complete=on_complete,
        )

    def default_report_path(
        self,
        context: MemoryWorkContext,
        request: SessionMemoryReportRequest,
    ) -> Path | None:
        if not self._is_current(context):
            return None
        memory_id = continuity_memory.normalize_memory_id(
            request.memory_id or context.binding.conversation_id,
            fallback="unsaved_chat",
        )
        active_name = str(request.chat_context_name or "").strip()
        normalized_name = continuity_memory.normalize_memory_id(
            active_name or memory_id,
            fallback="unsaved_chat",
        )
        return session_memory_report.default_export_path(
            self._runtime_dir,
            active_name=active_name,
            memory_id=memory_id,
            normalized_name=normalized_name,
            timestamp=request.path_timestamp or self._strftime("%Y%m%d_%H%M%S"),
        )

    def report_data(
        self,
        context: MemoryWorkContext,
        request: SessionMemoryReportRequest,
    ) -> session_memory_report.SessionMemoryReportData | None:
        self._validate_report_request(request)
        result = self._memory_effect(
            context,
            lambda: self._report_data_unchecked(context.binding, request),
        )
        return (
            result
            if isinstance(result, session_memory_report.SessionMemoryReportData)
            else None
        )

    def render_report(
        self,
        context: MemoryWorkContext,
        request: SessionMemoryReportRequest,
    ) -> str | None:
        data = self.report_data(context, request)
        if data is None:
            return None
        return session_memory_report.render_session_memory_report(
            data,
            format_turn_timestamp=self._format_turn_timestamp,
        )

    def export_report(
        self,
        context: MemoryWorkContext,
        request: SessionMemoryReportRequest,
        path: str | Path | None = None,
    ) -> Mapping[str, object] | None:
        self._validate_report_request(request)

        def export() -> Mapping[str, object]:
            data = self._report_data_unchecked(context.binding, request)
            output_path = (
                Path(path)
                if path
                else self._default_report_path_unchecked(
                    context.binding,
                    request,
                )
            )
            result = session_memory_report.write_session_memory_report(
                output_path,
                data,
                format_turn_timestamp=self._format_turn_timestamp,
            )
            if self._logger is not None:
                self._logger(
                    "\U0001f9e0 [Memory] Session memory export written: "
                    f"{result.get('path', '')}"
                )
            return result

        result = self._memory_effect(context, export)
        return result if isinstance(result, Mapping) else None

    def _run_embedding_rebuild(
        self,
        context: MemoryWorkContext,
        payload: object,
    ) -> dict[str, object]:
        values = payload if isinstance(payload, Mapping) else {}
        return self.rebuild_embeddings(
            context,
            limit=values.get("limit", 200),
            clear_existing=bool(values.get("clear_existing", False)),
        )

    @staticmethod
    def _run_archive_candidate(
        _context: MemoryWorkContext,
        prepared: object,
    ) -> dict[str, Any]:
        return long_term_memory_archive_rebuild.rebuild_archive_candidate(prepared)

    def _report_data_unchecked(
        self,
        binding: MemorySessionBinding,
        request: SessionMemoryReportRequest,
    ) -> session_memory_report.SessionMemoryReportData:
        path = binding.database_path
        records: list[Mapping[str, object]] = []
        chunks: list[Mapping[str, object]] = []
        if path.is_file():
            records = long_term_memory.list_memories(limit=100000, path=path)
            chunks = long_term_memory.list_archived_chunks(limit=100000, path=path)
        assets: dict[
            tuple[str, str],
            Sequence[Mapping[str, object]],
        ] = {}
        for kind, items in (("record", records), ("chunk", chunks)):
            for item in items:
                target_id = str(item.get("id", "") or "")
                try:
                    assets[(kind, target_id)] = tuple(
                        long_term_memory.list_assets_for_target(
                            kind,
                            target_id,
                            path=path,
                            include_blob=False,
                        )
                    )
                except Exception:  # noqa: BLE001 - reports omit unreadable assets
                    assets[(kind, target_id)] = ()
        memory_id = continuity_memory.normalize_memory_id(
            request.memory_id or binding.conversation_id,
            fallback="unsaved_chat",
        )
        return session_memory_report.SessionMemoryReportData(
            exported_at=request.exported_at or self._strftime("%Y-%m-%d %H:%M:%S"),
            chat_context_name=str(request.chat_context_name or "").strip(),
            chat_context_path=str(request.chat_context_path or "").strip(),
            memory_id=memory_id,
            store_path=str(path),
            continuity=dict(request.continuity or {}),
            history=tuple(
                dict(turn) for turn in request.history if isinstance(turn, Mapping)
            ),
            records=tuple(dict(record) for record in records),
            chunks=tuple(dict(chunk) for chunk in chunks),
            assets_by_target=assets,
        )

    def _default_report_path_unchecked(
        self,
        binding: MemorySessionBinding,
        request: SessionMemoryReportRequest,
    ) -> Path:
        memory_id = continuity_memory.normalize_memory_id(
            request.memory_id or binding.conversation_id,
            fallback="unsaved_chat",
        )
        active_name = str(request.chat_context_name or "").strip()
        return session_memory_report.default_export_path(
            self._runtime_dir,
            active_name=active_name,
            memory_id=memory_id,
            normalized_name=continuity_memory.normalize_memory_id(
                active_name or memory_id,
                fallback="unsaved_chat",
            ),
            timestamp=request.path_timestamp or self._strftime("%Y%m%d_%H%M%S"),
        )

    @staticmethod
    def _validate_report_request(request: SessionMemoryReportRequest) -> None:
        if not isinstance(request, SessionMemoryReportRequest):
            raise TypeError("A SessionMemoryReportRequest is required.")

    def _database_path(self, context: MemoryWorkContext) -> Path | None:
        return context.binding.database_path if self._is_current(context) else None

    def _existing_store_effect(
        self,
        context: MemoryWorkContext,
        missing: object,
        effect: Callable[[Path], object],
    ) -> object:
        path = self._database_path(context)
        if path is None:
            return missing
        result = self._memory_effect(
            context,
            lambda: effect(path) if path.is_file() else missing,
        )
        return missing if result is _STALE else result

    def _database_effect(
        self,
        context: MemoryWorkContext,
        effect: Callable[[], object],
    ) -> object:
        return self._guarded_effect(
            context,
            self._session_guard.commit_database_write,
            effect,
        )

    def _memory_effect(
        self,
        context: MemoryWorkContext,
        effect: Callable[[], object],
    ) -> object:
        return self._guarded_effect(
            context,
            self._session_guard.commit_memory_write,
            effect,
        )

    def _state_effect(
        self,
        context: MemoryWorkContext,
        effect: Callable[[], object],
    ) -> object:
        return self._guarded_effect(
            context,
            self._session_guard.commit_state_write,
            effect,
        )

    def _guarded_effect(
        self,
        context: MemoryWorkContext,
        commit: Callable[[Any, Callable[[], object]], CommandResult[object]],
        effect: Callable[[], object],
    ) -> object:
        if not self._is_current(context):
            return _STALE

        def current_effect() -> object:
            return effect() if self._is_current(context) else _STALE

        result = commit(context.lease, current_effect)
        return result.value if result.accepted else _STALE

    def _is_current(self, context: MemoryWorkContext) -> bool:
        return bool(
            isinstance(context, MemoryWorkContext)
            and context.lease.session_generation == context.binding.session_generation
            and self._memory.work_context_is_current(context)
        )

    def _reject_stale(
        self,
        context: MemoryWorkContext,
    ) -> CommandResult[WorkerHandle] | None:
        if self._is_current(context):
            return None
        return CommandResult(
            False,
            failure=RuntimeFailure(
                "stale_session",
                "Memory administration no longer owns its session binding.",
            ),
        )

    @staticmethod
    def _stale_rebuild_result(
        config: MemoryEmbeddingConfig,
    ) -> dict[str, object]:
        return {
            "model": config.model,
            "index_model": config.index_model,
            "context_length": config.context_length,
            "base_url": config.base_url,
            "cleared_embeddings": 0,
            "refreshed_assets": 0,
            "recovered_image_prompts": 0,
            "selected": 0,
            "embedded": 0,
            "failed": 0,
            "failures": [],
            "stale_session": True,
        }


__all__ = [
    "MemoryAdminService",
    "SessionMemoryReportRequest",
]
