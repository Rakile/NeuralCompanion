"""Concrete, engine-free ownership for production conversation memory."""

from __future__ import annotations

from core.image_attachments import image_paths

import json
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from core import (
    continuity_memory,
    conversation_history as conversation_history_runtime,
    long_term_memory,
    long_term_memory_archive_rebuild,
)
from core.runtime.config import RuntimeConfigService, RuntimeConfigSnapshot
from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.conversation import ConversationService
from core.runtime.lifecycle import WorkerSupervisor
from core.runtime.memory import (
    LongTermMemoryStatus,
    MemoryRecallCapabilities,
    MemoryService,
    MemorySessionBinding,
    MemoryWorkContext,
)
from core.runtime.memory_admin import (
    MemoryAdminService,
    SessionMemoryReportRequest,
)
from core.runtime.memory_embeddings import JsonRequest
from core.runtime.providers import infer_model_supports_images
from core.runtime.session_resources import SessionResourceGuard


Logger = Callable[[str], object]
MemoryCompletion = Callable[[MemoryWorkContext, object, BaseException | None], object]
_STALE_WRITE = object()


class ProductionMemoryProvider(Protocol):
    """Finite provider surface required by memory-only completions."""

    def capture(self, context: MemoryWorkContext) -> object: ...

    def complete(
        self,
        captured: object,
        params: Mapping[str, object],
        additional_params: Mapping[str, object] | None = None,
    ) -> object: ...

    def model_is_placeholder(self, model_name: object) -> bool: ...

    def model_supports_images(self, config: Mapping[str, object]) -> bool: ...


