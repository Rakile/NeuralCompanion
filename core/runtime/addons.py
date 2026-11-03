"""Restricted addon host contracts and addon-owned execution lanes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import logging
from pathlib import Path
import threading
from typing import Any, Generic, TypeVar
from uuid import uuid4
import weakref

from core.focused_lifecycle_owner import AddonOwnerToken
from core.runtime.events import _reject_hot_path_payload
from core.runtime.identifiers import RunId, WorkLease
from core.runtime.lifecycle import (
    Closable,
    ProcessHandle,
    ProcessLike,
    ResourceHandle,
    RuntimeFailureSnapshot,
    WorkerHandle,
    WorkerSupervisor,
)


T = TypeVar("T")


class AddonHostError(RuntimeError):
    """Base failure for restricted addon host operations."""


class AddonContextClosedError(AddonHostError):
    """Raised when an addon uses a context generation after close."""


class AddonOwnershipError(PermissionError):
    """Raised when one addon attempts to mutate another addon's ownership."""


class AddonHighFrequencyEventError(ValueError):
    """Raised when hot-path data is sent through the general event bus."""


class AddonUiUnavailableError(AddonHostError):
    """Raised when queued Qt delivery is unavailable."""


class AddonUiDispatchTimeout(TimeoutError):
    """Raised after invalidating a queued UI call that did not run in time."""


@dataclass(frozen=True, slots=True)
class AddonExecutionLanes:
    """Additive execution metadata for one addon manifest."""

    ui: bool = False
    worker: bool = True
    external_process: bool = False
    realtime: bool = False

    @classmethod
    def from_metadata(
        cls,
        metadata: object,
        *,
        inferred_ui: bool = False,
    ) -> "AddonExecutionLanes":
        inferred = {
            "ui": bool(inferred_ui),
            "worker": True,
            "external_process": False,
            "realtime": False,
        }
        if metadata is None:
            return cls(**inferred)
        if isinstance(metadata, Mapping):
            values = dict(inferred)
            for raw_name, raw_enabled in metadata.items():
                name = _normalize_lane_name(raw_name)
                if name in values:
                    values[name] = bool(raw_enabled)
            return cls(**values)
        if isinstance(metadata, Sequence) and not isinstance(
            metadata,
            (str, bytes, bytearray, memoryview),
        ):
            values = {name: False for name in inferred}
            for raw_name in metadata:
                name = _normalize_lane_name(raw_name)
                if name in values:
                    values[name] = True
            return cls(**values)
        raise ValueError("execution_lanes must be a mapping, sequence, or null")


def _normalize_lane_name(value: object) -> str:
    name = str(value or "").strip().lower().replace("-", "_")
    if name == "externalprocess":
        return "external_process"
    return name


@dataclass(frozen=True, slots=True)
class AddonPaths:
    """Immutable project, addon, and addon-storage paths."""

    app_root: Path
    addon_root: Path
    storage_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_root", Path(self.app_root).resolve())
        object.__setattr__(self, "addon_root", Path(self.addon_root).resolve())
        object.__setattr__(self, "storage_root", Path(self.storage_root).resolve())

    @property
    def project_root(self) -> Path:
        return self.app_root


@dataclass(frozen=True, slots=True)
class AddonShellSession:
    """Small shell-preview/session port with no shell object exposure."""

    preview: bool = False
    _snapshot: Callable[[], Mapping[str, object]] | None = None
    _notify: Callable[[], None] | None = None

    def snapshot(self) -> dict[str, object]:
        if not callable(self._snapshot):
            return {}
        return dict(self._snapshot() or {})

    def notify_settings_changed(self) -> None:
        if callable(self._notify):
            self._notify()


