"""Provider selection, frozen preparation, and direct text execution."""

from __future__ import annotations

import queue as queue_module
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from core import chat_providers, lmstudio_runtime, streaming_text
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import (
    CancellationToken,
    CommandResult,
    RuntimeFailure,
)
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerSupervisor
from core.runtime.prompt_assembly import PromptRequest

if TYPE_CHECKING:
    from core.runtime_chat import ChatProviderRuntime


ModelUnload = Callable[[str, str], object]
ModelLoad = Callable[[str, str], object]
ModelInspect = Callable[
    [str],
    Sequence[lmstudio_runtime.LoadedModelInstance],
]
ModelUnloadOne = Callable[[str, str], object]
ModelPlaceholderCheck = Callable[[str], bool]


@dataclass(frozen=True)
class _ModelPreparationOperations:
    inspect: ModelInspect | None
    unload_one: ModelUnloadOne | None
    unload: ModelUnload | None
    load: ModelLoad | None
    preserved_load: ModelLoad | None
    context_length: Callable[[], int | None]
    cancelled: Callable[[], bool] | None = None


def _provider_error_trace_payload(error: Exception) -> dict[str, object]:
    payload: dict[str, object] = {"error": error}
    if isinstance(error, chat_providers.FrozenChatProviderExecutionError):
        category = error.diagnostic_category
        payload["diagnostic_category"] = (
            category if category in chat_providers.FROZEN_FAILURE_CATEGORIES else "unknown"
        )
        status = error.diagnostic_http_status
        if type(status) is int and 400 <= status <= 599:
            payload["diagnostic_http_status"] = status
    return payload


def _lmstudio_endpoint_identity(value: object) -> tuple[str, str, int | None] | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        parsed = urlsplit(raw_value)
        scheme = parsed.scheme.lower()
        hostname = str(parsed.hostname or "").strip().lower()
        port = parsed.port
    except ValueError:
        return None
    if scheme not in {"http", "https"} or not hostname:
        return None
    if hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        hostname = "loopback"
    if port is None:
        port = 80 if scheme == "http" else 443
    return scheme, hostname, port


def _lmstudio_model_key_matches(requested_model: object, loaded_key: object) -> bool:
    """Match LM Studio model aliases with their loaded quantization suffix."""

    return lmstudio_runtime.model_key_matches(requested_model,loaded_key)


