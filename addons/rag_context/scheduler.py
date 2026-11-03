"""Single owned indexing worker with continuous idle admission and revision fences."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4
import numpy as np

from core.runtime.document_memory import idle_reason, embedding_prefixes, embedding_context_tokens, DocumentEmbeddingBusy
from .extraction import extract_snapshot, snapshot_chunks, next_token_chunk
from .models import IndexGeneration
from .packages import PackageConflict


class DocumentIndexScheduler:
    def __init__(self, *, library, snapshots, host, tasks, clock=time.monotonic):
        self.library, self.snapshots, self.host, self.tasks, self.clock = library, snapshots, host, tasks, clock
        self._scope = None
        self._jobs = OrderedDict()
        self._parked = {}
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._paused = False
        self._idle_since = None
        self._prepare_pending = False
        self._prepared = None
        self._errors = {}
        self._status = {"state": "idle", "stage": "idle", "busy_reason": "", "error": "", "completed": 0, "total": 0,
                        "processed_chars": 0, "total_chars": 0}
        self.on_publish = None
        self._worker = tasks.spawn("document-index", self._run) if tasks is not None else None

    def activate(self, scope):
        package = self.library.get(scope.package_id) if scope is not None else None
        with self._lock:
            if self._scope is not None:
                self._parked[self._scope.package_id] = OrderedDict(
                    (key, {**job, "vectors": list(job["vectors"]), "chunks":list(job["chunks"]) if isinstance(job["chunks"],list) else job["chunks"], "chunk_state":dict(job['chunk_state'])}) for key,job in self._jobs.items())
            self._scope = scope
            self._jobs = OrderedDict()
            for key,job in self._parked.pop(scope.package_id, {}).items() if scope is not None else ():
                source = next((s for s in package.sources if s.id == key), None)
                if source is not None and source.enabled and source == job["source"]:
                    self._jobs[key] = {**job, "scope": scope, "vectors": list(job["vectors"]), "chunks":list(job["chunks"]) if isinstance(job["chunks"],list) else job["chunks"], "chunk_state":dict(job['chunk_state'])}
            self._idle_since = None
            self._prepare_pending = scope is not None
            self._prepared = None
            self._status.update(state="waiting for idle" if scope else "idle", stage="idle", error="", completed=0, total=0,
                                processed_chars=0, total_chars=0)
            self._errors.clear()
        self._wake.set()

    def enqueue(self, source_id, *, kind):
        if kind not in {"import", "refresh", "reembed"}:
            raise ValueError("Unknown document indexing operation.")
        scope = self._scope
        if scope is None or self._closed:
            return
        package = self.library.get(scope.package_id)
        source = next(s for s in package.sources if s.id == source_id)
        with self._lock:
            if self._scope != scope or self._closed:
                return
            if not source.enabled:
                return
            existing = self._jobs.get(source_id)
            if existing and existing["source"] == source and existing["kind"] == kind:
                return
            self._jobs[source_id] = {"scope": self._scope, "source": source, "kind": kind,
                                     "snapshot": None, "chunks": None, "vectors": [], "snapshot_id": source.snapshot_id,
                                     "chunk_state": {"block":0,"start":0,"ordinal":0}, "chunking_done":False}
            self._errors.pop(source_id, None)
            self._prepare_pending = True
            self._status.update(error="", state="waiting for idle")
        self._wake.set()

    def set_paused(self, paused):
        with self._lock:
            self._paused = bool(paused)
            self._idle_since = None
        self._wake.set()

    def snapshot(self):
        with self._lock:
            return {**self._status, "paused": self._paused, "pending": len(self._jobs),
                    "errors": dict(self._errors),
                    "source_id": next(iter(self._jobs), "")}

    def cancel(self, reason):
        with self._lock:
            self._jobs.clear()
            self._parked.clear()
            self._scope = None
            self._prepare_pending = False
            self._status.update(state="cancelled", busy_reason=str(reason))
        self._wake.set()

    def close(self):
        self._closed = True
        self.cancel("addon closed")
        if self._worker is not None:
            self.tasks.cancel_worker(self._worker, "document addon closed")
            self.tasks.join_worker(self._worker)

    def _run(self, token):
        while not self._closed and not token.cancelled:
            self._wake.wait(.1)
            self._wake.clear()
            self.run_slice()

    def _current(self, job):
        if self._closed or self._scope != job["scope"]:
            return False
        try:
            package = self.library.get(job["scope"].package_id)
            source = next((s for s in package.sources if s.id == job["source"].id), None)
            return (package.revision == job["scope"].package_revision and source == job["source"] and source.enabled)
        except (KeyError, ValueError):
            return False

    def _eligible(self):
        state = self.host.idle_snapshot() if self.host is not None else {"known": False}
        reason = idle_reason(state)
        if self._scope is not None and state.get("session_generation") != self._scope.session_generation:
            reason = "conversation changed"
        if self._paused:
            reason = "indexing paused"
        if reason:
            self._idle_since = None
            self._status.update(state="paused for reply/audio", busy_reason=reason)
            return False
        if self._idle_since is None:
            self._idle_since = self.clock()
        self._status["busy_reason"] = ""
        if self.clock()-self._idle_since < 1:
            self._status["state"] = "waiting for idle"
            return False
        return not self._closed

    def _finish_source_state(self, job, *, error=""):
        with self.library.lock:
            if not self._current(job):
                return
            package = self.library.get(job["scope"].package_id)
            source = job["source"]
            changed = replace(source, pending_operation="", error=error,
                              status=("ready" if source.status == "ready" else "failed") if error else source.status)
            updated = self.library.update(replace(package, sources=tuple(changed if s.id == source.id else s for s in package.sources)), expected_revision=package.revision)
            with self._lock:
                if self._jobs.get(source.id) is job:
                    self._jobs.pop(source.id, None)
                if self._scope == job["scope"]:
                    self._scope = replace(self._scope, package_revision=updated.revision)
                    for pending in self._jobs.values():
                        pending["scope"] = self._scope
        if callable(self.on_publish):
            self.on_publish(package.id)

    def _extract(self, job, cancelled):
        if self.tasks is None:
            return extract_snapshot(Path(job["source"].path), cancelled=cancelled)
        package_id = job["scope"].package_id
        result = self.library.package_dir(package_id) / "staging" / (str(uuid4())+".json")
        result.parent.mkdir(parents=True, exist_ok=True)
        helper = Path(__file__).with_name("extraction_worker.py")
        process = subprocess.Popen([sys.executable, "-B", str(helper), job["source"].path, str(result)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.tasks.register_process("document-extraction", process)
            while process.poll() is None:
                if cancelled():
                    raise InterruptedError("Document extraction paused for activity.")
                self._wake.wait(.05)
                self._wake.clear()
            value = json.loads(result.read_text(encoding="utf-8"))
            if not value.get("ok"):
                raise ValueError(str(value.get("error") or "Extraction failed."))
            return value["snapshot"]
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            result.unlink(missing_ok=True)

    def run_slice(self):
        """One scheduling slice; production calls this only from the owned worker."""
        with self._lock:
            scope = self._scope
            if scope is None or not self._eligible():
                return
            job = next(iter(self._jobs.values()), None)
            preparation = self._prepare_pending
        try:
            package = self.library.get(scope.package_id)
            cancelled = lambda: self._closed or self._scope != scope or not self._eligible()
            if preparation:
                if self._prepared != package.embedding.fingerprint():
                    self._status.update(state="preparing local model", stage="preparing")
                    outcome = self.host.embeddings.prepare(package.embedding, cancelled=cancelled)
                    if not outcome.get("ok"):
                        if cancelled():
                            return
                        if outcome.get("retryable"):
                            self._status["state"] = "waiting for embedding provider"
                            return
                        raise RuntimeError(str(outcome.get("warning") or "Document model unavailable."))
                    with self._lock:
                        if self._scope != scope or self._closed or not self._eligible():
                            return
                        self._prepared = package.embedding.fingerprint()
                with self._lock:
                    if self._scope != scope or self._closed:
                        return
                    self._prepare_pending = False
                return
            if job is None:
                self._status.update(state="ready", stage="ready")
                return
            if not self._current(job):
                with self._lock:
                    if self._jobs.get(job["source"].id) is job:
                        self._jobs.pop(job["source"].id, None)
                return
            cancelled = lambda: not self._current(job) or not self._eligible()
            source = job["source"]
            if job["snapshot"] is None:
                self._status.update(state="extracting" if job["kind"] != "reembed" else "reading saved snapshot",
                                    stage="extracting", completed=0, total=0, processed_chars=0, total_chars=0)
                saved = self.snapshots.read_snapshot(package.id, source)
                snapshot = saved if job["kind"] == "reembed" and saved else self._extract(job, cancelled)
                if cancelled():
                    return
                if (saved and snapshot["content_hash"] == saved["content_hash"] and source.generation_id
                        and source.status == "ready" and saved.get("embedding_fingerprint") == package.embedding.fingerprint()
                        and job["kind"] != "reembed"):
                    self._finish_source_state(job)
                    self._status.update(state="ready (unchanged snapshot)", stage="ready")
                    return
                job["snapshot"] = snapshot
                job["snapshot_id"] = self.snapshots.stage(package.id, source, snapshot, package.embedding.fingerprint())
                if package.embedding.token_chunking() is None:
                    job["chunks"] = snapshot_chunks(snapshot, source, embedding_context_tokens(package.embedding) - len(embedding_prefixes(package.embedding)[0].encode("utf-8")))
                    job["chunking_done"] = True
                else:
                    job["chunks"] = []
                return
            if not job['chunking_done']:
                offsets = job.get('block_offsets')
                if offsets is None:
                    offsets = [0]
                    for block in job['snapshot']['blocks']:
                        offsets.append(offsets[-1]+len(block['text']))
                    job['block_offsets'] = tuple(offsets)
                cursor = job['chunk_state']
                self._status.update(state='splitting document into model tokens', stage='splitting',
                                    completed=len(job['chunks']), total=0, total_chars=offsets[-1],
                                    processed_chars=offsets[cursor['block']]+cursor['start'])
                with self.host.embeddings.token_counter(package.embedding,cancelled=cancelled,
                        register_process=self.tasks.register_process if self.tasks else None) as count:
                    while not cancelled():
                        result = next_token_chunk(job['snapshot'],source,package.embedding,job['chunk_state'],count_tokens=count)
                        if cancelled():raise InterruptedError('Document token counting paused.')
                        if result is None:
                            job['chunking_done'] = True
                            break
                        chunk, state = result
                        job['chunks'].append(chunk)
                        job['chunk_state'] = state
                        self._status.update(completed=len(job['chunks']),
                                            processed_chars=offsets[state['block']]+state['start'])
                return
            chunks = tuple(job["chunks"])
            self._status.update(state="embedding", stage="embedding", completed=len(job["vectors"]), total=len(chunks))
            if len(job["vectors"]) < len(chunks):
                chunk = chunks[len(job["vectors"])]
                vector = self.snapshots.cached_embedding(chunk.content_hash, package.embedding.fingerprint())
                if vector is None:
                    vector = self.host.embeddings.embed(chunk.text, spec=package.embedding, purpose="document", deadline=time.monotonic()+30, cancelled=cancelled)
                    if cancelled():
                        return
                    self.snapshots.cache_embedding(chunk.content_hash, package.embedding.fingerprint(), vector)
                job["vectors"].append(vector)
                self._status['completed'] = len(job['vectors'])
                return
            if cancelled():
                return
            self._status.update(state="saving index", stage="publishing")
            old = self.snapshots.load(package)
            retained = [i for i,c in enumerate(old.chunks) if c.source_id != source.id and any(s.id == c.source_id for s in package.sources)] if old else []
            all_chunks = tuple(old.chunks[i] for i in retained) + chunks if old else chunks
            all_vectors = [old.vectors[i] for i in retained] + job["vectors"] if old else job["vectors"]
            generation = IndexGeneration(package.id, str(uuid4()), package.embedding.fingerprint(), all_chunks, np.asarray(all_vectors, dtype=np.float32))
            ready = replace(source, snapshot_id=job["snapshot_id"], generation_id=generation.id, status="ready", error="", pending_operation="")
            sources = tuple(ready if s.id == source.id else s for s in package.sources)
            self.snapshots.publish(package.id, generation, expected_revision=package.revision, sources=sources, is_current=lambda: self._current(job) and self._eligible())
            updated = self.library.get(package.id)
            with self._lock:
                if self._jobs.get(source.id) is job:
                    self._jobs.pop(source.id, None)
                if self._scope == scope:
                    self._scope = replace(scope, package_revision=updated.revision)
                    for pending in self._jobs.values():
                        pending["scope"] = self._scope
            if callable(self.on_publish):
                self.on_publish(package.id)
        except DocumentEmbeddingBusy:
            self._status["state"] = "waiting for embedding provider"
        except (InterruptedError, PackageConflict):
            # Activity can resume the same staged work; ownership edits discard it.
            self._idle_since = None
        except Exception as exc:
            if job is not None and self._current(job) and not self._eligible():
                self._idle_since = None
                return
            failure = str(exc)[:1000]
            if job is not None and self._current(job):
                try:
                    self._finish_source_state(job, error=failure)
                except Exception as state_error:
                    failure += f"; could not save failure state: {state_error}"
            with self._lock:
                if self._scope is None or self._scope.activation_revision != scope.activation_revision:
                    return
                self._prepare_pending = False
                if job is not None and self._jobs.get(job["source"].id) is job:
                    self._jobs.pop(job["source"].id, None)
                if job is not None:
                    self._errors[job["source"].id] = failure
                self._status.update(state="failed", error=failure)
