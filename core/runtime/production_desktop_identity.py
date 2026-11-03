"""Concrete desktop policies for the production Identity Relay boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import json
import threading
import time
import urllib.request

from core.runtime.identity_relay import IdentityRelaySnapshotRegistry
from core.runtime.memory_embeddings import DEFAULT_BASE_URL, MemoryEmbeddingConfig
from core.runtime.production_identity import (
    ProductionIdentityRelayArtifactControllerBinding,
    ProductionIdentityRelayDeletionOwner,
    ProductionIdentityRelayEmbeddingOwner,
    ProductionIdentityRelayProviderDispatchOwner,
    ProductionIdentityRelayRuntimeOwners,
)


JsonRequest = Callable[..., object]
ConfigSnapshot = Callable[[], object]
PendingTurnSnapshot = Callable[[], Mapping[str, object] | None]


def request_json(
    url: str,
    *,
    payload: Mapping[str, object] | None = None,
    timeout: float = 30,
) -> object:
    data = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
    request = urllib.request.Request(
        str(url),
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer lm-studio",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _native_base_url(base_url: object) -> str:
    url = str(base_url or DEFAULT_BASE_URL).strip()
    url = url.rstrip("/")
    if url.endswith("/v1"):
        return url[:-3].rstrip("/") + "/api/v1"
    if url.endswith("/api/v1"):
        return url
    return url + "/api/v1"


def _require_lock(name: str, value: object) -> None:
    if not callable(getattr(value, "__enter__", None)) or not callable(
        getattr(value, "__exit__", None)
    ):
        raise TypeError(f"{name} must be a context-manager lock.")


@dataclass(frozen=True, slots=True)
class ProductionDesktopIdentityTransactions:
    """Live accepted-turn state required for atomic Relay provider admission."""

    registry: MutableMapping[str, MutableMapping[str, object]]
    lock: object
    current_session_generation: Callable[[], int]
    blocked_error: type[BaseException]

    def __post_init__(self) -> None:
        if not isinstance(self.registry, MutableMapping):
            raise TypeError("Identity Relay transactions require a mutable registry.")
        _require_lock("Identity Relay transaction lock", self.lock)
        if not callable(self.current_session_generation):
            raise TypeError("Identity Relay session generation must be callable.")
        if not isinstance(self.blocked_error, type) or not issubclass(
            self.blocked_error, BaseException
        ):
            raise TypeError("Identity Relay blocked_error must be an exception type.")


@dataclass(frozen=True, slots=True)
class ProductionDesktopIdentityDerivatives:
    """Live loaded-chat and compatibility-snapshot state for deletion policy."""

    conversation_history: Sequence[Mapping[str, object]]
    conversation_history_lock: object
    pending_loaded_input_turn: PendingTurnSnapshot
    snapshots: MutableMapping[str, object]
    snapshot_lock: object

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_history, Sequence):
            raise TypeError("Identity Relay conversation history must be a sequence.")
        _require_lock(
            "Identity Relay conversation history lock",
            self.conversation_history_lock,
        )
        if not callable(self.pending_loaded_input_turn):
            raise TypeError("Identity Relay pending turn snapshot must be callable.")
        if not isinstance(self.snapshots, MutableMapping):
            raise TypeError("Identity Relay snapshots require a mutable registry.")
        _require_lock("Identity Relay snapshot lock", self.snapshot_lock)


@dataclass(frozen=True, slots=True)
class ProductionDesktopIdentityInputs:
    """Finite process inputs needed to construct production Relay owners."""

    transactions: ProductionDesktopIdentityTransactions
    derivatives: ProductionDesktopIdentityDerivatives
    runtime_config: ConfigSnapshot
    request_json: JsonRequest = request_json
    logger: Callable[[str], object] = print
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        if not isinstance(self.transactions, ProductionDesktopIdentityTransactions):
            raise TypeError("Identity Relay desktop transactions are required.")
        if not isinstance(self.derivatives, ProductionDesktopIdentityDerivatives):
            raise TypeError("Identity Relay desktop derivative state is required.")
        for name in ("runtime_config", "request_json", "logger", "clock"):
            if not callable(getattr(self, name)):
                raise TypeError(f"Identity Relay desktop {name} must be callable.")


class ProductionDesktopIdentityProviderDispatch:
    """Admit Relay judge dispatch only while its accepted turn remains current."""

    __slots__ = ("_state",)

    def __init__(self, state: ProductionDesktopIdentityTransactions) -> None:
        self._state = state

    def claim(self, relay_state: object, provider_request: object, kind: str) -> None:
        state = self._state
        with state.lock:  # type: ignore[attr-defined]
            transaction = next(
                (
                    candidate
                    for candidate in state.registry.values()
                    if candidate.get("identity_relay_state") == relay_state
                ),
                None,
            )
        if transaction is None:
            self._blocked("Identity Relay provider dispatch lost its accepted turn.")

        assert transaction is not None
        dispatch_kind = str(kind or "").strip()
        transaction_lock = transaction.get("lock")
        _require_lock("Identity Relay accepted-turn lock", transaction_lock)
        with transaction_lock:  # type: ignore[attr-defined]
            turn_id = str(transaction.get("turn_id") or "")
            with state.lock:  # type: ignore[attr-defined]
                current = state.registry.get(turn_id) is transaction
                generation_matches = int(
                    transaction.get("session_generation", -1)
                ) == int(state.current_session_generation())
                cancel_event = transaction.get("cancel_event")
                is_set = getattr(cancel_event, "is_set", None)
                if not callable(is_set):
                    raise TypeError(
                        "Identity Relay accepted turn requires a cancellation event."
                    )
                cancelled = bool(is_set())
                if not current or not generation_matches or cancelled:
                    self._blocked(
                        "Normal Chat turn was cancelled or superseded before "
                        f"{dispatch_kind or 'provider'} dispatch."
                    )
                sequence = (
                    int(transaction.get("provider_dispatch_sequence", 0) or 0) + 1
                )
                transaction["provider_dispatch_sequence"] = sequence
                claims = transaction.setdefault("provider_dispatch_claims", [])
                if not isinstance(claims, list):
                    raise TypeError(
                        "Identity Relay provider dispatch claims must be a list."
                    )
                claims.append(
                    {
                        "sequence": sequence,
                        "kind": dispatch_kind,
                        "request_id": id(provider_request),
                    }
                )

    def _blocked(self, message: str) -> None:
        raise self._state.blocked_error(message)


class ProductionDesktopLmStudioEmbedding:
    """Real LM Studio model admission and embedding transport for Relay."""

    __slots__ = (
        "_clock",
        "_load_cache",
        "_lock",
        "_logger",
        "_request_json",
        "_runtime_config",
    )

    def __init__(
        self,
        *,
        runtime_config: ConfigSnapshot,
        request_json: JsonRequest,
        logger: Callable[[str], object],
        clock: Callable[[], float],
    ) -> None:
        self._runtime_config = runtime_config
        self._request_json = request_json
        self._logger = logger
        self._clock = clock
        self._lock = threading.RLock()
        self._load_cache: dict[
            tuple[str, str, int], tuple[float, dict[str, object]]
        ] = {}

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
        values = self._config_values(runtime_config)
        if model:
            values["long_term_memory_embedding_model"] = str(model or "").strip()
        if base_url:
            values["long_term_memory_embedding_base_url"] = (
                str(base_url or "").strip().rstrip("/")
            )
        if context_length is not None:
            values["long_term_memory_embedding_context_length"] = context_length
        config = MemoryEmbeddingConfig.from_values(values)
        if not config.model:
            return []
        if config.provider != 'lmstudio':
            from core.runtime.embedding_provider import EmbeddingProviderClient
            from core.runtime.memory_embeddings import _request_json
            if config.provider == 'openai' and not values.get('long_term_memory_embedding_cloud_consent'):
                raise ValueError('Open Providers and confirm OpenAI memory search on this installation before using it.')
            request = _request_json if self._request_json is request_json else self._request_json
            return EmbeddingProviderClient(request_json=request).embed(
                config.provider, config.base_url, config.model, payload_text)
        if ensure_loaded:
            loaded = self._ensure_model_loaded(config)
            warning = str(loaded.get("warning") or "")
            if warning:
                self._logger(f"\U0001f9e0 [Memory] Embedding model warning: {warning}")
            if loaded.get("ok") is False:
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

    def _config_values(
        self,
        override: Mapping[str, object] | None,
    ) -> dict[str, object]:
        if override is not None:
            return dict(override)
        snapshot = self._runtime_config()
        values = (
            snapshot
            if isinstance(snapshot, Mapping)
            else getattr(snapshot, "values", None)
        )
        if not isinstance(values, Mapping):
            raise TypeError("Identity Relay runtime config snapshot must be a mapping.")
        return dict(values)

    def _model_status(self, config: MemoryEmbeddingConfig) -> dict[str, object]:
        try:
            data = self._request_json(
                f"{_native_base_url(config.base_url)}/models",
                timeout=8,
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            return {
                "available": False,
                "warning": f"LM Studio model list unavailable: {exc}",
            }
        models = data.get("models", ()) if isinstance(data, Mapping) else ()
        for raw_item in tuple(models or ()):
            if not isinstance(raw_item, Mapping):
                continue
            if str(raw_item.get("key") or "") != config.model:
                continue
            loaded = list(raw_item.get("loaded_instances") or [])
            instance = loaded[0] if loaded and isinstance(loaded[0], Mapping) else {}
            loaded_context: int | None = None
            try:
                loaded_context = int(
                    (instance.get("config") or {}).get("context_length") or 0
                )
            except (AttributeError, TypeError, ValueError, OverflowError):
                loaded_context = None
            return {
                "available": True,
                "loaded": bool(loaded),
                "instance_id": str(instance.get("id") or ""),
                "loaded_context_length": loaded_context,
                "max_context_length": raw_item.get("max_context_length"),
                "type": raw_item.get("type"),
                "display_name": raw_item.get("display_name"),
            }
        return {
            "available": False,
            "warning": f"Embedding model '{config.model}' is not listed by LM Studio.",
        }

    def _ensure_model_loaded(
        self,
        config: MemoryEmbeddingConfig,
    ) -> dict[str, object]:
        key = (config.base_url, config.model, config.context_length)
        with self._lock:
            now = float(self._clock())
            cached = self._load_cache.get(key)
            if cached is not None and now - cached[0] < 30.0:
                return dict(cached[1])
            status = self._model_status(config)
            loaded_context = int(status.get("loaded_context_length") or 0)
            if (
                bool(status.get("available"))
                and bool(status.get("loaded"))
                and loaded_context == config.context_length
            ):
                return self._cache(key, now, {"ok": True, "status": status})
            if bool(status.get("loaded")) and loaded_context != config.context_length:
                instance_id = str(status.get("instance_id") or "").strip()
                if instance_id:
                    try:
                        self._request_json(
                            f"{_native_base_url(config.base_url)}/models/unload",
                            payload={"instance_id": instance_id},
                            timeout=60,
                        )
                    except Exception as exc:  # noqa: BLE001 - provider boundary
                        return self._cache(
                            key,
                            now,
                            {
                                "ok": False,
                                "status": status,
                                "warning": (
                                    "Embedding model is loaded at context "
                                    f"{status.get('loaded_context_length')}; could not "
                                    f"unload it to switch to {config.context_length}: {exc}"
                                ),
                            },
                        )
            try:
                loaded = self._request_json(
                    f"{_native_base_url(config.base_url)}/models/load",
                    payload={
                        "model": config.model,
                        "context_length": config.context_length,
                        "echo_load_config": True,
                    },
                    timeout=120,
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary
                return self._cache(
                    key,
                    now,
                    {
                        "ok": False,
                        "status": status,
                        "warning": (
                            "Could not load embedding model at context "
                            f"{config.context_length}: {exc}"
                        ),
                    },
                )
            load_config = (
                loaded.get("load_config")
                if isinstance(loaded, Mapping)
                and isinstance(loaded.get("load_config"), Mapping)
                else {}
            )
            actual_context = load_config.get("context_length")
            warning = ""
            try:
                if (
                    int(actual_context or 0)
                    and int(actual_context) != config.context_length
                ):
                    warning = (
                        f"LM Studio loaded context {actual_context}, expected "
                        f"{config.context_length}."
                    )
            except (TypeError, ValueError, OverflowError):
                warning = ""
            return self._cache(
                key,
                now,
                {
                    "ok": not bool(warning),
                    "status": status,
                    "load": loaded,
                    "warning": warning,
                },
            )

    def _cache(
        self,
        key: tuple[str, str, int],
        checked_at: float,
        result: Mapping[str, object],
    ) -> dict[str, object]:
        cached = dict(result)
        self._load_cache[key] = (checked_at, cached)
        return dict(cached)


class ProductionDesktopIdentityDeletion:
    """Block loaded artifacts and serialize deletion with snapshot publication."""

    __slots__ = ("_derivatives", "_transactions")

    def __init__(
        self,
        *,
        transactions: ProductionDesktopIdentityTransactions,
        derivatives: ProductionDesktopIdentityDerivatives,
    ) -> None:
        self._transactions = transactions
        self._derivatives = derivatives

    def delete_transaction(
        self, artifact_ref: str, commit: object
    ) -> dict[str, object]:
        if not callable(commit):
            raise TypeError("Identity Relay deletion requires a commit callback.")
        target_ref = str(artifact_ref or "")
        state = self._derivatives
        transactions = self._transactions
        with state.conversation_history_lock:  # type: ignore[attr-defined]
            with state.snapshot_lock:  # type: ignore[attr-defined]
                with transactions.lock:  # type: ignore[attr-defined]
                    blockers = self._loaded_reference_reasons(target_ref)
                    if blockers:
                        return {
                            "committed": False,
                            "blocked_by": blockers,
                            "result": None,
                        }
                    result = commit()
        return {"committed": True, "blocked_by": (), "result": result}

    def purge_derivatives(self, artifact_ref: str) -> dict[str, object]:
        target_ref = str(artifact_ref or "")
        blockers = self._loaded_reference_reasons(target_ref)
        if blockers:
            return {
                "purged": False,
                "blocked_by": blockers,
                "removed_snapshot_count": 0,
            }
        removed = 0
        state = self._derivatives
        with state.snapshot_lock:  # type: ignore[attr-defined]
            for snapshot_hash, snapshot in list(state.snapshots.items()):
                if self._artifact_ref(snapshot) != target_ref:
                    continue
                state.snapshots.pop(snapshot_hash, None)
                removed += 1
        return {
            "purged": True,
            "blocked_by": (),
            "removed_snapshot_count": removed,
        }

    def _loaded_reference_reasons(self, artifact_ref: str) -> tuple[str, ...]:
        target_ref = str(artifact_ref or "")
        reasons: list[str] = []
        state = self._derivatives
        transactions = self._transactions
        with state.conversation_history_lock:  # type: ignore[attr-defined]
            if any(
                self._turn_artifact_ref(turn) == target_ref
                for turn in state.conversation_history
            ):
                reasons.append("loaded_chat:conversation_history")
        with transactions.lock:  # type: ignore[attr-defined]
            if self._turn_artifact_ref(state.pending_loaded_input_turn()) == target_ref:
                reasons.append("loaded_chat:pending_turn")
            for transaction in transactions.registry.values():
                if any(
                    candidate == target_ref
                    for candidate in (
                        self._turn_artifact_ref(transaction.get("accepted_turn")),
                        self._artifact_ref(transaction.get("relay_capture")),
                        self._artifact_ref(transaction.get("relay_snapshot")),
                    )
                ):
                    reasons.append("loaded_chat:active_transaction")
                    break
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _turn_artifact_ref(turn: object) -> str:
        if not isinstance(turn, Mapping):
            return ""
        metadata = IdentityRelaySnapshotRegistry.sanitize_metadata(
            turn.get("identity_relay")
        )
        return str(metadata.artifact_ref if metadata is not None else "")

    @staticmethod
    def _artifact_ref(value: object) -> str:
        if isinstance(value, Mapping):
            return str(value.get("artifact_ref") or "")
        return str(getattr(value, "artifact_ref", "") or "")


def build_production_desktop_identity(
    inputs: ProductionDesktopIdentityInputs,
) -> ProductionIdentityRelayRuntimeOwners:
    """Construct the complete real desktop boundary consumed by the factory."""

    if not isinstance(inputs, ProductionDesktopIdentityInputs):
        raise TypeError("inputs must be ProductionDesktopIdentityInputs")
    dispatch = ProductionDesktopIdentityProviderDispatch(inputs.transactions)
    embedding = ProductionDesktopLmStudioEmbedding(
        runtime_config=inputs.runtime_config,
        request_json=inputs.request_json,
        logger=inputs.logger,
        clock=inputs.clock,
    )
    deletion = ProductionDesktopIdentityDeletion(
        transactions=inputs.transactions,
        derivatives=inputs.derivatives,
    )
    return ProductionIdentityRelayRuntimeOwners(
        artifacts=ProductionIdentityRelayArtifactControllerBinding(),
        provider_dispatch=ProductionIdentityRelayProviderDispatchOwner(dispatch.claim),
        embedding=ProductionIdentityRelayEmbeddingOwner(embedding.embed),
        deletion=ProductionIdentityRelayDeletionOwner(
            delete_transaction=deletion.delete_transaction,
            purge_derivatives=deletion.purge_derivatives,
        ),
    )


__all__ = [
    "ProductionDesktopIdentityDeletion",
    "ProductionDesktopIdentityDerivatives",
    "ProductionDesktopIdentityInputs",
    "ProductionDesktopIdentityProviderDispatch",
    "ProductionDesktopIdentityTransactions",
    "ProductionDesktopLmStudioEmbedding",
    "build_production_desktop_identity",
    "request_json",
]
