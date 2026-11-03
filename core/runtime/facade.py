"""Finite UI-facing command, query, and subscription adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import threading
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol
from core.continuity_memory import MemoryRecoveryError
from core.runtime.runtime_use import RuntimeUseBusy, RuntimeUseGate

from core.runtime.addon_extensions import (
    AudioStoryTtsRuntimeExtensionOwner,
    AvatarResourceRuntimeExtensionOwner,
    ChatContextRuntimeExtensionOwner,
    OrbRuntimeExtensionOwner,
    PromptRefinementRuntimeExtensionOwner,
    PushToTalkRuntimeExtensionOwner,
    SpeechRuntimeExtensionOwner,
    VisualRequestRuntimeExtensionOwner,
)
from core.runtime.addons import AddonGateway
from core.session_document import AddonSessionContribution
from core.runtime.avatar import AvatarService, AvatarSnapshot
from core.runtime.body_profile import BodyProfileService
from core.runtime.config import (
    RuntimeConfigChanged,
    RuntimeConfigService,
    RuntimeConfigSnapshot,
    RuntimeConfigSubscriberFailure,
)
from core.runtime.config_effects import RuntimeConfigEffects
from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.conversation import ConversationService, ConversationSnapshot
from core.runtime.events import (
    RuntimeEvent,
    RuntimeEventBus,
    RuntimeSubscription,
)
from core.runtime.interaction import (
    InteractionBindings,
    InteractionCommand,
    InteractionService,
)
from core.runtime.identity_relay import IdentityRelayService
from core.runtime.identifiers import TurnId, WorkLease
from core.runtime.lifecycle import RuntimeFailureSnapshot, RuntimeLifecycle
from core.runtime.memory import (
    ConversationMemoryStatus,
    LongTermMemoryStatus,
    MemoryService,
)
from core.runtime.memory_admin import MemoryAdminService, SessionMemoryReportRequest
from core.runtime.playback import PlaybackReceipt, PlaybackService, PlaybackSnapshot
from core.runtime.prompt_assembly import (
    PromptAssemblyService,
    PromptInputs,
    PromptRequest,
)
from core.runtime.providers import ProviderSelection, ProviderService
from core.runtime.replay import ReplayReceipt, ReplayService
from core.runtime.sensory import SensoryService, SensoryStateSnapshot
from core.runtime.speech_input import (
    FinalTranscript,
    SpeechInputService,
    SpeechInputSnapshot,
)
from core.runtime.speech_output import SpeechOutputService
from core.runtime.turns import TurnCoordinator, TurnSnapshot, UserInput
from core.runtime.visual import VisualService, VisualSnapshot

if TYPE_CHECKING:
    from core.long_term_memory_archive_rebuild import PreparedArchiveRebuild


ApplicationDispatch = Callable[[Callable[[], None]], None]
class ApplicationRun(Protocol):
    def __call__(self, config: Mapping[str, object], *, reservation: str | None = None) -> object: ...
ApplicationStopRequest = Callable[[bool], object]
ApplicationConfigUpdate = Callable[[str, object], object]
ApplicationActivity = Callable[[], tuple[bool, bool, bool]]
ApplicationCallbackBinding = Callable[[Callable[..., object]], Callable[[], None]]
ApplicationChatTypedQueue = Callable[[str, str | None, Mapping[str, object]], Mapping[str, object]]
ApplicationChatHistoryReplace = Callable[[
    list[Mapping[str, object]],
    bool,
    list[Mapping[str, object]] | None,
    bool,
], Mapping[str, object]]
ApplicationChatSessionReset = Callable[[], object]
ApplicationChatMessageDelete = Callable[[str, int, int, bool], CommandResult]
ApplicationChatSessionExport = Callable[[], Mapping[str, object]]
ApplicationChatSessionImport = Callable[[Mapping[str, object]], Mapping[str, object]]
ApplicationManualInteraction = Callable[[str], CommandResult[InteractionCommand]]
ApplicationMemoryContextPath = Callable[[str], Mapping[str, object]]
ApplicationMemoryIdentity = Callable[[str], str]
ApplicationMemoryEmbeddingBaseline = Callable[[str | None, int | None], object]
ApplicationMemoryFlushSchedule = Callable[[list[Mapping[str, object]], Callable[[object, object, object], object]], CommandResult[object]]
ApplicationMemoryWorkCurrent = Callable[[object], bool]
ApplicationMemoryContinuitySnapshot = Callable[[], Mapping[str, object]]
ApplicationMemoryStatusView = Callable[[], Mapping[str, object]]
ApplicationMemoryEmbeddingStatus = Callable[[], Mapping[str, object]]
ApplicationMemoryEmbeddingBlockedEvent = Callable[[], Mapping[str, object]]
ApplicationMemoryEmbeddingModels = Callable[[str, bool], list[str]]
ApplicationMemoryEmbeddingRebuild = Callable[[int, bool, Callable[[object, object, object], object]], CommandResult[object]]
ApplicationMemoryArchiveCandidate = Callable[["PreparedArchiveRebuild", Callable[[object, object, object], object]], CommandResult[object]]
ApplicationMemoryContinuityUpdate = Callable[[], Mapping[str, object]]
ApplicationMemoryContinuityBatch = Callable[[int, Callable[[object, object, object], object]], CommandResult[object]]
ApplicationMemoryContinuityClear = Callable[[], object]
ApplicationMemoryExtract = Callable[[int, int, Callable[[object, object, object], object]], CommandResult[object]]
ApplicationMemoryArchiveSnapshot = Callable[[int, int], Mapping[str, object]]
ApplicationMemoryExportDefaultPath = Callable[[], str]
ApplicationMemoryExportReport = Callable[[str], Mapping[str, object]]
ApplicationMemoryRetrieve = Callable[[str, int, int], list[Mapping[str, object]]]
ApplicationSpeechBackendCatalog = Callable[[], Iterable[Mapping[str, object]]]
ApplicationSpeechBackendReinitialize = Callable[[], object]
ApplicationAvatarCatalog = Callable[[], Iterable[Mapping[str, object]]]
ApplicationAvatarSelect = Callable[[str], object]
ApplicationBodySnapshot = Callable[[], Mapping[str, object]]
ApplicationBodyLiveSync = Callable[[bool], object]
ApplicationBodyEmotionSelect = Callable[[str], object]
ApplicationBodyPoseUpdate = Callable[[str, float], object]
ApplicationBodyProfileUpdate = Callable[[Mapping[str, object]], object]
ApplicationBodyHandCalibrationUpdate = Callable[[Mapping[str, object]], object]
ConfigSubscriber = Callable[[RuntimeConfigChanged], None]
EventSubscriber = Callable[[RuntimeEvent[object]], None]


def _direct_dispatch(callback: Callable[[], None]) -> None:
    callback()


def _freeze_public(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_public(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_public(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_public(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_public(item) for item in value)
    return value


def _copy_public(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _copy_public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_public(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return {_copy_public(item) for item in value}
    return value


def _command_failure(category: str, message: str, error: BaseException):
    return CommandResult(
        False,
        failure=RuntimeFailure(category, message, error),
    )


class _QueuedSubscription:
    """Own one source subscription and suppress callbacks after close."""

    __slots__ = ("_lock", "_source", "_closed")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._source: RuntimeSubscription | None = None
        self._closed = False

    def bind(self, source: RuntimeSubscription) -> None:
        close_now = False
        with self._lock:
            if self._closed:
                close_now = True
            else:
                self._source = source
        if close_now:
            source.close()

    def admit(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if self._closed:
                return
            callback()

    def close(self) -> None:
        source = None
        with self._lock:
            if self._closed:
                return
            self._closed = True
            source = self._source
            self._source = None
        if source is not None:
            source.close()


class _CallbackSubscription:
    """Close one finite callback binding exactly once."""

    __slots__ = ("_lock", "_close", "_closed")

    def __init__(self, close: Callable[[], None]) -> None:
        self._lock = threading.RLock()
        self._close = close
        self._closed = False

    def admit(self, callback: Callable[[], object]) -> object | None:
        with self._lock:
            if self._closed:
                return None
            return callback()

    def close(self) -> None:
        close = None
        with self._lock:
            if self._closed:
                return
            self._closed = True
            close = self._close
            self._close = lambda: None
        close()


class AvatarCreationAccess:
    """Creator-only reservations, optionally bound to an open addon generation."""

    def __init__(self, runtime_use: RuntimeUseGate, *, owner_is_open: Callable[[], bool] | None = None) -> None:
        self._runtime_use = runtime_use
        self._owner_is_open = owner_is_open
        self._tokens: set[str] = set()
        self._lock = threading.RLock()

    def bind(self, *, addon_id: str, generation: int, owner_is_open: Callable[[], bool]) -> AvatarCreationAccess:
        if self._owner_is_open is not None:
            raise RuntimeUseBusy("An addon-bound creator capability cannot create another binding.")
        if addon_id != "nc.musetalk_preprocess":
            raise PermissionError("Avatar creation is restricted to MuseTalk Preprocess.")
        return AvatarCreationAccess(self._runtime_use, owner_is_open=owner_is_open)

    def _require_open(self) -> None:
        if self._owner_is_open is not None and not self._owner_is_open():
            raise RuntimeUseBusy("Avatar creator addon generation is closed.")

    def _require_token(self, token: str) -> None:
        if token not in self._tokens:
            raise RuntimeUseBusy("Avatar creator does not own this reservation.")

    def reserve(self) -> str:
        with self._lock:
            self._require_open()
            token = self._runtime_use.reserve("creator")
            self._tokens.add(token)
            return token

    def claim(self, token: str) -> None:
        with self._lock:
            self._require_open()
            self._require_token(token)
            self._runtime_use.claim(token, "creator")

    def begin_cleanup(self, token: str) -> None:
        with self._lock:
            self._require_token(token)
            self._runtime_use.begin_cleanup(token)

    def finish(self, token: str, *, cleanup_ok: bool, reason: str = "") -> None:
        with self._lock:
            self._require_token(token)
            self._runtime_use.finish(token, cleanup_ok=cleanup_ok, reason=reason)
            if cleanup_ok:
                self._tokens.remove(token)

    def snapshot(self) -> dict[str, str]:
        self._require_open()
        state = self._runtime_use.snapshot()
        return {"owner": state.owner, "phase": state.phase, "reason": state.reason}


class LifecycleCommands:
    __slots__ = ("_lifecycle", "_addons", "_run", "_request_stop", "_runtime_use", "_reservations", "_reservation_lock")

    def __init__(
        self,
        lifecycle: RuntimeLifecycle,
        addons: AddonGateway,
        run: ApplicationRun | None,
        request_stop: ApplicationStopRequest | None,
        *,
        runtime_use: RuntimeUseGate | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._addons = addons
        self._run = run
        self._request_stop = request_stop
        self._runtime_use = runtime_use
        self._reservations: set[str] = set()
        self._reservation_lock = threading.RLock()

    def runtime_ready(self) -> bool:
        """Read backend readiness separately from worker/admission activity."""
        return self._runtime_use is None or self._runtime_use.snapshot().ready

    def runtime_use_snapshot(self) -> dict[str, str]:
        if self._runtime_use is None:
            return {"owner": "", "phase": "free", "reason": ""}
        state = self._runtime_use.snapshot()
        return {"owner": state.owner, "phase": state.phase, "reason": state.reason}

    def reserve_run(self) -> CommandResult[str]:
        if self._runtime_use is None:
            # Compatibility for application bindings composed without admission.
            return CommandResult(True)
        with self._reservation_lock:
            try:
                token = self._runtime_use.reserve("chat")
                self._reservations.add(token)
                return CommandResult(True, token)
            except RuntimeUseBusy as exc:
                category = "creator_busy" if self._runtime_use.snapshot().owner == "creator" else "runtime_busy"
                return _command_failure(category, str(exc), exc)

    def cancel_reserved_run(self, token: str) -> CommandResult[None]:
        with self._reservation_lock:
            try:
                if self._runtime_use is None or token not in self._reservations:
                    raise RuntimeUseBusy("The chat reservation is not unclaimed.")
                self._runtime_use.finish(token, cleanup_ok=True)
                self._reservations.remove(token)
                return CommandResult(True)
            except RuntimeUseBusy as exc:
                return _command_failure("runtime_busy", str(exc), exc)

    def run(self, config: Mapping[str, object], *, reservation: str | None = None) -> CommandResult[None]:
        consumed_reservation = False
        try:
            with self._reservation_lock:
                if reservation is not None:
                    if reservation not in self._reservations:
                        return _command_failure("runtime_busy", "The chat reservation is stale or already claimed.", RuntimeUseBusy())
                    self._reservations.remove(reservation)
                    consumed_reservation = True
            if self._run is None:
                return CommandResult(
                    False,
                    failure=RuntimeFailure(
                        "application_run_unavailable",
                        "The composed runtime has no application loop binding.",
                    ),
                )
            if reservation is None:
                outcome = self._run(MappingProxyType(dict(config)))
            else:
                outcome = self._run(MappingProxyType(dict(config)), reservation=reservation)
            if isinstance(outcome, CommandResult):
                return outcome
            return CommandResult(True)
        except BaseException as error:
            return _command_failure(
                "application_run_failed",
                "The companion runtime stopped with an error.",
                error,
            )
        finally:
            if consumed_reservation and self._runtime_use is not None:
                state = self._runtime_use.snapshot()
                if state.owner == "chat" and state.phase == "starting":
                    try:
                        self._runtime_use.finish(reservation, cleanup_ok=True)
                    except RuntimeUseBusy:
                        pass

    def request_stop(self, *, engine_running: bool) -> CommandResult[None]:
        if self._runtime_use is not None:
            self._runtime_use.cancel_startup()
        if self._request_stop is None:
            return self.stop()
        try:
            self._request_stop(bool(engine_running))
            return CommandResult(True)
        except BaseException as error:
            return _command_failure(
                "application_stop_request_failed",
                "Could not request companion runtime shutdown.",
                error,
            )

    def start(self) -> CommandResult[None]:
        return self._lifecycle.start()

    def restart(self, reason: str = "user") -> CommandResult[object]:
        return self._lifecycle.restart(str(reason or "user"))

    def stop(self) -> CommandResult[None]:
        if self.runtime_use_snapshot()["phase"] == "cleanup_failed":
            retry = getattr(self._run, "retry_cleanup", None)
            if callable(retry):
                return retry()
        return self._lifecycle.stop()

    def shutdown(self) -> CommandResult[None]:
        result = self._lifecycle.stop()
        self._addons.close()
        return result

    def run_id(self) -> object:
        return self._lifecycle.run_id


class RuntimeConfigCommands:
    __slots__ = ("_config", "_effects", "_update")

    def __init__(
        self,
        config: RuntimeConfigService,
        effects: RuntimeConfigEffects,
        update: ApplicationConfigUpdate | None,
    ) -> None:
        self._config = config
        self._effects = effects
        self._update = update

    def snapshot(self) -> RuntimeConfigSnapshot:
        return self._config.snapshot()

    def get(self, key: str, default: object = None) -> object:
        return _freeze_public(self._config.get(str(key), default))

    def update(self, key: str, value: object) -> CommandResult[RuntimeConfigChanged]:
        try:
            key_text = str(key)
            if self._update is None:
                event = self._effects.update(key_text, value)
                if event is None:
                    event = RuntimeConfigChanged(self._config.snapshot(), ())
            else:
                before = self._config.snapshot()
                self._update(key_text, value)
                after = self._config.snapshot()
                event = RuntimeConfigChanged(
                    after,
                    (key_text,) if after.revision != before.revision else (),
                )
            return CommandResult(True, event)
        except BaseException as error:
            return _command_failure(
                "config_update_failed",
                f"Could not update runtime setting '{key}'.",
                error,
            )

    def update_many(
        self,
        values: Mapping[str, object],
    ) -> CommandResult[RuntimeConfigChanged]:
        try:
            if self._update is None:
                before = self._config.snapshot()
                changed = []
                for key, value in values.items():
                    update = self._effects.update(str(key), value)
                    if update is not None:
                        changed.extend(update.changed_keys)
                event = RuntimeConfigChanged(
                    self._config.snapshot(),
                    tuple(dict.fromkeys(changed)),
                )
            else:
                before = self._config.snapshot()
                for key, value in values.items():
                    self._update(str(key), value)
                after = self._config.snapshot()
                changed_keys = tuple(
                    str(key)
                    for key in values
                    if after.values.get(str(key)) != before.values.get(str(key))
                )
                event = RuntimeConfigChanged(after, changed_keys)
            return CommandResult(True, event)
        except BaseException as error:
            return _command_failure(
                "config_update_failed",
                "Could not update runtime settings.",
                error,
            )

    def update_provider_selection(self, values: Mapping[str, object]) -> CommandResult[RuntimeConfigChanged]:
        """Publish the provider, model and sampling policy as one accepted revision."""
        from core.chat_runtime_session_schema import GENERATION_DEFAULT_KEYS

        allowed = set(GENERATION_DEFAULT_KEYS) | {"chat_provider", "model_name", "model_supports_images"}
        try:
            if not {"chat_provider", "model_name"}.issubset(values) or set(values) - allowed:
                raise ValueError("Provider selection requires a provider/model pair and provider generation settings.")
            # UI activation already normalizes the registered provider. Existing
            # config subscribers still receive this single atomic publication.
            return CommandResult(True, self._config.update_many(values))
        except BaseException as error:
            return _command_failure("config_update_failed", "Could not change the chat provider.", error)

    def remove(self, key: str) -> CommandResult[RuntimeConfigChanged]:
        try:
            return CommandResult(True, self._config.remove(str(key)))
        except BaseException as error:
            return _command_failure(
                "config_remove_failed",
                f"Could not remove runtime setting '{key}'.",
                error,
            )


class ChatCommands:
    __slots__ = (
        "_conversation",
        "_turns",
        "_queue_typed",
        "_replace_session_history",
        "_reset_session",
        "_export_session",
        "_import_session",
        "_delete_message",
        "_edit_history",
        "_conversation_actions",
    )

    def __init__(
        self,
        conversation: ConversationService,
        turns: TurnCoordinator,
        queue_typed: ApplicationChatTypedQueue | None,
        replace_session_history: ApplicationChatHistoryReplace | None,
        reset_session: ApplicationChatSessionReset | None,
        export_session: ApplicationChatSessionExport | None,
        import_session: ApplicationChatSessionImport | None,
        delete_message: ApplicationChatMessageDelete | None = None,
        conversation_actions=None,
        edit_history=None,
    ) -> None:
        self._conversation = conversation
        self._turns = turns
        self._queue_typed = queue_typed
        self._replace_session_history = replace_session_history
        self._reset_session = reset_session
        self._export_session = export_session
        self._import_session = import_session
        self._delete_message = delete_message
        self._conversation_actions = conversation_actions
        self._edit_history = edit_history

    def edit_history(self, messages, *, expected_revision: int, source_indices) -> CommandResult:
        if self._edit_history is None:
            return self.replace_history_if_revision(tuple(messages), expected_revision=expected_revision)
        try:
            return self._edit_history(tuple(messages), int(expected_revision), tuple(source_indices))
        except BaseException as error:
            return _command_failure('history_edit_failed', 'History edit was not applied: ' + str(error), error)

    def conversation_action(self, request):
        if self._conversation_actions is None:
            from concurrent.futures import Future
            from core.runtime.conversation_actions import ConversationActionResult
            future = Future()
            future.set_result(ConversationActionResult('unavailable', reason='unsupported_runtime'))
            return future
        return self._conversation_actions.submit(request)

    def conversation_actions_snapshot(self):
        return self._conversation_actions.snapshot() if self._conversation_actions is not None else {}

    def delete_message(self, message_id: str, *, expected_revision: int,
                       expected_session: int, remove_memories: bool = True) -> CommandResult:
        if self._delete_message is None:
            return CommandResult(False, failure=RuntimeFailure('message_delete_unavailable',
                'Message deletion requires the matching desktop runtime.'))
        try:
            return self._delete_message(str(message_id), int(expected_revision),
                                        int(expected_session), bool(remove_memories))
        except BaseException as error:
            return _command_failure('message_delete_failed',
                                    'Message was not deleted: ' + str(error), error)

    def snapshot(self) -> ConversationSnapshot:
        return self._conversation.snapshot()

    def has_active_turns(self) -> bool:
        return self._turns.has_active_turns()

    def with_history_snapshot(self, effect):
        """Keep local asset cleanup atomic with edits to live image references."""
        return self._conversation.with_history_snapshot(effect)

    def history(self) -> tuple[Mapping[str, object], ...]:
        """Return an immutable copy of the visible conversation records."""

        return tuple(
            _freeze_public(message)
            for message in self._conversation.message_mappings()
        )

    def submit_text(
        self,
        text: str,
        *,
        metadata: Mapping[str, object] | None = None,
        source: str = "typed",
        persist: bool = True,
    ) -> CommandResult[TurnSnapshot]:
        return self._turns.accept(
            UserInput.completed(
                text,
                metadata=metadata,
                source=source,
                persist=persist,
            )
        )

    def regenerate(self) -> CommandResult[TurnSnapshot]:
        return self._turns.regenerate()

    def cancel_current(
        self,
        turn_id: TurnId,
        reason: str = "user_cancelled",
    ) -> CommandResult[None]:
        return self._turns.cancel_current(
            turn_id,
            str(reason or "user_cancelled"),
        )

    def replace_history(
        self,
        messages: tuple[Mapping[str, object], ...],
    ) -> CommandResult[ConversationSnapshot]:
        try:
            return CommandResult(True, self._conversation.replace_messages(messages))
        except BaseException as error:
            return _command_failure(
                "conversation_replace_failed",
                "Could not replace conversation history.",
                error,
            )

    def replace_history_if_revision(
        self,
        messages: tuple[Mapping[str, object], ...],
        *,
        expected_revision: int,
    ) -> CommandResult[ConversationSnapshot]:
        """Replace visible history only while the caller's snapshot is current."""

        try:
            snapshot = self._conversation.replace_messages_if_revision(
                messages,
                expected_revision=int(expected_revision),
            )
            if snapshot is None:
                return CommandResult(
                    False,
                    failure=RuntimeFailure(
                        "conversation_revision_changed",
                        "The conversation changed before the edit could be saved.",
                    ),
                )
            return CommandResult(True, snapshot)
        except BaseException as error:
            return _command_failure(
                "conversation_replace_failed",
                "Could not replace conversation history.",
                error,
            )

    def reset(self) -> CommandResult[ConversationSnapshot]:
        try:
            return CommandResult(True, self._conversation.reset())
        except BaseException as error:
            return _command_failure(
                "conversation_reset_failed",
                "Could not reset the conversation.",
                error,
            )

    def queue_typed(
        self,
        text: str,
        *,
        role: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[Mapping[str, object]]:
        if self._queue_typed is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "typed_chat_queue_unavailable",
                    "The composed runtime has no typed-chat queue binding.",
                ),
            )
        try:
            result = _freeze_public(
                self._queue_typed(str(text or ""), role, dict(metadata or {}))
            )
            return CommandResult(True, result)
        except BaseException as error:
            return _command_failure(
                "typed_chat_queue_failed",
                "Could not queue the typed chat message.",
                error,
            )

    def replace_session_history(
        self,
        messages: list[Mapping[str, object]],
        *,
        allow_pending_loaded_user: bool,
        expected_history: list[Mapping[str, object]] | None = None,
        reconcile_long_term_memory_archive: bool = False,
    ) -> CommandResult[Mapping[str, object]]:
        if self._replace_session_history is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "session_history_replace_unavailable",
                    "The composed runtime has no chat-session history replacement binding.",
                ),
            )
        try:
            result = _freeze_public(
                self._replace_session_history(
                    [dict(message) for message in messages],
                    bool(allow_pending_loaded_user),
                    ([dict(message) for message in expected_history]
                     if expected_history is not None else None),
                    bool(reconcile_long_term_memory_archive),
                )
            )
            return CommandResult(True, result)
        except BaseException as error:
            return _command_failure(
                "session_history_replace_failed",
                "Could not replace the saved chat-session history.",
                error,
            )

    def reset_session(self) -> CommandResult[None]:
        if self._reset_session is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "chat_session_reset_unavailable",
                    "The composed runtime has no chat-session reset binding.",
                ),
            )
        try:
            self._reset_session()
            return CommandResult(True)
        except BaseException as error:
            return _command_failure(
                "chat_session_reset_failed",
                "Could not reset the chat session.",
                error,
            )

    def export_session(self) -> CommandResult[Mapping[str, object]]:
        if self._export_session is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "chat_session_export_unavailable",
                    "The composed runtime has no chat-session export binding.",
                ),
            )
        try:
            return CommandResult(True, _freeze_public(self._export_session()))
        except BaseException as error:
            return _command_failure(
                "chat_session_export_failed",
                "Could not export the current chat session.",
                error,
            )

    def import_session(
        self,
        payload: Mapping[str, object],
    ) -> CommandResult[Mapping[str, object]]:
        if self._import_session is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "chat_session_import_unavailable",
                    "The composed runtime has no chat-session import binding.",
                ),
            )
        try:
            return CommandResult(
                True,
                _freeze_public(self._import_session(dict(payload))),
            )
        except BaseException as error:
            return _command_failure(
                "chat_session_import_failed",
                "Could not import the selected chat session.",
                error,
            )