def _lmstudio_main_chat_profile_matches(
    instance: lmstudio_runtime.LoadedModelInstance,
    context_length: int | None = None,
) -> bool:
    context_range = lmstudio_runtime.MAIN_CHAT_CONTEXT_RANGE
    if context_length is not None:
        # LM Studio can round a requested context up to a 256-token boundary
        # (40000 -> 40192). Accept that exact normalization, not arbitrary
        # larger/smaller contexts, while retaining all other profile checks.
        rounded_context = ((context_length + 255) // 256) * 256
        if instance.context_length not in (None, context_length, rounded_context):
            return False
        context_range = (context_length, rounded_context)
    return lmstudio_runtime.loaded_model_matches_profile(
        instance,
        load_config=lmstudio_runtime.main_chat_load_config(context_length),
        context_range=context_range,
        parallel_predictions=lmstudio_runtime.DEFAULT_PARALLEL_PREDICTIONS,
    )


def _with_frozen_output_budget(
    selection: ProviderSelection,
    request: PromptRequest,
) -> PromptRequest:
    metadata = chat_providers.provider_metadata(selection.provider_id)
    if not bool(metadata.get("supports_frozen_output_token_budget_override")):
        return request
    additional_params = request.additional_params_copy()
    override_key = chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE
    if override_key in additional_params:
        return request

    output_budget: int | None = None
    for key in ("max_output_tokens", "max_completion_tokens", "max_tokens"):
        raw_value = request.parameters.get(key)
        if raw_value is None or isinstance(raw_value, bool):
            continue
        try:
            candidate = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            continue
        if candidate > 0:
            output_budget = candidate
            break
    if output_budget is None:
        return request

    additional_params[override_key] = output_budget
    return request.with_options(
        model_id=request.model_id,
        parameters=request.parameters,
        additional_parameters=additional_params,
    )


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Provider, model, and runtime configuration frozen for one turn."""

    provider_id: str
    model_id: str
    config: RuntimeConfigSnapshot
    context: chat_providers.FrozenChatProviderContext
    endpoint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_id",
            str(self.provider_id or "").strip().lower(),
        )
        object.__setattr__(self, "model_id", str(self.model_id or "").strip())
        endpoint = str(self.endpoint or "").strip()
        if not endpoint:
            provider_config = getattr(self.context, "provider_config", {})
            if hasattr(provider_config, "get"):
                endpoint = str(provider_config.get("base_url", "") or "").strip()
        object.__setattr__(self, "endpoint", endpoint)

    def with_context(
        self,
        context: chat_providers.FrozenChatProviderContext,
    ) -> ProviderSelection:
        return ProviderSelection(
            provider_id=context.provider_name,
            model_id=context.model_name,
            config=self.config,
            context=context,
        )


@dataclass(frozen=True, slots=True)
class PreservedLMStudioModel:
    owner: str
    endpoint: str
    model_id: str
    resolved_model_key: str
    identifier: str
    owned: bool


_IMAGE_MODEL_POSITIVE_FRAGMENTS = (
    "vision",
    "image",
    "multimodal",
    "vl",
    "llava",
    "bakllava",
    "moondream",
    "pixtral",
    "minicpm-v",
    "internvl",
    "phi-3.5-vision",
    "phi-4-multimodal",
    "gemma-3",
    "gpt-4o",
    "gpt-4.1",
    "omni",
    "qwen/qwen3.5",
    "qwen3.5",
    "qwen2-vl",
    "qwen2.5-vl",
    "qvq",
)
_IMAGE_MODEL_NEGATIVE_FRAGMENTS = (
    "embedding",
    "rerank",
    "whisper",
    "tts",
    "audio",
    "transcribe",
    "grok-imagine",
)


def infer_model_supports_images(model_id: object) -> bool:
    """Apply the existing catalog-name fallback without consulting live state."""

    value = str(model_id or "").strip().lower()
    if not value or any(
        fragment in value for fragment in _IMAGE_MODEL_NEGATIVE_FRAGMENTS
    ):
        return False
    # Catalogs without modality metadata: recognize the documented image-input
    # family, not an unrestricted prefix covering unknown future models.
    if re.fullmatch(r'gpt-5\.4(?:-(?:mini|nano|pro))?(?:-\d{4}-\d{2}-\d{2})?', value):
        return True
    return any(fragment in value for fragment in _IMAGE_MODEL_POSITIVE_FRAGMENTS)


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """A detached readiness projection for one captured provider selection."""

    selection: ProviderSelection
    label: str
    model_selected: bool
    supports_images: bool
    hosted_runtime: bool
    api_key_available: bool
    api_key_environment_names: tuple[str, ...] = ()

    @property
    def credential_error(self) -> str:
        if not self.hosted_runtime or self.api_key_available:
            return ""
        env_hint = (
            f" or set {' / '.join(self.api_key_environment_names)}"
            if self.api_key_environment_names
            else ""
        )
        return (
            f"{self.label} API key is required. Add it in Chat Provider settings"
            f"{env_hint}."
        )


FrozenTurnRequest = chat_providers.FrozenTurnRequest


class ProviderEffectAdmission:
    """Lease-bound authority for one observable provider effect."""

    def __init__(
        self,
        *,
        lease: WorkLease | None = None,
        purpose: str = "provider_effect",
    ) -> None:
        self._lock = threading.Lock()
        self._lease = lease
        self._purpose = str(purpose or "provider_effect")
        self._status = "pending"
        self._transition_count = 0

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._status == "pending"

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def transition_count(self) -> int:
        with self._lock:
            return self._transition_count

    @property
    def lease(self) -> WorkLease | None:
        return self._lease

    @property
    def purpose(self) -> str:
        return self._purpose

    @contextmanager
    def commit_scope(self) -> Iterator[bool]:
        """Let the effect owner perform one short native mutation."""

        self._lock.acquire()
        if self._status != "pending":
            self._lock.release()
            yield False
            return
        try:
            yield True
        except BaseException:
            self._status = "revoked"
            self._transition_count += 1
            raise
        else:
            self._status = "completed"
            self._transition_count += 1
        finally:
            self._lock.release()

    def admit_irreversible_diagnostic(self) -> bool:
        """Commit one console/file diagnostic before its potentially blocking I/O."""

        with self._lock:
            if self._status != "pending":
                return False
            self._status = "completed"
            self._transition_count += 1
            return True

    def revoke(self) -> bool:
        """Retire an effect that has not reached its owner commit point."""

        with self._lock:
            if self._status != "pending":
                return False
            self._status = "revoked"
            self._transition_count += 1
            return True

    @contextmanager
    def revoke_scope(self) -> Iterator[bool]:
        """Let the effect owner perform one short native retirement."""

        self._lock.acquire()
        if self._status != "pending":
            self._lock.release()
            yield False
            return
        try:
            yield True
        except BaseException:
            self._status = "revoked"
            self._transition_count += 1
            raise
        else:
            self._status = "revoked"
            self._transition_count += 1
        finally:
            self._lock.release()


class _ProviderStreamPublicationOwner:
    """Own the concrete state, queue, and event mutations for one stream."""

    def __init__(
        self,
        state: streaming_text.StreamingReplyState,
        text_queue: queue_module.Queue[object],
    ) -> None:
        if type(state) is not streaming_text.StreamingReplyState:
            raise TypeError(
                "Provider streaming requires the owned StreamingReplyState."
            )
        if type(text_queue) is not queue_module.Queue:
            raise TypeError("Provider streaming requires a standard queue.Queue.")
        for event_name in ("done", "cancel_requested", "first_chunk_emitted"):
            if type(getattr(state, event_name, None)) is not threading.Event:
                raise TypeError(
                    f"Provider stream state.{event_name} must be threading.Event."
                )
        self.state = state
        self._text_queue = text_queue

    def prepare_terminal(self, full_text: str) -> PreparedProviderStreamStateSeal:
        return PreparedProviderStreamStateSeal(
            owner=self,
            full_text=str(full_text or ""),
        )

    def publish_text(
        self,
        text: str,
        admission: ProviderEffectAdmission,
        *,
        mark_first_chunk: bool,
    ) -> bool:
        prepared_text = str(text or "")
        if mark_first_chunk:
            event = self.state.first_chunk_emitted
            with event._cond:
                with self._text_queue.not_full:
                    self._raise_if_queue_full()
                    return self._publish_text_locked(
                        prepared_text,
                        admission,
                        event=event,
                    )
        with self._text_queue.not_full:
            self._raise_if_queue_full()
            return self._publish_text_locked(
                prepared_text,
                admission,
                event=None,
            )

    def _publish_text_locked(
        self,
        prepared_text: str,
        admission: ProviderEffectAdmission,
        *,
        event: threading.Event | None,
    ) -> bool:
        with admission.commit_scope() as admitted:
            if not admitted:
                return False
            self._put_locked(prepared_text)
            if event is not None:
                self._set_event_locked(event)
            return True

    def publish_terminal(
        self,
        full_text: str,
        admission: ProviderEffectAdmission,
    ) -> bool:
        prepared_text = str(full_text or "")
        event = self.state.done
        with event._cond:
            with self._text_queue.not_full:
                self._raise_if_queue_full()
                with admission.commit_scope() as admitted:
                    if not admitted:
                        return False
                    self.state.__dict__["full_text"] = prepared_text
                    self._put_locked(None)
                    self._set_event_locked(event)
                    return True

    def request_cancel(self) -> None:
        event = self.state.cancel_requested
        with event._cond:
            self._set_event_locked(event)

    def _raise_if_queue_full(self) -> None:
        if (
            self._text_queue.maxsize > 0
            and len(self._text_queue.queue) >= self._text_queue.maxsize
        ):
            raise queue_module.Full

    def _put_locked(self, value: object) -> None:
        self._text_queue.queue.append(value)
        self._text_queue.unfinished_tasks += 1
        self._text_queue.not_empty.notify()

    @staticmethod
    def _set_event_locked(event: threading.Event) -> None:
        event._flag = True
        event._cond.notify_all()


@dataclass(frozen=True, slots=True)
class PreparedProviderStreamStateSeal:
    """Immutable terminal payload for one owner-controlled stream publish."""

    owner: _ProviderStreamPublicationOwner
    full_text: str

    def commit(self, admission: ProviderEffectAdmission) -> bool:
        return self.owner.publish_terminal(self.full_text, admission)


@dataclass(frozen=True, slots=True)
class ProviderTextStream:
    """A direct iterable over provider text chunks without event-bus routing."""

    _chunks: Iterable[str]
    _token: object | None = None

    def __iter__(self) -> Iterator[str]:
        iterator = iter(self._chunks)
        try:
            while not _token_cancelled(self._token):
                try:
                    chunk = next(iterator)
                except StopIteration:
                    return
                if _token_cancelled(self._token):
                    return
                yield chunk
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()


@dataclass(frozen=True, slots=True)
class ProviderExecutionCallbacks:
    """Engine adapters used by the authoritative provider execution policy."""

    freeze_normal_request: Callable[[], object]
    is_normal_request: Callable[[object], bool]
    prepared_normal_request: Callable[[object], FrozenTurnRequest]
    transaction_for_request: Callable[[object], object]
    claim_dispatch: Callable[[object, FrozenTurnRequest, str], None]
    transaction_cancel_token: Callable[[object], object]
    assert_transaction_current: Callable[[object, str], None]
    complete_empty_transaction: Callable[[object], None]
    build_request: Callable[[object], object]
    copy_request: Callable[[object], tuple[dict[str, Any], dict[str, Any]]]
    legacy_complete: Callable[[dict[str, Any], dict[str, Any]], object]
    legacy_stream: Callable[[dict[str, Any], dict[str, Any]], Iterable[str]]
    begin_request_marker: Callable[[ProviderEffectAdmission], None]
    end_request_marker: Callable[[ProviderEffectAdmission], None]
    revoke_request_marker: Callable[[ProviderEffectAdmission], None]
    register_stream_state: Callable[
        [object, object, ProviderEffectAdmission],
        None,
    ]
    unregister_stream_state: Callable[[object, ProviderEffectAdmission], None]
    revoke_stream_state: Callable[[object, ProviderEffectAdmission], None]
    stream_chunk_limits: Callable[[], tuple[int, int]]
    create_chunk_assembler: Callable[[int, int, object], object]
    prepare_speech_chunk: Callable[[str, bool], str]
    visual_tag_start_search: Callable[[str], object | None]
    stop_requested: Callable[[], bool]
    stream_log: Callable[[str, ProviderEffectAdmission], None]
    terminal_stream_log: Callable[[str, ProviderEffectAdmission], None]
    record_reply_event: Callable[[object, str, ProviderEffectAdmission], None]
    accumulate_reply_metric: Callable[
        [object, str, object, ProviderEffectAdmission],
        None,
    ]
    log: Callable[[str, ProviderEffectAdmission], None]
    memory_review_cancelled_error: type[BaseException]
    context_limit_error: type[BaseException]
    blocked_error: type[BaseException]


class _CombinedCancellation:
    def __init__(self, *tokens: object) -> None:
        self._tokens = tokens

    @property
    def cancelled(self) -> bool:
        return self.is_set()

    def is_set(self) -> bool:
        return any(_token_cancelled(token) for token in self._tokens)


class _ProviderStreamFinalizer:
    def __init__(
        self,
        callbacks: ProviderExecutionCallbacks,
        output: _ProviderStreamPublicationOwner,
        registration_operation: ProviderEffectAdmission,
        lease: WorkLease,
    ) -> None:
        self._callbacks = callbacks
        self._output = output
        self._state = output.state
        self._lease = lease
        self._condition = threading.Condition()
        self._effect_admissions: set[ProviderEffectAdmission] = set()
        self._closed = False
        self._cancelled = False
        self._worker_close_started = False
        self._request_operation = self._new_admission("request_marker")
        self._request_operations = [self._request_operation]
        self._started_request_ids: set[int] = set()
        self._registration_operation = registration_operation
        self._log_operation = self._new_admission("terminal_stream_log")
        self._state_operation = self._new_admission("stream_state_seal")
        self._full_parts: list[str] = []

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def append_text(self, text: str) -> bool:
        prepared_text = str(text)
        with self._condition:
            if self._closed:
                return False
            self._full_parts.append(prepared_text)
            return True

    def set_error(self, error: object) -> bool:
        prepared_error = str(error or "")
        with self._condition:
            if self._closed:
                return False
            self._state.__dict__["error"] = prepared_error
            return True

    def run_effect(
        self,
        callback: Callable[[ProviderEffectAdmission], None],
    ) -> bool:
        with self._condition:
            if self._closed:
                return False
            admission = self._new_admission("optional_stream_effect")
            self._effect_admissions.add(admission)
        try:
            callback(admission)
        finally:
            if admission.pending:
                admission.revoke()
            with self._condition:
                self._effect_admissions.discard(admission)
        return admission.status == "completed"

    def begin_request(self) -> bool:
        with self._condition:
            if self._closed:
                return False
            self._started_request_ids.add(id(self._request_operation))
        try:
            self._callbacks.begin_request_marker(self._request_operation)
        except BaseException:
            self._callbacks.revoke_request_marker(self._request_operation)
            raise
        return self._request_operation.pending

    def create_request_operation(self) -> ProviderEffectAdmission | None:
        with self._condition:
            if self._closed:
                return None
            operation = self._new_admission("fallback_request_marker")
            self._request_operations.append(operation)
            self._started_request_ids.add(id(operation))
            return operation

    def cancel(self, _reason: str) -> None:
        with self._condition:
            self._cancelled = True
            self._closed = True
            effect_admissions = tuple(self._effect_admissions)
            request_operations = tuple(self._request_operations)

        first_error: BaseException | None = None
        try:
            self._state_operation.revoke()
        except BaseException as exc:
            first_error = exc
        try:
            self._output.request_cancel()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        for operation in effect_admissions:
            try:
                operation.revoke()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        try:
            self._callbacks.revoke_stream_state(
                self._state,
                self._registration_operation,
            )
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        try:
            self._log_operation.revoke()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        for operation in request_operations:
            try:
                self._callbacks.revoke_request_marker(operation)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def close(self) -> None:
        with self._condition:
            if self._worker_close_started:
                return
            self._worker_close_started = True
            self._closed = True
            cancelled = self._cancelled
            request_operations = tuple(
                operation
                for operation in self._request_operations
                if id(operation) in self._started_request_ids
            )

        if cancelled:
            return

        first_error: BaseException | None = None
        try:
            self._seal_stream_state()
        except BaseException as exc:
            first_error = exc

        if self._registration_operation.pending:
            try:
                self._callbacks.unregister_stream_state(
                    self._state,
                    self._registration_operation,
                )
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if self._registration_operation.pending:
            try:
                self._callbacks.revoke_stream_state(
                    self._state,
                    self._registration_operation,
                )
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        if self._log_operation.pending:
            try:
                self._callbacks.terminal_stream_log(
                    self._final_log_message(),
                    self._log_operation,
                )
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if self._log_operation.pending:
            try:
                self._log_operation.revoke()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        for operation in request_operations:
            if not operation.pending:
                continue
            try:
                self._callbacks.end_request_marker(operation)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
            if operation.pending:
                try:
                    self._callbacks.revoke_request_marker(operation)
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

    def _seal_stream_state(self) -> None:
        if not self._state_operation.pending:
            return
        with self._condition:
            full_parts = tuple(self._full_parts)
        full_text = "".join(full_parts).strip()
        prepared = self._output.prepare_terminal(full_text)
        prepared.commit(self._state_operation)

    def _final_log_message(self) -> str:
        with self._condition:
            full_parts = tuple(self._full_parts)
        full_text = "".join(full_parts).strip()
        return (
            "🌊 [Stream] Reply stream done: "
            f"total_chars={len(full_text)} "
            f"emitted_any={self._state.first_chunk_emitted.is_set()}"
        )

    def _new_admission(self, purpose: str) -> ProviderEffectAdmission:
        return ProviderEffectAdmission(lease=self._lease, purpose=purpose)


class ProviderService:
    """Own provider execution policy around the existing registry runtime."""

    def __init__(
        self,
        runtime: ChatProviderRuntime,
        *,
        workers: WorkerSupervisor | None = None,
        worker_lease: Callable[[], WorkLease] | None = None,
        model_unload: ModelUnload | None = None,
        model_load: ModelLoad | None = None,
        preserved_model_load: ModelLoad | None = None,
        preserved_chat_model_load: ModelLoad | None = None,
        model_inspect: ModelInspect | None = None,
        model_unload_one: ModelUnloadOne | None = None,
        auxiliary_model_unload: ModelUnload | None = None,
        auxiliary_model_load: ModelLoad | None = None,
        is_model_placeholder: ModelPlaceholderCheck | None = None,
        main_chat_context_length: Callable[[], int | None] | None = None,
        resource_model_inspect: ModelInspect | None = None,
        resource_model_unload_one: ModelUnloadOne | None = None,
    ) -> None:
        self._owned_runtime = runtime
        self.communication_trace = None
        self._workers = workers
        self._worker_lease = worker_lease
        self._model_unload = model_unload
        self._model_load = model_load
        self._preserved_model_load = preserved_model_load or model_load
        self._preserved_chat_model_load = preserved_chat_model_load or self._preserved_model_load
        self._model_inspect = model_inspect
        self._resource_model_inspect = resource_model_inspect or model_inspect
        self._model_unload_one = model_unload_one
        self._resource_model_unload_one = resource_model_unload_one or model_unload_one
        self._auxiliary_model_unload = auxiliary_model_unload or model_unload
        self._auxiliary_model_load = auxiliary_model_load or model_load
        self._is_model_placeholder = is_model_placeholder or (lambda _model: False)
        self._main_chat_context_length = main_chat_context_length or (lambda: None)
        self._model_state_condition = threading.Condition()
        self._model_operation_active = False
        self._active_lmstudio_model_name = ""
        self._active_lmstudio_endpoint = ""
        self._lmstudio_inference_lock = threading.RLock()
        self._auxiliary_model_lock = threading.Lock()
        self._auxiliary_lmstudio_models: dict[str, str] = {}
        self._preserved_lmstudio_models: dict[
            tuple[tuple[str, str, int | None], str],
            PreservedLMStudioModel,
        ] = {}
        self._activity_lock = threading.Lock()
        self._active_requests = 0

    def active(self) -> bool:
        with self._activity_lock:
            return self._active_requests > 0

    def resource_model_snapshot(self, selection: ProviderSelection):
        """Inspect all resident instances; never prepare or reload a selection."""
        if selection.provider_id != "lmstudio" or self._resource_model_inspect is None:
            return []
        instances = tuple(self._resource_model_inspect(selection.endpoint))
        endpoint = _lmstudio_endpoint_identity(selection.endpoint)
        with self._auxiliary_model_lock:
            preserved = tuple(self._preserved_lmstudio_models.values())
        active = self.active()
        return [{"id": item.identifier, "name": item.model_key, "model": item.model_key,
                 "owner": "LM Studio · " + selection.endpoint,
                 "processEndpoint": selection.endpoint, "processBackend": "lmstudio",
                 "processLabel": "LM Studio",
                 "device": "Managed by LM Studio", "canUnload": self._resource_model_unload_one is not None,
                 "users": (["Model request"] if active else []) + [
                     r.owner.replace('_', ' ') for r in preserved
                     if _lmstudio_endpoint_identity(r.endpoint) == endpoint and r.identifier == item.identifier],
                 "memoryNote": "LM Studio does not report RAM/VRAM allocation per instance through this inspection API."}
                for item in instances]

    def resource_model_operation(self, callback):
        """Serialize a non-LM-Studio maintenance call with request admission."""
        with self._activity_lock:
            if self._active_requests:
                return False
            return callback()

    def unload_resource_model(self, selection: ProviderSelection, identifier: str) -> bool:
        """Unload exactly one idle instance, serialized with inference and pins."""
        if selection.provider_id != "lmstudio" or self._resource_model_inspect is None or self._resource_model_unload_one is None:
            return False
        # Follow the existing auxiliary -> inference lock order.
        with self._auxiliary_model_lock:
            if not self._lmstudio_inference_lock.acquire(blocking=False):
                return False
            try:
                with self._activity_lock:
                    if self._active_requests:
                        return False
                    with self._model_state_condition:
                        if self._model_operation_active:
                            return False
                        # Reserve atomically; concurrent load/prepare must wait
                        # until this exact-instance operation has finished.
                        previous = (self._active_lmstudio_model_name, self._active_lmstudio_endpoint)
                        self._model_operation_active = True
                    unloaded = False
                    try:
                        endpoint = _lmstudio_endpoint_identity(selection.endpoint)
                        if any(_lmstudio_endpoint_identity(r.endpoint) == endpoint and r.identifier == identifier
                               for r in self._preserved_lmstudio_models.values()):
                            return False
                        if not any(m.identifier == identifier for m in self._resource_model_inspect(selection.endpoint)):
                            return False
                        unloaded = bool(self._resource_model_unload_one(identifier, selection.endpoint))
                        return unloaded
                    finally:
                        self._finish_model_operation(*(('','') if unloaded else previous))
            finally:
                self._lmstudio_inference_lock.release()

    def model_residency_snapshot(
        self,
        selection: ProviderSelection,
    ) -> Mapping[str, object]:
        """Return a bounded, read-only LM Studio residency snapshot."""

        if not isinstance(selection, ProviderSelection):
            raise TypeError("Model residency snapshots require ProviderSelection.")
        endpoint = str(selection.endpoint or "").strip()
        if selection.provider_id != "lmstudio" or self._model_inspect is None:
            return {
                "provider_id": selection.provider_id,
                "model_id": selection.model_id,
                "endpoint": endpoint,
                "inspection_available": False,
                "requested_loaded": None,
                "loaded_models": [],
            }
        try:
            instances = tuple(self._model_inspect(endpoint))
        except BaseException as exc:
            return {
                "provider_id": selection.provider_id,
                "model_id": selection.model_id,
                "endpoint": endpoint,
                "inspection_available": True,
                "requested_loaded": None,
                "loaded_models": [],
                "error": str(exc)[:500],
            }
        return {
            "provider_id": selection.provider_id,
            "model_id": selection.model_id,
            "endpoint": endpoint,
            "inspection_available": True,
            "requested_loaded": any(
                _lmstudio_model_key_matches(selection.model_id, item.model_key)
                for item in instances
            ),
            "loaded_models": [
                {
                    "identifier": str(item.identifier or ""),
                    "model_key": str(item.model_key or ""),
                }
                for item in instances[:16]
            ],
        }

    def begin_request(self) -> None:
        with self._activity_lock:
            self._active_requests += 1

    def end_request(self) -> None:
        with self._activity_lock:
            self._active_requests = max(0, self._active_requests - 1)

    @property
    def runtime(self) -> ChatProviderRuntime:
        return self._owned_runtime

    def capture_selection(
        self,
        config: RuntimeConfigSnapshot,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        provider_config_override: Mapping[str, object] | None = None,
    ) -> ProviderSelection:
        if not isinstance(config, RuntimeConfigSnapshot):
            raise TypeError("Provider selection requires RuntimeConfigSnapshot.")
        values = config.values
        runtime = self.runtime
        from core.runtime_chat import ChatProviderRuntime

        if isinstance(runtime, ChatProviderRuntime):
            selected_provider_id = chat_providers.normalize_provider_id(
                str(
                    provider_id
                    if provider_id is not None
                    else values.get(
                        "chat_provider",
                        chat_providers.DEFAULT_PROVIDER_ID,
                    )
                    or ""
                ),
                fallback=chat_providers.DEFAULT_PROVIDER_ID,
            )
            selected_model_id = str(
                model_id
                if model_id is not None
                else values.get("model_name", "")
                or ""
            ).strip()
            context = runtime.capture_frozen_context(
                provider=selected_provider_id,
                model=selected_model_id,
                provider_config=(
                    dict(provider_config_override)
                    if isinstance(provider_config_override, Mapping)
                    else None
                ),
                runtime_config=config,
            )
        else:
            if provider_config_override is not None:
                raise TypeError(
                    "Provider config overrides require ChatProviderRuntime."
                )
            context = runtime.capture_frozen_context()
            selected_provider_id = str(
                getattr(context, "provider_name", values.get("chat_provider", ""))
                or ""
            ).strip().lower()
            selected_model_id = str(
                getattr(context, "model_name", values.get("model_name", ""))
                or ""
            ).strip()
        return ProviderSelection(
            selected_provider_id,
            selected_model_id,
            config,
            context,
        )

    def selection_from_context(
        self,
        context: chat_providers.FrozenChatProviderContext,
        config: RuntimeConfigSnapshot,
    ) -> ProviderSelection:
        return ProviderSelection(
            provider_id=str(getattr(context, "provider_name", "") or ""),
            model_id=str(getattr(context, "model_name", "") or ""),
            config=config,
            context=context,
        )

    def supports_images(self, selection: ProviderSelection) -> bool:
        """Resolve image support for the accepted model, not the live selection."""
        if not isinstance(selection, ProviderSelection):
            raise TypeError("Image capability requires ProviderSelection.")
        try:
            catalog = self.list_models(selection.provider_id, quiet=True)
        except Exception:
            catalog = ()
        for item in catalog:
            if not isinstance(item, Mapping):
                continue
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            if model_id == selection.model_id and isinstance(item.get("supports_images"), bool):
                return item["supports_images"]
        return self.readiness(selection).supports_images

    def readiness(self, selection: ProviderSelection) -> ProviderReadiness:
        """Project task readiness from the frozen model/config selection."""

        if not isinstance(selection, ProviderSelection):
            raise TypeError("Provider readiness requires ProviderSelection.")
        metadata = chat_providers.provider_metadata(selection.provider_id)
        environment_names: tuple[str, ...] = ()
        for field in metadata.get("config_fields", ()) or ():
            if not isinstance(field, Mapping) or str(
                field.get("id", "") or ""
            ).strip() != "api_key":
                continue
            environment_names = tuple(
                str(name or "").strip()
                for name in field.get("env", ()) or ()
                if str(name or "").strip()
            )
            break
        explicit_images = selection.config.values.get(
            "model_supports_images",
            None,
        )
        supports_images = (
            bool(explicit_images)
            if explicit_images is not None
            else infer_model_supports_images(selection.model_id)
        )
        hosted_runtime = bool(metadata.get("supports_hosted_runtime"))
        api_key_available = bool(
            str(self.runtime.provider_api_key(selection.provider_id) or "").strip()
        )
        return ProviderReadiness(
            selection=selection,
            label=self.runtime.provider_label(selection.provider_id),
            model_selected=not self._is_model_placeholder(selection.model_id),
            supports_images=supports_images,
            hosted_runtime=hosted_runtime,
            api_key_available=api_key_available,
            api_key_environment_names=environment_names,
        )

    def apply_generation_fields(
        self,
        selection: ProviderSelection,
        params: dict[str, Any],
        additional_params: dict[str, Any],
    ) -> None:
        """Apply generation options from the selection's frozen config snapshot."""

        if not isinstance(selection, ProviderSelection):
            raise TypeError("Frozen generation fields require ProviderSelection.")
        if not isinstance(params, dict) or not isinstance(additional_params, dict):
            raise TypeError("Provider generation targets must be dictionaries.")
        from core.runtime_chat import ChatProviderRuntime

        frozen_runtime = ChatProviderRuntime(lambda: selection.config)
        frozen_runtime.apply_generation_fields(
            params,
            additional_params,
            provider=selection.provider_id,
        )

    def prepare(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
    ) -> FrozenTurnRequest:
        if not isinstance(selection, ProviderSelection):
            raise TypeError("Frozen provider preparation requires ProviderSelection.")
        if not isinstance(request, PromptRequest):
            raise TypeError("Frozen provider preparation requires PromptRequest.")
        request = _with_frozen_output_budget(selection, request)
        params = request.params_copy()
        runtime = self.runtime
        normalizer = getattr(runtime, "normalize_request_params", None)
        if callable(normalizer):
            params = normalizer(
                selection.provider_id,
                params,
                runtime_config=selection.config,
            )
        else:
            from core import runtime_chat as runtime_chat_module

            params = runtime_chat_module.normalize_provider_request_params(
                selection.provider_id,
                params,
                runtime_config=selection.config,
            )
        return runtime.prepare_frozen_request(
            selection.context,
            params,
            request.additional_params_copy(),
        )

    def _trace_request(self, request):
        from core.communication_trace import current_correlation, record_to
        import uuid
        correlation=current_correlation()
        correlation['request_id']=uuid.uuid4().hex
        if self.communication_trace is None or self.communication_trace.snapshot()['state'] != 'recording':
            return correlation
        from core.native_tool_calls import trace_options
        record_to(self.communication_trace,'provider.request',dict(
            provider=request.context.provider_name,model=request.context.model_name,
            params=request.params_copy(),additional_params=trace_options(request.additional_params_copy())),correlation)
        return correlation

    def _trace_legacy_request(self, provider, params, additional_params):
        from core.communication_trace import current_correlation, record_to
        import uuid
        correlation=dict(current_correlation(),request_id=uuid.uuid4().hex)
        record_to(self.communication_trace,'provider.request',dict(provider=provider,
            model=params.get('model',''),params=params,additional_params=additional_params),correlation)
        return correlation

    def _trace_legacy_complete(self, callback, correlation):
        from core.communication_trace import record_to
        try:
            value=callback()
        except Exception as exc:
            record_to(self.communication_trace,'provider.error',dict(error=exc),correlation)
            raise
        record_to(self.communication_trace,'provider.response',dict(text=value),correlation)
        return value

    def _trace_legacy_stream(self, callback, correlation):
        from core.communication_trace import record_to
        try:
            for chunk in callback():
                record_to(self.communication_trace,'provider.chunk',dict(text=chunk),correlation)
                yield chunk
        except Exception as exc:
            record_to(self.communication_trace,'provider.error',dict(error=exc),correlation)
            raise
        finally:
            record_to(self.communication_trace,'provider.stream_end',{},correlation)

    def complete(
        self,
        request: FrozenTurnRequest,
        token: object,
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult[str]:
        from core.communication_trace import record_to
        correlation=self._trace_request(request)
        if _token_cancelled(token):
            record_to(self.communication_trace,'provider.cancelled',dict(reason='before dispatch'),correlation)
            return CommandResult(
                accepted=False,
                failure=RuntimeFailure(
                    "provider_cancelled",
                    "Provider completion was cancelled before dispatch.",
                ),
            )
        try:
            self.begin_request()
            try:
                lock = (
                    self._lmstudio_inference_lock
                    if str(request.context.provider_name or "").strip().lower()
                    in {"lmstudio", "lmstudio_sdk"}
                    else nullcontext()
                )
                with lock:
                    value = self.runtime.complete_frozen(
                        request,
                        timeout=timeout_seconds,
                        cancel_token=token,
                    )
            finally:
                self.end_request()
        except Exception as exc:
            record_to(self.communication_trace,'provider.error',_provider_error_trace_payload(exc),correlation)
            return CommandResult(
                accepted=False,
                failure=RuntimeFailure(
                    "provider_execution",
                    str(exc) or type(exc).__name__,
                    cause=exc,
                ),
            )
        from core.conversation_tools import TOOL_OPTION
        from core.native_tool_calls import trace_response
        trace_text=trace_response(str(value or '')) if TOOL_OPTION in request.additional_params_copy() else str(value or '')
        record_to(self.communication_trace,'provider.response',dict(text=trace_text),correlation)
        return CommandResult(accepted=True, value=str(value or ""))

    def stream(
        self,
        request: FrozenTurnRequest,
        token: object,
        *,
        timeout_seconds: float | None = None,
    ) -> ProviderTextStream:
        from core.communication_trace import record_to
        correlation=self._trace_request(request)
        if _token_cancelled(token):
            record_to(self.communication_trace,'provider.cancelled',dict(reason='before stream'),correlation)
            return ProviderTextStream(())
        def recorded_stream():
            finished=False
            try:
                for chunk in self.runtime.stream_frozen(request,timeout=timeout_seconds,cancel_token=token):
                    from core.conversation_tools import TOOL_OPTION
                    from core.native_tool_stream import trace_event
                    trace_chunk=trace_event(chunk) if TOOL_OPTION in request.additional_params_copy() else chunk
                    record_to(self.communication_trace,'provider.chunk',dict(text=trace_chunk),correlation)
                    yield chunk
                finished=True
            except Exception as exc:
                record_to(self.communication_trace,'provider.error',_provider_error_trace_payload(exc),correlation)
                raise
            finally:
                record_to(self.communication_trace,'provider.stream_end',dict(
                    finished=finished,cancelled=_token_cancelled(token)),correlation)
        return ProviderTextStream(
            self._tracked_stream(
                recorded_stream,
                inference_lock=(
                    self._lmstudio_inference_lock
                    if str(request.context.provider_name or "").strip().lower()
                    in {"lmstudio", "lmstudio_sdk"}
                    else None
                ),
            ),
            token,
        )

    def complete_reply(
        self,
        callbacks: ProviderExecutionCallbacks,
        request_context: object = None,
        prepared_request: object = None,
        *,
        discard_empty_transaction: bool = True,
        emit_console_output: bool = True,
        request_operation: ProviderEffectAdmission | None = None,
        effect_runner: Callable[
            [Callable[[ProviderEffectAdmission], None]],
            bool,
        ]
        | None = None,
        ) -> str:
        """Execute one completion while preserving frozen transaction claims."""

        request_operation = request_operation or ProviderEffectAdmission(
            purpose="completion_request_marker"
        )

        def publish_optional(
            effect: Callable[[ProviderEffectAdmission], None],
        ) -> bool:
            if effect_runner is not None:
                return effect_runner(effect)
            admission = ProviderEffectAdmission(purpose="completion_log")
            try:
                effect(admission)
            finally:
                if admission.pending:
                    admission.revoke()
            return admission.status == "completed"

        try:
            callbacks.begin_request_marker(request_operation)
            if not request_operation.pending:
                return ""
            if callbacks.is_normal_request(request_context):
                if prepared_request is None:
                    prepared_request = callbacks.prepared_normal_request(
                        request_context
                    )
                transaction = callbacks.transaction_for_request(request_context)
                callbacks.claim_dispatch(
                    transaction,
                    prepared_request,
                    "completion",
                )
                provider_result = self.complete(
                    prepared_request,
                    callbacks.transaction_cancel_token(transaction),
                )
                if not provider_result.accepted:
                    failure = provider_result.failure
                    if failure is not None and failure.cause is not None:
                        raise failure.cause
                    raise RuntimeError(
                        failure.message
                        if failure is not None
                        else "Provider completion failed."
                    )
                callbacks.assert_transaction_current(
                    transaction,
                    "provider completion",
                )
                response_text = str(provider_result.value or "")
                if not response_text and discard_empty_transaction:
                    callbacks.complete_empty_transaction(request_context)
                return response_text
            if prepared_request is None:
                prepared_request = callbacks.build_request(request_context)
            params, additional_params = callbacks.copy_request(prepared_request)
            if not request_operation.pending:
                return ""
            return str(callbacks.legacy_complete(params, additional_params) or "")
        except callbacks.memory_review_cancelled_error:
            if emit_console_output:
                publish_optional(
                    lambda admission: callbacks.log(
                        "🧠 [Memory] Reply cancelled during manual image review.",
                        admission,
                    )
                )
            return ""
        except callbacks.context_limit_error as exc:
            context_limit_message = f"⚠️ Context limit reached: {exc}"
            if emit_console_output:
                publish_optional(
                    lambda admission: callbacks.log(
                        context_limit_message,
                        admission,
                    )
                )
            return str(exc)
        except callbacks.blocked_error:
            raise
        except Exception as exc:
            error_message = f"✗ LLM Error: {exc}"
            if emit_console_output:
                publish_optional(
                    lambda admission: callbacks.log(
                        error_message,
                        admission,
                    )
                )
            return "I'm having trouble thinking right now."
        finally:
            try:
                if request_operation.pending:
                    callbacks.end_request_marker(request_operation)
            finally:
                if request_operation.pending:
                    callbacks.revoke_request_marker(request_operation)

    def start_streamed_reply(
        self,
        callbacks: ProviderExecutionCallbacks,
        text_queue: object,
        *,
        dry_run_reply_id: object = None,
        request_context: object = None,
        preserve_voice_labels: bool = False,
    ) -> object:
        """Start the existing single worker with service-owned stream policy."""

        if self._workers is None or self._worker_lease is None:
            raise RuntimeError(
                "Provider streaming requires composed worker supervision."
            )
        worker_lease = self._worker_lease()
        if not isinstance(worker_lease, WorkLease):
            raise TypeError("Provider stream worker capture requires WorkLease.")
        request_context = request_context or callbacks.freeze_normal_request()
        state = streaming_text.StreamingReplyState()
        output = _ProviderStreamPublicationOwner(state, text_queue)
        registration_operation = ProviderEffectAdmission(
            lease=worker_lease,
            purpose="stream_registration",
        )
        callbacks.register_stream_state(
            state,
            request_context,
            registration_operation,
        )
        stream_target_chars, stream_max_chars = callbacks.stream_chunk_limits()
        assembler = callbacks.create_chunk_assembler(
            stream_target_chars,
            stream_max_chars,
            text_queue,
        )
        finalizer = _ProviderStreamFinalizer(
            callbacks,
            output,
            registration_operation,
            worker_lease,
        )

        def worker(supervisor_token: CancellationToken) -> None:
            first_token_at: float | None = None
            visual_tail_open = False
            cancellation = _CombinedCancellation(
                state.cancel_requested,
                supervisor_token,
            )

            def strip_visual_tail(raw_text: str) -> str:
                nonlocal visual_tail_open
                text = str(raw_text or "")
                if not text:
                    return ""
                cleaned_parts: list[str] = []
                if visual_tail_open:
                    close_index = text.find("]")
                    if close_index < 0:
                        return ""
                    visual_tail_open = False
                    text = text[close_index + 1:]
                while text:
                    match = callbacks.visual_tag_start_search(text)
                    if match is None:
                        cleaned_parts.append(text)
                        break
                    cleaned_parts.append(text[:match.start()])
                    tail = text[match.end():]
                    close_index = tail.find("]")
                    if close_index < 0:
                        visual_tail_open = True
                        break
                    text = tail[close_index + 1:]
                return "".join(cleaned_parts)

            def emit_chunk(chunk_info: object, *, final: bool = False) -> bool:
                if not isinstance(chunk_info, dict):
                    return True

                raw_chunk_text = str(chunk_info.get("text", "") or "")
                chunk_text = callbacks.prepare_speech_chunk(
                    strip_visual_tail(raw_chunk_text),
                    bool(preserve_voice_labels),
                )
                if not chunk_text:
                    return True

                if not finalizer.run_effect(
                    lambda admission: output.publish_text(
                        chunk_text,
                        admission,
                        mark_first_chunk=True,
                    )
                ):
                    return False
                metrics = (
                    (
                        "chunk_quality_sum",
                        float(chunk_info.get("quality", 0.0) or 0.0),
                    ),
                    ("chunk_quality_count", 1),
                    (
                        "chunk_chars_sum",
                        int(
                            chunk_info.get("chars", len(raw_chunk_text))
                            or len(raw_chunk_text)
                        ),
                    ),
                    ("chunk_chars_count", 1),
                )
                for metric, value in metrics:
                    if not finalizer.run_effect(
                        lambda admission, metric=metric, value=value: (
                            callbacks.accumulate_reply_metric(
                                dry_run_reply_id,
                                metric,
                                value,
                                admission,
                            )
                        )
                    ):
                        return False
                label = "Final chunk" if final else "Chunk"
                message = (
                    f"🌊 [Stream] {label} emitted: chars={len(chunk_text.strip())} "
                    f"quality={float(chunk_info.get('quality', 0.0) or 0.0):.2f} "
                    f"reason={chunk_info.get('reason', 'unknown')} "
                    f"text={raw_chunk_text[:240]!r}"
                )
                return finalizer.run_effect(
                    lambda admission: callbacks.stream_log(message, admission)
                )

            prepared_request = None
            try:
                if _token_cancelled(cancellation):
                    return
                if not finalizer.run_effect(
                    lambda admission: callbacks.stream_log(
                        "🌊 [Stream] Reply stream started: "
                        f"target_chars={stream_target_chars} "
                        f"max_chars={stream_max_chars}",
                        admission,
                    )
                ):
                    return
                if not finalizer.run_effect(
                    lambda admission: callbacks.record_reply_event(
                        dry_run_reply_id,
                        "stream_reply_started_at",
                        admission,
                    )
                ):
                    return
                if not finalizer.begin_request():
                    return
                if callbacks.is_normal_request(request_context):
                    prepared_request = callbacks.prepared_normal_request(
                        request_context
                    )
                    transaction = callbacks.transaction_for_request(
                        request_context
                    )
                    callbacks.claim_dispatch(
                        transaction,
                        prepared_request,
                        "stream",
                    )
                    stream = self.stream(
                        prepared_request,
                        cancellation,
                    )
                    callbacks.assert_transaction_current(
                        transaction,
                        "provider stream startup",
                    )
                else:
                    transaction = None
                    prepared_request = callbacks.build_request(request_context)
                    params, additional_params = callbacks.copy_request(
                        prepared_request
                    )
                    stream = callbacks.legacy_stream(params, additional_params)
                for content in stream:
                    if _token_cancelled(cancellation) or callbacks.stop_requested():
                        break
                    if transaction is not None:
                        callbacks.assert_transaction_current(
                            transaction,
                            "provider stream",
                        )
                    if _token_cancelled(cancellation) or callbacks.stop_requested():
                        break
                    if not content:
                        continue
                    now = time.time()
                    if first_token_at is None:
                        first_token_at = now
                        if not finalizer.run_effect(
                            lambda admission: callbacks.stream_log(
                                "🌊 [Stream] First token received: "
                                f"len={len(content)}",
                                admission,
                            )
                        ):
                            break
                        if not finalizer.run_effect(
                            lambda admission: callbacks.record_reply_event(
                                dry_run_reply_id,
                                "first_token_at",
                                admission,
                            )
                        ):
                            break
                    if not finalizer.append_text(content):
                        break
                    for chunk_info in assembler.feed(content):
                        if not emit_chunk(chunk_info):
                            break

                if _token_cancelled(cancellation) or callbacks.stop_requested():
                    return
                if transaction is not None:
                    callbacks.assert_transaction_current(
                        transaction,
                        "provider stream completion",
                    )
                for chunk_info in assembler.feed("", final=True):
                    if not emit_chunk(chunk_info, final=True):
                        break
            except callbacks.memory_review_cancelled_error:
                output.request_cancel()
                finalizer.run_effect(
                    lambda admission: callbacks.log(
                        "🧠 [Memory] Streamed reply cancelled during manual image review.",
                        admission,
                    )
                )
            except callbacks.context_limit_error as exc:
                context_limit_text = str(exc)
                if finalizer.set_error(context_limit_text):
                    finalizer.run_effect(
                        lambda admission: output.publish_text(
                            context_limit_text,
                            admission,
                            mark_first_chunk=False,
                        )
                    )
                    finalizer.run_effect(
                        lambda admission: callbacks.log(
                            "⚠️ Streamed context limit reached: "
                            f"{context_limit_text}",
                            admission,
                        )
                    )
                    finalizer.run_effect(
                        lambda admission: callbacks.stream_log(
                            f"🌊 [Stream] Context limit: {context_limit_text}",
                            admission,
                        )
                    )
            except callbacks.blocked_error as exc:
                output.request_cancel()
                blocked_text = str(exc)
                if finalizer.set_error(blocked_text):
                    finalizer.run_effect(
                        lambda admission: callbacks.log(
                            "⚠️ [Identity Relay/Normal Chat] "
                            f"{blocked_text}",
                            admission,
                        )
                    )
                    finalizer.run_effect(
                        lambda admission: callbacks.stream_log(
                            "🌊 [Stream] Frozen transaction cancelled: "
                            f"{blocked_text}",
                            admission,
                        )
                    )
            except Exception as exc:
                error_text = str(exc) or repr(exc)
                if finalizer.closed or _token_cancelled(cancellation):
                    return
                finalizer.run_effect(
                    lambda admission: callbacks.stream_log(
                        f"🌊 [Stream] Error: {error_text}",
                        admission,
                    )
                )
                if (
                    first_token_at is None
                    and not _token_cancelled(cancellation)
                    and not callbacks.stop_requested()
                ):
                    try:
                        if not finalizer.run_effect(
                            lambda admission: callbacks.log(
                                "⚠️ LLM Stream startup failed, falling back to "
                                f"non-stream reply: {error_text}",
                                admission,
                            )
                        ):
                            return
                        fallback_request_operation = (
                            finalizer.create_request_operation()
                        )
                        if fallback_request_operation is None:
                            return
                        fallback_text = self.complete_reply(
                            callbacks,
                            request_context,
                            prepared_request=prepared_request,
                            discard_empty_transaction=False,
                            request_operation=fallback_request_operation,
                            effect_runner=finalizer.run_effect,
                        )
                        if fallback_text:
                            if finalizer.append_text(fallback_text):
                                fallback_chunk = callbacks.prepare_speech_chunk(
                                    fallback_text,
                                    bool(preserve_voice_labels),
                                )
                                if fallback_chunk:
                                    finalizer.run_effect(
                                        lambda admission: output.publish_text(
                                            fallback_chunk,
                                            admission,
                                            mark_first_chunk=True,
                                        )
                                    )
                        else:
                            finalizer.set_error(error_text)
                    except Exception as fallback_exc:
                        fallback_error = str(fallback_exc) or repr(fallback_exc)
                        if finalizer.set_error(fallback_error):
                            finalizer.run_effect(
                                lambda admission: callbacks.log(
                                    f"✗ LLM Stream Error: {error_text}",
                                    admission,
                                )
                            )
                            finalizer.run_effect(
                                lambda admission: callbacks.stream_log(
                                    f"🌊 [Stream] Fallback error: {fallback_error}",
                                    admission,
                                )
                            )
                else:
                    if finalizer.set_error(error_text):
                        finalizer.run_effect(
                            lambda admission: callbacks.log(
                                f"✗ LLM Stream Error: {error_text}",
                                admission,
                            )
                        )
            finally:
                finalizer.close()

        try:
            self._workers.spawn(
                name="nc-llm-stream",
                lease=worker_lease,
                target=worker,
                daemon=True,
                on_cancel=finalizer.cancel,
            )
        except BaseException:
            finalizer.cancel("worker_start_failed")
            raise
        return state

    def list_models(
        self,
        provider_id: str,
        *,
        quiet: bool = False,
    ) -> tuple[object, ...]:
        return tuple(
            self.runtime.list_models(provider=provider_id, quiet=quiet)
        )

    def frozen_execution_available(
        self,
        selection: ProviderSelection,
        *,
        stream: bool = False,
    ) -> bool:
        return self.runtime.frozen_execution_available(
            selection.context,
            stream=stream,
        )

    def upgrade_selection_for_relay(
        self,
        selection: ProviderSelection,
    ) -> ProviderSelection:
        context = self.runtime.upgrade_frozen_context_for_relay(selection.context)
        return selection.with_context(context)

    def strict_relay_capability_available(
        self,
        selection: ProviderSelection,
    ) -> bool:
        return self.runtime.strict_relay_capability_available(selection.context)

    def _model_operations(self):
        return _ModelPreparationOperations(self._model_inspect,self._model_unload_one,
            self._model_unload,self._model_load,self._preserved_chat_model_load,self._main_chat_context_length)

    def _sdk_model_operations(self, selection, cancel_token):
        config = selection.context._binding._provider_config_copy()
        requested = int(config.get('context_length') or 0)
        length = requested or None
        resolved = requested > 0
        def invoke(operation, **fields):
            return chat_providers.run_frozen_model_lifecycle(selection.context,operation=operation,
                cancel_token=cancel_token,**fields)
        def inspect(endpoint):
            nonlocal length,resolved
            rows = invoke('inspect')
            if not isinstance(rows,list):
                raise ValueError('SDK model inventory is invalid.')
            instances = lmstudio_runtime._loaded_model_instances_from_payload(rows)
            if not resolved:
                length = next((item.context_length for item in instances
                    if _lmstudio_model_key_matches(selection.model_id,item.model_key)),None)
                resolved = True
            return instances
        load = lambda model,endpoint: bool(invoke('load',context_length_override=length or 0))
        return _ModelPreparationOperations(inspect,
            lambda identifier,endpoint:bool(invoke('unload_one',identifier=identifier)),
            lambda reason,endpoint:bool(invoke('unload')),load,load,lambda:length,
            lambda:_token_cancelled(cancel_token))

    def _check_model_preparation_current(self, operations, *, release=True):
        if operations.cancelled is not None and operations.cancelled():
            if release:
                self._finish_model_operation('','')
            raise RuntimeError('SDK model preparation cancelled.')

    def prepare_model(
        self,
        selection: ProviderSelection | str,
        model_id: str | None = None,
        *,
        reason: str,
        force_unload: bool = False,
        endpoint: str = "",
        initialize: bool = False,
        cancel_token: object = None,
    ) -> bool:
        if isinstance(selection, ProviderSelection):
            provider_id = selection.provider_id
            model = selection.model_id
            frozen_endpoint = selection.endpoint
        else:
            provider_id = str(selection or "")
            model = str(model_id or "").strip()
            frozen_endpoint = str(endpoint or "").strip()
        provider = chat_providers.normalize_provider_id(
            provider_id,
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        sdk_managed = isinstance(selection, ProviderSelection) and selection.context.model_lifecycle_available
        if sdk_managed and _token_cancelled(cancel_token):
            raise RuntimeError('SDK model preparation cancelled.')
        if provider != "lmstudio" and not sdk_managed:
            return True
        operations = self._sdk_model_operations(selection, cancel_token) if sdk_managed else self._model_operations()
        if operations.unload is None or operations.load is None:
            return True
        active_model_name, active_endpoint = self._begin_model_operation()
        if (
            model
            and not force_unload
            and operations.inspect is not None
            and not self._is_model_placeholder(model)
        ):
            try:
                requested_instances = tuple(
                    item
                    for item in tuple(operations.inspect(frozen_endpoint))
                    if _lmstudio_model_key_matches(model, item.model_key)
                )
                requested_model_loaded = bool(requested_instances)
            except BaseException:
                requested_instances = ()
                requested_model_loaded = None
            requested_profile_ready = bool(
                requested_instances
                and len(requested_instances) == 1
                and _lmstudio_main_chat_profile_matches(
                    requested_instances[0], operations.context_length()
                )
            )
            self._check_model_preparation_current(operations)
            if requested_model_loaded is True and requested_profile_ready:
                self._finish_model_operation(model, frozen_endpoint)
                return True
            if requested_model_loaded is True:
                # A known oversized or parallel load is the common source of
                # startup stalls. Replace only this model instance; preserved
                # Orb vision models on the same endpoint remain untouched.
                force_unload = True
                active_model_name = model
                active_endpoint = frozen_endpoint
            if requested_model_loaded is False and active_model_name == model:
                # LM Studio may evict a model independently while NC still has the
                # old selection cached. Do not send a request that LM Studio could
                # silently route to another loaded model (for example Orb LFM).
                active_model_name = ""
                active_endpoint = ""
        if active_endpoint and active_endpoint != frozen_endpoint:
            active_model_name = ""
            active_endpoint = ""
        endpoint_identity = _lmstudio_endpoint_identity(frozen_endpoint)
        with self._auxiliary_model_lock:
            preserved = bool(
                endpoint_identity is not None
                and any(
                    key_endpoint == endpoint_identity
                    for key_endpoint, _owner in self._preserved_lmstudio_models
                )
            )
            if preserved:
                return self._prepare_model_with_preserved_auxiliaries(
                    provider=provider,
                    model=model,
                    endpoint=frozen_endpoint,
                    active_model_name=active_model_name,
                    active_endpoint=active_endpoint,
                    force_unload=bool(force_unload), operations=operations,
                )
        if (
            operations.inspect is not None
            and operations.unload_one is not None
            and operations.load is not None
        ):
            return self._prepare_model_exact(
                model=model,
                endpoint=frozen_endpoint,
                active_model_name=active_model_name,
                active_endpoint=active_endpoint,
                force_unload=bool(force_unload), operations=operations,
            )
        try:
            ready, active_model = lmstudio_runtime.prepare_chat_model_lifecycle(
                "lmstudio",
                model,
                active_model_name=active_model_name,
                unload_func=lambda reason="": operations.unload(
                    str(reason or ""),
                    frozen_endpoint,
                ),
                load_func=lambda model_name: operations.load(
                    str(model_name or ""),
                    frozen_endpoint,
                ),
                is_placeholder=self._is_model_placeholder,
                reason=str(reason or ""),
                force_unload=bool(force_unload),
            )
        except BaseException:
            self._finish_model_operation("", "")
            raise
        if ready and active_model:
            next_endpoint = (
                frozen_endpoint
                if active_model == model
                else active_endpoint
            )
            self._finish_model_operation(active_model, next_endpoint)
        else:
            self._finish_model_operation("", "")
        return bool(ready)

    def ensure_selection_model_ready(
        self,
        selection: ProviderSelection,
        *,
        reason: str,
        force_unload: bool = False,
    ) -> bool:
        """Prepare the exact captured model without reading live selection state."""

        if not isinstance(selection, ProviderSelection):
            raise TypeError("Provider model readiness requires ProviderSelection.")
        if not self.readiness(selection).model_selected:
            return False
        return self.prepare_model(
            selection,
            reason=reason,
            force_unload=force_unload,
        )

    def prepare_auxiliary_selection_model(
        self,
        selection: ProviderSelection,
        *,
        reason: str,
        model_handling: str,
        owner: str = "",
    ) -> bool:
        """Prepare a dedicated endpoint without changing Main Chat model state."""

        if not isinstance(selection, ProviderSelection):
            raise TypeError("Auxiliary model readiness requires ProviderSelection.")
        if not self.readiness(selection).model_selected:
            return False
        if selection.provider_id != "lmstudio":
            return True

        handling = str(model_handling or "").strip().lower()
        if handling not in {
            "auto_load",
            "already_loaded",
            "auto_with_fallback",
            "parallel_pinned",
        }:
            handling = "auto_load"
        if handling == "already_loaded":
            return True

        endpoint = str(selection.endpoint or "").strip()
        if not endpoint:
            return False
        if handling == "parallel_pinned":
            return self._prepare_preserved_auxiliary_selection_model(
                selection,
                owner=owner,
                endpoint=endpoint,
            )
        with self._model_state_condition:
            main_endpoint = self._active_lmstudio_endpoint
        if (
            main_endpoint
            and _lmstudio_endpoint_identity(main_endpoint)
            == _lmstudio_endpoint_identity(endpoint)
        ):
            return False
        if (
            self._auxiliary_model_unload is None
            or self._auxiliary_model_load is None
        ):
            return True

        with self._auxiliary_model_lock:
            if self._auxiliary_lmstudio_models.get(endpoint) == selection.model_id:
                return True
            try:
                self._auxiliary_model_unload(str(reason or ""), endpoint)
                loaded = bool(
                    self._auxiliary_model_load(selection.model_id, endpoint)
                )
            except BaseException:
                loaded = False
            if loaded:
                self._auxiliary_lmstudio_models[endpoint] = selection.model_id
                return True
            self._auxiliary_lmstudio_models.pop(endpoint, None)
            return handling == "auto_with_fallback"

    def _prepare_preserved_auxiliary_selection_model(
        self,
        selection: ProviderSelection,
        *,
        owner: str,
        endpoint: str,
    ) -> bool:
        clean_owner = str(owner or "").strip()
        model_id = str(selection.model_id or "").strip()
        endpoint_identity = _lmstudio_endpoint_identity(endpoint)
        if (
            not clean_owner
            or not model_id
            or endpoint_identity is None
            or self._model_inspect is None
            or self._preserved_model_load is None
        ):
            return False
        with self._model_state_condition:
            main_model = self._active_lmstudio_model_name
            main_endpoint = self._active_lmstudio_endpoint
        if (
            _lmstudio_model_key_matches(model_id, main_model)
            and _lmstudio_endpoint_identity(main_endpoint) == endpoint_identity
        ):
            return True

        key = (endpoint_identity, clean_owner)
        with self._auxiliary_model_lock:
            existing = self._preserved_lmstudio_models.get(key)
            if existing is not None and existing.model_id != model_id:
                if not self._release_preserved_record(existing):
                    return False
                self._preserved_lmstudio_models.pop(key, None)

            try:
                loaded_instances = tuple(self._model_inspect(endpoint))
            except BaseException:
                return False
            matches = tuple(
                item
                for item in loaded_instances
                if _lmstudio_model_key_matches(model_id, item.model_key)
                and str(item.identifier or "").strip()
            )
            if len(matches) > 1:
                return False
            matching = matches[0] if matches else None
            existing = self._preserved_lmstudio_models.get(key)
            if matching is not None:
                if existing is not None and existing.identifier == matching.identifier:
                    return True
                self._preserved_lmstudio_models[key] = PreservedLMStudioModel(
                    owner=clean_owner,
                    endpoint=endpoint,
                    model_id=model_id,
                    resolved_model_key=matching.model_key,
                    identifier=matching.identifier,
                    owned=False,
                )
                return True

            if existing is not None:
                self._preserved_lmstudio_models.pop(key, None)
            try:
                loaded = bool(self._preserved_model_load(model_id, endpoint))
            except BaseException:
                loaded = False
            if not loaded:
                return False
            try:
                confirmed_instances = tuple(self._model_inspect(endpoint))
            except BaseException:
                return False
            confirmed_matches = tuple(
                item
                for item in confirmed_instances
                if _lmstudio_model_key_matches(model_id, item.model_key)
                and str(item.identifier or "").strip()
            )
            confirmed = (
                confirmed_matches[0]
                if len(confirmed_matches) == 1
                else None
            )
            if confirmed is None:
                return False
            self._preserved_lmstudio_models[key] = PreservedLMStudioModel(
                owner=clean_owner,
                endpoint=endpoint,
                model_id=model_id,
                resolved_model_key=confirmed.model_key,
                identifier=confirmed.identifier,
                owned=True,
            )
            return True

    def preserved_auxiliary_selection_snapshot(
        self,
        selection: ProviderSelection,
        *,
        owner: str,
    ) -> Mapping[str, object]:
        if not isinstance(selection, ProviderSelection):
            raise TypeError("Auxiliary model snapshot requires ProviderSelection.")
        clean_owner = str(owner or "").strip()
        endpoint_identity = _lmstudio_endpoint_identity(selection.endpoint)
        if not clean_owner or endpoint_identity is None:
            return {}
        key = (endpoint_identity, clean_owner)
        with self._auxiliary_model_lock:
            record = self._preserved_lmstudio_models.get(key)
            if record is None or record.model_id != selection.model_id:
                return {}
            return {
                "endpoint": record.endpoint,
                "model_id": record.model_id,
                "resolved_model_key": record.resolved_model_key,
                "identifier": record.identifier,
                "owned": record.owned,
            }

    def adopt_loaded_auxiliary_selection_model(
        self,
        selection: ProviderSelection,
        *,
        owner: str,
    ) -> bool:
        """Record one exact externally managed LM Studio instance without loading."""

        if not isinstance(selection, ProviderSelection):
            raise TypeError("Auxiliary model adoption requires ProviderSelection.")
        clean_owner = str(owner or "").strip()
        model_id = str(selection.model_id or "").strip()
        endpoint = str(selection.endpoint or "").strip()
        endpoint_identity = _lmstudio_endpoint_identity(endpoint)
        if (
            selection.provider_id != "lmstudio"
            or not clean_owner
            or not model_id
            or endpoint_identity is None
            or self._model_inspect is None
        ):
            return False
        try:
            matches = tuple(
                item
                for item in tuple(self._model_inspect(endpoint))
                if _lmstudio_model_key_matches(model_id, item.model_key)
            )
        except BaseException:
            return False
        if len(matches) != 1:
            return False
        match = matches[0]
        key = (endpoint_identity, clean_owner)
        with self._auxiliary_model_lock:
            existing = self._preserved_lmstudio_models.get(key)
            if existing is not None:
                if (
                    existing.model_id == model_id
                    and existing.identifier == match.identifier
                ):
                    return True
                if not self._release_preserved_record(existing):
                    return False
            self._preserved_lmstudio_models[key] = PreservedLMStudioModel(
                owner=clean_owner,
                model_id=model_id,
                endpoint=endpoint,
                resolved_model_key=str(match.model_key or model_id),
                identifier=str(match.identifier or ""),
                owned=False,
            )
            return bool(match.identifier)

    def release_preserved_auxiliary_selection_model(
        self,
        selection: ProviderSelection,
        *,
        owner: str,
        reason: str,
    ) -> bool:
        del reason
        if not isinstance(selection, ProviderSelection):
            raise TypeError("Auxiliary model release requires ProviderSelection.")
        clean_owner = str(owner or "").strip()
        endpoint_identity = _lmstudio_endpoint_identity(selection.endpoint)
        if not clean_owner or endpoint_identity is None:
            return False
        key = (endpoint_identity, clean_owner)
        with self._auxiliary_model_lock:
            record = self._preserved_lmstudio_models.get(key)
            if record is None or record.model_id != selection.model_id:
                return True
            if not self._release_preserved_record(record):
                return False
            self._preserved_lmstudio_models.pop(key, None)
            return True

    def _release_preserved_record(self, record: PreservedLMStudioModel) -> bool:
        if not record.owned:
            return True
        if self._model_unload_one is None:
            return False
        try:
            with self._lmstudio_inference_lock:
                return bool(
                    self._model_unload_one(record.identifier, record.endpoint)
                )
        except BaseException:
            return False

    def reload_selection_model_exact(
        self,
        selection: ProviderSelection,
        *,
        reason: str,
    ) -> bool:
        """Reload only the requested LM Studio model, preserving auxiliaries."""

        del reason
        if not isinstance(selection, ProviderSelection):
            raise TypeError("Exact model reload requires ProviderSelection.")
        if selection.provider_id != "lmstudio":
            return True
        if (
            self._model_inspect is None
            or self._model_unload_one is None
            or self._preserved_model_load is None
        ):
            return False
        model = str(selection.model_id or "").strip()
        endpoint = str(selection.endpoint or "").strip()
        if not model or self._is_model_placeholder(model):
            return False
        self._begin_model_operation()
        try:
            with self._lmstudio_inference_lock:
                instances = tuple(self._model_inspect(endpoint))
                matches = tuple(
                    item
                    for item in instances
                    if _lmstudio_model_key_matches(model, item.model_key)
                    and str(item.identifier or "").strip()
                )
                for item in matches:
                    if not bool(
                        self._model_unload_one(item.identifier, endpoint)
                    ):
                        self._finish_model_operation("", "")
                        return False
                ready = bool(self._preserved_model_load(model, endpoint))
        except BaseException:
            self._finish_model_operation("", "")
            return False
        self._finish_model_operation(model if ready else "", endpoint if ready else "")
        return ready

    def _prepare_model_exact(
        self,
        *,
        model: str,
        endpoint: str,
        active_model_name: str,
        active_endpoint: str,
        force_unload: bool,
        operations=None,
    ) -> bool:
        """Prepare exactly one owned Main Chat instance on a cold endpoint."""

        operations = operations or self._model_operations()
        clean_model = str(model or "").strip()
        if not clean_model or self._is_model_placeholder(clean_model):
            self._finish_model_operation(active_model_name, active_endpoint)
            return True
        try:
            with self._lmstudio_inference_lock:
                instances = tuple(operations.inspect(endpoint))
                requested = tuple(
                    item
                    for item in instances
                    if _lmstudio_model_key_matches(clean_model, item.model_key)
                )
                requested_profile_ready = bool(
                    len(requested) == 1
                    and _lmstudio_main_chat_profile_matches(
                        requested[0], operations.context_length()
                    )
                )
                self._check_model_preparation_current(operations,release=False)
                if requested_profile_ready and not force_unload:
                    self._finish_model_operation(clean_model, endpoint)
                    return True
                if requested and not requested_profile_ready:
                    force_unload = True
                    active_model_name = clean_model
                    active_endpoint = endpoint
                cold_start_recovery = bool(
                    not requested
                    and not str(active_model_name or "").strip()
                )
                if cold_start_recovery:
                    # This exact path is used only when no registered auxiliary
                    # lease exists. Reclaim stale LM Studio instances left from
                    # an earlier NC session before loading the selected main
                    # model, otherwise two 9B models can overcommit VRAM.
                    for item in instances:
                        identifier = str(item.identifier or "").strip()
                        if not identifier:
                            continue
                        if not bool(operations.unload_one(identifier, endpoint)):
                            self._finish_model_operation("", "")
                            return False
                    instances = ()
                stale_model = (
                    clean_model
                    if force_unload
                    else str(active_model_name or "").strip()
                )
                if stale_model and (
                    force_unload or stale_model != clean_model
                ):
                    for item in instances:
                        if not _lmstudio_model_key_matches(
                            stale_model,
                            item.model_key,
                        ):
                            continue
                        if not str(item.identifier or "").strip():
                            continue
                        if not bool(
                            operations.unload_one(item.identifier, endpoint)
                        ):
                            self._finish_model_operation(
                                active_model_name,
                                active_endpoint,
                            )
                            return False
                ready = bool(operations.load(clean_model, endpoint))
        except BaseException:
            self._finish_model_operation("", "")
            raise
        self._finish_model_operation(
            clean_model if ready else "",
            endpoint if ready else "",
        )
        return ready

    def _prepare_model_with_preserved_auxiliaries(
        self,
        *,
        provider: str,
        model: str,
        endpoint: str,
        active_model_name: str,
        active_endpoint: str,
        force_unload: bool,
        operations=None,
    ) -> bool:
        operations = operations or self._model_operations()
        clean_model = str(model or "").strip()
        if (
            provider not in {"lmstudio", "lmstudio_sdk"}
            or not clean_model
            or self._is_model_placeholder(clean_model)
        ):
            self._finish_model_operation(active_model_name, active_endpoint)
            return True
        same_endpoint = (
            _lmstudio_endpoint_identity(active_endpoint)
            == _lmstudio_endpoint_identity(endpoint)
        )
        if same_endpoint and active_model_name == clean_model and not force_unload:
            active_model_loaded = True
            if operations.inspect is not None:
                try:
                    active_model_loaded = any(
                        _lmstudio_model_key_matches(clean_model, item.model_key)
                        and _lmstudio_main_chat_profile_matches(
                            item, operations.context_length()
                        )
                        for item in tuple(operations.inspect(endpoint))
                    )
                except BaseException:
                    active_model_loaded = True
            self._check_model_preparation_current(operations)
            if active_model_loaded:
                self._finish_model_operation(active_model_name, active_endpoint)
                return True

        active_unloaded = False
        try:
            with self._lmstudio_inference_lock:
                if (
                    same_endpoint
                    and active_model_name
                    and operations.inspect is not None
                    and operations.unload_one is not None
                ):
                    instances = tuple(operations.inspect(endpoint))
                    active_instance = next(
                        (
                            item
                            for item in instances
                            if _lmstudio_model_key_matches(
                                active_model_name,
                                item.model_key,
                            )
                        ),
                        None,
                    )
                    if active_instance is not None:
                        active_unloaded = bool(
                            operations.unload_one(
                                active_instance.identifier,
                                endpoint,
                            )
                        )
                ready = bool(operations.preserved_load(clean_model, endpoint))
        except BaseException:
            ready = False
        if ready:
            self._finish_model_operation(clean_model, endpoint)
            return True
        if active_unloaded:
            self._finish_model_operation("", "")
        else:
            self._finish_model_operation(active_model_name, active_endpoint)
        return False

    def unload_selection_models(self, selection: ProviderSelection, *, reason: str, cancel_token: object = None) -> bool:
        if selection.context.model_lifecycle_available:
            active_model,active_endpoint = self._begin_model_operation()
            identity = _lmstudio_endpoint_identity(selection.endpoint)
            with self._auxiliary_model_lock:
                preserved = any(key_endpoint == identity for key_endpoint,_owner in self._preserved_lmstudio_models)
            if preserved:
                self._finish_model_operation(active_model,active_endpoint)
                return False
            try:
                with self._lmstudio_inference_lock:
                    return bool(chat_providers.run_frozen_model_lifecycle(selection.context,
                        operation='unload', reason=reason, cancel_token=cancel_token))
            finally:
                self._finish_model_operation('','')
        return bool(self.unload_lmstudio_models(reason, endpoint=selection.endpoint))

    def unload_lmstudio_models(self, reason: str, *, endpoint: str = "") -> object:
        if self._model_unload is None:
            return False
        active_model, active_endpoint = self._begin_model_operation()
        requested_endpoint = str(endpoint or "").strip()
        endpoint_identity = _lmstudio_endpoint_identity(
            requested_endpoint or active_endpoint
        )
        with self._auxiliary_model_lock:
            preserved = bool(
                endpoint_identity is not None
                and any(
                    key_endpoint == endpoint_identity
                    for key_endpoint, _owner in self._preserved_lmstudio_models
                )
            )
        if preserved:
            self._finish_model_operation(active_model, active_endpoint)
            return False
        try:
            result = self._model_unload(
                str(reason or ""),
                requested_endpoint,
            )
        except BaseException:
            self._finish_model_operation("", "")
            raise
        self._finish_model_operation("", "")
        return result

    def load_lmstudio_model(self, model_id: str, *, endpoint: str = "") -> object:
        if self._model_load is None:
            return False
        model = str(model_id or "").strip()
        frozen_endpoint = str(endpoint or "").strip()
        self._begin_model_operation()
        try:
            result = self._model_load(model, frozen_endpoint)
        except BaseException:
            self._finish_model_operation("", "")
            raise
        if bool(result) and model:
            self._finish_model_operation(model, frozen_endpoint)
        else:
            self._finish_model_operation("", "")
        return result

    def _begin_model_operation(self) -> tuple[str, str]:
        with self._model_state_condition:
            while self._model_operation_active:
                self._model_state_condition.wait()
            self._model_operation_active = True
            return (
                self._active_lmstudio_model_name,
                self._active_lmstudio_endpoint,
            )

    def _finish_model_operation(self, model_id: str, endpoint: str) -> None:
        with self._model_state_condition:
            self._active_lmstudio_model_name = str(model_id or "").strip()
            self._active_lmstudio_endpoint = str(endpoint or "").strip()
            self._model_operation_active = False
            self._model_state_condition.notify_all()

    def complete_legacy(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
    ) -> Any:
        runtime = self.runtime
        provider = runtime.current_provider()
        normalizer = getattr(runtime, "normalize_request_params", None)
        normalized = (
            normalizer(provider, params)
            if callable(normalizer)
            else _normalize_legacy_request(provider, params)
        )
        self.begin_request()
        try:
            correlation=self._trace_legacy_request(provider,normalized,additional_params)
            return self._trace_legacy_complete(lambda:runtime.complete(normalized, additional_params),correlation)
        finally:
            self.end_request()

    def complete_selected_legacy(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
    ) -> str:
        """Run legacy fallback against the captured provider/model/config choice."""

        params, additional_params = self._selected_legacy_payload(
            selection,
            request,
        )
        self.begin_request()
        try:
            correlation=self._trace_legacy_request(selection.provider_id,params,additional_params)
            return self._trace_legacy_complete(lambda: str(
                chat_providers.complete_chat(
                    selection.provider_id,
                    params,
                    additional_params,
                )
                or ""
            ),correlation)
        finally:
            self.end_request()

    def complete_prompt_request(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
        token: object | None = None,
        *,
        reason: str = "provider prompt request",
        timeout_seconds: float | None = None,
        prefer_frozen_execution: bool = False,
        allow_legacy_fallback: bool = True,
        prepare_model: bool = True,
    ) -> str:
        """Execute a captured auxiliary prompt without following live selection."""

        if prepare_model and not self.ensure_selection_model_ready(
            selection,
            reason=reason,
        ):
            raise RuntimeError(
                f"The chat model {selection.model_id!r} could not be prepared "
                f"for {selection.provider_id!r}."
            )
        if prefer_frozen_execution and self.frozen_execution_available(selection):
            bounded_request = _with_frozen_output_budget(selection, request)
            result = self.complete(
                self.prepare(selection, bounded_request),
                token,
                timeout_seconds=timeout_seconds,
            )
            if result.accepted:
                return str(result.value or "")
            failure = result.failure
            if failure is not None and failure.cause is not None:
                raise failure.cause
            raise RuntimeError(
                failure.message
                if failure is not None
                else "Provider completion failed."
            )
        if prefer_frozen_execution and not allow_legacy_fallback:
            raise RuntimeError(
                "Frozen completion is unavailable for the captured provider."
            )
        if not allow_legacy_fallback:
            raise RuntimeError("Selected-provider legacy completion is disabled.")
        return self.complete_selected_legacy(selection, request)

    def stream_legacy(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
    ) -> Iterable[str]:
        runtime = self.runtime
        provider = runtime.current_provider()
        normalizer = getattr(runtime, "normalize_request_params", None)
        normalized = (
            normalizer(provider, params)
            if callable(normalizer)
            else _normalize_legacy_request(provider, params)
        )
        correlation=self._trace_legacy_request(provider,normalized,additional_params)
        return self._tracked_stream(lambda:self._trace_legacy_stream(
            lambda:runtime.stream(normalized, additional_params),correlation))

    def stream_selected_legacy(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
    ) -> Iterable[str]:
        """Run legacy streaming against the captured provider/model/config choice."""

        params, additional_params = self._selected_legacy_payload(
            selection,
            request,
        )
        correlation=self._trace_legacy_request(selection.provider_id,params,additional_params)
        return self._tracked_stream(lambda:self._trace_legacy_stream(
            lambda: chat_providers.stream_chat(
                selection.provider_id,
                params,
                additional_params,
            ),correlation))

    def _tracked_stream(
        self,
        factory: Callable[[], Iterable[str]],
        *,
        inference_lock: threading.RLock | None = None,
    ) -> Iterable[str]:
        def generate() -> Iterator[str]:
            self.begin_request()
            try:
                lock = inference_lock or nullcontext()
                with lock:
                    yield from factory()
            finally:
                self.end_request()

        return generate()

    def stream_prompt_request(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
        token: object | None = None,
        *,
        reason: str = "provider prompt stream",
        timeout_seconds: float | None = None,
        prefer_frozen_execution: bool = False,
        allow_legacy_fallback: bool = True,
        prepare_model: bool = True,
    ) -> ProviderTextStream:
        """Stream an auxiliary prompt with selected-provider legacy fallback."""

        if prepare_model and not self.ensure_selection_model_ready(
            selection,
            reason=reason,
        ):
            raise RuntimeError(
                f"The chat model {selection.model_id!r} could not be prepared "
                f"for {selection.provider_id!r}."
            )
        if prefer_frozen_execution and self.frozen_execution_available(
            selection,
            stream=True,
        ):
            return self.stream(
                self.prepare(selection, request),
                token,
                timeout_seconds=timeout_seconds,
            )
        if prefer_frozen_execution and not allow_legacy_fallback:
            raise RuntimeError(
                "Frozen streaming is unavailable for the captured provider."
            )
        if not allow_legacy_fallback:
            raise RuntimeError("Selected-provider legacy streaming is disabled.")
        return ProviderTextStream(
            self.stream_selected_legacy(selection, request),
            token,
        )

    def _selected_legacy_payload(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(selection, ProviderSelection):
            raise TypeError("Selected provider fallback requires ProviderSelection.")
        if not isinstance(request, PromptRequest):
            raise TypeError("Selected provider fallback requires PromptRequest.")
        params = request.params_copy()
        normalizer = getattr(self.runtime, "normalize_request_params", None)
        normalized = (
            normalizer(
                selection.provider_id,
                params,
                runtime_config=selection.config,
            )
            if callable(normalizer)
            else _normalize_legacy_request(selection.provider_id, params)
        )
        normalized["model"] = selection.model_id
        return normalized, request.additional_params_copy()


def _token_cancelled(token: object) -> bool:
    if isinstance(token, CancellationToken):
        return token.cancelled
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:
            return False
    return False


def _normalize_legacy_request(
    provider: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    from core import runtime_chat as runtime_chat_module

    return runtime_chat_module.normalize_provider_request_params(
        provider,
        params,
        runtime_config={},
    )


__all__ = [
    "FrozenTurnRequest",
    "ModelInspect",
    "ModelUnloadOne",
    "PreparedProviderStreamStateSeal",
    "ProviderEffectAdmission",
    "ProviderExecutionCallbacks",
    "PreservedLMStudioModel",
    "ProviderReadiness",
    "ProviderSelection",
    "ProviderService",
    "ProviderTextStream",
    "infer_model_supports_images",
]