@dataclass(frozen=True, slots=True)
class AddonCapabilities:
    """Explicitly named addon-facing capability ports."""

    runtime_config: object | None = None
    dialogs: object | None = None
    shell_session: AddonShellSession = field(default_factory=AddonShellSession)
    speech: object | None = None
    speech_providers: object | None = None
    music: object | None = None
    music_commands: object | None = None
    providers: object | None = None
    playback: object | None = None
    interaction: object | None = None
    hotkeys: object | None = None
    avatar: object | None = None
    emotion: object | None = None
    visual_reply: object | None = None
    story: object | None = None
    accepted_turns: object | None = None
    conversation: object | None = None
    replay: object | None = None
    memory: object | None = None
    document_memory: object | None = None
    prompt_refinement: object | None = None
    sensory_targets: object | None = None
    diagnostics: object | None = None
    runtime_status: object | None = None
    realtime: object | None = None
    file_transcription: object | None = None
    user_image_turns: object | None = None
    shell: object | None = None
    tutorials: object | None = None
    engine_lifecycle: object | None = None
    remote_commands: object | None = None
    audio_story: object | None = None
    orb_runtime: object | None = None
    audio_story_visual: object | None = None
    scenic_avatar_host: object | None = None
    main_chat_remote_host: object | None = None
    avatar_creation: object | None = None
    identity_relay_runtime: object | None = None
    chess_personas: object | None = None
    execution_lanes: AddonExecutionLanes = field(
        default_factory=AddonExecutionLanes
    )

    @classmethod
    def from_host_services(
        cls,
        host_services: Mapping[str, object] | None,
        *,
        execution_lanes: AddonExecutionLanes | None = None,
        owner_binding: "AddonOwnerBinding | None" = None,
    ) -> "AddonCapabilities":
        services = dict(host_services or {})
        shell = services.get("qt.shell")
        snapshot = services.get("qt.shell_session_snapshot")
        preview = bool(
            services.get("qt.shell_preview")
            or services.get("qt.chatterbox_tts_shell_preview")
            or services.get("qt.pockettts_shell_preview")
        )
        main_chat_remote_host = None
        host_service = services.get("runtime.main_chat_remote_host")
        if (
            owner_binding is not None
            and owner_binding.owner.addon_id == "nc.main_chat_remote"
            and host_service is not None
        ):
            main_chat_remote_host = host_service.bind(
                addon_id=owner_binding.owner.addon_id,
                generation=owner_binding.owner.generation,
                owner_is_open=lambda: not owner_binding.closed,
            )
        avatar_creation = None
        creator_service = services.get("runtime.avatar_creation")
        if owner_binding is not None and owner_binding.owner.addon_id == "nc.musetalk_preprocess" and creator_service is not None:
            avatar_creation = creator_service.bind(
                addon_id=owner_binding.owner.addon_id,
                generation=owner_binding.owner.generation,
                owner_is_open=lambda: not owner_binding.closed,
            )
        return cls(
            chess_personas=(services['runtime.chess_persona_turns.v1'].bind(
                addon_id=owner_binding.owner.addon_id, generation=owner_binding.owner.generation,
                owner_is_open=lambda: not owner_binding.closed)
                if owner_binding is not None and owner_binding.owner.addon_id == 'nc.companion_chess'
                and services.get('runtime.chess_persona_turns.v1') is not None else None),
            runtime_config=services.get("qt.runtime_config"),
            dialogs=services.get("qt.dialogs"),
            shell_session=AddonShellSession(
                preview=preview,
                _snapshot=snapshot if callable(snapshot) else None,
                _notify=getattr(shell, "notify_settings_changed", None),
            ),
            speech=services.get("runtime.speech"),
            providers=services.get("qt.chat_providers"),
            playback=services.get("runtime.playback"),
            interaction=(
                services.get("qt.input_actions")
                or services.get("qt.runtime_controls")
            ),
            hotkeys=services.get("qt.hotkeys"),
            avatar=services.get("qt.avatar_providers"),
            emotion=services.get("qt.persona_avatar"),
            visual_reply=services.get("qt.visual_reply"),
            identity_relay_runtime=services.get("identity_relay.runtime"),
            story=services.get("qt.audio_story_actions"),
            accepted_turns=services.get("runtime.accepted_turns"),
            conversation=services.get("qt.chat_context"),
            replay=services.get("qt.chat_replay"),
            memory=services.get("runtime.memory"),
            document_memory=(services["runtime.document_memory"].bind(owner_is_open=lambda: not owner_binding.closed)
                             if owner_binding is not None and services.get("runtime.document_memory") is not None else None),
            prompt_refinement=services.get("runtime.prompt_refinement"),
            sensory_targets=services.get("qt.sensory"),
            diagnostics=services.get("diagnostics.tts_latency"),
            runtime_status=services.get("qt.runtime_status"),
            realtime=services.get("runtime.realtime"),
            file_transcription=services.get("runtime.file_transcription"),
            user_image_turns=services.get("qt.user_image_turns"),
            shell=services.get("qt.shell"),
            tutorials=services.get("qt.tutorials"),
            engine_lifecycle=services.get("qt.engine_lifecycle"),
            remote_commands=services.get("runtime.remote_commands"),
            music_commands=services.get("runtime.music_commands"),
            audio_story=services.get("runtime.audio_story"),
            orb_runtime=services.get("runtime.companion_orb"),
            audio_story_visual=services.get("runtime.audio_story_visual"),
            scenic_avatar_host=services.get("qt.scenic_avatar_host"),
            main_chat_remote_host=main_chat_remote_host,
            avatar_creation=avatar_creation,
            execution_lanes=execution_lanes or AddonExecutionLanes(),
        )


@dataclass(frozen=True, slots=True)
class _AddonOwner:
    addon_id: str
    generation: int
    token: UUID | None = None