class ProviderQueries:
    __slots__ = ("_providers", "_config")

    def __init__(self, providers: ProviderService, config: RuntimeConfigService) -> None:
        self._providers = providers
        self._config = config

    def capture_selection(self) -> ProviderSelection:
        return self._providers.capture_selection(self._config.snapshot())

    def list_models(self, provider_id: str, *, quiet: bool = False) -> tuple[object, ...]:
        return tuple(
            _freeze_public(item)
            for item in self._providers.list_models(provider_id, quiet=quiet)
        )

    def prepare_model(
        self,
        selection: ProviderSelection,
        *,
        reason: str,
        force_unload: bool = False,
    ) -> CommandResult[bool]:
        try:
            value = self._providers.prepare_model(
                selection,
                reason=str(reason or "ui_selection"),
                force_unload=bool(force_unload),
            )
            return CommandResult(True, bool(value))
        except BaseException as error:
            return _command_failure(
                "provider_model_prepare_failed",
                "Could not prepare the selected model.",
                error,
            )


@dataclass(frozen=True, slots=True)
class SpeechBackendSpec:
    id: str
    label: str
    kind: str
    service_name: str
    metadata: Mapping[str, object]


def _speech_backend_catalog(
    catalog: ApplicationSpeechBackendCatalog | None,
) -> tuple[SpeechBackendSpec, ...]:
    if catalog is None:
        return ()
    specs = []
    for raw in catalog() or ():
        item = dict(raw or {})
        backend_id = str(item.get("id") or "").strip().lower()
        if not backend_id:
            continue
        specs.append(
            SpeechBackendSpec(
                id=backend_id,
                label=str(item.get("label") or backend_id).strip() or backend_id,
                kind=str(item.get("kind") or "").strip().lower(),
                service_name=str(item.get("service_name") or "").strip(),
                metadata=_freeze_public(dict(item.get("metadata") or {})),
            )
        )
    return tuple(specs)