class ProductionMemoryOwner:
    """Own production memory services and their facade/session adapters."""

    def __init__(
        self,
        config: RuntimeConfigService,
        conversation: ConversationService,
        workers: WorkerSupervisor,
        provider: ProductionMemoryProvider,
        *,
        runtime_dir: str | Path,
        session_guard: SessionResourceGuard | None = None,
        embedding_request_json: JsonRequest | None = None,
        request_json: JsonRequest | None = None,
        refresh_assets: Callable[[MemoryWorkContext], object] | None = None,
        logger: Logger | None = print,
        strftime: Callable[[str], str] = time.strftime,
    ) -> None:
        if not isinstance(config, RuntimeConfigService):
            raise TypeError("Production memory requires RuntimeConfigService.")
        if not isinstance(conversation, ConversationService):
            raise TypeError("Production memory requires ConversationService.")
        if not isinstance(workers, WorkerSupervisor):
            raise TypeError("Production memory requires WorkerSupervisor.")
        if embedding_request_json is not None and request_json is not None:
            raise TypeError("Pass only one memory embedding JSON request capability.")
        self._config = config
        self._conversation = conversation
        self._provider = provider
        self._logger = logger
        self._callback_lock = threading.RLock()
        self._update_callbacks: list[Callable[[Mapping[str, object]], object]] = []
        self._image_review_callback: Callable[..., object] | None = None
        self._session_guard = session_guard or SessionResourceGuard(conversation)
        self._admin: MemoryAdminService | None = None
        self._deletion_recovery = None
        self._service = MemoryService(
            workers=workers,
            session_guard=self._session_guard,
            session_lease=conversation.session_lease,
            session_lease_is_current=conversation.session_lease_is_current,
            config_snapshot=config.snapshot,
            recall_capabilities=MemoryRecallCapabilities(
                semantic_query=self._semantic_query,
                complete_image_context=self._complete_image_context,
                model_supports_images=self._model_supports_images,
                image_review_callback=self.image_review_callback,
                log=self._log,
            ),
            archive_embed_chunk=self._embed_archive_chunk,
            archive_embedding_write_blocked=self._embedding_write_blocked,
            archive_embedding_blocked=self._record_archive_embedding_blocked,
            conversation_complete=self._complete_conversation_memory,
            conversation_updated=self._conversation_memory_updated,
            logger=self._log,
        )
        self._admin = MemoryAdminService(
            memory_service=self._service,
            session_guard=self._session_guard,
            runtime_dir=runtime_dir,
            baseline_writer=self._write_embedding_baseline,
            format_turn_timestamp=conversation_history_runtime.format_turn_timestamp,
            request_json=embedding_request_json or request_json,
            refresh_assets=refresh_assets or self._refresh_assets,
            blocked_notifier=self.notify_updates,
            logger=self._log,
            strftime=strftime,
        )
        self._bind_active_store(self._active_memory_id())

    @property
    def service(self) -> MemoryService:
        return self._service

    @property
    def memory(self) -> MemoryService:
        """Compatibility name used by production runtime composition."""

        return self._service

    @property
    def admin(self) -> MemoryAdminService:
        assert self._admin is not None
        return self._admin

    @property
    def session_guard(self) -> SessionResourceGuard:
        return self._session_guard

    def close(self) -> None:
        self.admin.stop()
        self._service.stop()
        with self._callback_lock:
            self._update_callbacks.clear()
            self._image_review_callback = None

    def stop(self) -> CommandResult[None]:
        self.close()
        return CommandResult(True)

    def current_work_context(self) -> MemoryWorkContext:
        lease = self._conversation.session_lease()
        snapshot = self._config.snapshot()
        frozen = self._service.freeze_dispatch(lease, snapshot)
        if not frozen.accepted:
            self._bind_active_store(self._active_memory_id())
            snapshot = self._config.snapshot()
            frozen = self._service.freeze_dispatch(lease, snapshot)
        if not frozen.accepted or frozen.value is None:
            raise RuntimeError("Could not freeze the current memory session binding.")
        return frozen.value

    def maybe_update_continuity(
        self,
        chat_context_payload_factory: Callable[[], Mapping[str, object]],
    ) -> bool:
        """Queue the legacy-compatible automatic continuity-memory update."""

        if not callable(chat_context_payload_factory):
            raise TypeError("Continuity memory requires a chat-session exporter.")
        config = self._config.snapshot()
        snapshot = self._conversation.snapshot()
        work = self.resolve_work_context(
            self._conversation.session_lease(),
            config,
        )
        if work is None or self._service.worker_active(
            "nc-continuity-memory-auto",
            work,
        ):
            return False
        scheduled = self._service.schedule_conversation_update(
            snapshot,
            config,
            work_context=work,
            history=self._history(),
            provider_context_factory=self._capture_provider,
            chat_context_payload_factory=chat_context_payload_factory,
        )
        if not scheduled.accepted or scheduled.value is None:
            return False
        self._log("🧠 [Memory] Auto continuity summary queued.")
        return True

    def maybe_archive_long_term(self) -> bool:
        """Queue the legacy-compatible automatic Long-Term Memory archive."""

        config = self._config.snapshot()
        snapshot = self._conversation.snapshot()
        work = self.resolve_work_context(
            self._conversation.session_lease(),
            config,
        )
        if work is None or self._service.worker_active(
            "nc-long-term-memory-auto-archive",
            work,
        ):
            return False
        scheduled = self._service.on_conversation_changed(
            snapshot,
            config,
            work_context=work,
        )
        if not scheduled.accepted or scheduled.value is None:
            return False
        status = self._service.status(
            snapshot.session_generation,
            snapshot=snapshot,
            config=config,
        )
        self._log(
            "🧠 [Memory] Auto Long-Term archive queued: "
            f"{status.pending_messages}/{status.archive_interval} pending turn(s)."
        )
        return True

    def resolve_work_context(
        self,
        value: object = None,
        runtime_config: RuntimeConfigSnapshot | Mapping[str, object] | None = None,
    ) -> MemoryWorkContext | None:
        if isinstance(value, MemoryWorkContext):
            return value
        if value is None and runtime_config is None:
            return self.current_work_context()
        lease = value if value is not None else self._conversation.session_lease()
        config = runtime_config if runtime_config is not None else self._config.snapshot()
        frozen = self._service.freeze_dispatch(lease, config)
        if frozen.accepted:
            return frozen.value
        if self._conversation.session_lease_is_current(lease):
            self._bind_active_store(self._active_memory_id())
            if runtime_config is None:
                config = self._config.snapshot()
            frozen = self._service.freeze_dispatch(lease, config)
            if frozen.accepted:
                return frozen.value
        return None

    def work_context_is_current(self, context: object) -> bool:
        return bool(
            isinstance(context, MemoryWorkContext)
            and self._service.work_context_is_current(context)
        )

    def refresh_history_assets(self, lease: object) -> int:
        """Refresh archived image links for one current conversation lease."""

        context = self.resolve_work_context(lease)
        return self._refresh_assets(context) if context is not None else 0

    def new_memory_id(self) -> str:
        return continuity_memory.new_memory_id()

    def activate_memory(self, memory_id: str) -> str:
        return self.set_identity(memory_id)

    def set_identity(self, memory_id: str) -> str:
        normalized = continuity_memory.normalize_memory_id(
            memory_id,
            fallback=continuity_memory.new_memory_id(),
        )
        self._config.update("continuity_memory_id", normalized)
        path = self._bind_active_store(normalized)
        if path.is_file():
            long_term_memory.init_store(path)
        return normalized

    def set_context_path(self, path: str) -> Mapping[str, object]:
        raw_path = str(path or "").strip()
        previous_path = str(
            self._config.get("active_chat_context_path", "") or ""
        ).strip()
        updates: dict[str, object] = {
            "active_chat_context_path": raw_path,
            "quick_chat_context_active": False,
            "active_chat_context_name": Path(raw_path).stem if raw_path else "",
        }
        self._config.update_many(updates)
        if raw_path:
            current_id = continuity_memory.normalize_memory_id(
                self._config.get("continuity_memory_id", "")
            )
            if not current_id or (
                not previous_path
                and re.fullmatch(r"chat_[0-9a-f]{12}", current_id or "")
            ):
                self.set_identity(
                    continuity_memory.memory_id_from_label(Path(raw_path).stem)
                )
            else:
                self._bind_active_store(current_id)
        else:
            self._bind_active_store(self._active_memory_id())
        values = self._config.snapshot().values
        return {
            "active_chat_context_path": values.get("active_chat_context_path", ""),
            "active_chat_context_name": values.get("active_chat_context_name", ""),
            "continuity_memory_id": values.get("continuity_memory_id", ""),
            "long_term_memory_db_path": values.get("long_term_memory_db_path", ""),
        }

    def set_embedding_baseline(
        self,
        model: str | None,
        context_length: int | None,
    ) -> bool:
        context = self.current_work_context()
        if not self.admin.set_embedding_baseline(context, model, context_length):
            raise RuntimeError("Could not update the memory embedding baseline.")
        return True

    def bind_updates(
        self,
        callback: Callable[[Mapping[str, object]], object],
    ) -> Callable[[], None]:
        if callable(callback):
            with self._callback_lock:
                if callback not in self._update_callbacks:
                    self._update_callbacks.append(callback)

        def unbind() -> None:
            with self._callback_lock:
                try:
                    self._update_callbacks.remove(callback)
                except ValueError:
                    pass

        return unbind

    def notify_updates(self, payload: Mapping[str, object] | None = None) -> None:
        event = dict(payload or {})
        with self._callback_lock:
            callbacks = tuple(self._update_callbacks)
        for callback in callbacks:
            try:
                callback(dict(event))
            except Exception as exc:  # noqa: BLE001 - subscriber boundary
                self._log(f"[Memory] Update callback failed: {exc}")

    def bind_image_review(
        self,
        callback: Callable[..., object],
    ) -> Callable[[], None]:
        with self._callback_lock:
            self._image_review_callback = callback if callable(callback) else None

        def unbind() -> None:
            with self._callback_lock:
                if self._image_review_callback is callback:
                    self._image_review_callback = None

        return unbind

    def image_review_callback(self) -> Callable[..., object] | None:
        with self._callback_lock:
            return self._image_review_callback

    def continuity_snapshot(self) -> Mapping[str, object]:
        memory_id = self._active_memory_id()
        return continuity_memory.load_memory(memory_id)

    def update_continuity(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
        *,
        work_context: MemoryWorkContext | None = None,
        provider_context: object | None = None,
    ) -> Mapping[str, object]:
        work = work_context or self.current_work_context()
        if not self.work_context_is_current(work):
            return self._stale_continuity_result()
        values = work.config.values
        memory_id = continuity_memory.normalize_memory_id(
            values.get("continuity_memory_id"), fallback="default"
        )
        memory_path = continuity_memory.memory_path(memory_id).resolve()
        max_chars = continuity_memory.normalize_max_chars(
            values.get(
                "continuity_memory_max_chars", continuity_memory.DEFAULT_MAX_CHARS
            )
        )
        turns = self._history(history)
        existing = continuity_memory.load_memory(memory_id, path=memory_path)
        if existing.get("recovery_error"):
            raise continuity_memory.MemoryRecoveryError(existing["recovery_error"])
        previous_count = max(
            0,
            min(len(turns), int(existing.get("source_turn_count", 0) or 0)),
        )
        new_turns = continuity_memory.unsummarized_turns(turns, existing)
        if not new_turns:
            saved = self._guarded_write(
                work,
                self._session_guard.commit_memory_write,
                lambda: continuity_memory.save_memory(
                    existing, memory_id=memory_id, path=memory_path
                ),
            )
            if not saved.accepted:
                return self._stale_continuity_result(memory_id=memory_id)
            return {
                "path": str(saved.value),
                "summary_chars": len(str(existing.get("summary", "") or "")),
                "source_turn_count": int(
                    existing.get("source_turn_count", 0) or 0
                ),
                "memory_id": memory_id,
                "updated": False,
            }
        model_name = self._require_chat_model(values, "updating Continuity Memory")
        batch_turns = continuity_memory.update_batch_turns(
            new_turns,
            max_turns=self._continuity_batch_size(values),
        )
        summary = self._complete_summary(
            work,
            model_name,
            continuity_memory.build_summary_update_messages(
                str(existing.get("summary", "") or ""),
                continuity_memory.format_turn_segment(batch_turns),
                max_chars=max_chars,
            ),
            provider_context=provider_context,
        )
        payload = continuity_memory.memory_payload(
            continuity_memory.trim_to_budget(summary, max_chars),
            memory_id=memory_id,
            source_turn_count=previous_count + len(batch_turns),
        )
        saved = self._guarded_write(
            work,
            self._session_guard.commit_memory_write,
            lambda: continuity_memory.save_memory(
                payload, memory_id=memory_id, path=memory_path
            ),
        )
        if not saved.accepted:
            return self._stale_continuity_result(
                memory_id=memory_id,
                source_turn_count=previous_count,
                remaining_turns=len(turns) - previous_count,
            )
        remaining = max(
            0, len(turns) - int(payload.get("source_turn_count", 0) or 0)
        )
        result = {
            "path": str(saved.value),
            "summary_chars": len(str(payload.get("summary", "") or "")),
            "source_turn_count": int(payload.get("source_turn_count", 0) or 0),
            "processed_turns": len(batch_turns),
            "remaining_turns": remaining,
            "memory_id": memory_id,
            "updated": True,
        }
        self.notify_updates({"continuity_memory": True, **result})
        return result

    def batch_update_continuity(
        self,
        max_batches: int = 1000,
        history: Sequence[Mapping[str, object]] | None = None,
        *,
        work_context: MemoryWorkContext | None = None,
        provider_context: object | None = None,
    ) -> Mapping[str, object]:
        work = work_context or self.current_work_context()
        if not self.work_context_is_current(work):
            return self._stale_continuity_result(batch_count=0)
        try:
            limit = max(1, int(max_batches or 1000))
        except (TypeError, ValueError, OverflowError):
            limit = 1000
        count = 0
        processed = 0
        last: Mapping[str, object] = {}
        while count < limit:
            last = self.update_continuity(
                history,
                work_context=work,
                provider_context=provider_context,
            )
            if not bool(last.get("updated", False)):
                break
            count += 1
            processed += int(last.get("processed_turns", 0) or 0)
            if int(last.get("remaining_turns", 0) or 0) <= 0:
                break
        result = {
            "path": str(last.get("path", "") or ""),
            "summary_chars": int(last.get("summary_chars", 0) or 0),
            "source_turn_count": int(last.get("source_turn_count", 0) or 0),
            "processed_turns": processed,
            "remaining_turns": int(last.get("remaining_turns", 0) or 0),
            "batch_count": count,
            "memory_id": str(last.get("memory_id", self._active_memory_id()) or ""),
            "updated": count > 0,
        }
        if bool(last.get("stale_session")):
            result["stale_session"] = True
        return result

    def summarize_recent_continuity(
        self,
        turn_count: int = continuity_memory.DEFAULT_TAIL_SUMMARY_TURNS,
        history: Sequence[Mapping[str, object]] | None = None,
        *,
        work_context: MemoryWorkContext | None = None,
        provider_context: object | None = None,
    ) -> Mapping[str, object]:
        work = work_context or self.current_work_context()
        if not self.work_context_is_current(work):
            return self._stale_continuity_result(batch_count=0)
        values = work.config.values
        memory_id = continuity_memory.normalize_memory_id(
            values.get("continuity_memory_id"), fallback="default"
        )
        memory_path = continuity_memory.memory_path(memory_id).resolve()
        turns = self._history(history)
        selected = continuity_memory.tail_summary_turns(
            continuity_memory.sanitize_history_turns(turns), turn_count
        )
        existing = continuity_memory.load_memory(memory_id, path=memory_path)
        if existing.get("recovery_error"):
            raise continuity_memory.MemoryRecoveryError(existing["recovery_error"])
        if not selected:
            saved = self._guarded_write(
                work,
                self._session_guard.commit_memory_write,
                lambda: continuity_memory.save_memory(
                    existing, memory_id=memory_id, path=memory_path
                ),
            )
            if not saved.accepted:
                return self._stale_continuity_result(
                    memory_id=memory_id, batch_count=0
                )
            return {
                "path": str(saved.value),
                "summary_chars": len(str(existing.get("summary", "") or "")),
                "source_turn_count": int(
                    existing.get("source_turn_count", 0) or 0
                ),
                "processed_turns": 0,
                "remaining_turns": 0,
                "memory_id": memory_id,
                "updated": False,
            }
        model_name = self._require_chat_model(values, "updating Continuity Memory")
        max_chars = continuity_memory.normalize_max_chars(
            values.get(
                "continuity_memory_max_chars", continuity_memory.DEFAULT_MAX_CHARS
            )
        )
        frozen_provider = provider_context or self._capture_provider(work)
        running = str(existing.get("summary", "") or "")
        batch_count = 0
        size = self._continuity_batch_size(values)
        for start in range(0, len(selected), size):
            batch = selected[start : start + size]
            running = continuity_memory.trim_to_budget(
                self._complete_summary(
                    work,
                    model_name,
                    continuity_memory.build_summary_update_messages(
                        running,
                        continuity_memory.format_turn_segment(batch),
                        max_chars=max_chars,
                    ),
                    provider_context=frozen_provider,
                ),
                max_chars,
            )
            batch_count += 1
        payload = continuity_memory.memory_payload(
            running,
            memory_id=memory_id,
            source_turn_count=len(turns),
        )
        saved = self._guarded_write(
            work,
            self._session_guard.commit_memory_write,
            lambda: continuity_memory.save_memory(
                payload, memory_id=memory_id, path=memory_path
            ),
        )
        if not saved.accepted:
            return self._stale_continuity_result(
                memory_id=memory_id,
                remaining_turns=len(selected),
                batch_count=batch_count,
            )
        state = self._guarded_write(
            work,
            self._session_guard.commit_state_write,
            lambda: self._config.update(
                "continuity_memory_auto_baseline_turn_count", len(turns)
            ),
        )
        if not state.accepted:
            return self._stale_continuity_result(
                memory_id=memory_id, batch_count=batch_count
            )
        result = {
            "path": str(saved.value),
            "summary_chars": len(str(payload.get("summary", "") or "")),
            "source_turn_count": int(payload.get("source_turn_count", 0) or 0),
            "processed_turns": len(selected),
            "remaining_turns": 0,
            "batch_count": batch_count,
            "memory_id": memory_id,
            "updated": True,
        }
        self.notify_updates({"continuity_memory": True, **result})
        return result

    def schedule_continuity_batch(
        self,
        turn_count: int,
        on_complete: MemoryCompletion,
    ) -> CommandResult:
        work = self.current_work_context()
        existing = continuity_memory.load_memory(work.config.values.get("continuity_memory_id"))
        if existing.get("recovery_error"):
            raise continuity_memory.MemoryRecoveryError(existing["recovery_error"])
        provider = self._capture_provider(work)
        return self._service.schedule_operation(
            name="nc-continuity-memory-batch",
            work_context=work,
            payload={
                "turn_count": int(turn_count),
                "history": self._history(),
                "provider_context": provider,
            },
            operation=self._run_continuity_batch,
            on_complete=on_complete,
        )

    def clear_continuity(self) -> Mapping[str, object]:
        context = self.current_work_context()
        memory_id = self._active_memory_id()
        self._service.release_bound_store()
        cleared = self._guarded_write(
            context,
            self._session_guard.commit_memory_write,
            lambda: continuity_memory.clear_memory(memory_id),
        )
        if not cleared.accepted:
            return {"path": "", "memory_id": memory_id, "stale_session": True}
        path = cleared.value
        result = {"path": str(path), "memory_id": memory_id}
        self.notify_updates(result)
        return result

    def long_term_status(self) -> LongTermMemoryStatus:
        snapshot = self._conversation.snapshot()
        return self._service.status(
            snapshot.session_generation,
            snapshot=snapshot,
            config=self._config.snapshot(),
        )

    def status_view(self) -> Mapping[str, object]:
        snapshot = self._conversation.snapshot()
        context = self.current_work_context()
        return self._service.status_view(
            snapshot,
            self._config.snapshot(),
            embedding_status=self.admin.embedding_status(context),
        )

    def embedding_status(self) -> Mapping[str, object]:
        return self.admin.embedding_status(self.current_work_context())

    def embedding_blocked_event(self) -> Mapping[str, object]:
        return self.admin.embedding_blocked_event(self.current_work_context())

    def list_embedding_models(
        self, base_url: str = "", quiet: bool = True
    ) -> list[str]:
        return self.admin.list_embedding_models(
            self.current_work_context(),
            base_url=str(base_url or ""),
            quiet=bool(quiet),
        )

    def schedule_embedding_rebuild(
        self,
        limit: int,
        clear_existing: bool,
        on_complete: MemoryCompletion,
    ) -> CommandResult:
        return self.admin.schedule_embedding_rebuild(
            self.current_work_context(),
            limit=int(limit),
            clear_existing=bool(clear_existing),
            on_complete=on_complete,
        )

    def schedule_archive_candidate(
        self,
        prepared: long_term_memory_archive_rebuild.PreparedArchiveRebuild,
        on_complete: MemoryCompletion,
    ) -> CommandResult:
        return self.admin.schedule_archive_candidate(
            self.current_work_context(), prepared, on_complete=on_complete
        )

    def schedule_extract(
        self,
        turn_count: int,
        max_records: int,
        on_complete: MemoryCompletion,
    ) -> CommandResult:
        work = self.current_work_context()
        provider = self._capture_provider(work)
        return self._service.schedule_operation(
            name="nc-long-term-memory-extract",
            work_context=work,
            payload={
                "turn_count": int(turn_count),
                "max_records": int(max_records),
                "history": self._history(),
                "provider_context": provider,
            },
            operation=self._run_extract,
            on_complete=on_complete,
        )

    def schedule_context_flush(
        self,
        history: list[Mapping[str, object]],
        on_complete: MemoryCompletion,
    ) -> CommandResult:
        work = self.current_work_context()
        values = work.config.values
        continuity_enabled = bool(values.get("continuity_memory_enabled", False))
        archive_enabled = bool(
            values.get("long_term_memory_auto_archive_enabled", False)
        )
        provider = self._capture_provider(work) if continuity_enabled else None
        return self._service.schedule_operation(
            name="nc-chat-context-memory-save",
            work_context=work,
            payload={
                "history": self._history(history),
                "continuity_enabled": continuity_enabled,
                "archive_enabled": archive_enabled,
                "provider_context": provider,
            },
            operation=self._run_context_flush,
            on_complete=on_complete,
        )

    def extract(
        self,
        *,
        turn_count: int = long_term_memory.DEFAULT_EXTRACTION_TURNS,
        start_index: int | None = None,
        end_index: int | None = None,
        max_records: int = long_term_memory.DEFAULT_EXTRACTION_MAX_RECORDS,
        source_chat_id: str = "",
        history: Sequence[Mapping[str, object]] | None = None,
        work_context: MemoryWorkContext | None = None,
        provider_context: object | None = None,
    ) -> Mapping[str, object]:
        work = work_context or self.current_work_context()
        if not self.work_context_is_current(work):
            return self._stale_extract_result(source_chat_id)
        turns = long_term_memory.select_history_turns(
            self._history(history),
            start_index=start_index,
            end_index=end_index,
            turn_count=turn_count,
        )
        resolved_source = str(
            source_chat_id or work.binding.conversation_id or "unsaved_chat"
        )
        if not turns:
            return self._empty_extract_result(resolved_source)
        values = work.config.values
        model_name = self._require_chat_model(
            values, "extracting Long-Term Memory records"
        )
        path = work.binding.database_path
        chunk_text = long_term_memory.format_history_segment(turns)
        chunk_id = long_term_memory.chunk_id_for_segment(
            resolved_source,
            turns[0]["index"],
            turns[-1]["index"],
            chunk_text,
        )
        existing_chunk = long_term_memory.get_archived_chunk(chunk_id, path=path)
        blocked = bool(
            self.admin.embeddings.embedding_enabled(values)
            and self.admin.embeddings.write_blocked(values)
        )
        if existing_chunk and str(existing_chunk.get("status", "") or "") == "active":
            guarded = self._guarded_write(
                work,
                self._session_guard.commit_database_write,
                lambda: long_term_memory.ensure_history_chunk_assets(
                    existing_chunk,
                    turns,
                    source_chat_id=resolved_source,
                    path=path,
                ),
            )
            if not guarded.accepted:
                return self._stale_extract_result(
                    resolved_source, selected_turns=len(turns)
                )
            self._embed_or_report_blocked(work, existing_chunk, blocked)
            return {
                "source_chat_id": long_term_memory.normalize_memory_id(
                    resolved_source
                ),
                "selected_turns": len(turns),
                "archived_chunks": 0,
                "chunks": [existing_chunk],
                "stored_records": 0,
                "records": [],
                "skipped_existing_chunk": True,
                "embeddings_blocked": blocked,
            }
        guarded_chunk = self._guarded_write(
            work,
            self._session_guard.commit_database_write,
            lambda: long_term_memory.archive_history_chunk(
                turns,
                source_chat_id=resolved_source,
                tags=["raw_chat", "manual_extract"],
                path=path,
            ),
        )
        if not guarded_chunk.accepted:
            return self._stale_extract_result(
                resolved_source, selected_turns=len(turns)
            )
        chunk = guarded_chunk.value
        self._embed_or_report_blocked(work, chunk, blocked)
        messages = long_term_memory.build_extraction_messages(
            turns,
            source_chat_id=resolved_source,
            max_records=max_records,
        )
        params: dict[str, object] = {
            "model": model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        frozen_provider = provider_context or self._capture_provider(work)
        try:
            response = self._complete_provider(frozen_provider, params)
        except Exception as exc:
            message = str(exc)
            if "response_format" not in message and "json_object" not in message:
                raise
            params.pop("response_format", None)
            response = self._complete_provider(frozen_provider, params)
        candidates = long_term_memory.normalize_extracted_memories(
            self._extraction_payload(response),
            max_records=max_records,
        )
        stored: list[Mapping[str, Any]] = []
        for candidate in candidates:
            source_start = candidate.get("source_message_start") or turns[0]["index"]
            source_end = candidate.get("source_message_end") or turns[-1]["index"]
            existing = self._existing_extracted_record(
                resolved_source,
                candidate,
                source_start,
                source_end,
                path,
            )
            record_id = (existing or {}).get("id") or self._extracted_record_id(
                resolved_source, candidate, source_start, source_end
            )
            guarded = self._guarded_write(
                work,
                self._session_guard.commit_database_write,
                lambda candidate=candidate, existing=existing, record_id=record_id: (
                    long_term_memory.upsert_memory(
                        {
                            "memory_id": record_id,
                            "type": candidate.get("type", "note"),
                            "title": candidate.get("title", ""),
                            "summary": candidate.get("summary", ""),
                            "content": candidate.get("content", ""),
                            "tags": candidate.get("tags", []),
                            "source_chat_id": resolved_source,
                            "source_message_start": source_start,
                            "source_message_end": source_end,
                            "importance": candidate.get("importance", 0.5),
                            "confidence": candidate.get("confidence", 0.8),
                            "status": "active",
                            "created_at": (existing or {}).get("created_at", ""),
                        },
                        path=path,
                    )
                ),
            )
            if not guarded.accepted:
                break
            record = guarded.value
            if record and not blocked:
                self.admin.embed_record(work, record)
            if record:
                stored.append(record)
        result = {
            "source_chat_id": long_term_memory.normalize_memory_id(resolved_source),
            "selected_turns": len(turns),
            "archived_chunks": 1 if chunk else 0,
            "chunks": [chunk] if chunk else [],
            "stored_records": len(stored),
            "records": stored,
            "embeddings_blocked": blocked,
        }
        self.notify_updates({"long_term_memory_archive": True})
        return result

    def archive_snapshot(
        self, record_limit: int, chunk_limit: int
    ) -> Mapping[str, object]:
        context = self.current_work_context()
        return {
            "storage_path": str(context.binding.database_path),
            "records": self.admin.list_records(context, limit=int(record_limit)),
            "chunks": self.admin.list_chunks(context, limit=int(chunk_limit)),
        }

    def export_default_path(self) -> str:
        path = self.admin.default_report_path(
            self.current_work_context(), self._report_request()
        )
        return str(path or "")

    def export_session_report(self, path: str = "") -> Mapping[str, object]:
        result = self.admin.export_report(
            self.current_work_context(),
            self._report_request(),
            path=str(path or "") or None,
        )
        if result is None:
            raise RuntimeError("The active memory session changed during export.")
        return result

    def retrieve(
        self, query: str, record_limit: int, chunk_limit: int
    ) -> list[Mapping[str, object]]:
        return self._service.retrieve_results(
            self.current_work_context(),
            str(query or ""),
            record_limit=int(record_limit),
            chunk_limit=int(chunk_limit),
        )

    def reconcile_message_deletion(self, previous_history, replacement_history, *,
                                   message_index: int, remove_memories: bool) -> Mapping[str, object]:
        """Invoked under ConversationService's drained deletion transition."""
        from core.memory_message_deletion import delete_message_memories, DeletionRecoveryError
        from contextlib import closing
        import hashlib
        import sqlite3
        work = self.current_work_context()
        recovery_key = (work.binding, tuple(previous_history), message_index)
        if (self._deletion_recovery is not None
                and self._deletion_recovery[0].session_generation == work.binding.session_generation
                and (self._deletion_recovery != recovery_key or not remove_memories)):
            raise RuntimeError('Retry the original message deletion with memory cleanup enabled first. '
                               'Memory recovery is still required.')
        invalidated = self._service.invalidate_history_work(work)
        if not invalidated.accepted:
            raise RuntimeError('Memory source changed before deletion. Try again.')
        memory_id = str(work.config.values.get('continuity_memory_id') or '')
        summary_path = continuity_memory.memory_path(memory_id) if memory_id else None
        # Protect an asset reused in retained history even if it has not yet
        # acquired a second archive link. Read images; never remove their files.
        hashes = set()
        unresolved_image = False
        for message in replacement_history:
            metadata = message.get('metadata') or {}
            retained_paths = image_paths(message) or image_paths(metadata)
            retained_paths.append(message.get('generated_image_path') or metadata.get('generated_image_path'))
            for raw in retained_paths:
                if raw:
                    try:
                        with Path(str(raw)).open('rb') as image:
                            hashes.add(hashlib.file_digest(image, 'sha256').hexdigest())
                    except OSError:
                        unresolved_image = True
        protected = set()
        if work.binding.database_path.is_file():
            with closing(sqlite3.connect(work.binding.database_path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
                protected = {row[0] for row in connection.execute('SELECT id,sha256 FROM long_term_memory_assets')
                             if unresolved_image or row[1] in hashes}
        if remove_memories:
            self._config.update('continuity_memory_auto_baseline_turn_count', 0)
        try:
            if remove_memories:
                from core.memory_history_repair import repair_history_memories
                result = repair_history_memories(database_path=work.binding.database_path,
                    summary_path=summary_path, memory_id=memory_id,
                    source_chat_id=work.binding.conversation_id, previous_history=previous_history,
                    replacement_history=replacement_history,
                    retained_asset_ids=protected,
                    archive_batch_size=int(work.config.values.get('long_term_memory_archive_batch_turns', 8) or 8),
                    source_indices=[n for n in range(1, len(previous_history)+1) if n != message_index])
            else:
                result = delete_message_memories(database_path=work.binding.database_path,
                summary_path=summary_path, memory_id=memory_id,
                source_chat_id=work.binding.conversation_id, message_index=message_index,
                history_count=len(previous_history), remove_memories=remove_memories,
                retained_asset_ids=protected, removed_image_turns=[previous_history[message_index-1]],
                retained_image_turns=replacement_history)
        except DeletionRecoveryError:
            # The summary stays empty if restoration failed. Do not schedule
            # fresh memory work until this exact deletion is successfully retried.
            self._service.set_history_recovery_required(work.binding.session_generation, True)
            self._deletion_recovery = recovery_key
            raise
        self._service.set_history_recovery_required(work.binding.session_generation, False)
        self._deletion_recovery = None
        return result

    def repair_mapped_history(self, previous, replacement, indices):
        from core.memory_history_repair import repair_history_memories
        work = self.current_work_context()
        invalidated = self._service.invalidate_history_work(work)
        if not invalidated.accepted:
            raise RuntimeError('Memory changed before the edit could be applied. Try again.')
        memory_id = str(work.config.values.get('continuity_memory_id') or '')
        result = repair_history_memories(database_path=work.binding.database_path,
            summary_path=continuity_memory.memory_path(memory_id) if memory_id else None,
            memory_id=memory_id, source_chat_id=work.binding.conversation_id,
            archive_batch_size=int(work.config.values.get('long_term_memory_archive_batch_turns', 8) or 8),
            previous_history=previous, replacement_history=replacement, source_indices=indices)
        return result

    def finish_history_repair(self, result):
        """Inference starts only after repaired canonical history is committed."""
        if not result.get('changed'):
            return
        work = self.current_work_context()
        history = self._history()
        self.notify_updates({'history_repair': {**result, 'phase': 'queued'}})
        def operation(context, payload):
            errors = []
            self.notify_updates({'history_repair': {**result, 'phase': 'running'}})
            for identity in result.get('rebuilt_chunk_ids', []):
                if not self.work_context_is_current(context):
                    return {'stale_session': True}
                try:
                    chunk = long_term_memory.get_archived_chunk(identity, path=context.binding.database_path)
                    if chunk:
                        turns = long_term_memory.sanitize_history_turns(history)
                        batch = [t for t in turns if chunk['source_message_start'] <= t['index'] <= chunk['source_message_end']]
                        self._guarded_write(context, self._session_guard.commit_database_write,
                            lambda: long_term_memory.ensure_history_chunk_assets(chunk, batch,
                                source_chat_id=context.binding.conversation_id, path=context.binding.database_path))
                        if context.config.values.get('long_term_memory_embedding_enabled'):
                            if self._embedding_write_blocked(context.config.values):
                                self._record_archive_embedding_blocked(context)
                                errors.append('Search embeddings are locked. Restore the saved chat’s model/context or rebuild embeddings.')
                            else:
                                self._embed_archive_chunk(context, chunk)
                except Exception as error:
                    errors.append('Search index: ' + str(error))
            if history and context.config.values.get('continuity_memory_enabled'):
                try:
                    self.summarize_recent_continuity(len(history), history, work_context=context)
                except Exception as error:
                    errors.append('Summary: ' + str(error))
            return {**result, 'phase': 'failed' if errors else 'complete', 'error': '\n'.join(dict.fromkeys(errors)),
                    'summary_disabled': not bool(context.config.values.get('continuity_memory_enabled'))}
        def completed(context, value, error):
            if self.work_context_is_current(context):
                self.notify_updates({'history_repair': dict(value or {}, **({'phase': 'failed', 'error': str(error)} if error else {}))})
        scheduled = self._service.schedule_operation(name='nc-memory-history-repair', work_context=work,
            payload={}, operation=operation, on_complete=completed)
        if not scheduled.accepted:
            self.notify_updates({'history_repair': {**result, 'phase': 'failed',
                'error': str(getattr(scheduled.failure, 'message', 'Memory repair could not start.'))}})

    def reconcile_history_edit(
        self,
        previous_history: Sequence[Mapping[str, object]],
        replacement_history: Sequence[Mapping[str, object]],
    ) -> Mapping[str, object]:
        context = self.current_work_context()
        result = self._service.reconcile(
            self._conversation.snapshot(),
            previous_history=previous_history,
            replacement_history=replacement_history,
            work_context=context,
            on_reconciled=self.notify_updates,
        )
        if not result.accepted or result.value is None:
            return {"changed": False, "archive_queued": False, "stale_session": True}
        return dict(result.value)

    def pending_content_migration_report(self) -> Mapping[str, object]:
        path = self.current_work_context().binding.database_path
        return dict(long_term_memory.pending_content_migration_report(path) or {})

    def _bind_active_store(self, memory_id: str) -> Path:
        normalized = continuity_memory.normalize_memory_id(
            memory_id or self._config.get("continuity_memory_id", ""),
            fallback="default",
        )
        path = long_term_memory.db_path_for_memory_id(normalized).resolve()
        conversation_id = long_term_memory.normalize_memory_id(
            self._config.get("active_chat_context_name", "") or normalized,
            fallback="unsaved_chat",
        )
        binding = MemorySessionBinding(
            self._conversation.snapshot().session_generation,
            conversation_id,
            path,
        )
        bound = self._service.bind_session(binding)
        if not bound.accepted:
            message = (
                bound.failure.message
                if bound.failure is not None
                else "Could not bind the Long-Term Memory store."
            )
            raise RuntimeError(message)
        long_term_memory.set_default_db_path(path)
        self._config.update_many(
            {
                "long_term_memory_db_path": str(path),
                "long_term_memory_db_id": normalized,
            }
        )
        return path

    def _active_memory_id(self) -> str:
        memory_id = continuity_memory.normalize_memory_id(
            self._config.get("continuity_memory_id", "")
        )
        if not memory_id:
            memory_id = continuity_memory.new_memory_id()
            self._config.update("continuity_memory_id", memory_id)
        return memory_id

    def _write_embedding_baseline(self, model: str, context_length: int) -> object:
        return self._config.update_many(
            {
                "long_term_memory_embedding_session_model": str(model or ""),
                "long_term_memory_embedding_session_context_length": int(
                    context_length
                ),
            }
        )

    def _history(
        self, history: Sequence[Mapping[str, object]] | None = None
    ) -> list[dict[str, object]]:
        source = self._conversation.message_mappings() if history is None else history
        return [dict(turn) for turn in source if isinstance(turn, Mapping)]

    def _capture_provider(self, context: MemoryWorkContext) -> object:
        values = context.config.values
        model = self._require_chat_model(values, "running memory work")
        provider_name = str(values.get("chat_provider", "") or "").strip()
        ensure_ready = getattr(self._provider, "ensure_model_ready", None)
        if callable(ensure_ready):
            ensure_ready(provider_name, model)
        capture = getattr(self._provider, "capture", None)
        if callable(capture):
            return capture(context)
        return self._provider.runtime.capture_frozen_context(
            provider=provider_name or None,
            model=model,
            runtime_config=values,
        )

    def _complete_provider(
        self,
        provider_context: object,
        params: Mapping[str, object],
        additional_params: Mapping[str, object] | None = None,
    ) -> object:
        prepared = dict(params)
        if getattr(provider_context, "provider_name", "") == "lmstudio":
            prepared["max_tokens"] = -1
        else:
            prepared.pop("max_tokens", None)
            prepared.pop("max_completion_tokens", None)
        complete = getattr(self._provider, "complete", None)
        if callable(complete):
            return complete(
                provider_context,
                prepared,
                dict(additional_params or {}),
            )
        request = self._provider.runtime.prepare_frozen_request(
            provider_context,
            prepared,
            dict(additional_params or {}),
        )
        return self._provider.runtime.complete_frozen(request)

    def _complete_summary(
        self,
        context: MemoryWorkContext,
        model_name: str,
        messages: Sequence[Mapping[str, object]],
        *,
        provider_context: object | None,
    ) -> str:
        provider = provider_context or self._capture_provider(context)
        summary = str(
            self._complete_provider(
                provider,
                {"model": model_name, "messages": [dict(item) for item in messages]},
            )
            or ""
        ).strip()
        if not summary:
            raise RuntimeError("The provider returned an empty Continuity Memory summary.")
        return summary

    def _complete_conversation_memory(self, job, messages) -> str:
        if job.provider_context is None:
            raise RuntimeError(
                "Conversation Memory job is missing its frozen provider context."
            )
        return str(
            self._complete_provider(
                job.provider_context,
                {
                    "model": job.model_name,
                    "messages": [dict(message) for message in messages],
                },
            )
            or ""
        )

    def _conversation_memory_updated(
        self, context: MemoryWorkContext, result: Mapping[str, object]
    ) -> None:
        if not self.work_context_is_current(context):
            return
        baseline = int(result.get("source_turn_count", 0) or 0)
        committed = self._guarded_write(
            context,
            self._session_guard.commit_state_write,
            lambda: self._config.update(
                "continuity_memory_auto_baseline_turn_count", baseline
            ),
        )
        if committed.accepted and self.work_context_is_current(context):
            self.notify_updates(result)

    def _semantic_query(
        self, context: MemoryWorkContext, query: str
    ) -> Mapping[str, object]:
        values = context.config.values
        embeddings = self.admin.embeddings
        if not embeddings.embedding_enabled(values) or embeddings.write_blocked(values):
            return {}
        config = embeddings.config(values)
        vector = embeddings.embed(
            query,
            model=config.model,
            base_url=config.base_url,
            context_length=config.context_length,
            runtime_config=values,
        )
        if not vector or not self.work_context_is_current(context):
            return {}
        return {
            "query_vector": vector,
            "embedding_model": config.index_model,
            "semantic_min_score": float(
                values.get("long_term_memory_embedding_min_score", 0.25) or 0.25
            ),
        }

    def _complete_image_context(
        self,
        context: MemoryWorkContext,
        params: Mapping[str, object],
        additional_params: Mapping[str, object],
    ) -> str:
        return str(
            self._complete_provider(
                self._capture_provider(context), params, additional_params
            )
            or ""
        )

    def _model_supports_images(self, values: Mapping[str, object]) -> bool:
        supports_images = getattr(self._provider, "model_supports_images", None)
        if callable(supports_images):
            return bool(supports_images(values))
        explicit = values.get("model_supports_images")
        if explicit is not None:
            return bool(explicit)
        return infer_model_supports_images(values.get("model_name", ""))

    def _embed_archive_chunk(
        self, context: MemoryWorkContext, chunk: Mapping[str, object]
    ) -> object:
        return self.admin.embed_chunk(context, chunk)

    def _embedding_write_blocked(self, values: Mapping[str, object]) -> bool:
        return self.admin.embeddings.write_blocked(values)

    def _record_archive_embedding_blocked(
        self, context: MemoryWorkContext
    ) -> None:
        self.admin.record_embedding_blocked_attempt(
            context, "long_term_memory_archive_sync"
        )

    def _embed_or_report_blocked(
        self,
        context: MemoryWorkContext,
        chunk: Mapping[str, object] | None,
        blocked: bool,
    ) -> None:
        if blocked:
            self.admin.record_embedding_blocked_attempt(
                context, "long_term_memory_manual_extract"
            )
        elif chunk:
            self.admin.embed_chunk(context, chunk)

    def _refresh_assets(self, context: MemoryWorkContext) -> int:
        if (
            not self.work_context_is_current(context)
            or not bool(
                context.config.values.get(
                    "long_term_memory_auto_archive_enabled", False
                )
            )
        ):
            return 0
        turns = long_term_memory.sanitize_history_turns(self._history())
        if not turns:
            return 0
        binding = context.binding
        linked = 0
        for chunk in long_term_memory.list_archived_chunks(
            source_chat_id=binding.conversation_id,
            limit=1000,
            path=binding.database_path,
        ):
            if str(chunk.get("status", "") or "") != "active":
                continue
            try:
                start = int(chunk.get("source_message_start", 0) or 0)
                end = int(chunk.get("source_message_end", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            selected = [
                turn
                for turn in turns
                if start <= int(turn.get("index", 0) or 0) <= end
            ]
            if start <= 0 or end < start or not selected:
                continue
            refreshed = self._guarded_write(
                context,
                self._session_guard.commit_database_write,
                lambda chunk=chunk, selected=selected: (
                    long_term_memory.ensure_history_chunk_assets(
                        chunk,
                        selected,
                        source_chat_id=binding.conversation_id,
                        path=binding.database_path,
                    )
                ),
            )
            if not refreshed.accepted:
                return linked
            linked += int(refreshed.value or 0)
        return linked

    def _run_continuity_batch(
        self, context: MemoryWorkContext, payload: object
    ) -> Mapping[str, object]:
        values = payload if isinstance(payload, Mapping) else {}
        return self.summarize_recent_continuity(
            int(
                values.get(
                    "turn_count", continuity_memory.DEFAULT_TAIL_SUMMARY_TURNS
                )
                or continuity_memory.DEFAULT_TAIL_SUMMARY_TURNS
            ),
            [dict(turn) for turn in values.get("history", ())],
            work_context=context,
            provider_context=values.get("provider_context"),
        )

    def _run_extract(
        self, context: MemoryWorkContext, payload: object
    ) -> Mapping[str, object]:
        values = payload if isinstance(payload, Mapping) else {}
        return self.extract(
            turn_count=int(
                values.get(
                    "turn_count", long_term_memory.DEFAULT_EXTRACTION_TURNS
                )
            ),
            max_records=int(
                values.get(
                    "max_records", long_term_memory.DEFAULT_EXTRACTION_MAX_RECORDS
                )
            ),
            history=[dict(turn) for turn in values.get("history", ())],
            work_context=context,
            provider_context=values.get("provider_context"),
        )

    def _run_context_flush(
        self, context: MemoryWorkContext, payload: object
    ) -> Mapping[str, object]:
        values = payload if isinstance(payload, Mapping) else {}
        history = [dict(turn) for turn in values.get("history", ())]
        result: dict[str, object] = {"continuity": None, "archive": None}
        if bool(values.get("continuity_enabled", False)):
            result["continuity"] = self.batch_update_continuity(
                1000,
                history,
                work_context=context,
                provider_context=values.get("provider_context"),
            )
        if bool(values.get("archive_enabled", False)):
            result["archive"] = self._service.sync_archive(
                context,
                history,
                flush_partial=True,
            )
        return result

    def _report_request(self) -> SessionMemoryReportRequest:
        values = self._config.snapshot().values
        return SessionMemoryReportRequest(
            continuity=dict(self.continuity_snapshot()),
            history=tuple(self._conversation.message_mappings()),
            chat_context_name=str(values.get("active_chat_context_name", "") or ""),
            chat_context_path=str(values.get("active_chat_context_path", "") or ""),
            memory_id=str(values.get("continuity_memory_id", "") or ""),
        )

    def _require_chat_model(
        self, values: Mapping[str, object], operation: str
    ) -> str:
        model = str(values.get("model_name", "") or "").strip()
        placeholder = getattr(self._provider, "model_is_placeholder", None)
        if not callable(placeholder):
            placeholder = self._provider.is_model_catalog_placeholder
        if placeholder(model):
            raise RuntimeError(f"Choose a chat model before {operation}.")
        return model

    @staticmethod
    def _continuity_batch_size(values: Mapping[str, object]) -> int:
        try:
            size = int(
                values.get(
                    "continuity_memory_auto_turns",
                    continuity_memory.DEFAULT_UPDATE_BATCH_TURNS,
                )
                or continuity_memory.DEFAULT_UPDATE_BATCH_TURNS
            )
        except (TypeError, ValueError, OverflowError):
            size = continuity_memory.DEFAULT_UPDATE_BATCH_TURNS
        return max(1, min(10000, size))

    @staticmethod
    def _extraction_payload(response: object) -> Mapping[str, object]:
        text = str(response or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text).strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(
                "The provider did not return a valid Long-Term Memory JSON payload."
            )
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "The provider did not return a valid Long-Term Memory JSON payload."
            ) from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError(
                "The provider did not return a valid Long-Term Memory JSON payload."
            )
        return payload

    @staticmethod
    def _extracted_record_id(
        source_chat_id: object,
        candidate: Mapping[str, object],
        source_start: object,
        source_end: object,
    ) -> str:
        title = str(candidate.get("title", "") or "").strip().lower()
        memory_type = long_term_memory.normalize_memory_type(
            candidate.get("type", "note")
        )
        key = json.dumps(
            [
                long_term_memory.normalize_memory_id(
                    source_chat_id, fallback="unsaved_chat"
                ),
                int(source_start or 0),
                int(source_end or 0),
                memory_type,
                re.sub(r"\s+", " ", title),
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        digest = uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16]
        return long_term_memory.normalize_memory_id(
            f"mem_{digest}", fallback=f"mem_{digest}"
        )

    @staticmethod
    def _existing_extracted_record(
        source_chat_id: object,
        candidate: Mapping[str, object],
        source_start: object,
        source_end: object,
        path: Path,
    ) -> Mapping[str, Any] | None:
        normalized_source = long_term_memory.normalize_memory_id(
            source_chat_id, fallback="unsaved_chat"
        )
        memory_type = long_term_memory.normalize_memory_type(
            candidate.get("type", "note")
        )
        title = re.sub(
            r"\s+", " ", str(candidate.get("title", "") or "").strip().lower()
        )
        start, end = int(source_start or 0), int(source_end or 0)
        for record in long_term_memory.list_memories(
            source_chat_id=normalized_source, limit=1000, path=path
        ):
            record_title = re.sub(
                r"\s+", " ", str(record.get("title", "") or "").strip().lower()
            )
            if (
                int(record.get("source_message_start", 0) or 0) == start
                and int(record.get("source_message_end", 0) or 0) == end
                and long_term_memory.normalize_memory_type(
                    record.get("type", "note")
                )
                == memory_type
                and record_title == title
            ):
                return record
        return None

    @staticmethod
    def _empty_extract_result(source_chat_id: object) -> Mapping[str, object]:
        return {
            "source_chat_id": str(source_chat_id or ""),
            "selected_turns": 0,
            "archived_chunks": 0,
            "chunks": [],
            "stored_records": 0,
            "records": [],
        }

    @classmethod
    def _stale_extract_result(
        cls, source_chat_id: object, *, selected_turns: int = 0
    ) -> Mapping[str, object]:
        result = dict(cls._empty_extract_result(source_chat_id))
        result["selected_turns"] = int(selected_turns)
        result["stale_session"] = True
        return result

    @staticmethod
    def _stale_continuity_result(
        *,
        memory_id: str = "",
        source_turn_count: int = 0,
        remaining_turns: int = 0,
        batch_count: int | None = None,
    ) -> Mapping[str, object]:
        result: dict[str, object] = {
            "path": "",
            "summary_chars": 0,
            "source_turn_count": int(source_turn_count),
            "processed_turns": 0,
            "remaining_turns": int(remaining_turns),
            "memory_id": str(memory_id),
            "updated": False,
            "stale_session": True,
        }
        if batch_count is not None:
            result["batch_count"] = int(batch_count)
        return result

    def _guarded_write(
        self,
        context: MemoryWorkContext,
        commit: Callable[[object, Callable[[], object]], CommandResult],
        effect: Callable[[], object],
    ) -> CommandResult:
        """Reject writes after either the session lease or store epoch changes."""

        if not self.work_context_is_current(context):
            return self._stale_write_result()

        result = commit(
            context.lease,
            lambda: (
                effect()
                if self.work_context_is_current(context)
                else _STALE_WRITE
            ),
        )
        if not result.accepted or result.value is _STALE_WRITE:
            return self._stale_write_result()
        return result

    @staticmethod
    def _stale_write_result() -> CommandResult:
        return CommandResult(
            False,
            failure=RuntimeFailure(
                "stale_session",
                "Memory work no longer owns the current session binding.",
            ),
        )

    def _log(self, message: str) -> None:
        if self._logger is not None:
            self._logger(str(message))


__all__ = ["ProductionMemoryOwner", "ProductionMemoryProvider"]
