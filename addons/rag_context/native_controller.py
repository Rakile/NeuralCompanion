"""Widget-free document package orchestration. Chat reads only ready memory."""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import threading
import time
from uuid import uuid4

from core.runtime.document_memory import embedding_prefixes, embedding_context_tokens, DocumentEmbeddingBusy, idle_reason
from . import indexer
from .models import DocumentScope, EmbeddingSpec, RetrievalSettings, SourceRecord, UsageSettings
from .packages import PackageLibrary, path_key, PackageConflict
from .package_retrieval import PackageReaders, package_row
from .retrieval import DocumentRetriever
from .scheduler import DocumentIndexScheduler
from .snapshots import SnapshotStore


class RagContextController:
    def __init__(self, storage, *, host=None, tasks=None, clock=time.monotonic):
        self.storage, self.host, self.tasks, self.clock = storage, host, tasks, clock
        self.settings = indexer.load_settings(storage)
        self.settings["enabled"] = False  # Only an explicit chat restore/action enables recall.
        self.library = PackageLibrary(Path(storage.addon_dir), recover=True)
        self.snapshots = SnapshotStore(Path(storage.addon_dir), library=self.library)
        self._lock = self.library.lock
        self._closed, self._activation, self._session = False, 0, 0
        self._error = ""
        self._generation = None
        self._snapshot_meta = {}
        self._ready_packages = {}
        self._scope = DocumentScope(1, 0, "", 0, 0)
        self._load_wake = threading.Event()
        self._load_pending = None
        self._indexing_requested = False
        self._models = []
        self._model_refresh_pending = False
        self._availability = {"state": "empty", "message": ""}
        self._previous_package = ""
        self._last_model_check = time.monotonic()
        self.retriever = DocumentRetriever(embeddings=host.embeddings if host else None, clock=clock, tasks=tasks)
        self.package_readers = PackageReaders(library=self.library, snapshots=self.snapshots,
            embeddings=host.embeddings if host else None, clock=clock, tasks=tasks)
        self.scheduler = DocumentIndexScheduler(library=self.library, snapshots=self.snapshots, host=host, tasks=tasks, clock=clock)
        self.scheduler.on_publish = self._published
        self._load_worker = tasks.spawn("document-activation", self._load_loop) if tasks else None
        selected = self.settings.get("package_id")
        if not selected and self.settings.get("schema_version") != 2 and not self.library.read_only:
            selected = self.library.migrate_legacy(self.settings, indexer.load_index(storage))
        self._select(str(selected or ""), check_model=True)

    def _session_generation(self):
        if self.host is not None:
            return int(self.host.idle_snapshot().get("session_generation", self._session))
        return self._session

    def _select(self, package_id, *, check_model=False, index_requested=False):
        with self._lock:
            # Restoring a package must not warm a model while chat recall is off.
            self._indexing_requested = not self.library.read_only and bool(self.settings.get("enabled") or index_requested)
            previous = self._scope.package_id if self._availability["state"] == "ready" else self._previous_package
            was_ready = self._availability["state"] == "ready" and package_id == self._scope.package_id
            self._activation += 1
            self._generation = None
            self._snapshot_meta = {}
            self._error = ""
            self.settings["package_id"] = package_id
            try:
                package = self.library.get(package_id)
                self._scope = DocumentScope(1, self._session_generation(), package.id, package.revision, self._activation)
            except (ValueError, KeyError):
                package = None
                self._scope = DocumentScope(1, self._session_generation(), "", 0, self._activation)
                self._error = "Selected knowledge package is unavailable. Select another package." if package_id else ""
            self.retriever.invalidate(self._scope)
            needs_check = bool(package and (check_model or not was_ready))
            if needs_check:
                self._previous_package = previous if previous != package_id else ""
            self._availability = {"state": "checking" if needs_check else "ready" if package else "empty",
                                  "model": package.embedding.model if package else "", "message": "Checking package embedding model…" if needs_check else ""}
            self.scheduler.activate(self._scope if package and not needs_check and self._indexing_requested else None)
            cached = self._ready_packages.get(package.id) if package else None
            if (not needs_check and cached and cached[0].id == package.generation_id and cached[0].fingerprint == package.embedding.fingerprint()
                    and self.retriever.reactivate(self._scope,cached[0],frozenset(s.id for s in package.sources if s.enabled and s.status == "ready"),package.retrieval,embedding=package.embedding,package_name=package.name,usage=package.usage)):
                self._generation, self._snapshot_meta = cached
                self._load_pending = None
            else:
                self._load_pending = (self._scope, package, needs_check)
        self._load_wake.set()
        if package and not needs_check:
            self._queue_pending(package)
        if not self.tasks:
            pending, self._load_pending = self._load_pending, None
            if pending:
                self._activate_package(*pending)

    def _activate_package(self, scope, package, check_model):
        if package is None or (check_model and not self._check_model(scope, package)):
            return
        with self._lock:
            if self._scope != scope or self._closed:
                return
            self.scheduler.activate(scope if self._indexing_requested else None)
            self._queue_pending(package)
        self._load_generation(scope, package)

    def _check_model(self, scope, package):
        try:
            models = self.host.embeddings.list_models(package.embedding.base_url) if self.host else []
            found = any(str(m.get("key") or m.get("id")) == package.embedding.model for m in models)
            state = "ready" if found else "missing"
            message = "" if found else (f'Embedding model “{package.embedding.model}” is not installed on the local server. '
                'Add the same model again and press Retry to reuse this index, or Cancel loading this package. '
                'Using another model requires applying changes and re-indexing the package.')
        except DocumentEmbeddingBusy:
            with self._lock:
                if self._scope == scope:
                    self._load_pending = (scope, package, True)
            return False
        except Exception as exc:
            state, models = "unavailable", None
            message = f'Cannot check embedding model “{package.embedding.model}”: {exc}'
        with self._lock:
            if self._scope != scope or self._closed:
                return False
            self._last_model_check = time.monotonic()
            if models is not None:
                self._models = [dict(m) for m in models]
            if state == "unavailable" and self._availability["state"] == "ready":
                self._error = message
                return True
            self._availability = {"state": state, "model": package.embedding.model, "message": message}
            if state != "ready":
                self.retriever.invalidate(scope)
                self.scheduler.activate(None)
                self._generation, self._snapshot_meta = None, {}
            else:
                self._error = ""
            return state == "ready"

    def retry_package_load(self):
        self._select(self._scope.package_id, check_model=True)

    def cancel_package_load(self):
        if self._availability["state"] not in {"missing", "unavailable", "checking"}:
            return
        previous, self._previous_package = self._previous_package, ""
        self._select(previous, check_model=bool(previous))
        self._save_settings()

    def _queue_pending(self, package):
        if self.library.read_only or not self._indexing_requested:
            return
        for source in package.sources:
            if source.enabled and (source.pending_operation or source.status == "pending"):
                self.scheduler.enqueue(source.id, kind=source.pending_operation or ("reembed" if source.snapshot_id else "import"))

    def _load_loop(self, token):
        while not self._closed and not token.cancelled:
            self._load_wake.wait(.1)
            self._load_wake.clear()
            with self._lock:
                pending, self._load_pending = self._load_pending, None
                refresh, self._model_refresh_pending = self._model_refresh_pending, False
                model_scope = self._scope
            if pending:
                self._activate_package(*pending)
            if (not refresh and time.monotonic() - self._last_model_check >= 30 and self.host
                    and self._availability["state"] == "ready" and not self.scheduler.snapshot().get("pending")
                    and self.scheduler.snapshot().get("state") != "preparing local model"
                    and not idle_reason(self.host.idle_snapshot())):
                refresh = True
            if refresh and self.host and model_scope.package_id:
                package = self.library.get(model_scope.package_id)
                was_ready = self._availability["state"] == "ready"
                if self._check_model(model_scope, package) and not was_ready:
                    self._activate_package(model_scope, package, False)

    def _load_generation(self, scope, package):
        if package is None:
            return
        try:
            generation = self.snapshots.load(package)
            metadata = {s.id: self.snapshots.read_snapshot(package.id, s) for s in package.sources if s.snapshot_id}
            with self._lock:
                if self._scope != scope or self._closed or self._availability["state"] != "ready":
                    return
                if generation:
                    self.retriever.activate(scope, generation, frozenset(s.id for s in package.sources if s.enabled and s.status == "ready"), package.retrieval, embedding=package.embedding, package_name=package.name, usage=package.usage)
                self._generation, self._snapshot_meta = generation, metadata
                if generation:
                    self._ready_packages[package.id] = (generation, metadata)
                    while len(self._ready_packages) > 4:
                        self._ready_packages.pop(next(iter(self._ready_packages)))
        except Exception as exc:
            with self._lock:
                if self._scope == scope:
                    self._error = str(exc)[:1000]

    def _published(self, package_id):
        with self._lock:
            if self._scope.package_id != package_id or self._closed or self._availability["state"] != "ready":
                return
            package = self.library.get(package_id)
            self._scope = replace(self._scope, package_revision=package.revision)
            scope = self._scope
            self.retriever.invalidate(scope)
        self._load_generation(scope, package)  # Already on owned indexing worker.

    def list_packages(self):
        return self.library.list_packages()

    def run_scoped(self, request, operation):
        """Atomically reject UI work queued for a superseded package activation."""
        with self._lock:
            expected_package = request.get("_expected_package_id")
            expected_activation = request.get("_expected_activation_revision")
            if ((expected_package is not None and expected_package != self._scope.package_id)
                    or (expected_activation is not None and expected_activation != self._scope.activation_revision)):
                raise PackageConflict("Document package changed while this action was queued. Please try again.")
            return operation()

    def _ensure_writable(self):
        with self._lock:
            try:
                self.library.ensure_writable()
            except RuntimeError:
                if self.library.read_only:
                    self._indexing_requested = False
                    self._model_refresh_pending = False
                    self._availability.update(state="recovery_required", message=self.library.recovery_error)
                    self.scheduler.cancel("Document Memory recovery required.")
                raise

    def create_package(self, name):
        self._ensure_writable()
        try:
            template = self._package()
        except (ValueError, KeyError):
            template = None
        package = self.library.create(name, template=template)
        self.select_package(package.id)
        return package

    def select_package(self, package_id):
        self.library.get(str(package_id))
        self._select(str(package_id), check_model=True)
        self._save_settings()

    def _package(self):
        return self.library.get(self.settings["package_id"])

    def export_state(self):
        with self._lock:
            value = dict(self.settings)
            try:
                package = self._package()
                value.update(asdict(package.retrieval))
                value.update(asdict(package.embedding))
                value["chunk_prefix"], value["query_prefix"] = embedding_prefixes(package.embedding)
                value.update(asdict(package.usage))
                value["files"] = [s.path for s in package.sources]
            except (KeyError, ValueError):
                value["files"] = []
            value.update(schema_version=2, package_id=self.settings.get("package_id", ""))
            return value

    def import_state(self, payload):
        with self._lock:
            self._session += 1
            self.settings["enabled"] = bool(payload.get("enabled", False))
            if payload.get("schema_version") == 2:
                package_id = str(payload.get("package_id") or "")
            elif self.library.read_only:
                package_id = str(self.settings.get("package_id") or "")
            else:
                package_id = self.library.migrate_legacy(payload, {})
            self._select(package_id, check_model=True)
        self._save_settings()

    def update_settings(self, changes, *, package_id=None, expected_revision=None):
        with self._lock:
            self._ensure_writable()
            package = self._package()
            if (package_id is not None and package.id != package_id) or (expected_revision is not None and package.revision != expected_revision):
                raise PackageConflict("Package changed before settings update.")
            retrieval = replace(package.retrieval, **{k: changes[k] for k in RetrievalSettings.__dataclass_fields__ if k in changes}).normalized()
            embedding_changes = {k: changes[k] for k in EmbeddingSpec.__dataclass_fields__ if k in changes}
            if "prefix_scheme" in changes:
                for key in ("chunk_prefix", "query_prefix"):
                    embedding_changes.setdefault(key, None)
            embedding = replace(package.embedding, **embedding_changes)
            if "context_tokens" in embedding_changes:
                embedding = replace(embedding, context_tokens=embedding_context_tokens(embedding))
            if "chunk_size_tokens" in embedding_changes or "chunk_overlap_tokens" in embedding_changes:
                embedding = replace(embedding,
                    chunk_size_tokens=embedding_changes.get("chunk_size_tokens", package.embedding.chunk_size_tokens if package.embedding.chunk_size_tokens is not None else 512),
                    chunk_overlap_tokens=embedding_changes.get("chunk_overlap_tokens", package.embedding.chunk_overlap_tokens if package.embedding.chunk_overlap_tokens is not None else 50))
                chunking = embedding.token_chunking()
                if chunking is None:
                    raise ValueError("Choose a token chunk size and overlap before applying.")
                size, overlap = chunking
                embedding = replace(embedding, chunk_size_tokens=size, chunk_overlap_tokens=overlap)
            embedding_changed = embedding.fingerprint() != package.embedding.fingerprint()
            usage = UsageSettings.preset(changes["usage_mode"]) if "usage_mode" in changes else package.usage
            usage = replace(usage, **{k: changes[k] for k in UsageSettings.__dataclass_fields__ if k in changes}).normalized()
            sources = package.sources
            if embedding_changed:
                sources = tuple(replace(s, status="pending", revision=s.revision+1, pending_operation="reembed" if s.snapshot_id else "import") for s in sources)
            if retrieval != package.retrieval or embedding != package.embedding or usage != package.usage:
                self.library.update(replace(package, retrieval=retrieval, embedding=embedding, usage=usage, sources=sources), expected_revision=package.revision)
            if "enabled" in changes:
                self.settings["enabled"] = bool(changes["enabled"])
            requested = embedding_changed or (self._indexing_requested and "enabled" not in changes)
            self._select(package.id, check_model=embedding_changed, index_requested=requested)
        self._save_settings()

    def add_files(self, paths):
        with self._lock:
            self._ensure_writable()
            package = self._package()
            sources = list(package.sources)
            seen = {path_key(s.path) for s in sources}
            for raw in paths or ():
                path = str(raw or "").strip()
                if path and path_key(path) not in seen:
                    if Path(path).suffix.casefold() not in indexer.ALLOWED_EXTENSIONS:
                        raise ValueError(f"Unsupported document type: {Path(path).suffix}")
                    sources.append(SourceRecord(str(uuid4()), path))
                    seen.add(path_key(path))
            if tuple(sources) != package.sources:
                self.library.update(replace(package, sources=tuple(sources)), expected_revision=package.revision)
                self._select(package.id, index_requested=True)
        self._save_settings()

    def remove_files(self, paths):
        selected = {path_key(p) for p in paths or ()}
        with self._lock:
            self._ensure_writable()
            package = self._package()
            self.library.update(replace(package, sources=tuple(s for s in package.sources if path_key(s.path) not in selected)), expected_revision=package.revision)
            self._select(package.id, index_requested=self._indexing_requested)
        self._save_settings()

    def clear_files(self):
        self._ensure_writable()
        self.remove_files([s.path for s in self._package().sources])

    def set_source_enabled(self, source_id, enabled):
        with self._lock:
            self._ensure_writable()
            package = self._package()
            if not any(s.id == source_id for s in package.sources):
                raise KeyError("Unknown document source.")
            sources = []
            for source in package.sources:
                if source.id != source_id:
                    sources.append(source)
                    continue
                retry = bool(enabled) and not source.enabled and source.status != "ready"
                sources.append(replace(source, enabled=bool(enabled), revision=source.revision+1,
                    status="pending" if retry else source.status,
                    pending_operation=("reembed" if source.snapshot_id else "import") if retry else source.pending_operation,
                    error="" if retry else source.error))
            sources = tuple(sources)
            self.library.update(replace(package, sources=sources), expected_revision=package.revision)
            self._select(package.id, index_requested=bool(enabled) or self._indexing_requested)

    def refresh_sources(self, source_ids):
        with self._lock:
            self._ensure_writable()
            package = self._package()
            selected = set(source_ids)
            if not selected.issubset({s.id for s in package.sources}):
                raise KeyError("Unknown document source.")
            sources = tuple(replace(s,pending_operation="refresh",error="",revision=s.revision+1) if s.id in selected and s.enabled else s for s in package.sources)
            self.library.update(replace(package,sources=sources),expected_revision=package.revision)
            self._select(package.id, index_requested=True)

    def build_index(self):
        with self._lock:
            self._ensure_writable()
            package = self._package()
            sources = tuple(replace(s,pending_operation="reembed" if s.snapshot_id else "import",error="",revision=s.revision+1) if s.enabled else s for s in package.sources)
            self.library.update(replace(package,sources=sources),expected_revision=package.revision)
            self._select(package.id, index_requested=True)
        return {**self.status_snapshot(), "status": "Document indexing queued for idle time."}

    def refresh_models(self):
        self._model_refresh_pending = True
        self._load_wake.set()
        return {"accepted": True, "status": "Model catalog refresh queued."}

    def collect_chat_context(self, payload):
        # A saved Persona may opt in/out for its own reply without switching
        # global recall, activating indexing, or changing the selected package.
        override = payload.get("_persona_document_memory")
        def enabled():
            return override if isinstance(override, bool) else bool(self.settings.get("enabled"))

        if not enabled() or self._closed:
            return None
        explicit = payload.get("_persona_document_package_id")
        package_id = explicit.strip() if isinstance(explicit, str) and explicit.strip() else self.settings.get("package_id", "")
        if not package_id or (not explicit and not self._scope.package_id):
            return None
        messages = payload.get("messages") or payload.get("history") or []
        if not messages and payload.get("query"):
            messages = [{"role": "user", "content": str(payload["query"])}]
        # Selection changes affect future inherited requests only. Both the
        # package revision and the chat session are frozen for this request.
        session = (self._session, self._session_generation())
        return self.package_readers.collect(package_id, messages,
            consumer=str(payload.get("request_kind") or "addon"), session=session,
            current_session=lambda: (self._session, self._session_generation()),
            enabled=lambda: not self._closed and enabled())

    def test_query(self, query):
        with self._lock:
            if not self.library.read_only and not self._indexing_requested and self._availability["state"] == "ready":
                self._indexing_requested = True
                self.scheduler.activate(self._scope)
                self._queue_pending(self._package())
        scope = self._scope
        result = self.retriever.collect([{"role": "user", "content": str(query or "")}], consumer="test_search", cancelled=lambda: self._closed or self._scope != scope)
        return {"query": str(query or ""), "context": result.context, "match_count": result.debug["matches"], "debug": result.debug, "status": f"Test search returned {result.debug['matches']} matching note(s)."}

    def status_snapshot(self):
        with self._lock:
            try:
                package = self._package()
            except (KeyError, ValueError):
                package = None
            generation = self._generation
            indexed_ids = {c.source_id for c in generation.chunks} if generation else set()
            indexing = self.scheduler.snapshot()
            sources = []
            for source in package.sources if package else ():
                indexed = source.id in indexed_ids and source.status == "ready"
                meta = self._snapshot_meta.get(source.id) or {}
                error = indexing.get("errors", {}).get(source.id, "") or source.error
                state = indexing["state"] if indexing.get("source_id") == source.id else ("ready" if indexed else "waiting for idle")
                if error:
                    state = "refresh failed; using saved version" if indexed else "failed"
                elif indexed and indexing.get("source_id") == source.id:
                    state += "; using saved version"
                sources.append({**asdict(source), "title": Path(source.path).name, "indexed": indexed, "included": indexed and source.enabled, "saved_at": meta.get("saved_at", ""), "state": state, "error": error})
            count = len(generation.chunks) if generation else 0
            availability_status = self._availability.get("message", "")
            if not package:
                availability_status = "No knowledge package selected."
            elif self._availability["state"] == "ready":
                availability_status = f"Selected files: {len(sources)}. Search memory notes: {count}. {indexing['state']}."
            recovery_error = self.library.recovery_error
            availability = dict(self._availability)
            if recovery_error:
                availability_status = recovery_error
                availability.update(state="recovery_required", message=recovery_error)
            return {"file_count": len(sources), "chunk_count": count, "built_at": max((s["saved_at"] for s in sources), default=""), "status": availability_status, "packages": [package_row(p) for p in self.library.list_packages()], "packageStates": self.package_readers.snapshot(), "activePackageId": package.id if package else "", "package_revision": package.revision if package else 0, "sources": sources, "indexing": indexing, "retrieval": self.retriever.snapshot(), "settings": self.export_state(), "models": list(self._models), "error": recovery_error or self._error or indexing.get("error", ""), "revision": self._scope.activation_revision,
                    "modelAvailability": availability,
                    "recovery": self.library.recovery_snapshot(),
                    "session_generation": self._scope.session_generation,
                    "usagePresets": [{"id": mode, "name": name, **asdict(UsageSettings.preset(mode))} for mode, name in (("reference", "Reference documents"), ("integrated", "Integrated knowledge"))]}

    def _current_settings(self):
        return self.export_state()

    def _save_settings(self):
        if self.library.read_only:
            return
        try:
            self._ensure_writable()
        except RuntimeError:
            if self.library.read_only:
                return
            raise
        indexer.save_settings(self.storage, self.export_state())

    def close(self):
        self._closed = True
        self._load_wake.set()
        self.retriever.close()
        self.package_readers.close()
        self.scheduler.close()
        if self._load_worker is not None:
            self.tasks.cancel_worker(self._load_worker, "document addon closed")
            self.tasks.join_worker(self._load_worker)