class SpeechInputCommands:
    __slots__ = ("_service", "_catalog", "_reinitialize")

    def __init__(
        self,
        service: SpeechInputService,
        catalog: ApplicationSpeechBackendCatalog | None,
        reinitialize: ApplicationSpeechBackendReinitialize | None,
    ) -> None:
        self._service = service
        self._catalog = catalog
        self._reinitialize = reinitialize

    def backend_catalog(self) -> tuple[SpeechBackendSpec, ...]:
        return _speech_backend_catalog(self._catalog)

    def reinitialize_backend(self) -> CommandResult[bool]:
        if self._reinitialize is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "speech_input_reinitialize_unavailable",
                    "The composed runtime cannot reinitialize speech input.",
                ),
            )
        try:
            return CommandResult(True, bool(self._reinitialize()))
        except BaseException as error:
            return _command_failure(
                "speech_input_reinitialize_failed",
                "Could not reinitialize speech input.",
                error,
            )

    def snapshot(self) -> SpeechInputSnapshot:
        return self._service.snapshot()

    def start(self) -> CommandResult[None]:
        return self._service.start()

    def stop(self) -> CommandResult[None]:
        return self._service.stop()

    def begin_push_to_talk(self, lease: WorkLease) -> CommandResult[None]:
        return self._service.begin_push_to_talk(lease)

    def end_push_to_talk(self) -> CommandResult[FinalTranscript]:
        return self._service.end_push_to_talk()


class SpeechOutputCommands:
    __slots__ = ("_service", "_catalog", "_reinitialize")

    def __init__(
        self,
        service: SpeechOutputService,
        catalog: ApplicationSpeechBackendCatalog | None,
        reinitialize: ApplicationSpeechBackendReinitialize | None,
    ) -> None:
        self._service = service
        self._catalog = catalog
        self._reinitialize = reinitialize

    def backend_catalog(self) -> tuple[SpeechBackendSpec, ...]:
        return _speech_backend_catalog(self._catalog)

    def reinitialize_backend(self) -> CommandResult[bool]:
        if self._reinitialize is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "speech_output_reinitialize_unavailable",
                    "The composed runtime cannot reinitialize speech output.",
                ),
            )
        try:
            return CommandResult(True, bool(self._reinitialize()))
        except BaseException as error:
            return _command_failure(
                "speech_output_reinitialize_failed",
                "Could not reinitialize speech output.",
                error,
            )

    def start(self) -> CommandResult[None]:
        return self._service.start()

    def stop(self) -> CommandResult[None]:
        return self._service.stop()

    def cancel(self, speech_id: str, reason: str = "user_cancelled") -> CommandResult[None]:
        return self._service.cancel(str(speech_id), str(reason or "user_cancelled"))


class PlaybackCommands:
    __slots__ = ("_service",)

    def __init__(self, service: PlaybackService) -> None:
        self._service = service

    def snapshot(self) -> PlaybackSnapshot:
        return self._service.snapshot()

    def activity_snapshot(self) -> PlaybackSnapshot:
        return self._service.activity_snapshot()

    def pause(self) -> CommandResult[None]:
        return self._service.pause()

    def resume(self) -> CommandResult[None]:
        return self._service.resume()

    def skip(self) -> PlaybackReceipt:
        return self._service.skip()

    def interrupt(self, reason: str = "user_interrupt") -> PlaybackReceipt:
        return self._service.interrupt(str(reason or "user_interrupt"))


class ReplayCommands:
    __slots__ = ("_service",)

    def __init__(self, service: ReplayService) -> None:
        self._service = service

    def replay_latest_assistant(self, *, voice: str | None = None) -> CommandResult[ReplayReceipt]:
        return self._service.replay_latest_assistant(voice=voice)

    def replay_assistant_at_history_index(
        self,
        history_index: int,
        *,
        voice: str | None = None,
    ) -> CommandResult[ReplayReceipt]:
        """Replay one canonical assistant message selected by visible history index."""

        return self._service.replay_assistant_at_history_index(
            int(history_index),
            voice=voice,
        )

    def replay_chat_session(self, *, start_index: int = 1) -> CommandResult[ReplayReceipt]:
        return self._service.replay_chat_session(start_index=start_index)

    def cancel_all(self, reason: str = "user_cancelled") -> CommandResult[int]:
        return self._service.cancel_all(str(reason or "user_cancelled"))

    def skip_active_message(self) -> CommandResult[bool]:
        return self._service.skip_active_message()

    def has_active_replay(self) -> bool:
        return bool(self._service.active_receipts())

    def chat_entries(self) -> tuple[Mapping[str, object], ...]:
        return tuple(
            _freeze_public(entry)
            for entry in self._service.collect_replayable_chat_entries()
        )


@dataclass(frozen=True, slots=True)
class AvatarProviderSpec:
    id: str
    label: str
    description: str
    order: int
    addon_id: str
    metadata: Mapping[str, object]


class AvatarCommands:
    __slots__ = ("_service", "_config", "_catalog", "_select")

    def __init__(
        self,
        service: AvatarService,
        config: RuntimeConfigService,
        catalog: ApplicationAvatarCatalog | None,
        select: ApplicationAvatarSelect | None,
    ) -> None:
        self._service = service
        self._config = config
        self._catalog = catalog
        self._select = select

    def provider_catalog(self) -> tuple[AvatarProviderSpec, ...]:
        if self._catalog is None:
            return ()
        providers = []
        for raw in self._catalog() or ():
            item = dict(raw or {})
            provider_id = str(item.get("id") or "").strip().lower()
            if not provider_id:
                continue
            providers.append(
                AvatarProviderSpec(
                    id=provider_id,
                    label=str(item.get("label") or provider_id).strip() or provider_id,
                    description=str(item.get("description") or "").strip(),
                    order=int(item.get("order", 1000) or 1000),
                    addon_id=str(item.get("addon_id") or "").strip(),
                    metadata=_freeze_public(dict(item.get("metadata") or {})),
                )
            )
        return tuple(providers)

    def select_provider(self, provider_id: str) -> CommandResult[str]:
        selected = str(provider_id or "").strip().lower()
        if not selected:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "avatar_provider_invalid",
                    "An avatar provider id is required.",
                ),
            )
        try:
            if self._select is None:
                self._config.update("avatar_mode", selected)
            else:
                self._select(selected)
            return CommandResult(True, selected)
        except BaseException as error:
            return _command_failure(
                "avatar_provider_select_failed",
                f"Could not select avatar provider '{selected}'.",
                error,
            )

    def snapshot(self) -> AvatarSnapshot:
        return self._service.snapshot()

    def start(self, config: RuntimeConfigSnapshot | None = None) -> CommandResult[None]:
        return self._service.start(config)

    def stop(self) -> CommandResult[None]:
        return self._service.stop()


@dataclass(frozen=True, slots=True)
class BodyProfileSnapshot:
    profile: Mapping[str, object]
    state: Mapping[str, object]
    hand_calibration: Mapping[str, object]
    edit_emotion: str
    force_edit_mode: bool


class BodyProfileCommands:
    __slots__ = (
        "_service",
        "_snapshot",
        "_set_live_sync",
        "_select_emotion",
        "_update_pose",
        "_update_profile",
        "_update_hand_calibration",
    )

    def __init__(
        self,
        service: BodyProfileService,
        snapshot: ApplicationBodySnapshot | None,
        set_live_sync: ApplicationBodyLiveSync | None,
        select_emotion: ApplicationBodyEmotionSelect | None,
        update_pose: ApplicationBodyPoseUpdate | None,
        update_profile: ApplicationBodyProfileUpdate | None,
        update_hand_calibration: ApplicationBodyHandCalibrationUpdate | None,
    ) -> None:
        self._service = service
        self._snapshot = snapshot
        self._set_live_sync = set_live_sync
        self._select_emotion = select_emotion
        self._update_pose = update_pose
        self._update_profile = update_profile
        self._update_hand_calibration = update_hand_calibration

    def snapshot(self) -> BodyProfileSnapshot:
        raw = (
            dict(self._snapshot() or {})
            if self._snapshot is not None
            else dict(self._service.snapshot().to_mapping())
        )
        return BodyProfileSnapshot(
            profile=_freeze_public(dict(raw.get("profile") or {})),
            state=_freeze_public(dict(raw.get("state") or {})),
            hand_calibration=_freeze_public(dict(raw.get("hand_calibration") or {})),
            edit_emotion=str(raw.get("edit_emotion") or "neutral").strip().lower() or "neutral",
            force_edit_mode=bool(raw.get("force_edit_mode", True)),
        )

    def _invoke(self, binding: Callable[..., object] | None, category: str, message: str, *args) -> CommandResult[None]:
        if binding is None:
            return CommandResult(False, failure=RuntimeFailure(category + "_unavailable", message))
        try:
            binding(*args)
            return CommandResult(True)
        except BaseException as error:
            return _command_failure(category + "_failed", message, error)

    def set_live_sync(self, enabled: bool) -> CommandResult[None]:
        if self._set_live_sync is None:
            self._service.set_live_sync(bool(enabled))
            return CommandResult(True)
        return self._invoke(
            self._set_live_sync,
            "body_live_sync",
            "Could not update body live sync.",
            bool(enabled),
        )

    def select_emotion(self, emotion: str) -> CommandResult[None]:
        if self._select_emotion is None:
            self._service.select_emotion(str(emotion or "").strip().lower())
            return CommandResult(True)
        return self._invoke(
            self._select_emotion,
            "body_emotion_select",
            "Could not select the body emotion.",
            str(emotion or "").strip().lower(),
        )

    def update_pose(self, key: str, value: float) -> CommandResult[None]:
        if self._update_pose is None:
            self._service.update_pose(str(key), float(value))
            return CommandResult(True)
        return self._invoke(
            self._update_pose,
            "body_pose_update",
            f"Could not update body pose field '{key}'.",
            str(key),
            float(value),
        )

    def update_profile(self, profile: Mapping[str, object]) -> CommandResult[None]:
        if self._update_profile is None:
            self._service.update_profile(_copy_public(profile))
            return CommandResult(True)
        return self._invoke(
            self._update_profile,
            "body_profile_update",
            "Could not update the body profile.",
            _copy_public(profile),
        )

    def update_hand_calibration(self, values: Mapping[str, object]) -> CommandResult[None]:
        if self._update_hand_calibration is None:
            self._service.update_hand_calibration(_copy_public(values))
            return CommandResult(True)
        return self._invoke(
            self._update_hand_calibration,
            "body_hand_calibration_update",
            "Could not update hand calibration.",
            _copy_public(values),
        )


