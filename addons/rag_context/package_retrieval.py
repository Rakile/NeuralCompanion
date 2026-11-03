"""Lazy, request-scoped readers for shared immutable knowledge packages.

The editor's selected package owns indexing. These readers only open published
indexes, and never change selection, settings, source records or index files.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import threading
from uuid import uuid4
from weakref import WeakValueDictionary

from core.runtime.document_context import DocumentContextTicket
from .models import DocumentScope
from .retrieval import DocumentRetriever


def package_row(package):
    """Catalog readiness describes stored metadata, not embedding-server health."""
    indexed = sum(bool(s.snapshot_id and s.status == 'ready') for s in package.sources) if package.generation_id else 0
    enabled = [s for s in package.sources if s.enabled]
    if not enabled:
        state, status = 'empty', 'No enabled documents in this package.'
    elif any(s.status == 'ready' and s.snapshot_id for s in enabled) and package.generation_id:
        state, status = 'ready', 'Saved document index available.'
    elif any(s.status == 'pending' or s.pending_operation for s in enabled):
        state, status = 'pending', 'Documents are waiting for indexing.'
    else:
        state, status = 'unavailable', 'No ready saved document index. Index this package before recalling it.'
    return {'id': package.id, 'name': package.name, 'document_count': len(package.sources),
            'indexed_document_count': indexed, 'state': state, 'status': status}


@dataclass
class _SharedGeneration:
    generation: object
    statistics_lock: object = field(default_factory=threading.Lock)
    corpus: object = None


@dataclass
class _GenerationLoad:
    done: object = field(default_factory=threading.Event)
    shared: object = None
    error: object = None


@dataclass
class _Reader:
    key: tuple
    retriever: DocumentRetriever
    scope: DocumentScope
    generation: object
    shared: _SharedGeneration
    references: int = 0


class PackageReaders:
    def __init__(self, *, library, snapshots, embeddings, clock, tasks=None, max_idle=4):
        self.library, self.snapshots = library, snapshots
        self.embeddings, self.clock, self.tasks = embeddings, clock, tasks
        self.max_idle = max_idle
        self._lock = threading.RLock()
        self._readers = OrderedDict()
        self._generations = OrderedDict()
        self._generation_refs = WeakValueDictionary()
        self._generation_loads = {}
        self._states = OrderedDict()
        self._activation = 0
        self._closed = False

    def snapshot(self):
        with self._lock:
            return {key: {**value, 'active': any(r.key[0] == key and r.references for r in self._readers.values())}
                    for key, value in self._states.items()}

    def _status(self, package_id, **value):
        with self._lock:
            self._states[package_id] = value
            self._states.move_to_end(package_id)
            while len(self._states) > 64:
                self._states.popitem(last=False)

    def _shared_generation(self, package):
        key = (package.id, package.generation_id, package.embedding.fingerprint())
        with self._lock:
            if self._closed:
                raise ValueError('Document readers are closed.')
            shared = self._generations.get(key)
            if shared is None:
                # An active lease can outlive the bounded warm cache. Reuse its
                # immutable generation instead of reopening another vector copy.
                shared = self._generation_refs.get(key)
            if shared is not None:
                self._cache_generation(key, shared)
                return shared
            loading = self._generation_loads.get(key)
            owner = loading is None
            if owner:
                loading = _GenerationLoad()
                self._generation_loads[key] = loading
        if owner:
            try:
                generation = self.snapshots.load(package)
                if generation is None:
                    raise ValueError('No compatible saved index is ready for this package.')
                shared = _SharedGeneration(generation)
                with self._lock:
                    if self._closed:
                        raise ValueError('Document readers are closed.')
                    loading.shared = shared
                    self._cache_generation(key, shared)
            except Exception as exc:
                loading.error = exc
            finally:
                with self._lock:
                    self._generation_loads.pop(key, None)
                loading.done.set()
        else:
            # Waiting never owns the pool or library mutex, so catalog polling
            # and unrelated packages remain responsive during cold disk IO.
            loading.done.wait()
        if loading.error is not None:
            raise loading.error
        return loading.shared

    def _cache_generation(self, key, shared):
        # Caller owns the pool lock. Active readers retain their strong refs.
        self._generation_refs[key] = shared
        self._generations[key] = shared
        self._generations.move_to_end(key)
        while len(self._generations) > self.max_idle:
            self._generations.popitem(last=False)

    def _acquire(self, package, session):
        key = (package.id, package.revision, package.generation_id, session)
        with self._lock:
            if self._closed:
                raise ValueError('Document readers are closed.')
            # A reader is exclusively leased for a request. Concurrent members
            # using the same package also get independent nonqueued workers.
            reader = next((r for r in self._readers.values() if r.key == key and not r.references and r.retriever._pending is None), None)
            if reader is None:
                # Retrieval/usage/source edits keep the immutable vectors and
                # compatible query embeddings while invalidating old tickets.
                reader = next((r for r in self._readers.values() if r.key[0] == package.id
                    and r.key[2:] == key[2:] and r.generation.fingerprint == package.embedding.fingerprint()
                    and not r.references and r.retriever._pending is None), None)
                if reader is not None:
                    self._readers.pop(reader.scope.activation_revision)
                    self._activation += 1
                    reader.key = key
                    reader.scope = DocumentScope(1, session[1], package.id, package.revision, self._activation)
                    reader.retriever.invalidate(reader.scope)
                    reader.retriever.activate(reader.scope, reader.generation,
                        frozenset(s.id for s in package.sources if s.enabled and s.status == 'ready'), package.retrieval,
                        embedding=package.embedding, package_name=package.name, usage=package.usage)
                    self._readers[reader.scope.activation_revision] = reader
            if reader is not None:
                reader.references += 1
                self._readers.move_to_end(reader.scope.activation_revision)
                return reader
            self._activation += 1
            scope = DocumentScope(1, session[1], package.id, package.revision, self._activation)
        # Disk checks and corpus statistics never hold the pool/library locks:
        # the UI can keep reading cheap catalog metadata during a cold query.
        shared = self._shared_generation(package)
        generation = shared.generation
        retriever = DocumentRetriever(embeddings=self.embeddings, clock=self.clock, tasks=self.tasks)
        try:
            # DocumentRetriever's corpus cache already shares its read-only
            # lexical tables on activation. Seed it once per generation, under
            # a generation-local lock, while each reader keeps its own scope,
            # source filter, request queue and query/result caches.
            with shared.statistics_lock:
                cache_key = (generation.package_id, generation.id, generation.fingerprint)
                if shared.corpus is not None:
                    retriever._corpus_cache[cache_key] = shared.corpus
                retriever.activate(scope, generation, frozenset(s.id for s in package.sources if s.enabled and s.status == 'ready'),
                    package.retrieval, embedding=package.embedding, package_name=package.name, usage=package.usage)
                shared.corpus = retriever._corpus
            with self._lock:
                if self._closed:
                    raise ValueError('Document readers are closed.')
                reader = _Reader(key, retriever, scope, generation, shared, references=1)
                self._readers[scope.activation_revision] = reader
                return reader
        except Exception:
            retriever.close()
            raise

    def _release(self, reader):
        retired = []
        with self._lock:
            reader.references -= 1
            idle = [r for r in self._readers.values() if not r.references]
            for old in idle[:max(0, len(idle) - self.max_idle)]:
                self._readers.pop(old.scope.activation_revision)
                retired.append(old)
        # Joining workers must never hold the package library lock.
        for old in retired:
            old.retriever.close()

    def collect(self, package_id, messages, *, consumer, session, current_session, enabled):
        request_id = str(uuid4())
        def unavailable(message, state='unavailable', name=''):
            self._status(package_id, state=state, status=message, warning=message, active=False)
            return {'context': '', 'debug': {'addon': 'nc.rag_context', 'request_id': request_id,
                    'consumer': consumer, 'package_id': package_id, 'package_name': name,
                    'mode': 'none', 'matches': 0, 'sources': [], 'warning': message, 'fallback_reason': message}}
        try:
            package = self.library.get(package_id)
        except (KeyError, ValueError):
            return unavailable('Selected knowledge package is unavailable. Choose an existing package.')
        row = package_row(package)
        if row['state'] != 'ready':
            return unavailable(row['status'], row['state'], package.name)
        def current():
            if self._closed or current_session() != session or not enabled():
                return False
            try:
                return self.library.get(package_id) == package
            except (KeyError, ValueError):
                return False
        if not current():
            return None
        try:
            reader = self._acquire(package, session)
        except Exception as exc:
            return unavailable(f'Saved document index is unavailable: {exc}', name=package.name)
        try:
            self._status(package_id, state='ready', status='Searching saved document index.', warning='', active=True)
            result = reader.retriever.collect(messages, consumer=consumer, cancelled=lambda: not current())
            if not current():
                self._status(package_id, state='unavailable', status='Package or session changed during document recall.',
                             warning='Package or session changed during document recall.', active=False)
                return None
            warning = str(result.debug.get('fallback_reason') or '')
            self._status(package_id, state='ready', status=warning or 'Document recall complete.', warning=warning, active=False)
            ticket = DocumentContextTicket(package_id, reader.scope.activation_revision, str(result.debug['request_id']), current)
            return {'context': result.context, 'debug': {'addon': 'nc.rag_context', **result.debug, 'warning': warning},
                    '_nc_document_ticket': ticket}
        finally:
            self._release(reader)

    def close(self):
        with self._lock:
            self._closed = True
            readers, self._readers = tuple(self._readers.values()), OrderedDict()
            self._generations.clear()
            self._generation_refs.clear()
            for loading in self._generation_loads.values():
                loading.error = ValueError('Document readers are closed.')
                loading.done.set()
            self._generation_loads.clear()
        for reader in readers:
            reader.retriever.close()