class _AddonOwnerState:
    def __init__(self, addon_id: str, generation: int) -> None:
        self.owner = _AddonOwner(str(addon_id), int(generation), uuid4())
        self._lock = threading.RLock()
        self._closed = False

    @property
    def addon_id(self) -> str:
        return self.owner.addon_id

    @property
    def generation(self) -> int:
        return self.owner.generation

    @property
    def token(self) -> UUID:
        assert self.owner.token is not None
        return self.owner.token

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def ensure_open(self) -> None:
        if self.closed:
            raise AddonContextClosedError(
                f"Addon host context '{self.addon_id}' is closed."
            )

    def run_open(self, callback):
        with self._lock:
            if self._closed:
                raise AddonContextClosedError(
                    f"Addon host context '{self.addon_id}' is closed."
                )
            return callback()

    def begin_close(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._closed = True
            return True


@dataclass(frozen=True, slots=True)
class AddonOwnerBinding:
    """Host-only binding between an immutable owner token and live state."""

    owner: AddonOwnerToken
    _state: _AddonOwnerState = field(repr=False, compare=False)
    _registration_is_open: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    def ensure_open(self) -> None:
        self._state.ensure_open()
        if self._registration_is_open is not None and not self._registration_is_open():
            raise AddonContextClosedError("Owner-bound service registration is closed.")

    @property
    def closed(self) -> bool:
        return self._state.closed or (
            self._registration_is_open is not None and not self._registration_is_open()
        )


class AddonTaskSupervisor:
    """Exact-owner task, process, and resource supervision for one addon."""

    def __init__(
        self,
        *,
        addon_id: str,
        state: _AddonOwnerState,
        supervisor: WorkerSupervisor,
        lease: WorkLease,
    ) -> None:
        self._addon_id = addon_id
        self._state = state
        self._supervisor = supervisor
        self._lease = lease

    @property
    def closed(self) -> bool:
        return self._state.closed

    def spawn(
        self,
        name: str,
        target: Callable[[object], None],
        *,
        daemon: bool = True,
        on_cancel: Callable[[str], None] | None = None,
    ) -> WorkerHandle:
        return self._state.run_open(
            lambda: self._supervisor.spawn(
                name=self._owned_name(name),
                lease=self._lease,
                target=target,
                daemon=daemon,
                on_cancel=on_cancel,
                identity=self._addon_id,
                owner_token=self._state.token,
            )
        )

    def register_process(
        self,
        name: str,
        process: ProcessLike,
        *,
        graceful_stop: Callable[[], None] | None = None,
    ) -> ProcessHandle:
        return self._state.run_open(
            lambda: self._supervisor.register_process(
                name=self._owned_name(name),
                process=process,
                lease=self._lease,
                graceful_stop=graceful_stop,
                owner_token=self._state.token,
            )
        )

    def register_resource(
        self,
        name: str,
        resource: Closable,
    ) -> ResourceHandle:
        return self._state.run_open(
            lambda: self._supervisor.register_resource(
                name=self._owned_name(name),
                resource=resource,
                lease=self._lease,
                owner_token=self._state.token,
            )
        )

    def active(self) -> tuple[WorkerHandle | ProcessHandle | ResourceHandle, ...]:
        return self._supervisor.active_for_owner(self._state.token)

    def cancel_worker(self, handle: WorkerHandle, reason: str) -> None:
        if handle.owner_token != self._state.token:
            raise AddonOwnershipError(
                f"Addon '{self._addon_id}' cannot cancel another owner's worker."
            )
        self._supervisor.cancel_handles((handle,), str(reason))

    def join_worker(self, handle: WorkerHandle) -> None:
        if handle.owner_token != self._state.token:
            raise AddonOwnershipError(
                f"Addon '{self._addon_id}' cannot join another owner's worker."
            )
        self._supervisor.join_handles((handle,))

    def cancel_and_join(self, reason: str) -> None:
        self._supervisor.cancel_owner(self._state.token, str(reason))
        self._supervisor.join_owner(self._state.token)

    def failures(self) -> tuple[RuntimeFailureSnapshot, ...]:
        return tuple(
            failure
            for failure in self._supervisor.failures()
            if failure.lease == self._lease
            and failure.owner_token == self._state.token
        )

    def _owned_name(self, name: str) -> str:
        label = str(name or "").strip()
        if not label:
            raise ValueError("Addon task name is required.")
        return f"{self._addon_id}:{label}"

    def _begin_context_close(self) -> bool:
        return self._state.begin_close()

    def _close_owned(self) -> None:
        self._supervisor.cancel_owner(self._state.token, "addon_context_closed")
        self._supervisor.join_owner(self._state.token)


@dataclass(frozen=True, slots=True)
class AddonServiceRegistration:
    name: str
    owner_addon_id: str
    metadata: Mapping[str, object]


@dataclass(slots=True)
class _ServiceEntry:
    name: str
    owner: _AddonOwner
    service: object
    metadata: dict[str, object]
    provider_binding: AddonOwnerBinding | None = None


class AddonServiceRegistry:
    """Thread-safe service catalog with exact mutation ownership."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._services: dict[str, _ServiceEntry] = {}

    def register(
        self,
        *,
        owner_addon_id: str,
        service_name: str,
        service: object,
        metadata: Mapping[str, object] | None = None,
        owner_generation: int | None = None,
        owner_token: UUID | None = None,
        _provider_binding: AddonOwnerBinding | None = None,
    ) -> dict[str, object]:
        owner = _AddonOwner(
            _required_text(owner_addon_id, "Service owner addon id"),
            int(owner_generation or 0),
            owner_token,
        )
        name = _required_text(service_name, "Service name")
        with self._lock:
            existing = self._services.get(name)
            if existing is not None and existing.owner != owner:
                raise AddonOwnershipError(
                    f"Addon '{owner.addon_id}' may not replace service '{name}' owned by "
                    f"'{existing.owner.addon_id}'."
                )
            entry = _ServiceEntry(name, owner, service, dict(metadata or {}), _provider_binding)
            self._services[name] = entry
            return self._entry_payload(entry)

    def unregister(
        self,
        service_name: str,
        *,
        owner_addon_id: str | None = None,
        owner_generation: int | None = None,
        owner_token: UUID | None = None,
    ) -> bool:
        name = str(service_name or "").strip()
        if not name:
            return False
        with self._lock:
            existing = self._services.get(name)
            if existing is None:
                return False
            if (
                owner_addon_id is not None
                and (
                    existing.owner.addon_id != str(owner_addon_id)
                    or (
                        owner_generation is not None
                        and existing.owner.generation != int(owner_generation)
                    )
                    or (
                        owner_token is not None
                        and existing.owner.token != owner_token
                    )
                )
            ):
                raise AddonOwnershipError(
                    f"Addon '{owner_addon_id}' may not unregister service '{name}' "
                    f"owned by '{existing.owner.addon_id}'."
                )
            del self._services[name]
            return True

    def unregister_owner(
        self,
        owner_addon_id: str,
        *,
        owner_generation: int | None = None,
        owner_token: UUID | None = None,
    ) -> int:
        owner = str(owner_addon_id or "").strip()
        if not owner:
            return 0
        with self._lock:
            names = [
                name
                for name, entry in self._services.items()
                if entry.owner.addon_id == owner
                and (
                    owner_generation is None
                    or entry.owner.generation == int(owner_generation)
                )
                and (owner_token is None or entry.owner.token == owner_token)
            ]
            for name in names:
                del self._services[name]
            return len(names)

    def get(self, service_name: str, default: object = None) -> object:
        name = str(service_name or "").strip()
        if not name:
            return default
        with self._lock:
            entry = self._services.get(name)
            return default if entry is None or entry.provider_binding is not None else entry.service

    def _get_bound(self, service_name: str, caller: AddonOwnerBinding, default: object = None) -> object:
        caller.ensure_open()
        name = str(service_name or "").strip()
        with self._lock:
            entry = self._services.get(name)
        if entry is None:
            return default
        if entry.provider_binding is None:
            return entry.service

        def registration_is_open() -> bool:
            if entry.provider_binding.closed:
                return False
            with self._lock:
                return self._services.get(name) is entry

        binding = AddonOwnerBinding(caller.owner, caller._state, registration_is_open)
        binding.ensure_open()
        # Addon code must run outside registry and owner-state locks.
        result = entry.service(binding)
        binding.ensure_open()
        return result

    def list_entries(self) -> list[dict[str, object]]:
        with self._lock:
            entries = [self._entry_payload(entry) for entry in self._services.values()]
        return sorted(
            entries,
            key=lambda item: (
                str(item.get("owner_addon_id") or ""),
                str(item.get("name") or ""),
            ),
        )

    @staticmethod
    def _entry_payload(entry: _ServiceEntry) -> dict[str, object]:
        return {
            "name": entry.name,
            "owner_addon_id": entry.owner.addon_id,
            "service": None if entry.provider_binding is not None else entry.service,
            "metadata": dict(entry.metadata),
        }


class AddonScopedServiceRegistry:
    """One addon's close-aware view of the shared service catalog."""

    def __init__(
        self,
        registry: AddonServiceRegistry,
        state: _AddonOwnerState,
    ) -> None:
        self._registry = registry
        self._state = state

    def register(
        self,
        service_name: str,
        service: object,
        metadata: Mapping[str, object] | None = None,
    ) -> AddonServiceRegistration:
        entry = self._state.run_open(
            lambda: self._registry.register(
                owner_addon_id=self._state.addon_id,
                owner_generation=self._state.generation,
                owner_token=self._state.token,
                service_name=service_name,
                service=service,
                metadata=metadata,
            )
        )
        return AddonServiceRegistration(
            name=str(entry["name"]),
            owner_addon_id=str(entry["owner_addon_id"]),
            metadata=dict(entry.get("metadata") or {}),
        )

    def unregister(self, service_name: str) -> bool:
        return self._state.run_open(
            lambda: self._registry.unregister(
                service_name,
                owner_addon_id=self._state.addon_id,
                owner_generation=self._state.generation,
                owner_token=self._state.token,
            )
        )

    def register_consumer_factory(
        self,
        service_name: str,
        factory: Callable[[AddonOwnerBinding], object],
        metadata: Mapping[str, object] | None = None,
    ) -> AddonServiceRegistration:
        if not callable(factory):
            raise TypeError("Consumer factory must be callable.")
        entry = self._state.run_open(lambda: self._registry.register(
            owner_addon_id=self._state.addon_id,
            owner_generation=self._state.generation,
            owner_token=self._state.token,
            service_name=service_name,
            service=factory,
            metadata=metadata,
            _provider_binding=AddonOwnerBinding(
                AddonOwnerToken(self._state.addon_id, self._state.generation, self._state.token), self._state
            ),
        ))
        return AddonServiceRegistration(str(entry["name"]), str(entry["owner_addon_id"]),
                                        dict(entry.get("metadata") or {}))

    def get(self, service_name: str, default: object = None) -> object:
        self._state.ensure_open()
        return self._registry._get_bound(
            service_name, AddonOwnerBinding(
                AddonOwnerToken(self._state.addon_id, self._state.generation, self._state.token), self._state
            ), default
        )

    def list(self) -> tuple[AddonServiceRegistration, ...]:
        self._state.ensure_open()
        return tuple(
            AddonServiceRegistration(
                name=str(entry.get("name") or ""),
                owner_addon_id=str(entry.get("owner_addon_id") or ""),
                metadata=dict(entry.get("metadata") or {}),
            )
            for entry in self._registry.list_entries()
        )

    def _close_owned(self) -> None:
        self._registry.unregister_owner(
            self._state.addon_id,
            owner_generation=self._state.generation,
            owner_token=self._state.token,
        )


class AddonSpeechProviderRegistration:
    """Owner-bound registration port for an addon's TTS provider."""

    def __init__(self, services: AddonScopedServiceRegistry) -> None:
        self._services = services

    def register_provider(
        self,
        provider_id: str,
        provider: object,
        metadata: Mapping[str, object] | None = None,
    ) -> AddonServiceRegistration:
        return self._services.register(provider_id, provider, metadata)

    def unregister_provider(self, provider_id: str) -> bool:
        return self._services.unregister(provider_id)


class AddonMusicServiceRegistration:
    """Owner-bound publication port for the Spotify integration controller."""

    SERVICE_NAME = "spotify.sense"

    def __init__(self, services: AddonScopedServiceRegistry) -> None:
        self._services = services

    def register_controller(
        self,
        controller: object,
        metadata: Mapping[str, object] | None = None,
    ) -> AddonServiceRegistration:
        return self._services.register(self.SERVICE_NAME, controller, metadata)

    def unregister_controller(self) -> bool:
        return self._services.unregister(self.SERVICE_NAME)


@dataclass(slots=True)
class _EventSubscription:
    token: int
    event_name: str
    owner_addon_id: str
    owner_generation: int
    owner_token: UUID | None
    handler: Callable[[object], None]
    owner_is_open: Callable[[], bool] | None
    active: bool = True


_HIGH_FREQUENCY_EVENT_PARTS = frozenset(
    {
        "amplitude",
        "audiochunk",
        "audioframe",
        "frames",
        "prebuffer",
        "providertoken",
        "spectrum",
        "streamingtoken",
        "ttschunk",
    }
)


class AddonEventBus:
    """Thread-safe low-frequency addon event fanout."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscriptions: dict[str, list[_EventSubscription]] = {}
        self._tokens: dict[int, _EventSubscription] = {}
        self._next_token = 1

    def subscribe(
        self,
        event_name: str,
        handler: Callable[[object], None],
        *,
        owner_addon_id: str = "__host__",
        owner_generation: int = 0,
        owner_token: UUID | None = None,
        owner_is_open: Callable[[], bool] | None = None,
    ) -> int:
        name = _required_text(event_name, "Event name")
        if not callable(handler):
            raise TypeError("Event handler must be callable.")
        owner = _required_text(owner_addon_id, "Event owner addon id")
        with self._lock:
            token = self._next_token
            self._next_token += 1
            subscription = _EventSubscription(
                token,
                name,
                owner,
                int(owner_generation),
                owner_token,
                handler,
                owner_is_open,
            )
            self._subscriptions.setdefault(name, []).append(subscription)
            self._tokens[token] = subscription
            return token

    def unsubscribe(
        self,
        token: int,
        *,
        owner_addon_id: str | None = None,
        owner_generation: int | None = None,
        owner_token: UUID | None = None,
    ) -> None:
        with self._lock:
            subscription = self._tokens.get(int(token))
            if subscription is None:
                return
            if (
                owner_addon_id is not None
                and (
                    subscription.owner_addon_id != str(owner_addon_id)
                    or (
                        owner_generation is not None
                        and subscription.owner_generation != int(owner_generation)
                    )
                    or (
                        owner_token is not None
                        and subscription.owner_token != owner_token
                    )
                )
            ):
                raise AddonOwnershipError(
                    f"Addon '{owner_addon_id}' may not remove event subscription "
                    f"owned by '{subscription.owner_addon_id}'."
                )
            self._remove_locked(subscription)

    def unsubscribe_owner(
        self,
        owner_addon_id: str,
        *,
        owner_generation: int | None = None,
        owner_token: UUID | None = None,
    ) -> int:
        owner = str(owner_addon_id or "").strip()
        if not owner:
            return 0
        with self._lock:
            owned = [
                subscription
                for subscription in self._tokens.values()
                if subscription.owner_addon_id == owner
                and (
                    owner_generation is None
                    or subscription.owner_generation == int(owner_generation)
                )
                and (
                    owner_token is None
                    or subscription.owner_token == owner_token
                )
            ]
            for subscription in owned:
                self._remove_locked(subscription)
            return len(owned)

    def publish(
        self,
        event_name: str,
        payload: object = None,
        *,
        high_frequency: bool = False,
    ) -> None:
        name = _required_text(event_name, "Event name")
        _validate_general_event(name, payload, high_frequency=high_frequency)
        delivered_payload = dict(payload) if isinstance(payload, Mapping) else payload
        with self._lock:
            subscriptions = tuple(self._subscriptions.get(name, ()))
        for subscription in subscriptions:
            with self._lock:
                active = subscription.active
            if not active:
                continue
            if (
                subscription.owner_is_open is not None
                and not subscription.owner_is_open()
            ):
                continue
            try:
                subscription.handler(delivered_payload)
            except Exception:
                logging.getLogger("nc.addons.events").exception(
                    "Addon event handler failed for '%s'",
                    name,
                )

    def _remove_locked(self, subscription: _EventSubscription) -> None:
        if not subscription.active:
            return
        subscription.active = False
        self._tokens.pop(subscription.token, None)
        subscriptions = self._subscriptions.get(subscription.event_name)
        if subscriptions is None:
            return
        try:
            subscriptions.remove(subscription)
        except ValueError:
            return
        if not subscriptions:
            del self._subscriptions[subscription.event_name]


class AddonScopedEventBus:
    """One addon's close-aware event subscription and publication surface."""

    def __init__(self, event_bus: AddonEventBus, state: _AddonOwnerState) -> None:
        self._event_bus = event_bus
        self._state = state

    def subscribe(
        self,
        event_name: str,
        handler: Callable[[object], None],
    ) -> int:
        return self._state.run_open(
            lambda: self._event_bus.subscribe(
                event_name,
                handler,
                owner_addon_id=self._state.addon_id,
                owner_generation=self._state.generation,
                owner_token=self._state.token,
                owner_is_open=lambda: not self._state.closed,
            )
        )

    def unsubscribe(self, token: int) -> None:
        self._state.run_open(
            lambda: self._event_bus.unsubscribe(
                token,
                owner_addon_id=self._state.addon_id,
                owner_generation=self._state.generation,
                owner_token=self._state.token,
            )
        )

    def publish(
        self,
        event_name: str,
        payload: object = None,
        *,
        high_frequency: bool = False,
    ) -> None:
        self._state.ensure_open()
        self._event_bus.publish(
            event_name,
            payload,
            high_frequency=high_frequency,
        )

    def _close_owned(self) -> None:
        self._event_bus.unsubscribe_owner(
            self._state.addon_id,
            owner_generation=self._state.generation,
            owner_token=self._state.token,
        )


def _validate_general_event(
    event_name: str,
    payload: object,
    *,
    high_frequency: bool,
) -> None:
    normalized_name = "".join(
        character for character in event_name.lower() if character.isalnum()
    )
    if high_frequency or any(
        part in normalized_name for part in _HIGH_FREQUENCY_EVENT_PARTS
    ):
        raise AddonHighFrequencyEventError(
            "High-frequency addon data requires a bounded or latest-value lane."
        )
    try:
        _reject_hot_path_payload(payload)
    except ValueError as exc:
        raise AddonHighFrequencyEventError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AddonLatestValueSnapshot(Generic[T]):
    revision: int
    value: T | None


class AddonLatestValueChannel(Generic[T]):
    """A bounded one-slot channel for coalesced high-frequency state."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._revision = 0
        self._value: T | None = None
        self._closed = False

    def publish(self, value: T) -> int:
        with self._condition:
            if self._closed:
                raise AddonContextClosedError("Latest-value channel is closed.")
            self._revision += 1
            self._value = value
            self._condition.notify_all()
            return self._revision

    def snapshot(self) -> AddonLatestValueSnapshot[T]:
        with self._condition:
            return AddonLatestValueSnapshot(self._revision, self._value)

    def wait_for_newer(
        self,
        revision: int,
        timeout: float | None = None,
    ) -> AddonLatestValueSnapshot[T]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._revision > int(revision) or self._closed,
                timeout,
            )
            return AddonLatestValueSnapshot(self._revision, self._value)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()


@dataclass(frozen=True, slots=True)
class AddonUiTarget:
    owner_addon_id: str
    key: str
    generation: int
    _reference: Callable[[], object | None] = field(repr=False, compare=False)


class AddonUiCall:
    """One queued call whose admission can be invalidated before delivery."""

    def __init__(
        self,
        callback: Callable[[], T],
        *,
        may_run: Callable[[], bool],
        on_terminal: Callable[["AddonUiCall"], None],
    ) -> None:
        self._callback = callback
        self._may_run = may_run
        self._on_terminal = on_terminal
        self._lock = threading.Lock()
        self._complete = threading.Event()
        self._state = "pending"
        self._result: T | None = None
        self._error: BaseException | None = None

    @property
    def done(self) -> bool:
        return self._complete.is_set()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._state == "cancelled"

    def cancel(self) -> bool:
        with self._lock:
            if self._state != "pending":
                return False
            self._state = "cancelled"
            self._complete.set()
        self._on_terminal(self)
        return True

    def deliver(self) -> None:
        with self._lock:
            if self._state != "pending":
                return
            if not self._may_run():
                self._state = "cancelled"
                self._complete.set()
                terminal_without_run = True
            else:
                self._state = "running"
                terminal_without_run = False
        if terminal_without_run:
            self._on_terminal(self)
            return
        try:
            result = self._callback()
        except BaseException as exc:
            with self._lock:
                self._error = exc
                self._state = "failed"
                self._complete.set()
        else:
            with self._lock:
                self._result = result
                self._state = "completed"
                self._complete.set()
        self._on_terminal(self)

    def result(self, timeout: float | None = None) -> T | None:
        if not self._complete.wait(timeout):
            raise AddonUiDispatchTimeout("Queued addon UI callback timed out.")
        with self._lock:
            if self._error is not None:
                raise self._error
            return self._result


class _QtQueuedSubmitter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bridge = None

    def __call__(self, callback: Callable[[], None]) -> None:
        bridge = self._get_bridge()
        bridge.dispatch.emit(callback)

    def _get_bridge(self):
        with self._lock:
            if self._bridge is not None:
                return self._bridge
            try:
                from PySide6 import QtCore
            except Exception as exc:
                raise AddonUiUnavailableError(
                    "PySide6 is unavailable for queued addon UI delivery."
                ) from exc
            application = QtCore.QCoreApplication.instance()
            if application is None:
                raise AddonUiUnavailableError(
                    "A Qt application is required for queued addon UI delivery."
                )

            class _Bridge(QtCore.QObject):
                dispatch = QtCore.Signal(object)

                def __init__(self) -> None:
                    super().__init__()
                    self.dispatch.connect(
                        self._deliver,
                        QtCore.Qt.QueuedConnection,
                    )

                @staticmethod
                def _deliver(queued_callback) -> None:
                    queued_callback()

            bridge = _Bridge()
            application_thread = application.thread()
            if application_thread is not None and bridge.thread() is not application_thread:
                bridge.moveToThread(application_thread)
            self._bridge = bridge
            return bridge


class AddonUiDispatcher:
    """Addon-scoped UI delivery through one queued route, never direct fallback."""

    def __init__(
        self,
        *,
        state: _AddonOwnerState,
        queue_callback: Callable[[Callable[[], None]], None],
    ) -> None:
        self._state = state
        self._queue_callback = queue_callback
        self._lock = threading.RLock()
        self._pending: set[AddonUiCall] = set()
        self._target_generations: dict[str, int] = {}
        self._targets: dict[str, Callable[[], object | None]] = {}

    def bind_target(self, key: str, widget: object) -> AddonUiTarget:
        self._state.ensure_open()
        target_key = _required_text(key, "UI target key")
        reference = _weak_reference(widget)
        with self._lock:
            generation = self._target_generations.get(target_key, 0) + 1
            self._target_generations[target_key] = generation
            self._targets[target_key] = reference
        return AddonUiTarget(
            self._state.addon_id,
            target_key,
            generation,
            reference,
        )

    def invalidate_target(self, key: str) -> None:
        self._state.ensure_open()
        target_key = _required_text(key, "UI target key")
        with self._lock:
            self._target_generations[target_key] = (
                self._target_generations.get(target_key, 0) + 1
            )
            self._targets.pop(target_key, None)

    def post(
        self,
        callback: Callable[[], T],
        *,
        target: AddonUiTarget | None = None,
    ) -> AddonUiCall:
        self._state.ensure_open()
        if not callable(callback):
            raise TypeError("UI callback must be callable.")
        if target is not None and target.owner_addon_id != self._state.addon_id:
            raise AddonOwnershipError(
                f"Addon '{self._state.addon_id}' may not use UI target owned by "
                f"'{target.owner_addon_id}'."
            )
        call = AddonUiCall(
            callback,
            may_run=lambda: self._may_run(target),
            on_terminal=self._discard,
        )
        with self._lock:
            self._state.ensure_open()
            self._pending.add(call)
        try:
            self._queue_callback(call.deliver)
        except BaseException:
            call.cancel()
            raise
        return call

    def invoke(
        self,
        callback: Callable[[], T],
        *,
        timeout: float | None = None,
        target: AddonUiTarget | None = None,
    ) -> T | None:
        call = self.post(callback, target=target)
        if not call._complete.wait(timeout):
            call.cancel()
            raise AddonUiDispatchTimeout(
                "Queued addon UI callback timed out and was invalidated."
            )
        return call.result()

    def _may_run(self, target: AddonUiTarget | None) -> bool:
        if self._state.closed:
            return False
        if target is None:
            return True
        with self._lock:
            if self._target_generations.get(target.key) != target.generation:
                return False
            current_reference = self._targets.get(target.key)
        widget = target._reference()
        if widget is None or current_reference is not target._reference:
            return False
        return _qt_object_is_valid(widget)

    def _discard(self, call: AddonUiCall) -> None:
        with self._lock:
            self._pending.discard(call)

    def _close_owned(self) -> None:
        with self._lock:
            pending = tuple(self._pending)
            self._targets.clear()
            self._target_generations.clear()
        for call in pending:
            call.cancel()


def _weak_reference(value: object) -> Callable[[], object | None]:
    try:
        return weakref.ref(value)
    except TypeError:
        return lambda: value


def _qt_object_is_valid(value: object) -> bool:
    try:
        import shiboken6
    except Exception:
        return True
    try:
        return bool(shiboken6.isValid(value))
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class AddonHostContext:
    """Restricted immutable host surface for one addon generation."""

    addon_id: str
    owner: AddonOwnerToken
    logger: logging.Logger
    paths: AddonPaths
    tasks: AddonTaskSupervisor
    ui: AddonUiDispatcher
    services: AddonScopedServiceRegistry
    events: AddonScopedEventBus
    capabilities: AddonCapabilities

    @property
    def closed(self) -> bool:
        return self.tasks.closed

    def close(self) -> None:
        if not self.tasks._begin_context_close():
            return
        self.ui._close_owned()
        self.events._close_owned()
        self.services._close_owned()
        self.tasks._close_owned()


class AddonGateway:
    """Creates and owns restricted addon context generations."""

    def __init__(
        self,
        *,
        service_registry: AddonServiceRegistry | None = None,
        event_bus: AddonEventBus | None = None,
        worker_supervisor: WorkerSupervisor | None = None,
        ui_queue: Callable[[Callable[[], None]], None] | None = None,
        join_timeout_seconds: float = 4.0,
    ) -> None:
        self.service_registry = service_registry or AddonServiceRegistry()
        self.event_bus = event_bus or AddonEventBus()
        self.worker_supervisor = worker_supervisor or WorkerSupervisor(
            join_timeout_seconds=join_timeout_seconds
        )
        self._ui_queue = ui_queue if ui_queue is not None else _QtQueuedSubmitter()
        self._lock = threading.RLock()
        self._next_generation = 1
        self._contexts: dict[str, AddonHostContext] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def create_context(
        self,
        *,
        addon_id: str,
        logger: logging.Logger,
        paths: AddonPaths,
        capabilities: AddonCapabilities | None = None,
        capabilities_factory: Callable[[AddonOwnerBinding], AddonCapabilities] | None = None,
    ) -> AddonHostContext:
        owner = _required_text(addon_id, "Addon id")
        with self._lock:
            if self._closed:
                raise RuntimeError("Addon gateway is closed.")
            current = self._contexts.get(owner)
            if current is not None and not current.closed:
                raise AddonOwnershipError(
                    f"Addon '{owner}' already owns an open host context."
                )
            lease = WorkLease(RunId(self._next_generation))
            self._next_generation += 1
            state = _AddonOwnerState(owner, lease.run_id.value)
            owner_binding = AddonOwnerBinding(
                owner=AddonOwnerToken(owner, state.generation, state.token),
                _state=state,
            )
            services = AddonScopedServiceRegistry(self.service_registry, state)
            if capabilities is not None and capabilities_factory is not None:
                raise ValueError("Provide capabilities or capabilities_factory, not both.")
            capabilities = (
                capabilities_factory(owner_binding)
                if capabilities_factory is not None
                else capabilities or AddonCapabilities()
            )
            if capabilities.speech_providers is None or capabilities.music is None:
                capabilities = replace(
                    capabilities,
                    speech_providers=(
                        capabilities.speech_providers
                        or AddonSpeechProviderRegistration(services)
                    ),
                    music=(
                        capabilities.music
                        or AddonMusicServiceRegistration(services)
                    ),
                )
            context = AddonHostContext(
                addon_id=owner,
                owner=owner_binding.owner,
                logger=logger,
                paths=paths,
                tasks=AddonTaskSupervisor(
                    addon_id=owner,
                    state=state,
                    supervisor=self.worker_supervisor,
                    lease=lease,
                ),
                ui=AddonUiDispatcher(
                    state=state,
                    queue_callback=self._ui_queue,
                ),
                services=services,
                events=AddonScopedEventBus(self.event_bus, state),
                capabilities=capabilities,
            )
            self._contexts[owner] = context
            return context

    def context(self, addon_id: str) -> AddonHostContext | None:
        with self._lock:
            return self._contexts.get(str(addon_id or "").strip())

    def close_addon(self, addon_id: str) -> bool:
        context = self.context(addon_id)
        if context is None:
            return False
        context.close()
        return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            contexts = tuple(reversed(tuple(self._contexts.values())))
        for context in contexts:
            context.close()


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required.")
    return text


__all__ = [
    "AddonCapabilities",
    "AddonContextClosedError",
    "AddonEventBus",
    "AddonExecutionLanes",
    "AddonGateway",
    "AddonHighFrequencyEventError",
    "AddonHostContext",
    "AddonHostError",
    "AddonLatestValueChannel",
    "AddonLatestValueSnapshot",
    "AddonOwnershipError",
    "AddonPaths",
    "AddonMusicServiceRegistration",
    "AddonScopedEventBus",
    "AddonScopedServiceRegistry",
    "AddonServiceRegistration",
    "AddonServiceRegistry",
    "AddonSpeechProviderRegistration",
    "AddonTaskSupervisor",
    "AddonUiCall",
    "AddonUiDispatcher",
    "AddonUiDispatchTimeout",
    "AddonUiTarget",
    "AddonUiUnavailableError",
]