class VisualCommands:
    __slots__ = ("_service",)

    def __init__(self, service: VisualService) -> None:
        self._service = service

    def snapshot(self) -> VisualSnapshot:
        return self._service.snapshot()

    def cancel(self, request_id: str, reason: str = "user_cancelled") -> CommandResult[None]:
        return self._service.cancel(str(request_id), str(reason or "user_cancelled"))

    def clear_history(self) -> CommandResult[None]:
        try:
            self._service.clear_history()
            return CommandResult(True)
        except BaseException as error:
            return _command_failure(
                "visual_history_clear_failed",
                "Could not clear Visual Reply history.",
                error,
            )


def _memory_binding_unavailable(binding: str) -> CommandResult:
    return CommandResult(
        False,
        failure=RuntimeFailure(
            f"memory_{str(binding or 'operation')}_unavailable",
            "The composed runtime has no binding for this memory operation.",
        ),
    )


@dataclass(frozen=True, slots=True)
class MemoryWorkReceipt:
    """Opaque UI receipt for validating one delayed memory completion."""

    value: int


@dataclass(frozen=True, slots=True)
class MemoryArchiveSnapshot:
    storage_path: str
    records: tuple[Mapping[str, object], ...]
    chunks: tuple[Mapping[str, object], ...]


class MemoryCommands:
    __slots__ = (
        "_service",
        "_admin",
        "_conversation",
        "_config",
        "_bind_image_review",
        "_set_context_path",
        "_set_identity",
        "_set_embedding_baseline",
        "_schedule_context_flush",
        "_work_context_is_current",
        "_bind_updates",
        "_continuity_snapshot",
        "_status_view",
        "_embedding_status",
        "_embedding_blocked_event",
        "_embedding_models",
        "_schedule_embedding_rebuild",
        "_schedule_archive_candidate",
        "_update_continuity",
        "_schedule_continuity_batch",
        "_clear_continuity",
        "_schedule_extract",
        "_archive_snapshot",
        "_export_default_path",
        "_export_report",
        "_retrieve",
        "_receipt_lock",
        "_receipt_sequence",
        "_work_contexts",
    )

    def __init__(
        self,
        service: MemoryService,
        admin: MemoryAdminService,
        conversation: ConversationService,
        config: RuntimeConfigService,
        bind_image_review: ApplicationCallbackBinding | None,
        set_context_path: ApplicationMemoryContextPath | None,
        set_identity: ApplicationMemoryIdentity | None,
        set_embedding_baseline: ApplicationMemoryEmbeddingBaseline | None,
        schedule_context_flush: ApplicationMemoryFlushSchedule | None,
        work_context_is_current: ApplicationMemoryWorkCurrent | None,
        bind_updates: ApplicationCallbackBinding | None,
        continuity_snapshot: ApplicationMemoryContinuitySnapshot | None,
        status_view: ApplicationMemoryStatusView | None,
        embedding_status: ApplicationMemoryEmbeddingStatus | None,
        embedding_blocked_event: ApplicationMemoryEmbeddingBlockedEvent | None,
        embedding_models: ApplicationMemoryEmbeddingModels | None,
        schedule_embedding_rebuild: ApplicationMemoryEmbeddingRebuild | None,
        schedule_archive_candidate: ApplicationMemoryArchiveCandidate | None,
        update_continuity: ApplicationMemoryContinuityUpdate | None,
        schedule_continuity_batch: ApplicationMemoryContinuityBatch | None,
        clear_continuity: ApplicationMemoryContinuityClear | None,
        schedule_extract: ApplicationMemoryExtract | None,
        archive_snapshot: ApplicationMemoryArchiveSnapshot | None,
        export_default_path: ApplicationMemoryExportDefaultPath | None,
        export_report: ApplicationMemoryExportReport | None,
        retrieve: ApplicationMemoryRetrieve | None,
    ) -> None:
        self._service = service
        self._admin = admin
        self._conversation = conversation
        self._config = config
        self._bind_image_review = bind_image_review
        self._set_context_path = set_context_path
        self._set_identity = set_identity
        self._set_embedding_baseline = set_embedding_baseline
        self._schedule_context_flush = schedule_context_flush
        self._work_context_is_current = work_context_is_current
        self._bind_updates = bind_updates
        self._continuity_snapshot = continuity_snapshot
        self._status_view = status_view
        self._embedding_status = embedding_status
        self._embedding_blocked_event = embedding_blocked_event
        self._embedding_models = embedding_models
        self._schedule_embedding_rebuild = schedule_embedding_rebuild
        self._schedule_archive_candidate = schedule_archive_candidate
        self._update_continuity = update_continuity
        self._schedule_continuity_batch = schedule_continuity_batch
        self._clear_continuity = clear_continuity
        self._schedule_extract = schedule_extract
        self._archive_snapshot = archive_snapshot
        self._export_default_path = export_default_path
        self._export_report = export_report
        self._retrieve = retrieve
        self._receipt_lock = threading.Lock()
        self._receipt_sequence = 0
        self._work_contexts: dict[int, object] = {}

    def long_term_status(self) -> LongTermMemoryStatus:
        snapshot = self._conversation.snapshot()
        return self._service.status(
            snapshot=snapshot,
            config=self._config.snapshot(),
        )

    def reset_session(self) -> CommandResult[None]:
        return self._service.reset_session()

    def bind_image_review(
        self,
        callback: Callable[..., object],
    ) -> RuntimeSubscription:
        if self._bind_image_review is None:
            return _CallbackSubscription(lambda: None)
        return _CallbackSubscription(self._bind_image_review(callback))

    def set_context_path(self, path: str) -> CommandResult[Mapping[str, object]]:
        if self._set_context_path is None:
            return _memory_binding_unavailable("context_path")
        try:
            return CommandResult(True, _freeze_public(self._set_context_path(str(path or ""))))
        except BaseException as error:
            return _command_failure("memory_context_path_failed", "Could not select the chat memory context.", error)

    def set_identity(self, memory_id: str) -> CommandResult[str]:
        if self._set_identity is None:
            return _memory_binding_unavailable("identity")
        try:
            return CommandResult(True, str(self._set_identity(str(memory_id or ""))))
        except BaseException as error:
            return _command_failure("memory_identity_failed", "Could not select the chat memory identity.", error)

    def set_embedding_baseline(
        self,
        model: str | None,
        context_length: int | None,
    ) -> CommandResult[None]:
        if self._set_embedding_baseline is None:
            context = self._current_work_context()
            if context is None:
                return _memory_binding_unavailable("embedding_baseline")
            try:
                accepted = self._admin.set_embedding_baseline(
                    context,
                    model,
                    context_length,
                )
                return CommandResult(bool(accepted))
            except BaseException as error:
                return _command_failure("memory_embedding_baseline_failed", "Could not set the memory embedding baseline.", error)
        try:
            self._set_embedding_baseline(model, context_length)
            return CommandResult(True)
        except BaseException as error:
            return _command_failure("memory_embedding_baseline_failed", "Could not set the memory embedding baseline.", error)

    def schedule_context_flush(
        self,
        history: list[Mapping[str, object]],
        *,
        on_complete: Callable[[object, object, object], object],
    ) -> CommandResult[None]:
        if self._schedule_context_flush is None:
            return _memory_binding_unavailable("context_flush")
        try:
            result = self._schedule_context_flush(
                [dict(message) for message in history],
                self._completion_callback(on_complete),
            )
            return CommandResult(bool(result.accepted), failure=result.failure)
        except BaseException as error:
            return _command_failure("memory_context_flush_failed", "Could not schedule the memory save.", error)

    def work_context_is_current(self, receipt: MemoryWorkReceipt) -> bool:
        if not isinstance(receipt, MemoryWorkReceipt):
            return False
        with self._receipt_lock:
            work_context = self._work_contexts.pop(receipt.value, None)
        if work_context is None:
            return False
        try:
            checker = self._work_context_is_current or self._service.work_context_is_current
            return bool(checker(work_context))
        except BaseException:
            return False

    def bind_updates(
        self,
        callback: Callable[[Mapping[str, object]], object],
    ) -> RuntimeSubscription:
        if self._bind_updates is None:
            return _CallbackSubscription(lambda: None)

        owned_ref: list[_CallbackSubscription] = []

        def receive(payload: object = None) -> object:
            frozen = _freeze_public(payload if isinstance(payload, Mapping) else {})
            if not owned_ref:
                return None
            return owned_ref[0].admit(lambda: callback(frozen))

        owned = _CallbackSubscription(self._bind_updates(receive))
        owned_ref.append(owned)
        return owned

    def conversation_status(self) -> ConversationMemoryStatus:
        return self._service.conversation_status(
            self._conversation.snapshot(),
            self._config.snapshot(),
        )

    def continuity_snapshot(self) -> Mapping[str, object]:
        if self._continuity_snapshot is None:
            raise RuntimeError("The composed runtime has no continuity-memory snapshot binding.")
        return _freeze_public(self._continuity_snapshot())

    def status_view(self) -> Mapping[str, object]:
        if self._status_view is not None:
            return _freeze_public(self._status_view())
        context = self._current_work_context()
        embedding_status = (
            self._admin.embedding_status(context) if context is not None else {}
        )
        return _freeze_public(
            self._service.status_view(
                self._conversation.snapshot(),
                self._config.snapshot(),
                embedding_status=embedding_status,
            )
        )

    def embedding_status(self) -> Mapping[str, object]:
        if self._embedding_status is not None:
            return _freeze_public(self._embedding_status())
        context = self._require_work_context("embedding status")
        return _freeze_public(self._admin.embedding_status(context))

    def embedding_blocked_event(self) -> Mapping[str, object]:
        if self._embedding_blocked_event is not None:
            return _freeze_public(self._embedding_blocked_event())
        context = self._current_work_context()
        return _freeze_public(
            self._admin.embedding_blocked_event(context) if context is not None else {}
        )

    def list_embedding_models(
        self,
        *,
        base_url: str = "",
        quiet: bool = True,
    ) -> tuple[str, ...]:
        if self._embedding_models is None:
            context = self._require_work_context("embedding model listing")
            return tuple(
                self._admin.list_embedding_models(
                    context,
                    base_url=str(base_url or ""),
                    quiet=bool(quiet),
                )
            )
        return tuple(
            str(model)
            for model in self._embedding_models(str(base_url or ""), bool(quiet))
        )

    def schedule_embedding_rebuild(
        self,
        *,
        limit: int,
        clear_existing: bool,
        on_complete: Callable[[object, object, object], object],
    ) -> CommandResult[None]:
        if self._schedule_embedding_rebuild is None:
            context = self._current_work_context()
            if context is None:
                return _memory_binding_unavailable("embedding_rebuild")
            try:
                result = self._admin.schedule_embedding_rebuild(
                    context,
                    limit=int(limit),
                    clear_existing=bool(clear_existing),
                    on_complete=self._completion_callback(on_complete),
                )
                return CommandResult(bool(result.accepted), failure=result.failure)
            except BaseException as error:
                return _command_failure("memory_embedding_rebuild_failed", "Could not schedule the embedding rebuild.", error)
        try:
            result = self._schedule_embedding_rebuild(
                int(limit),
                bool(clear_existing),
                self._completion_callback(on_complete),
            )
            return CommandResult(bool(result.accepted), failure=result.failure)
        except BaseException as error:
            return _command_failure("memory_embedding_rebuild_failed", "Could not schedule the embedding rebuild.", error)

    def schedule_archive_candidate(
        self,
        prepared: PreparedArchiveRebuild,
        *,
        on_complete: Callable[[object, object, object], object],
    ) -> CommandResult[None]:
        if self._schedule_archive_candidate is None:
            context = self._current_work_context()
            if context is None:
                return _memory_binding_unavailable("archive_candidate")
            try:
                result = self._admin.schedule_archive_candidate(
                    context,
                    prepared,
                    on_complete=self._completion_callback(on_complete),
                )
                return CommandResult(bool(result.accepted), failure=result.failure)
            except BaseException as error:
                return _command_failure("memory_archive_candidate_failed", "Could not schedule the archive candidate.", error)
        try:
            result = self._schedule_archive_candidate(
                prepared,
                self._completion_callback(on_complete),
            )
            return CommandResult(bool(result.accepted), failure=result.failure)
        except BaseException as error:
            return _command_failure("memory_archive_candidate_failed", "Could not schedule the archive candidate.", error)

    def update_continuity(self) -> CommandResult[Mapping[str, object]]:
        if self._update_continuity is None:
            return _memory_binding_unavailable("continuity_update")
        try:
            return CommandResult(True, _freeze_public(self._update_continuity()))
        except MemoryRecoveryError as error:
            return _command_failure("memory_continuity_recovery_required", str(error), error)
        except BaseException as error:
            return _command_failure("memory_continuity_update_failed", "Could not update Continuity Memory.", error)

    def schedule_continuity_batch(
        self,
        turn_count: int,
        *,
        on_complete: Callable[[object, object, object], object],
    ) -> CommandResult[None]:
        if self._schedule_continuity_batch is None:
            return _memory_binding_unavailable("continuity_batch")
        try:
            result = self._schedule_continuity_batch(
                int(turn_count),
                self._completion_callback(on_complete),
            )
            return CommandResult(bool(result.accepted), failure=result.failure)
        except MemoryRecoveryError as error:
            return _command_failure("memory_continuity_recovery_required", str(error), error)
        except BaseException as error:
            return _command_failure("memory_continuity_batch_failed", "Could not schedule the continuity summary.", error)

    def clear_continuity(self) -> CommandResult[None]:
        if self._clear_continuity is None:
            return _memory_binding_unavailable("continuity_clear")
        try:
            self._clear_continuity()
            return CommandResult(True)
        except BaseException as error:
            return _command_failure("memory_continuity_clear_failed", "Could not clear Continuity Memory.", error)

    def schedule_extract(
        self,
        turn_count: int,
        *,
        max_records: int,
        on_complete: Callable[[object, object, object], object],
    ) -> CommandResult[None]:
        if self._schedule_extract is None:
            return _memory_binding_unavailable("extract")
        try:
            result = self._schedule_extract(
                int(turn_count),
                int(max_records),
                self._completion_callback(on_complete),
            )
            return CommandResult(bool(result.accepted), failure=result.failure)
        except BaseException as error:
            return _command_failure("memory_extract_failed", "Could not schedule memory extraction.", error)

    def archive_snapshot(
        self,
        *,
        record_limit: int,
        chunk_limit: int,
    ) -> MemoryArchiveSnapshot:
        if self._archive_snapshot is None:
            context = self._require_work_context("archive snapshot")
            binding = context.binding
            payload = {
                "storage_path": str(binding.database_path),
                "records": self._admin.list_records(context, limit=int(record_limit)),
                "chunks": self._admin.list_chunks(context, limit=int(chunk_limit)),
            }
        else:
            payload = self._archive_snapshot(int(record_limit), int(chunk_limit))
        return MemoryArchiveSnapshot(
            storage_path=str(payload.get("storage_path", "") or ""),
            records=tuple(_freeze_public(item) for item in payload.get("records", ()) or ()),
            chunks=tuple(_freeze_public(item) for item in payload.get("chunks", ()) or ()),
        )

    def export_default_path(self) -> str:
        if self._export_default_path is not None:
            return str(self._export_default_path() or "")
        context = self._current_work_context()
        if context is None:
            return ""
        path = self._admin.default_report_path(context, self._report_request())
        return str(path or "")

    def export_session_report(self, path: str) -> CommandResult[Mapping[str, object]]:
        if self._export_report is None:
            context = self._current_work_context()
            if context is None:
                return _memory_binding_unavailable("export_report")
            try:
                result = self._admin.export_report(
                    context,
                    self._report_request(),
                    path=str(path or "") or None,
                )
                if result is None:
                    return _memory_binding_unavailable("export_report")
                return CommandResult(True, _freeze_public(result))
            except BaseException as error:
                return _command_failure("memory_export_report_failed", "Could not export session memory.", error)
        try:
            return CommandResult(True, _freeze_public(self._export_report(str(path or ""))))
        except BaseException as error:
            return _command_failure("memory_export_report_failed", "Could not export session memory.", error)

    def retrieve(
        self,
        query: str,
        *,
        record_limit: int,
        chunk_limit: int,
    ) -> tuple[Mapping[str, object], ...]:
        if self._retrieve is None:
            context = self._require_work_context("Long-Term Memory retrieval")
            return tuple(
                _freeze_public(item)
                for item in self._service.retrieve_results(
                    context,
                    str(query or ""),
                    record_limit=int(record_limit),
                    chunk_limit=int(chunk_limit),
                )
            )
        return tuple(
            _freeze_public(item)
            for item in self._retrieve(
                str(query or ""),
                int(record_limit),
                int(chunk_limit),
            )
        )

    def _current_work_context(self):
        frozen = self._service.freeze_dispatch(
            self._conversation.session_lease(),
            self._config.snapshot(),
        )
        return frozen.value if frozen.accepted else None

    def _require_work_context(self, operation: str):
        context = self._current_work_context()
        if context is None:
            raise RuntimeError(
                f"The active memory session is unavailable for {operation}."
            )
        return context

    def _report_request(self) -> SessionMemoryReportRequest:
        values = self._config.snapshot().values
        continuity = (
            dict(self._continuity_snapshot() or {})
            if self._continuity_snapshot is not None
            else {}
        )
        return SessionMemoryReportRequest(
            continuity=continuity,
            history=tuple(self._conversation.message_mappings()),
            chat_context_name=str(values.get("active_chat_context_name") or ""),
            chat_context_path=str(values.get("active_chat_context_path") or ""),
            memory_id=str(values.get("continuity_memory_id") or ""),
        )

    def _completion_callback(
        self,
        callback: Callable[[object, object, object], object],
    ) -> Callable[[object, object, object], object]:
        def complete(work_context: object, result: object, error: object) -> object:
            receipt = None
            if work_context is not None:
                with self._receipt_lock:
                    self._receipt_sequence += 1
                    receipt = MemoryWorkReceipt(self._receipt_sequence)
                    self._work_contexts[receipt.value] = work_context
            return callback(receipt, _freeze_public(result), error)

        return complete


