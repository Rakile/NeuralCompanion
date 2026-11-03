"""Session-bound LM Studio embedding ownership for Long-Term Memory."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from contextlib import contextmanager
from functools import wraps
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core import long_term_memory
from core.runtime.contracts import CommandResult
from core.runtime.memory import MemorySessionBinding, MemoryWorkContext
from core.runtime.session_resources import SessionResourceGuard
from core.runtime.embedding_provider import EmbeddingProviderClient, PROVIDERS, provider_id, baseline_model

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_MODEL = "text-embedding-bge-m3"
MODEL_LOAD_CACHE_SECONDS = 30.0

JsonRequest = Callable[..., object]
Logger = Callable[[str], None]
BlockedNotifier = Callable[[Mapping[str, object]], object]
WorkContextCheck = Callable[[MemoryWorkContext], bool]


def _serialize_embedding_model(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._model_lock:
            return method(self, *args, **kwargs)
    return call


def _request_json(
    url: str,
    *,
    payload: Mapping[str, object] | None = None,
    timeout: float = 30,
    local_only: bool = False,
    headers: Mapping[str, str] | None = None,
) -> object:
    data = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
    request = urllib.request.Request(
        str(url),
        data=data,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": "Bearer lm-studio"} if headers is None else dict(headers)),
        },
        method="POST" if payload is not None else "GET",
    )
    if local_only:
        from core.runtime.document_memory import LocalOnlyRedirect, validate_local_url
        validate_local_url(str(url))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), LocalOnlyRedirect())
        response_context = opener.open(request, timeout=timeout)
    else:
        class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                from urllib.parse import urlsplit
                before, after = urlsplit(req.full_url), urlsplit(newurl)
                if (before.scheme, before.hostname, before.port) != (after.scheme, after.hostname, after.port):
                    raise ValueError('The search server redirected to a different address. Check its configuration.')
                return super().redirect_request(req, fp, code, msg, hdrs, newurl)
        response_context = urllib.request.build_opener(SameOriginRedirect()).open(request, timeout=timeout)
    with response_context as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _native_base_url(base_url: object) -> str:
    url = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if url.endswith("/v1"):
        return url[:-3].rstrip("/") + "/api/v1"
    if url.endswith("/api/v1"):
        return url
    return url + "/api/v1"


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingConfig:
    enabled: bool
    base_url: str
    model: str
    context_length: int
    index_model: str
    provider: str = "lmstudio"

    @classmethod
    def from_values(cls, values: Mapping[str, object] | None) -> MemoryEmbeddingConfig:
        source = values or {}
        provider = provider_id(source.get('long_term_memory_embedding_provider'))
        defaults = PROVIDERS[provider]
        base_url = str(
            source.get("long_term_memory_embedding_base_url", defaults['base_url']) or ""
        ).strip()
        model = str(
            source.get("long_term_memory_embedding_model", defaults['model']) or ""
        ).strip()
        context_length = long_term_memory.embedding_context_length(
            source.get(
                "long_term_memory_embedding_context_length",
                long_term_memory.DEFAULT_EMBEDDING_CONTEXT_TOKENS,
            )
        )
        model_name = model or defaults['model']
        normalized_base_url = base_url.rstrip("/") or defaults['base_url']
        return cls(
            enabled=bool(source.get("long_term_memory_embedding_enabled", False)),
            base_url=normalized_base_url,
            model=model_name,
            context_length=context_length,
            index_model=long_term_memory.embedding_model_key(
                baseline_model(provider, model_name),
                context_length,
            ),
            provider=provider,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "model": self.model,
            "context_length": self.context_length,
            "index_model": self.index_model,
            "provider": self.provider,
        }


@dataclass(frozen=True, slots=True)
class EmbeddingProviderCapability:
    """The one embedding operation exposed to provider-adjacent consumers."""

    embed: Callable[..., list[float]]


class MemoryEmbeddingService:
    """Own LM Studio embedding state and session-bound database writes."""

    name = "memory_embeddings"

    def __init__(
        self,
        *,
        session_guard: SessionResourceGuard,
        request_json: JsonRequest | None = None,
        work_context_is_current: WorkContextCheck | None = None,
        blocked_notifier: BlockedNotifier | None = None,
        logger: Logger | None = print,
        clock: Callable[[], float] = time.time,
        cache_seconds: float = MODEL_LOAD_CACHE_SECONDS,
        api_key_getter: Callable[[str], str] | None = None,
    ) -> None:
        if not isinstance(session_guard, SessionResourceGuard):
            raise TypeError("Memory embeddings require a SessionResourceGuard.")
        if request_json is not None and not callable(request_json):
            raise TypeError("LM Studio request capability must be callable.")
        self._session_guard = session_guard
        self._request_json = request_json or _request_json
        self._provider_client = EmbeddingProviderClient(request_json=self._request_json, api_key_getter=api_key_getter)
        self._work_context_is_current = work_context_is_current
        self._blocked_notifier = blocked_notifier
        self._logger = logger
        self._clock = clock
        self._cache_seconds = max(0.0, float(cache_seconds))
        self._model_lock = threading.RLock()
        self._load_cache: dict[
            tuple[str, str, int],
            tuple[float, dict[str, object]],
        ] = {}
        self._blocked_lock = threading.Lock()
        self._blocked_event_id = 0
        self._blocked_event: dict[str, object] = {}
        self._document_port = None

    def start(self) -> CommandResult[None]:
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        self.clear_load_cache()
        return CommandResult(True)

    def provider_capability(self) -> EmbeddingProviderCapability:
        return EmbeddingProviderCapability(embed=self.embed)

    def document_capability(self):
        from functools import partial
        from core.runtime.document_memory import LocalDocumentEmbeddingPort
        with self._model_lock:
            if self._document_port is None:
                request = partial(_request_json, local_only=True) if self._request_json is _request_json else self._request_json
                self._document_port = LocalDocumentEmbeddingPort(request_json=request, native_base_url=_native_base_url)
            return self._document_port

    def resource_busy(self):
        if not self._model_lock.acquire(blocking=False):
            return True
        try:
            return bool(self._document_port and self._document_port.resource_busy())
        finally:
            self._model_lock.release()

    @contextmanager
    def resource_maintenance(self):
        if not self._model_lock.acquire(blocking=False):
            raise RuntimeError('Conversation memory is searching or indexing.')
        try:
            with self.document_capability().resource_maintenance():
                yield
        finally:
            self._model_lock.release()

    @staticmethod
    def config(
        values: Mapping[str, object] | None = None,
    ) -> MemoryEmbeddingConfig:
        return MemoryEmbeddingConfig.from_values(values)

    def embedding_enabled(self, values: Mapping[str, object] | None = None) -> bool:
        config = self.config(values)
        return bool(config.enabled and config.model and config.base_url)

    def session_mismatch(
        self,
        values: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        source = values or {}
        config = self.config(source)
        session_model = str(
            source.get("long_term_memory_embedding_session_model", "") or ""
        ).strip()
        try:
            session_context = int(
                source.get(
                    "long_term_memory_embedding_session_context_length",
                    0,
                )
                or 0
            )
        except (TypeError, ValueError, OverflowError):
            session_context = 0
        if not session_model or not session_context:
            return {
                "mismatch": False,
                "session_model": "",
                "session_context_length": 0,
            }
        mismatch = (
            session_model != baseline_model(config.provider, config.model) or session_context != config.context_length
        )
        return {
            "mismatch": mismatch,
            "session_model": session_model,
            "session_context_length": session_context,
            "current_model": config.model,
            "current_context_length": config.context_length,
        }

    def write_blocked(self, values: Mapping[str, object] | None = None) -> bool:
        if not self.embedding_enabled(values):
            return False
        return bool(self.session_mismatch(values).get("mismatch"))

    def list_models(self, *, base_url: str = "", quiet: bool = True, provider: str = "lmstudio") -> list[str]:
        if provider != 'lmstudio':
            return self._provider_client.list_models(provider, base_url)
        native_base = _native_base_url(base_url or DEFAULT_BASE_URL)
        try:
            data = self._request_json(f"{native_base}/models", timeout=8)
        except Exception as exc:  # noqa: BLE001 - provider boundary
            if not quiet and self._logger is not None:
                self._logger(f"Error fetching LM Studio embedding models: {exc}")
            return []
        models = data.get("models") if isinstance(data, Mapping) else None
        if not isinstance(models, list):
            return []
        embedding_models: list[str] = []
        seen: set[str] = set()
        for item in models:
            if not isinstance(item, Mapping):
                continue
            model_id = str(item.get("key") or item.get("id") or "").strip()
            if not model_id:
                continue
            model_type = str(item.get("type") or "").strip().lower()
            capabilities = (
                item.get("capabilities")
                if isinstance(item.get("capabilities"), Mapping)
                else {}
            )
            value = model_id.lower()
            looks_embedding = (
                model_type in {"embd", "embedding", "embeddings"}
                or bool(capabilities.get("embedding", False))
                or "embedding" in value
                or "embed" in value
                or "bge" in value
                or "e5" in value
                or "gte" in value
                or "nomic-embed" in value
                or "jina-embeddings" in value
            )
            looks_non_embedding = any(
                fragment in value
                for fragment in ("whisper", "tts", "rerank", "grok-imagine")
            )
            if not looks_embedding or looks_non_embedding or model_id in seen:
                continue
            seen.add(model_id)
            embedding_models.append(model_id)
        return sorted(embedding_models, key=str.lower)

    def model_status(
        self,
        config: MemoryEmbeddingConfig | Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        resolved = self._resolve_config(config)
        if resolved.provider != 'lmstudio':
            return {'available': True, 'loaded': True, 'provider': resolved.provider}
        try:
            data = self._request_json(
                f"{_native_base_url(resolved.base_url)}/models",
                timeout=8,
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            return {
                "available": False,
                "warning": f"LM Studio model list unavailable: {exc}",
            }
        models = data.get("models", ()) if isinstance(data, Mapping) else ()
        for item in tuple(models or ()):
            if not isinstance(item, Mapping):
                continue
            if str(item.get("key") or "") != resolved.model:
                continue
            loaded = list(item.get("loaded_instances") or [])
            context: int | None = None
            instance_id = ""
            if loaded:
                instance = loaded[0] if isinstance(loaded[0], Mapping) else {}
                instance_id = str(instance.get("id") or "")
                try:
                    context = int(
                        (instance.get("config") or {}).get("context_length") or 0
                    )
                except (AttributeError, TypeError, ValueError, OverflowError):
                    context = None
            return {
                "available": True,
                "loaded": bool(loaded),
                "instance_id": instance_id,
                "loaded_context_length": context,
                "max_context_length": item.get("max_context_length"),
                "type": item.get("type"),
                "display_name": item.get("display_name"),
            }
        return {
            "available": False,
            "warning": (
                f"Embedding model '{resolved.model}' is not listed by LM Studio."
            ),
        }

    def ensure_model_loaded(
        self,
        config: MemoryEmbeddingConfig | Mapping[str, object] | None = None,
        *,
        force: bool = False,
    ) -> dict[str, object]:
        resolved = self._resolve_config(config)
        if resolved.provider != 'lmstudio':
            return {'ok': True, 'provider': resolved.provider}
        if not resolved.model:
            return {"ok": False, "warning": "No embedding model selected."}
        cache_key = (
            resolved.base_url,
            resolved.model,
            resolved.context_length,
        )
        with self._model_lock:
            now = float(self._clock())
            cached = self._load_cache.get(cache_key)
            if (
                not force
                and cached is not None
                and now - cached[0] < self._cache_seconds
            ):
                return dict(cached[1])
            status = self.model_status(resolved)
            loaded_context = int(status.get("loaded_context_length") or 0)
            if (
                bool(status.get("available"))
                and bool(status.get("loaded"))
                and loaded_context == resolved.context_length
            ):
                return self._cache_load_result(
                    cache_key,
                    now,
                    {"ok": True, "status": status},
                )
            if bool(status.get("loaded")) and loaded_context != resolved.context_length:
                instance_id = str(status.get("instance_id") or "").strip()
                if instance_id:
                    try:
                        self._request_json(
                            f"{_native_base_url(resolved.base_url)}/models/unload",
                            payload={"instance_id": instance_id},
                            timeout=60,
                        )
                    except Exception as exc:  # noqa: BLE001 - provider boundary
                        return self._cache_load_result(
                            cache_key,
                            now,
                            {
                                "ok": False,
                                "status": status,
                                "warning": (
                                    "Embedding model is loaded at context "
                                    f"{status.get('loaded_context_length')}; could not "
                                    f"unload it to switch to {resolved.context_length}: {exc}"
                                ),
                            },
                        )
            try:
                data = self._request_json(
                    f"{_native_base_url(resolved.base_url)}/models/load",
                    payload={
                        "model": resolved.model,
                        "context_length": resolved.context_length,
                        "echo_load_config": True,
                    },
                    timeout=120,
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary
                return self._cache_load_result(
                    cache_key,
                    now,
                    {
                        "ok": False,
                        "status": status,
                        "warning": (
                            "Could not load embedding model at context "
                            f"{resolved.context_length}: {exc}"
                        ),
                    },
                )
            load_config = (
                data.get("load_config")
                if isinstance(data, Mapping)
                and isinstance(data.get("load_config"), Mapping)
                else {}
            )
            loaded_context = load_config.get("context_length")
            warning = ""
            try:
                if (
                    int(loaded_context or 0)
                    and int(loaded_context) != resolved.context_length
                ):
                    warning = (
                        f"LM Studio loaded context {loaded_context}, expected "
                        f"{resolved.context_length}."
                    )
            except (TypeError, ValueError, OverflowError):
                warning = ""
            return self._cache_load_result(
                cache_key,
                now,
                {
                    "ok": not bool(warning),
                    "status": status,
                    "load": data,
                    "warning": warning,
                },
            )

    def clear_load_cache(self) -> None:
        with self._model_lock:
            self._load_cache.clear()

    @_serialize_embedding_model
    def embed(
        self,
        text: object,
        *,
        model: str = "",
        base_url: str = "",
        context_length: object | None = None,
        ensure_loaded: bool = True,
        runtime_config: Mapping[str, object] | None = None,
    ) -> list[float]:
        payload_text = str(text or "").replace("\n", " ").strip()
        if not payload_text:
            return []
        values = dict(runtime_config or {})
        if model:
            values["long_term_memory_embedding_model"] = str(model).strip()
        if base_url:
            values["long_term_memory_embedding_base_url"] = str(base_url).strip()
        if context_length is not None:
            values["long_term_memory_embedding_context_length"] = context_length
        config = self.config(values)
        if not config.model:
            return []
        if config.provider != 'lmstudio':
            if config.provider == 'openai' and not values.get('long_term_memory_embedding_cloud_consent'):
                raise ValueError('Open Providers and confirm OpenAI memory search on this installation before using it.')
            return self._provider_client.embed(config.provider, config.base_url, config.model, payload_text)
        if ensure_loaded:
            load_result = self.ensure_model_loaded(config)
            warning = str(load_result.get("warning") or "")
            if warning and self._logger is not None:
                self._logger(f"🧠 [Memory] Embedding model warning: {warning}")
            if load_result.get("ok") is False:
                return []
        data = self._request_json(
            f"{config.base_url}/embeddings",
            payload={"input": [payload_text], "model": config.model},
            timeout=30,
        )
        rows = data.get("data") if isinstance(data, Mapping) else None
        first = rows[0] if isinstance(rows, list) and rows else {}
        embedding = first.get("embedding") if isinstance(first, Mapping) else ()
        return [float(value) for value in list(embedding or [])]

    def record_blocked_attempt(
        self,
        context: MemoryWorkContext,
        reason: str = "long_term_memory_archive",
        *,
        runtime_config: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        values = runtime_config or context.config.values
        if not self.write_blocked(values) or not self._context_matches_binding(context):
            return {}
        config = self.config(values)
        mismatch = self.session_mismatch(values)

        def publish() -> dict[str, object]:
            payload = {
                "reason": str(reason or "long_term_memory_archive"),
                "session_model": str(mismatch.get("session_model") or ""),
                "session_context_length": int(
                    mismatch.get("session_context_length") or 0
                ),
                "current_model": str(mismatch.get("current_model") or config.model),
                "current_context_length": int(
                    mismatch.get("current_context_length") or config.context_length
                ),
                "created_at": float(self._clock()),
            }
            with self._blocked_lock:
                self._blocked_event_id += 1
                payload["id"] = self._blocked_event_id
                self._blocked_event = dict(payload)
            if self._blocked_notifier is not None:
                self._blocked_notifier({"long_term_memory_embedding_blocked": True})
            return payload

        result = self._session_guard.commit_state_write(context.lease, publish)
        return dict(result.value or {}) if result.accepted else {}

    def blocked_event(self) -> dict[str, object]:
        with self._blocked_lock:
            return dict(self._blocked_event)

    def embed_target(
        self,
        context: MemoryWorkContext,
        target: Mapping[str, object],
        *,
        allow_session_mismatch: bool = False,
        runtime_config: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        if not self._preflight(context):
            return None
        values = runtime_config or context.config.values
        if not self.embedding_enabled(values):
            return None
        config = self.config(values)
        if not allow_session_mismatch and self.write_blocked(values):
            mismatch = self.session_mismatch(values)
            self.record_blocked_attempt(
                context,
                "long_term_memory_embedding_target",
                runtime_config=values,
            )
            if self._logger is not None:
                self._logger(
                    "🧠 [Memory] Embedding skipped: selected semantic model/context "
                    "differs from this chat session. Session expects "
                    f"{mismatch.get('session_model') or 'unknown'} at context "
                    f"{mismatch.get('session_context_length') or 0}; selected "
                    f"{mismatch.get('current_model') or config.model} at context "
                    f"{mismatch.get('current_context_length') or config.context_length}. "
                    "Switch back or rebuild embeddings for the selected model."
                )
            return None
        text = str(target.get("text", "") or "").strip()
        if not text:
            return None
        try:
            vector = self.embed(
                text,
                model=config.model,
                base_url=config.base_url,
                context_length=config.context_length,
                runtime_config=values,
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            if self._logger is not None:
                self._logger(f"🧠 [Memory] Embedding skipped: {exc}")
            return None
        if not vector or not self._context_matches_binding(context):
            return None
        result = self._session_guard.commit_embedding_write(
            context.lease,
            lambda: long_term_memory.upsert_embedding(
                target_kind=target.get("kind"),
                target_id=target.get("id"),
                model=config.index_model,
                text=text,
                vector=vector,
                path=context.binding.database_path,
            ) if self._context_matches_binding(context) else None,
        )
        return result.value if result.accepted else None

    def embed_record(
        self,
        context: MemoryWorkContext,
        record: Mapping[str, object] | None,
        *,
        runtime_config: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        if not record:
            return None
        return self.embed_target(
            context,
            {
                "kind": "record",
                "id": record.get("id", ""),
                "text": long_term_memory.embedding_text_for_record(
                    dict(record),
                    path=context.binding.database_path,
                ),
            },
            runtime_config=runtime_config,
        )

    def embed_chunk(
        self,
        context: MemoryWorkContext,
        chunk: Mapping[str, object] | None,
        *,
        runtime_config: Mapping[str, object] | None = None,
    ) -> list[Mapping[str, Any]]:
        if not chunk:
            return []
        values = runtime_config or context.config.values
        config = self.config(values)
        results: list[Mapping[str, Any]] = []
        pending_ids = {item['id'] for item in long_term_memory.pending_archive_chunks(
            batch_size=int(values.get('long_term_memory_archive_batch_turns', 8) or 8),
            path=context.binding.database_path)}
        if chunk.get('id') in pending_ids:
            return []
        for target in long_term_memory.embedding_targets_for_chunk(
            dict(chunk),
            context_length=config.context_length,
            path=context.binding.database_path,
        ):
            result = self.embed_target(
                context,
                target,
                runtime_config=values,
            )
            if result:
                results.append(result)
        return results

    def status(
        self,
        binding: MemorySessionBinding,
        *,
        include_lmstudio: bool = False,
        runtime_config: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if not isinstance(binding, MemorySessionBinding):
            raise TypeError("Embedding status requires a MemorySessionBinding.")
        config = self.config(runtime_config)
        if binding.database_path.is_file():
            status = long_term_memory.embedding_status(
                model=config.index_model,
                batch_size=int((runtime_config or {}).get('long_term_memory_archive_batch_turns', 8) or 8),
                source_chat_id=binding.conversation_id,
                path=binding.database_path,
            )
        else:
            status = {
                "total_embeddings": 0,
                "model_embeddings": 0,
                "missing_for_model": 0,
                "model": config.index_model,
            }
        status.update(config.as_dict())
        mismatch = self.session_mismatch(runtime_config)
        status["session_mismatch"] = bool(mismatch.get("mismatch"))
        status["session_model"] = str(mismatch.get("session_model", "") or "")
        status["session_context_length"] = int(
            mismatch.get("session_context_length", 0) or 0
        )
        status["writes_blocked"] = bool(status["session_mismatch"])
        if config.enabled and include_lmstudio:
            lmstudio_status = self.model_status(config)
            status["lmstudio"] = lmstudio_status
            if lmstudio_status.get("warning"):
                status["warning"] = lmstudio_status.get("warning")
            elif (
                lmstudio_status.get("loaded")
                and int(lmstudio_status.get("loaded_context_length") or 0)
                != config.context_length
            ):
                status["warning"] = (
                    f"LM Studio has {config.model} loaded at context "
                    f"{lmstudio_status.get('loaded_context_length')}; NC expects "
                    f"{config.context_length} for this chat session."
                )
        return status

    def _preflight(self, context: MemoryWorkContext) -> bool:
        if not self._context_matches_binding(context):
            return False
        admitted = self._session_guard.commit_embedding_write(
            context.lease,
            lambda: None,
        )
        return admitted.accepted

    def _context_matches_binding(self, context: MemoryWorkContext) -> bool:
        if not isinstance(context, MemoryWorkContext):
            return False
        if context.lease.session_generation != context.binding.session_generation:
            return False
        return self._work_context_is_current is None or self._work_context_is_current(
            context
        )

    def _resolve_config(
        self,
        config: MemoryEmbeddingConfig | Mapping[str, object] | None,
    ) -> MemoryEmbeddingConfig:
        if isinstance(config, MemoryEmbeddingConfig):
            return config
        if isinstance(config, Mapping) and any(
            key in config
            for key in ("base_url", "model", "context_length", "index_model")
        ):
            model = str(config.get("model") or DEFAULT_MODEL).strip()
            base_url = str(config.get("base_url") or DEFAULT_BASE_URL).strip()
            context_length = long_term_memory.embedding_context_length(
                config.get("context_length")
            )
            return MemoryEmbeddingConfig(
                enabled=bool(config.get("enabled", False)),
                base_url=base_url.rstrip("/") or DEFAULT_BASE_URL,
                model=model or DEFAULT_MODEL,
                context_length=context_length,
                index_model=str(config.get("index_model") or "").strip()
                or long_term_memory.embedding_model_key(model, context_length),
                provider=provider_id(config.get('provider')),
            )
        return self.config(config)

    def _cache_load_result(
        self,
        cache_key: tuple[str, str, int],
        checked_at: float,
        result: Mapping[str, object],
    ) -> dict[str, object]:
        copied = dict(result)
        self._load_cache[cache_key] = (checked_at, copied)
        return dict(copied)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "MODEL_LOAD_CACHE_SECONDS",
    "EmbeddingProviderCapability",
    "MemoryEmbeddingConfig",
    "MemoryEmbeddingService",
]
