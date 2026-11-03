"""Finite local document capabilities, independent of chat-memory databases."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
import ipaddress
import math
import threading
import time
from typing import Literal, Protocol
from urllib.parse import urlsplit
import urllib.request
from uuid import uuid4

BUSY_FIELDS = ("active_turns", "interaction_pending", "recording", "active_captures",
               "active_speech", "speech_warmups", "current_playback", "queued_playback",
               "playback_paused", "playback_stopping", "avatar_speaking", "external_active")


def idle_reason(snapshot: Mapping[str, object]) -> str:
    if not snapshot.get("known") or any(key not in snapshot for key in BUSY_FIELDS):
        return "Runtime activity unavailable"
    for key in BUSY_FIELDS:
        if snapshot[key]:
            return "playback" if "playback" in key else key.replace("_", " ")
    return ""


class DocumentActivityLease:
    def __init__(self, close: Callable):
        self._close = close
        self._closed = False
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class DocumentMemoryRuntimePort:
    def __init__(self, *, embeddings, activity: Callable, owner_is_open: Callable = lambda: True,
                 leases=None, lock=None):
        self.embeddings = embeddings
        self._activity = activity
        self._owner_open = owner_is_open
        self._leases = leases if leases is not None else {}
        self._lock = lock if lock is not None else threading.Lock()

    def bind(self, *, owner_is_open: Callable):
        return DocumentMemoryRuntimePort(embeddings=_OwnedDocumentEmbeddings(self.embeddings,owner_is_open), activity=self._activity,
                                        owner_is_open=owner_is_open, leases=self._leases, lock=self._lock)

    def begin_activity(self, consumer: str, key: str) -> DocumentActivityLease:
        if not self._owner_open():
            raise RuntimeError("Document activity owner is closed.")
        token = str(uuid4())
        with self._lock:
            self._leases[token] = (self._owner_open, str(consumer), str(key))
        def release():
            with self._lock:
                self._leases.pop(token, None)
        return DocumentActivityLease(release)

    def idle_snapshot(self) -> Mapping[str, object]:
        try:
            value = dict(self._activity())
            value["known"] = bool(value.get("known") and self._owner_open())
            with self._lock:
                for token, (is_open, _, _) in tuple(self._leases.items()):
                    if not is_open():
                        self._leases.pop(token, None)
                value["external_active"] = len(self._leases)
            return value
        except Exception:
            return {"known": False}


class _OwnedDocumentEmbeddings:
    def __init__(self, embeddings, owner_is_open):
        self._embeddings, self._owner_open = embeddings, owner_is_open

    def _require_open(self):
        if not self._owner_open():
            raise RuntimeError("Document embedding owner is closed.")

    def list_models(self, base_url):
        self._require_open()
        return self._embeddings.list_models(base_url)

    def prepare(self, spec, *, cancelled):
        self._require_open()
        return self._embeddings.prepare(spec,cancelled=lambda:not self._owner_open() or cancelled())

    def embed(self, text, *, spec, purpose, deadline, cancelled):
        self._require_open()
        return self._embeddings.embed(text,spec=spec,purpose=purpose,deadline=deadline,cancelled=lambda:not self._owner_open() or cancelled())

    def token_counter(self, spec, *, cancelled, register_process=None):
        self._require_open()
        return self._embeddings.token_counter(spec,cancelled=lambda:not self._owner_open() or cancelled(),register_process=register_process)


def build_document_activity_reader(*, lifecycle, conversation, turns, speech_input,
                                   speech_output, playback, avatar, interaction, activity):
    def read():
        if activity is None:
            return {"known": False}
        flags = tuple(activity())
        if len(flags) != 3:
            return {"known": False}
        playback_activity = getattr(playback, 'activity_snapshot', None)
        audio = playback_activity() if callable(playback_activity) else playback.snapshot()
        inputs, output, face = speech_input.snapshot(), speech_output.activity_snapshot(), avatar.snapshot()
        session = conversation.snapshot().session_generation
        return dict(known=True, run_id=str(lifecycle.run_id), session_generation=int(session.value),
                    active_turns=turns.has_active_turns(), interaction_pending=interaction.pending_count(),
                    recording=bool(flags[1]), active_captures=inputs.active_captures,
                    active_speech=output["active_speech"], speech_warmups=output["speech_warmups"],
                    current_playback=audio.current is not None, queued_playback=audio.next is not None,
                    playback_paused=audio.paused, playback_stopping=audio.stopping,
                    avatar_speaking=face.speaking)
    return read


class LocalEmbeddingSpec(Protocol):
    base_url: str
    model: str
    context_tokens: int
    prefix_scheme: str


def validate_local_url(url: str) -> str:
    value = str(url).strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
        local = host.casefold() == "localhost"
        if not local:
            local = ipaddress.ip_address(host).is_loopback
        if (parsed.scheme not in {"http", "https"} or not local or
                parsed.username is not None or parsed.password is not None or
                parsed.query or parsed.fragment or (port is not None and port < 1)):
            raise ValueError
    except ValueError as exc:
        raise ValueError("Document embeddings require a loopback HTTP endpoint without credentials.") from exc
    return value


class LocalOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_local_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def embedding_context_tokens(spec):
    value = spec.context_tokens
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            or value < 256 or int(value) != value):
        raise ValueError("Embedding context must be a whole number of at least 256 tokens.")
    return int(value)


def embedding_prefixes(spec):
    context_tokens = embedding_context_tokens(spec)
    presets = {"bge-m3": ("", ""), "nomic": ("search_document: ", "search_query: "),
               "qwen3": ("", "Instruct: Given a question, retrieve relevant passages that answer the question\nQuery: "),
               "custom": ("", "")}
    if spec.prefix_scheme not in presets:
        raise ValueError("Unknown embedding preprocessing.")
    defaults = presets[spec.prefix_scheme]
    prefixes = tuple(default if getattr(spec, key, None) is None else getattr(spec, key)
                     for key, default in zip(("chunk_prefix", "query_prefix"), defaults))
    for prefix in prefixes:
        if not isinstance(prefix, str) or len(prefix) > 2048 or "\x00" in prefix:
            raise ValueError("Embedding prefixes must be text of at most 2,048 characters.")
        if len(prefix.encode("utf-8")) + 128 > context_tokens:
            raise ValueError("Embedding prefix leaves too little room for text. Increase model context or shorten the prefix.")
    return prefixes


class DocumentEmbeddingBusy(RuntimeError):
    pass


def _key(spec):
    return (validate_local_url(spec.base_url), str(spec.model), embedding_context_tokens(spec), embedding_prefixes(spec))


class LocalDocumentEmbeddingPort:
    """One nonqueued I/O slot. Caller deadlines are enforced by the retriever."""
    def __init__(self, *, request_json: Callable, clock: Callable = time.monotonic, native_base_url=None):
        self._request = request_json
        self._clock = clock
        self._slot = threading.Lock()
        self._prepared: dict[tuple, Mapping] = {}
        self._dimensions: dict[tuple, int] = {}
        self._native_base = native_base_url or self._default_native_base

    def resource_busy(self):
        return self._slot.locked() and getattr(self, '_resource_owner', None) != threading.get_ident()

    @contextmanager
    def resource_maintenance(self):
        if not self._slot.acquire(blocking=False):
            raise DocumentEmbeddingBusy('Document memory is indexing or searching.')
        self._resource_owner = threading.get_ident()
        try:
            yield
        finally:
            self._resource_owner = None
            self._slot.release()

    def resource_endpoints(self):
        # A tuple copy does not perform provider I/O or prepare a model.
        return tuple(dict.fromkeys(key[0] for key in tuple(self._prepared)))

    def forget_resource(self, base_url, model):
        # Called with resource_maintenance held, so embeddings cannot race this.
        try:
            base = validate_local_url(base_url)
        except ValueError:
            return  # Document Memory never prepared remote endpoints.
        from .resource_sources import endpoint_key
        self._prepared = {key: value for key, value in self._prepared.items()
                          if not (endpoint_key(key[0]) == endpoint_key(base) and key[1] == model)}

    @staticmethod
    def _default_native_base(base):
        if base.endswith("/api/v1"):
            return base
        return base[:-3] + "/api/v1" if base.endswith("/v1") else base + "/api/v1"

    def _catalog(self, base_url):
        base = validate_local_url(base_url)
        native = self._native_base(base)
        data = self._request(native + "/models", timeout=8)
        if not isinstance(data, Mapping) or not isinstance(data.get("models"), list):
            raise ValueError("Invalid embedding model catalog response.")
        return tuple(item for item in data["models"] if isinstance(item, Mapping))

    @staticmethod
    def _is_embedding(item):
        return str(item.get("type", "")).casefold() in {"embedding", "embeddings", "embd"} or (not item.get("type") and bool((item.get("capabilities") or {}).get("embedding")))

    def list_models(self, base_url: str) -> tuple[Mapping[str, object], ...]:
        if not self._slot.acquire(blocking=False):
            raise DocumentEmbeddingBusy("Document embedding provider is busy.")
        try:
            return tuple(dict(item) for item in self._catalog(base_url) if self._is_embedding(item))
        finally:
            self._slot.release()

    @contextmanager
    def token_counter(self, spec, *, cancelled, register_process=None):
        from .document_tokenizer import token_counter_process
        key = _key(spec)
        if key not in self._prepared:
            raise RuntimeError('Document model must be prepared before token counting.')
        if not self._slot.acquire(blocking=False):
            raise DocumentEmbeddingBusy('Document embedding provider is busy.')
        try:
            with token_counter_process(spec,cancelled=cancelled,register_process=register_process) as count:
                yield count
        finally:
            self._slot.release()

    def prepare(self, spec: LocalEmbeddingSpec, *, cancelled: Callable) -> Mapping[str, object]:
        key = _key(spec)
        if cancelled():
            return {"ok": False, "warning": "Preparation cancelled."}
        if not self._slot.acquire(blocking=False):
            return {"ok": False, "retryable": True, "warning": "Document embedding provider is busy."}
        try:
            # Explicit preparation revalidates a model that another consumer may unload.
            self._prepared.pop(key, None)
            item = next((i for i in self._catalog(spec.base_url) if str(i.get("key") or i.get("id")) == spec.model), None)
            if not item or not self._is_embedding(item):
                return {"ok": False, "warning": "Selected model is not an installed embedding model."}
            loaded = tuple(item.get("loaded_instances") or ())
            if loaded:
                context = int((loaded[0].get("config") or {}).get("context_length") or 0)
                if context and context != spec.context_tokens:
                    return {"ok": False, "warning": f"Model is already loaded at context {context}; it will not be unloaded."}
            else:
                if cancelled():
                    return {"ok": False, "warning": "Preparation cancelled."}
                base = key[0]
                native = self._native_base(base)
                data = self._request(native + "/models/load", payload={"model": spec.model, "context_length": key[2], "echo_load_config": True}, timeout=120)
                actual = int((data.get("load_config") or {}).get("context_length") or 0)
                if actual and actual != spec.context_tokens:
                    return {"ok": False, "warning": "Model loaded with an incompatible context."}
            if cancelled():
                return {"ok": False, "warning": "Preparation cancelled."}
            self._prepared[key] = dict(item)
            return {"ok": True, "model": spec.model, "metadata": dict(item)}
        except Exception as exc:
            return {"ok": False, "warning": str(exc)}
        finally:
            self._slot.release()

    def embed(self, text: str, *, spec: LocalEmbeddingSpec,
              purpose: Literal["query", "document"], deadline: float,
              cancelled: Callable) -> list[float]:
        key = _key(spec)
        if cancelled() or self._clock() >= deadline:
            raise TimeoutError("Document embedding deadline expired.")
        if key not in self._prepared:
            raise RuntimeError("Document model is not prepared; wait for idle indexing.")
        if purpose not in {"query", "document"}:
            raise ValueError("Unknown embedding purpose.")
        value = str(text).replace("\r\n", "\n").strip()
        if not value:
            raise ValueError("Cannot embed empty text.")
        value = embedding_prefixes(spec)[1 if purpose == "query" else 0] + value
        if not self._slot.acquire(blocking=False):
            raise DocumentEmbeddingBusy("Document embedding provider is busy.")
        try:
            remaining = deadline - self._clock()
            if remaining <= 0 or cancelled():
                raise TimeoutError("Document embedding deadline expired.")
            data = self._request(key[0] + "/embeddings", payload={"input": [value], "model": spec.model}, timeout=min(30.0, remaining))
            if self._clock() >= deadline or cancelled():
                raise TimeoutError("Document embedding deadline expired.")
            vector = [float(v) for v in data["data"][0]["embedding"]]
            norm = math.sqrt(sum(v*v for v in vector))
            if not vector or not all(math.isfinite(v) for v in vector) or not math.isfinite(norm) or norm == 0:
                raise ValueError("Embedding must be a finite nonzero vector.")
            dimension = self._dimensions.get(key, getattr(spec, "dimensions", 0))
            if dimension and len(vector) != dimension:
                raise ValueError("Embedding dimensions changed; rebuild the document index.")
            self._dimensions[key] = len(vector)
            return [v/norm for v in vector]
        finally:
            self._slot.release()