class SensoryCommands:
    __slots__ = ("_service", "_config")

    def __init__(self, service: SensoryService, config: RuntimeConfigService) -> None:
        self._service = service
        self._config = config

    def snapshot(self) -> SensoryStateSnapshot:
        return self._service.snapshot_state()

    def enabled(self) -> bool:
        return self._service.enabled(self._config.snapshot())

    def image_fallback_status(self) -> dict[str, object]:
        return self._service.image_fallback_status()

    def retry_images(self) -> CommandResult[None]:
        return self._service.retry_images()

    def reset_session(self) -> CommandResult[None]:
        return self._service.reset_session()


class InteractionCommands:
    __slots__ = ("_service", "_submit_manual")

    def __init__(
        self,
        service: InteractionService,
        submit_manual: ApplicationManualInteraction | None,
    ) -> None:
        self._service = service
        self._submit_manual = submit_manual

    def submit(
        self,
        action: str,
        *,
        payload: Mapping[str, object] | None = None,
        source: str = "ui",
    ) -> CommandResult[InteractionCommand]:
        return self._service.submit(
            InteractionCommand(
                str(action),
                payload=MappingProxyType(dict(payload or {})),
                source=str(source or "ui"),
            )
        )

    def stage(
        self,
        action: str,
        *,
        payload: Mapping[str, object] | None = None,
        source: str = "offline_bootstrap",
    ) -> CommandResult[InteractionCommand]:
        return self._service.stage(
            InteractionCommand(
                str(action),
                payload=MappingProxyType(dict(payload or {})),
                source=str(source or "offline_bootstrap"),
            )
        )

    def submit_manual(self, action: str) -> CommandResult[InteractionCommand]:
        if self._submit_manual is not None:
            try:
                return self._submit_manual(str(action or ""))
            except BaseException as error:
                return _command_failure(
                    "manual_interaction_failed",
                    "Could not submit the manual interaction.",
                    error,
                )
        return self.submit(str(action or ""), source="ui")

    def bindings(self) -> InteractionBindings:
        return self._service.bindings()

    def pending_count(self) -> int:
        return self._service.pending_count()


def _require_addon_owner(owner, surface: str):
    if owner is None:
        raise RuntimeError(
            f"The {surface} application facade surface is not composed."
        )
    return owner


class AddonChatCommands:
    __slots__ = ("_config", "_owner", "_providers", "_replay")

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        providers: ProviderService,
        replay: ReplayService,
        owner: ChatContextRuntimeExtensionOwner | None,
    ) -> None:
        self._config = config
        self._providers = providers
        self._replay = replay
        self._owner = owner

    def provider_config_snapshot(self) -> RuntimeConfigSnapshot:
        return self._config.snapshot()

    def capture_provider_selection(
        self,
        config: RuntimeConfigSnapshot,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> ProviderSelection:
        return self._providers.capture_selection(
            config,
            provider_id=provider_id,
            model_id=model_id,
        )

    def prepare_provider_request(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
    ):
        return self._providers.prepare(selection, request)

    def apply_provider_generation_fields(
        self,
        selection: ProviderSelection,
        params: dict[str, object],
        additional_params: dict[str, object],
    ) -> None:
        self._providers.apply_generation_fields(selection, params, additional_params)

    def complete_provider_request(self, request, token) -> CommandResult[str]:
        return self._providers.complete(request, token)

    def stream_provider_request(self, request, token):
        return self._providers.stream(request, token)

    def ensure_model_ready(self, provider_name: str, model_name: str) -> object:
        return _require_addon_owner(self._owner, "addon chat").ensure_model_ready(
            str(provider_name or ""),
            str(model_name or ""),
        )

    def history_snapshot(self):
        return _require_addon_owner(self._owner, "addon chat").history_snapshot()

    def collect_contexts(
        self,
        history: list[Mapping[str, object]],
        *,
        request_kind: str | None = None,
        excluded_addon_ids=(),
    ):
        return _require_addon_owner(self._owner, "addon chat").collect_addon_contexts(
            history,
            request_kind=request_kind,
            excluded_addon_ids=tuple(excluded_addon_ids or ()),
        )

    def submit_if_current_and_idle(self, text: str, **kwargs):
        return _require_addon_owner(self._owner, "addon chat").submit_if_current_and_idle(text, **kwargs)

    def stage_continuous_next(self, proposed_user, binding, cancellation) -> str | None:
        return _require_addon_owner(self._owner, "addon chat").stage_continuous_next(
            proposed_user, binding, cancellation)

    def submit_accepted_turn(
        self,
        text: str,
        role: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ):
        return _require_addon_owner(self._owner, "addon chat").submit_accepted_turn(
            str(text or ""),
            role=role,
            metadata=dict(metadata or {}),
        )

    def snapshot_session(self):
        return _require_addon_owner(self._owner, "addon chat").snapshot_session()

    def phone_reply_controls(self):
        provider = getattr(self._owner, "phone_reply_controls", None)
        return provider() if callable(provider) else None

    def replayable_chat_entries(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ):
        return self._replay.collect_replayable_chat_entries(history)

    def replayable_chat_messages(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ):
        return self._replay.collect_replayable_chat_messages(history)

    def replayable_assistant_entries(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ):
        return self._replay.collect_replayable_assistant_entries(history)

    def replayable_assistant_messages(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ):
        return self._replay.collect_replayable_assistant_messages(history)

    def build_replay_session_action(self, start_index: int) -> str:
        from core.runtime_hotkeys import build_replay_chat_session_from_action

        return build_replay_chat_session_from_action(start_index)


class AddonSpeechCommands:
    __slots__ = ("_config", "_owner", "_push_to_talk", "_speech_input")

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        speech_input: SpeechInputService,
        owner: SpeechRuntimeExtensionOwner | None,
        push_to_talk: PushToTalkRuntimeExtensionOwner | None,
    ) -> None:
        self._config = config
        self._speech_input = speech_input
        self._owner = owner
        self._push_to_talk = push_to_talk

    def snapshot(self):
        return _require_addon_owner(self._owner, "addon speech").snapshot()

    def set_paused(self, paused: bool) -> bool:
        return bool(
            _require_addon_owner(self._owner, "addon speech").set_paused(
                bool(paused)
            )
        )

    def interrupt(
        self,
        *,
        reason: str = "",
        cancel_llm_streams: bool = False,
    ):
        return _require_addon_owner(self._owner, "addon speech").interrupt(
            reason=str(reason or ""),
            cancel_llm_streams=bool(cancel_llm_streams),
        )

    def ensure_ready(self) -> bool:
        return bool(_require_addon_owner(self._owner, "addon speech").ensure_ready())

    def speak(
        self,
        text: str,
        text_iterable=None,
        voice_path_override: str | None = None,
        runtime_config_override: Mapping[str, object] | None = None,
    ):
        return _require_addon_owner(self._owner, "addon speech").speak(
            str(text or ""),
            text_iterable=(
                None
                if text_iterable is None
                else tuple(str(item or "") for item in text_iterable)
            ),
            voice_path_override=voice_path_override,
            runtime_config_override=(
                None
                if runtime_config_override is None
                else dict(runtime_config_override)
            ),
        )

    def speak_chess(self, text: str, *, voice_path: str, runtime_config: Mapping[str, object]) -> object:
        """Host composition only: optional owner-scoped speech, never a global interrupt."""
        return _require_addon_owner(self._owner, "addon speech").speak(
            text, voice_path_override=voice_path, runtime_config_override=runtime_config,
            chess_low_priority=True)

    def push_to_talk_hotkey(self) -> str:
        return str(
            _require_addon_owner(
                self._push_to_talk,
                "addon speech push-to-talk",
            ).hotkey()
            or ""
        )

    def set_push_to_talk_hold(self, active: bool):
        return _require_addon_owner(
            self._push_to_talk,
            "addon speech push-to-talk",
        ).set_hold(bool(active))

    def prepare_transcription(self) -> bool:
        result = self._speech_input.initialize_backend(self._config.snapshot())
        if not result.accepted:
            raise RuntimeError(getattr(result.failure, "message", None) or "Selected STT backend is unavailable.")
        return True

    def transcribe_file(self, path: str, *, language=None):
        return self._speech_input.transcribe_file(
            str(path),
            language=language,
            raw=True,
            config=self._config.snapshot(),
        )


class AddonOrbCommands:
    __slots__ = ("_owner",)

    def __init__(self, owner: OrbRuntimeExtensionOwner | None) -> None:
        self._owner = owner

    def conversation_scope(self):
        return _require_addon_owner(self._owner, 'addon orb').conversation_scope()

    def interpret_watch_intent(self, **kwargs):
        return _require_addon_owner(self._owner, 'addon orb').interpret_watch_intent(**kwargs)

    def observe_watch(self, **kwargs):
        return _require_addon_owner(self._owner, 'addon orb').observe_watch(**kwargs)

    def record_communication(self, **kwargs):
        return _require_addon_owner(self._owner, 'addon orb').record_communication(**kwargs)

    def busy_snapshot(self):
        return _require_addon_owner(self._owner, "addon orb").busy_snapshot()

    def extract_selected_text(self, *, image_path: str, screen_bounds=None) -> str:
        return str(
            _require_addon_owner(self._owner, "addon orb").extract_selected_text(
                image_path=str(image_path),
                screen_bounds=screen_bounds,
            )
            or ""
        )

    def ground_region(
        self,
        *,
        image_path: str,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "auto_load",
        capture_bounds=None,
        gaze_point=None,
    ) -> Mapping[str, object]:
        result = _require_addon_owner(
            self._owner,
            "addon orb",
        ).ground_region(
            image_path=str(image_path),
            provider_id=str(provider_id or ""),
            model_id=str(model_id or ""),
            base_url=str(base_url or ""),
            model_handling=str(model_handling or "auto_load"),
            capture_bounds=capture_bounds,
            gaze_point=gaze_point,
        )
        return dict(result or {})

    def generate_visual_guidance(
        self,
        *,
        image_path: str,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "auto_load",
        restore_main_model: bool = False,
        reaction_scope: str = "gaze",
    ) -> Mapping[str, object]:
        result = _require_addon_owner(
            self._owner,
            "addon orb",
        ).generate_visual_guidance(
            image_path=str(image_path),
            provider_id=str(provider_id or ""),
            model_id=str(model_id or ""),
            base_url=str(base_url or ""),
            model_handling=str(model_handling or "auto_load"),
            restore_main_model=bool(restore_main_model),
            reaction_scope=str(reaction_scope or "gaze"),
        )
        return dict(result or {})

    def ensure_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> Mapping[str, object]:
        result = _require_addon_owner(
            self._owner,
            "addon orb",
        ).ensure_vision_model(
            provider_id=str(provider_id or ""),
            model_id=str(model_id or ""),
            base_url=str(base_url or ""),
            model_handling=str(model_handling or "parallel_pinned"),
        )
        return dict(result or {})

    def observe_visual(
        self,
        *,
        image_path: str,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
        capture_bounds=None,
        reaction_scope: str = "gaze",
        capability_mode: str = "auto",
        target_text: str = "",
        question_text: str = "",
        timeout_seconds: float = 15.0,
        cancel_token: object | None = None,
        trace_id: str = "",
    ) -> Mapping[str, object]:
        result = _require_addon_owner(
            self._owner,
            "addon orb",
        ).observe_visual(
            image_path=str(image_path),
            provider_id=str(provider_id or ""),
            model_id=str(model_id or ""),
            base_url=str(base_url or ""),
            model_handling=str(model_handling or "parallel_pinned"),
            capture_bounds=capture_bounds,
            reaction_scope=str(reaction_scope or "gaze"),
            capability_mode=str(capability_mode or "auto"),
            target_text=str(target_text or ""),
            question_text=str(question_text or ""),
            timeout_seconds=float(timeout_seconds),
            cancel_token=cancel_token,
            trace_id=str(trace_id or ""),
        )
        return dict(result or {})

    def release_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> bool:
        return bool(
            _require_addon_owner(
                self._owner,
                "addon orb",
            ).release_vision_model(
                provider_id=str(provider_id or ""),
                model_id=str(model_id or ""),
                base_url=str(base_url or ""),
                model_handling=str(model_handling or "parallel_pinned"),
            )
        )

    def ephemeral_comment(
        self,
        *,
        selected_text: str,
        behavior_prompt: str,
        response_style_label: str = "Very friendly",
        exclude_from_memory: bool = True,
        mode: str = "select_area_comment",
    ) -> str:
        return str(
            _require_addon_owner(self._owner, "addon orb").ephemeral_comment(
                selected_text=str(selected_text or ""),
                behavior_prompt=str(behavior_prompt or ""),
                response_style_label=str(response_style_label or "Very friendly"),
                exclude_from_memory=bool(exclude_from_memory),
                mode=str(mode or "select_area_comment"),
            )
            or ""
        )

    def submit_proactive(
        self,
        candidate: str,
        *,
        summary: str = "",
        attention: str = "",
        emotion: str = "",
        source: str = "sensory",
        allow_repeated_candidate: bool = False,
        focus_bounds: object = None,
        focus_label: str = "",
        focus_text: str = "",
        focus_duration_seconds: float = 14.0,
        trace_id: str = "",
    ):
        return _require_addon_owner(self._owner, "addon orb").submit_proactive(
            str(candidate or ""),
            summary=str(summary or ""),
            attention=str(attention or ""),
            emotion=str(emotion or ""),
            source=str(source or "sensory"),
            allow_repeated_candidate=bool(allow_repeated_candidate),
            focus_bounds=focus_bounds,
            focus_label=str(focus_label or ""),
            focus_text=str(focus_text or ""),
            focus_duration_seconds=float(focus_duration_seconds),
            trace_id=str(trace_id or ""),
        )

    def run_sensory_cycle(
        self,
        force: bool = False,
        snapshots_override: object = None,
        priority: bool = False,
        priority_source: str = "",
        trace_id: str = "",
    ):
        return _require_addon_owner(self._owner, "addon orb").run_sensory_cycle(
            force=bool(force),
            snapshots_override=snapshots_override,
            priority=bool(priority),
            priority_source=str(priority_source or ""),
            trace_id=str(trace_id or ""),
        )

    def generate_drop_guidance(
        self,
        *,
        image_path: str,
        snapshot_metadata: Mapping[str, object] | None = None,
        response_style_label: str = "Very friendly",
    ):
        return _require_addon_owner(self._owner, "addon orb").generate_drop_guidance(
            image_path=str(image_path),
            snapshot_metadata=(
                None if snapshot_metadata is None else dict(snapshot_metadata)
            ),
            response_style_label=str(response_style_label or "Very friendly"),
        )

    def format_drop_guidance(self, guidance: Mapping[str, object]) -> str:
        return str(
            _require_addon_owner(self._owner, "addon orb").format_drop_guidance(
                guidance
            )
            or ""
        )


class AddonAudioStoryCommands:
    __slots__ = ("_owner",)

    def __init__(self, owner: AudioStoryTtsRuntimeExtensionOwner | None) -> None:
        self._owner = owner

    def text_chunk_limits(self, runtime_config=None):
        return _require_addon_owner(
            self._owner,
            "addon audio story",
        ).text_chunk_limits(runtime_config)

    def chunk_text(self, text: str, target_length: int, maximum_length: int):
        return _require_addon_owner(self._owner, "addon audio story").chunk_text(
            str(text),
            int(target_length),
            int(maximum_length),
        )

    def set_seed(self, seed: int):
        return _require_addon_owner(self._owner, "addon audio story").set_seed(
            int(seed)
        )

    def generate(self, text: str, **settings):
        return _require_addon_owner(self._owner, "addon audio story").generate(
            str(text),
            **dict(settings),
        )

    def save_wav(self, path: str, wav, sample_rate: int):
        return _require_addon_owner(self._owner, "addon audio story").save_wav(
            str(path),
            wav,
            int(sample_rate),
        )

    def safe_delete(self, path: str):
        return _require_addon_owner(self._owner, "addon audio story").safe_delete(
            str(path)
        )

    def sample_rate(self, default: int) -> int:
        return int(
            _require_addon_owner(self._owner, "addon audio story").sample_rate(
                int(default)
            )
        )


class AddonAvatarResourceCommands:
    __slots__ = ("_avatar", "_owner")

    def __init__(
        self,
        avatar: AvatarService,
        owner: AvatarResourceRuntimeExtensionOwner | None,
    ) -> None:
        self._avatar = avatar
        self._owner = owner

    def adapter(self):
        return self._avatar.adapter()

    def refresh_emotions(self):
        return _require_addon_owner(
            self._owner,
            "addon avatar resources",
        ).refresh_emotions()

    def tts_device(self) -> str:
        return str(
            _require_addon_owner(
                self._owner,
                "addon avatar resources",
            ).tts_device()
            or "cpu"
        )


class AddonVisualRequestCommands:
    __slots__ = ("_owner",)

    def __init__(self, owner: VisualRequestRuntimeExtensionOwner | None) -> None:
        self._owner = owner

    def request_generation(
        self,
        prompt: str,
        *,
        inputs: Sequence[object] = (),
        source_text: str = "",
        request_id: str | None = None,
        runtime_config_override=None,
        asset_metadata: Mapping[str, object] | None = None,
    ):
        request_kwargs = {
            "source_text": str(source_text or ""),
            "request_id": request_id,
            "runtime_config_override": dict(runtime_config_override or {}),
            "asset_metadata": dict(asset_metadata or {}),
        }
        if inputs:
            request_kwargs["inputs"] = tuple(inputs)
        return _require_addon_owner(
            self._owner,
            "addon visual request",
        ).request_generation(
            str(prompt or ""),
            **request_kwargs,
        )


class PromptRefinementCommands:
    __slots__ = ("_owner",)

    def __init__(self, owner: PromptRefinementRuntimeExtensionOwner | None) -> None:
        self._owner = owner

    def refine_persona(
        self, draft: Mapping[str, object], *, provider_id: str, model_id: str,
        regenerate: bool = False, cancel_token: object | None = None,
    ) -> str:
        return str(_require_addon_owner(self._owner, "persona prompt refinement").refine_persona(
            draft, provider_id=provider_id, model_id=model_id, regenerate=regenerate, cancel_token=cancel_token,
        ))

    def refine(
        self,
        text: str,
        *,
        label: str = "Instruction",
        guidance: str = "",
    ) -> str:
        return str(
            _require_addon_owner(
                self._owner,
                "prompt refinement",
            ).refine(
                str(text or ""),
                label=str(label or "Instruction"),
                guidance=str(guidance or ""),
            )
            or ""
        )


class AddonRegistrationCommands:
    __slots__ = (
        "_gateway",
        "_identity_relay",
        "_bind_manager_getter",
        "_bind_event_publisher",
        "_lock",
        "_manager_getter",
    )

    def __init__(
        self,
        gateway: AddonGateway,
        identity_relay: IdentityRelayService,
        bind_manager_getter: ApplicationCallbackBinding | None,
        bind_event_publisher: ApplicationCallbackBinding | None,
    ) -> None:
        self._gateway = gateway
        self._identity_relay = identity_relay
        self._bind_manager_getter = bind_manager_getter
        self._bind_event_publisher = bind_event_publisher
        self._lock = threading.RLock()
        self._manager_getter: Callable[[], object | None] | None = None

    def closed(self) -> bool:
        return self._gateway.closed

    def close_addon(self, addon_id: str) -> CommandResult[bool]:
        try:
            return CommandResult(True, self._gateway.close_addon(str(addon_id)))
        except BaseException as error:
            return _command_failure(
                "addon_close_failed",
                f"Could not close addon '{addon_id}'.",
                error,
            )

    def install_identity_relay_runtime(self, host: object) -> bool:
        """Attach the Relay runtime before the host initializes any addons."""

        return self._identity_relay.install_addon_runtime(host)

    def bind_manager_getter(
        self,
        callback: Callable[..., object],
    ) -> RuntimeSubscription:
        if not callable(callback):
            raise TypeError("Addon manager binding requires a callable getter.")
        with self._lock:
            if self._manager_getter is not None:
                raise RuntimeError("Application addon manager is already bound.")
            self._manager_getter = callback
        try:
            unbind = (
                self._bind_manager_getter(callback)
                if self._bind_manager_getter is not None
                else lambda: None
            )
        except BaseException:
            with self._lock:
                if self._manager_getter is callback:
                    self._manager_getter = None
            raise

        def close() -> None:
            with self._lock:
                if self._manager_getter is callback:
                    self._manager_getter = None
            unbind()

        return _CallbackSubscription(close)

    def manager_available(self) -> bool:
        """Return whether an initialized addon manager is currently bound."""

        return self._manager() is not None

    def publish_event(
        self,
        event_name: str,
        payload: Mapping[str, object] | None = None,
    ) -> CommandResult[bool]:
        """Publish one finite runtime event without exposing the addon manager."""

        manager = self._manager()
        callback = getattr(manager, "publish_event", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            callback(str(event_name or ""), dict(payload or {}))
            return CommandResult(True, True)
        except BaseException as error:
            return _command_failure(
                "addon_event_publish_failed",
                f"Addon event '{event_name}' could not be published.",
                error,
            )

    def invoke_addon_capability(
        self,
        addon_id: str,
        capability: str,
        payload: Mapping[str, object] | None = None,
    ) -> CommandResult[object]:
        """Invoke one declared addon capability without exposing the manager."""

        manager = self._manager()
        callback = getattr(manager, "invoke_addon_capability", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            value = callback(
                str(addon_id or ""),
                str(capability or ""),
                dict(payload or {}),
            )
            return CommandResult(True, value)
        except BaseException as error:
            return _command_failure(
                "addon_capability_failed",
                f"Addon capability '{capability}' failed for '{addon_id}'.",
                error,
            )

    def invoke_service_capability(
        self,
        service_id: str,
        capability: str,
        payload: Mapping[str, object] | None = None,
        **metadata_match: object,
    ) -> CommandResult[object]:
        """Invoke one capability on the addon that owns a registered service."""

        manager = self._manager()
        callback = getattr(manager, "invoke_service_capability", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            value = callback(
                str(service_id or ""),
                str(capability or ""),
                dict(payload or {}),
                **{
                    str(key): value
                    for key, value in metadata_match.items()
                    if str(key or "").strip()
                },
            )
            return CommandResult(True, value)
        except BaseException as error:
            return _command_failure(
                "addon_service_capability_failed",
                f"Addon service capability '{capability}' failed for '{service_id}'.",
                error,
            )

    def export_session_state(self) -> CommandResult[Mapping[str, object]]:
        """Return the combined addon session payload through a finite boundary."""

        manager = self._manager()
        callback = getattr(manager, "export_session_state", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            payload = callback()
            if not isinstance(payload, Mapping):
                raise TypeError("Addon session export must return a mapping.")
            return CommandResult(True, _freeze_public(dict(payload)))
        except BaseException as error:
            return _command_failure(
                "addon_session_export_failed",
                "Could not export addon session state.",
                error,
            )

    def export_session_state_contributions(self) -> CommandResult[tuple[object, ...]]:
        """Return per-addon session contributions through a finite boundary."""

        manager = self._manager()
        callback = getattr(manager, "export_session_contributions", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            payload = callback()
            if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
                raise TypeError("Addon session export contributions must return a sequence.")
            if not all(isinstance(item, AddonSessionContribution) for item in payload):
                raise TypeError(
                    "Addon session export contributions must contain AddonSessionContribution records."
                )
            return CommandResult(True, tuple(payload))
        except BaseException as error:
            return _command_failure(
                "addon_session_export_failed",
                "Could not export addon session state.",
                error,
            )

    def import_session_state(
        self,
        payload: Mapping[str, object],
    ) -> CommandResult[bool]:
        """Apply one persisted session payload through the initialized addon manager."""

        manager = self._manager()
        callback = getattr(manager, "import_session_state", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            if not isinstance(payload, Mapping):
                raise TypeError("Addon session import payload must be a mapping.")
            callback(dict(payload))
            return CommandResult(True, True)
        except BaseException as error:
            return _command_failure(
                "addon_session_import_failed",
                "Could not import addon session state.",
                error,
            )

    def export_preset_state(self) -> CommandResult[Mapping[str, object]]:
        """Return addon-owned preset values without exposing addon instances."""

        return self._mapping_manager_command(
            "export_preset_state",
            error_code="addon_preset_export_failed",
            error_message="Could not export addon preset state.",
        )

    def import_preset_state(
        self,
        payload: Mapping[str, object],
    ) -> CommandResult[bool]:
        """Apply one persisted preset through the initialized addon manager."""

        manager = self._manager()
        callback = getattr(manager, "import_preset_state", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            callback(dict(payload or {}))
            return CommandResult(True, True)
        except BaseException as error:
            return _command_failure(
                "addon_preset_import_failed",
                "Could not import addon preset state.",
                error,
            )

    def _mapping_manager_command(
        self,
        method_name: str,
        *,
        error_code: str,
        error_message: str,
    ) -> CommandResult[Mapping[str, object]]:
        manager = self._manager()
        callback = getattr(manager, method_name, None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            payload = callback()
            if not isinstance(payload, Mapping):
                raise TypeError(f"{method_name} must return a mapping.")
            return CommandResult(True, _freeze_public(dict(payload)))
        except BaseException as error:
            return _command_failure(error_code, error_message, error)

    def registry_snapshot(self) -> CommandResult[tuple[object, ...]]:
        """Return the serializable addon registry without exposing records."""

        manager = self._manager()
        callback = getattr(manager, "get_addon_registry_snapshot", None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            catalog = _freeze_public(tuple(callback() or ()))
            recovery_getter = getattr(manager, "get_addon_registry_recovery_error", None)
            recovery_message = str(recovery_getter() or "") if callable(recovery_getter) else ""
            if recovery_message:
                return CommandResult(
                    False, catalog,
                    RuntimeFailure("addon_registry_recovery_required", recovery_message),
                )
            return CommandResult(True, catalog)
        except BaseException as error:
            return _command_failure(
                "addon_registry_snapshot_failed",
                "Could not read the addon registry.",
                error,
            )

    def set_addon_enabled(
        self,
        addon_id: str,
        enabled: bool,
    ) -> CommandResult[bool]:
        return self._set_registry_enabled("set_addon_enabled", addon_id, enabled)

    def set_category_enabled(
        self,
        category_id: str,
        enabled: bool,
    ) -> CommandResult[bool]:
        return self._set_registry_enabled(
            "set_category_enabled", category_id, enabled
        )

    def _set_registry_enabled(
        self,
        method_name: str,
        item_id: str,
        enabled: bool,
    ) -> CommandResult[bool]:
        manager = self._manager()
        callback = getattr(manager, method_name, None)
        if not callable(callback):
            return _command_failure(
                "addon_manager_unavailable",
                "The addon runtime is not initialized.",
                RuntimeError("Addon manager is unavailable."),
            )
        try:
            return CommandResult(
                True,
                bool(callback(str(item_id or "").strip(), bool(enabled))),
            )
        except BaseException as error:
            recovery_getter = getattr(manager, "get_addon_registry_recovery_error", None)
            recovery_message = str(recovery_getter() or "") if callable(recovery_getter) else ""
            if recovery_message:
                return _command_failure(
                    "addon_registry_recovery_required", recovery_message, error,
                )
            return _command_failure(
                "addon_registry_update_failed",
                f"Could not update addon registry item '{item_id}'.",
                error,
            )

    def _manager(self) -> object | None:
        with self._lock:
            getter = self._manager_getter
        if getter is None:
            return None
        try:
            return getter()
        except BaseException:
            return None

    def bind_event_publisher(
        self,
        callback: Callable[..., object],
    ) -> RuntimeSubscription:
        if self._bind_event_publisher is None:
            return _CallbackSubscription(lambda: None)
        return _CallbackSubscription(self._bind_event_publisher(callback))


class PromptToolCommands:
    __slots__ = ("_service",)

    def __init__(self, service: PromptAssemblyService) -> None:
        self._service = service

    def build(self, inputs: PromptInputs) -> PromptRequest:
        return self._service.build(inputs)


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    lifecycle_failures: tuple[RuntimeFailureSnapshot, ...]
    config_subscriber_failures: tuple[RuntimeConfigSubscriberFailure, ...]


class DiagnosticQueries:
    __slots__ = ("_lifecycle", "_config")

    def __init__(
        self,
        lifecycle: RuntimeLifecycle,
        config: RuntimeConfigService,
    ) -> None:
        self._lifecycle = lifecycle
        self._config = config

    def snapshot(self) -> DiagnosticSnapshot:
        return DiagnosticSnapshot(
            lifecycle_failures=self._lifecycle.failures(),
            config_subscriber_failures=self._config.subscriber_failures(),
        )


@dataclass(frozen=True, slots=True)
class ApplicationActivitySnapshot:
    listening: bool
    recording: bool
    paused: bool


@dataclass(frozen=True, slots=True)
class ApplicationStatusSnapshot:
    run_id: object
    config_revision: int
    conversation_revision: int
    speech_input: SpeechInputSnapshot
    playback: PlaybackSnapshot
    avatar: AvatarSnapshot
    visual: VisualSnapshot
    sensory: SensoryStateSnapshot
    interaction_pending: int
    activity: ApplicationActivitySnapshot


class RuntimeStatusQueries:
    __slots__ = (
        "_lifecycle",
        "_config",
        "_conversation",
        "_speech_input",
        "_playback",
        "_avatar",
        "_visual",
        "_sensory",
        "_interaction",
        "_activity",
    )

    def __init__(
        self,
        *,
        lifecycle: RuntimeLifecycle,
        config: RuntimeConfigService,
        conversation: ConversationService,
        speech_input: SpeechInputService,
        playback: PlaybackService,
        avatar: AvatarService,
        visual: VisualService,
        sensory: SensoryService,
        interaction: InteractionService,
        activity: ApplicationActivity | None,
    ) -> None:
        self._lifecycle = lifecycle
        self._config = config
        self._conversation = conversation
        self._speech_input = speech_input
        self._playback = playback
        self._avatar = avatar
        self._visual = visual
        self._sensory = sensory
        self._interaction = interaction
        self._activity = activity

    def activity(self) -> ApplicationActivitySnapshot:
        activity = (
            tuple(bool(value) for value in self._activity())
            if self._activity is not None
            else (False, False, False)
        )
        if len(activity) != 3:
            activity = (False, False, False)
        return ApplicationActivitySnapshot(*activity)

    def snapshot(self) -> ApplicationStatusSnapshot:
        config = self._config.snapshot()
        conversation = self._conversation.snapshot()
        return ApplicationStatusSnapshot(
            run_id=self._lifecycle.run_id,
            config_revision=config.revision,
            conversation_revision=conversation.revision,
            speech_input=self._speech_input.snapshot(),
            playback=self._playback.snapshot(),
            avatar=self._avatar.snapshot(),
            visual=self._visual.snapshot(),
            sensory=self._sensory.snapshot_state(),
            interaction_pending=self._interaction.pending_count(),
            activity=self.activity(),
        )


class RuntimeSubscriptions:
    __slots__ = ("_config", "_events", "_dispatch")

    def __init__(
        self,
        config: RuntimeConfigService,
        events: RuntimeEventBus,
        dispatch: ApplicationDispatch | None,
    ) -> None:
        self._config = config
        self._events = events
        self._dispatch = dispatch or _direct_dispatch

    def config(self, callback: ConfigSubscriber) -> RuntimeSubscription:
        owned = _QueuedSubscription()

        def receive(event: RuntimeConfigChanged) -> None:
            self._dispatch(lambda: owned.admit(lambda: callback(event)))

        owned.bind(self._config.subscribe(receive))
        return owned

    def event(self, event_name: str, callback: EventSubscriber) -> RuntimeSubscription:
        owned = _QueuedSubscription()

        def receive(event: RuntimeEvent[object]) -> None:
            frozen = RuntimeEvent(
                name=event.name,
                payload=_freeze_public(event.payload),
                lease=event.lease,
            )
            self._dispatch(lambda: owned.admit(lambda: callback(frozen)))

        owned.bind(self._events.subscribe(str(event_name), receive))
        return owned


class CommunicationLoggingCommands:
    """Session-local diagnostics; deliberately not part of persisted configuration."""
    def __init__(self, providers):
        self._providers=providers

    def snapshot(self):
        trace=getattr(self._providers,'communication_trace',None)
        return trace.snapshot() if trace is not None else dict(state='unavailable',path='',byte_count=0,
            incomplete_reason='Communication recorder is not configured.',max_bytes=1073741824)

    def set_enabled(self, enabled):
        trace=getattr(self._providers,'communication_trace',None)
        if trace is None:
            raise RuntimeError('Communication recorder is not configured.')
        if enabled and trace.snapshot()['state']!='recording':
            trace.start()
        elif not enabled:
            trace.stop(wait=False)
        return trace.snapshot()

    def export(self):
        trace=getattr(self._providers,'communication_trace',None)
        if trace is None:
            raise RuntimeError('No communication recorder is configured.')
        return trace.export()


@dataclass(frozen=True, slots=True)
class ApplicationFacade:
    """The only runtime aggregate intended for UI consumers."""

    lifecycle: LifecycleCommands
    config: RuntimeConfigCommands
    chat: ChatCommands
    providers: ProviderQueries
    speech_input: SpeechInputCommands
    speech_output: SpeechOutputCommands
    playback: PlaybackCommands
    replay: ReplayCommands
    avatar: AvatarCommands
    body: BodyProfileCommands
    visual: VisualCommands
    memory: MemoryCommands
    sensory: SensoryCommands
    interaction: InteractionCommands
    addons: AddonRegistrationCommands
    prompt_tools: PromptToolCommands
    addon_chat: AddonChatCommands
    addon_speech: AddonSpeechCommands
    addon_orb: AddonOrbCommands
    addon_audio_story: AddonAudioStoryCommands
    addon_avatar_resources: AddonAvatarResourceCommands
    addon_visual_request: AddonVisualRequestCommands
    prompt_refinement: PromptRefinementCommands
    diagnostics: DiagnosticQueries
    status: RuntimeStatusQueries
    subscriptions: RuntimeSubscriptions
    avatar_creation: AvatarCreationAccess | None = None
    communication_logging: object | None = None
    document_memory: object | None = None
    resources: object | None = None


def build_application_facade(
    *,
    lifecycle: RuntimeLifecycle,
    config: RuntimeConfigService,
    config_effects: RuntimeConfigEffects,
    conversation: ConversationService,
    turns: TurnCoordinator,
    providers: ProviderService,
    speech_input: SpeechInputService,
    speech_output: SpeechOutputService,
    playback: PlaybackService,
    replay: ReplayService,
    avatar: AvatarService,
    body_profile: BodyProfileService,
    visual: VisualService,
    memory: MemoryService,
    memory_admin: MemoryAdminService,
    sensory: SensoryService,
    interaction: InteractionService,
    identity_relay: IdentityRelayService,
    addons: AddonGateway,
    prompt_assembly: PromptAssemblyService,
    events: RuntimeEventBus,
    dispatch: ApplicationDispatch | None = None,
    application_run: ApplicationRun | None = None,
    runtime_use: RuntimeUseGate | None = None,
    application_request_stop: ApplicationStopRequest | None = None,
    application_config_update: ApplicationConfigUpdate | None = None,
    application_activity: ApplicationActivity | None = None,
    application_stt_backend_catalog: ApplicationSpeechBackendCatalog | None = None,
    application_stt_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None,
    application_tts_backend_catalog: ApplicationSpeechBackendCatalog | None = None,
    application_tts_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None,
    application_avatar_catalog: ApplicationAvatarCatalog | None = None,
    application_avatar_select: ApplicationAvatarSelect | None = None,
    application_body_snapshot: ApplicationBodySnapshot | None = None,
    application_body_set_live_sync: ApplicationBodyLiveSync | None = None,
    application_body_select_emotion: ApplicationBodyEmotionSelect | None = None,
    application_body_update_pose: ApplicationBodyPoseUpdate | None = None,
    application_body_update_profile: ApplicationBodyProfileUpdate | None = None,
    application_body_update_hand_calibration: ApplicationBodyHandCalibrationUpdate | None = None,
    application_bind_image_review: ApplicationCallbackBinding | None = None,
    application_bind_addon_manager_getter: ApplicationCallbackBinding | None = None,
    application_bind_addon_event_publisher: ApplicationCallbackBinding | None = None,
    application_queue_typed_chat: ApplicationChatTypedQueue | None = None,
    application_replace_chat_session_history: ApplicationChatHistoryReplace | None = None,
    application_delete_chat_message: ApplicationChatMessageDelete | None = None,
    application_edit_chat_history: Callable | None = None,
    application_conversation_actions=None,
    application_reset_chat_session: ApplicationChatSessionReset | None = None,
    application_export_chat_session: ApplicationChatSessionExport | None = None,
    application_import_chat_session: ApplicationChatSessionImport | None = None,
    application_submit_manual_interaction: ApplicationManualInteraction | None = None,
    application_set_memory_context_path: ApplicationMemoryContextPath | None = None,
    application_set_memory_identity: ApplicationMemoryIdentity | None = None,
    application_set_memory_embedding_baseline: ApplicationMemoryEmbeddingBaseline | None = None,
    application_schedule_memory_context_flush: ApplicationMemoryFlushSchedule | None = None,
    application_memory_work_context_is_current: ApplicationMemoryWorkCurrent | None = None,
    application_bind_memory_updates: ApplicationCallbackBinding | None = None,
    application_memory_continuity_snapshot: ApplicationMemoryContinuitySnapshot | None = None,
    application_memory_status_view: ApplicationMemoryStatusView | None = None,
    application_memory_embedding_status: ApplicationMemoryEmbeddingStatus | None = None,
    application_memory_embedding_blocked_event: ApplicationMemoryEmbeddingBlockedEvent | None = None,
    application_memory_embedding_models: ApplicationMemoryEmbeddingModels | None = None,
    application_schedule_memory_embedding_rebuild: ApplicationMemoryEmbeddingRebuild | None = None,
    application_schedule_memory_archive_candidate: ApplicationMemoryArchiveCandidate | None = None,
    application_update_continuity_memory: ApplicationMemoryContinuityUpdate | None = None,
    application_schedule_continuity_memory_batch: ApplicationMemoryContinuityBatch | None = None,
    application_clear_continuity_memory: ApplicationMemoryContinuityClear | None = None,
    application_schedule_long_term_memory_extract: ApplicationMemoryExtract | None = None,
    application_memory_archive_snapshot: ApplicationMemoryArchiveSnapshot | None = None,
    application_memory_export_default_path: ApplicationMemoryExportDefaultPath | None = None,
    application_export_session_memory_report: ApplicationMemoryExportReport | None = None,
    application_retrieve_long_term_memory: ApplicationMemoryRetrieve | None = None,
    addon_chat_owner: ChatContextRuntimeExtensionOwner | None = None,
    addon_speech_owner: SpeechRuntimeExtensionOwner | None = None,
    addon_push_to_talk_owner: PushToTalkRuntimeExtensionOwner | None = None,
    addon_orb_owner: OrbRuntimeExtensionOwner | None = None,
    addon_audio_story_owner: AudioStoryTtsRuntimeExtensionOwner | None = None,
    addon_avatar_resource_owner: AvatarResourceRuntimeExtensionOwner | None = None,
    addon_visual_request_owner: VisualRequestRuntimeExtensionOwner | None = None,
    prompt_refinement_owner: PromptRefinementRuntimeExtensionOwner | None = None,
) -> ApplicationFacade:
    """Compose finite adapters from explicit owners, never from RuntimeContext."""

    from core.runtime.document_memory import DocumentMemoryRuntimePort, build_document_activity_reader
    document_memory = None
    if callable(getattr(memory_admin, "document_capability", None)):
        document_memory = DocumentMemoryRuntimePort(
            embeddings=memory_admin.document_capability(),
            activity=build_document_activity_reader(lifecycle=lifecycle, conversation=conversation,
                turns=turns, speech_input=speech_input, speech_output=speech_output, playback=playback,
                avatar=avatar, interaction=interaction, activity=application_activity))
    addon_commands = AddonRegistrationCommands(
        addons, identity_relay, application_bind_addon_manager_getter,
        application_bind_addon_event_publisher)

    def resource_registry():
        # Native Qt addons bind their own live manager after composition.
        # Resolve its catalog per inspection rather than retaining the unused
        # foundation catalog captured before addon initialization.
        manager = addon_commands._manager()
        return getattr(manager, 'service_registry', addons.service_registry)

    from core.runtime.resource_sources import build_resource_service
    resources = build_resource_service(
        config=config, providers=providers, registry=resource_registry, runtime_use=runtime_use,
        activity=build_document_activity_reader(lifecycle=lifecycle, conversation=conversation,
            turns=turns, speech_input=speech_input, speech_output=speech_output, playback=playback,
            avatar=avatar, interaction=interaction, activity=application_activity),
        document_memory=document_memory, embeddings=getattr(memory_admin, 'embeddings', None))
    return ApplicationFacade(
        resources=resources,
        document_memory=document_memory,
        communication_logging=CommunicationLoggingCommands(providers),
        lifecycle=LifecycleCommands(
            lifecycle,
            addons,
            application_run,
            application_request_stop,
            runtime_use=runtime_use,
        ),
        avatar_creation=AvatarCreationAccess(runtime_use) if runtime_use is not None else None,
        config=RuntimeConfigCommands(config, config_effects, application_config_update),
        chat=ChatCommands(
            conversation,
            turns,
            application_queue_typed_chat,
            application_replace_chat_session_history,
            application_reset_chat_session,
            application_export_chat_session,
            application_import_chat_session,
            application_delete_chat_message,
            application_conversation_actions,
            application_edit_chat_history,
        ),
        providers=ProviderQueries(providers, config),
        speech_input=SpeechInputCommands(
            speech_input,
            application_stt_backend_catalog,
            application_stt_backend_reinitialize,
        ),
        speech_output=SpeechOutputCommands(
            speech_output,
            application_tts_backend_catalog,
            application_tts_backend_reinitialize,
        ),
        playback=PlaybackCommands(playback),
        replay=ReplayCommands(replay),
        avatar=AvatarCommands(
            avatar,
            config,
            application_avatar_catalog,
            application_avatar_select,
        ),
        body=BodyProfileCommands(
            body_profile,
            application_body_snapshot,
            application_body_set_live_sync,
            application_body_select_emotion,
            application_body_update_pose,
            application_body_update_profile,
            application_body_update_hand_calibration,
        ),
        visual=VisualCommands(visual),
        memory=MemoryCommands(
            memory,
            memory_admin,
            conversation,
            config,
            application_bind_image_review,
            application_set_memory_context_path,
            application_set_memory_identity,
            application_set_memory_embedding_baseline,
            application_schedule_memory_context_flush,
            application_memory_work_context_is_current,
            application_bind_memory_updates,
            application_memory_continuity_snapshot,
            application_memory_status_view,
            application_memory_embedding_status,
            application_memory_embedding_blocked_event,
            application_memory_embedding_models,
            application_schedule_memory_embedding_rebuild,
            application_schedule_memory_archive_candidate,
            application_update_continuity_memory,
            application_schedule_continuity_memory_batch,
            application_clear_continuity_memory,
            application_schedule_long_term_memory_extract,
            application_memory_archive_snapshot,
            application_memory_export_default_path,
            application_export_session_memory_report,
            application_retrieve_long_term_memory,
        ),
        sensory=SensoryCommands(sensory, config),
        interaction=InteractionCommands(interaction, application_submit_manual_interaction),
        addons=addon_commands,
        prompt_tools=PromptToolCommands(prompt_assembly),
        addon_chat=AddonChatCommands(
            config=config,
            providers=providers,
            replay=replay,
            owner=addon_chat_owner,
        ),
        addon_speech=AddonSpeechCommands(
            config=config,
            speech_input=speech_input,
            owner=addon_speech_owner,
            push_to_talk=addon_push_to_talk_owner,
        ),
        addon_orb=AddonOrbCommands(addon_orb_owner),
        addon_audio_story=AddonAudioStoryCommands(addon_audio_story_owner),
        addon_avatar_resources=AddonAvatarResourceCommands(
            avatar,
            addon_avatar_resource_owner,
        ),
        addon_visual_request=AddonVisualRequestCommands(addon_visual_request_owner),
        prompt_refinement=PromptRefinementCommands(prompt_refinement_owner),
        diagnostics=DiagnosticQueries(lifecycle, config),
        status=RuntimeStatusQueries(
            lifecycle=lifecycle,
            config=config,
            conversation=conversation,
            speech_input=speech_input,
            playback=playback,
            avatar=avatar,
            visual=visual,
            sensory=sensory,
            interaction=interaction,
            activity=application_activity,
        ),
        subscriptions=RuntimeSubscriptions(config, events, dispatch),
    )


__all__ = [
    "AddonAudioStoryCommands",
    "AddonAvatarResourceCommands",
    "AddonChatCommands",
    "AddonOrbCommands",
    "AddonSpeechCommands",
    "AddonVisualRequestCommands",
    "ApplicationFacade",
    "ApplicationActivitySnapshot",
    "ApplicationStatusSnapshot",
    "AvatarProviderSpec",
    "BodyProfileSnapshot",
    "DiagnosticSnapshot",
    "MemoryArchiveSnapshot",
    "MemoryWorkReceipt",
    "PromptRefinementCommands",
    "SpeechBackendSpec",
    "build_application_facade",
]
