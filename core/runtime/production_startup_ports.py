"""Concrete production adapters for the synchronous startup orchestrator."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from core.runtime.config import RuntimeConfigService
from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.startup import (
    StartupNotice,
    StartupSettings,
    SynchronousConversationApplication,
)

if TYPE_CHECKING:
    from core.runtime.addons import AddonGateway
    from core.runtime.avatar import AvatarAdapter, AvatarService
    from core.runtime.lifecycle import RuntimeLifecycle
    from core.runtime.providers import ProviderSelection, ProviderService
    from core.runtime.speech_input import SpeechInputService


class EventState(Protocol):
    """The finite ``threading.Event`` surface used during startup."""

    def clear(self) -> None: ...
    def is_set(self) -> bool: ...
    def set(self) -> None: ...


class ProductionStartupEnvironmentPort:
    """Own configuration freezing and the legacy preflight side effects."""

    def __init__(
        self,
        config: RuntimeConfigService,
        stop_event: EventState,
        *,
        clear_avatar_stream_state: Callable[[], object],
        runtime_cleanup: Callable[[], object],
        sentence_tokenizer_prepare: Callable[[], object],
        seam_debug_directory: str | Path = Path("MuseTalk", "runtime", "seam_debug"),
        capture_provider_selection: Callable[[], ProviderSelection] | None = None,
        on_provider_selection: Callable[[ProviderSelection | None], None] | None = None,
    ) -> None:
        self._config = config
        self._stop_event = stop_event
        self._clear_avatar_stream_state = clear_avatar_stream_state
        self._runtime_cleanup = runtime_cleanup
        self._sentence_tokenizer_prepare = sentence_tokenizer_prepare
        self._seam_debug_directory = Path(seam_debug_directory)
        self._capture_provider_selection = capture_provider_selection
        self._on_provider_selection = on_provider_selection

    def apply_config_override(self, override: Mapping[str, object]) -> None:
        self._config.update_many(override)

    def settings(self) -> StartupSettings:
        values = self._config.snapshot().values
        selection = (self._capture_provider_selection()
                     if self._capture_provider_selection is not None
                     and not values.get("offline_replay_only", False) else None)
        if self._on_provider_selection is not None:
            self._on_provider_selection(selection)
        return StartupSettings(
            audio_input_device=str(
                values.get("audio_input_device", "Default Input")
                or "Default Input"
            ),
            audio_output_device=str(
                values.get("audio_output_device", "Default Output")
                or "Default Output"
            ),
            offline_replay_only=bool(values.get("offline_replay_only", False)),
            avatar_mode=str(
                values.get("avatar_mode", "vseeface") or "vseeface"
            ).strip().lower(),
            chat_provider=str(selection.provider_id if selection is not None
                              else values.get("chat_provider", "lmstudio") or "lmstudio")
            .strip()
            .lower(),
            model_name=str(selection.model_id if selection is not None
                           else values.get("model_name", "") or "").strip(),
            stt_backend=str(values.get("stt_backend", "none") or "none")
            .strip()
            .lower(),
        )

    def reset_run_state(self) -> None:
        self._stop_event.clear()
        self._clear_avatar_stream_state()

    def prepare_runtime_files(self) -> None:
        self._runtime_cleanup()
        shutil.rmtree(self._seam_debug_directory, ignore_errors=True)
        self._seam_debug_directory.mkdir(parents=True, exist_ok=True)

    def prepare_sentence_tokenizer(self) -> None:
        self._sentence_tokenizer_prepare()


class ProductionProviderStartupPort:
    """Adapt startup policy to the authoritative provider owner."""

    def __init__(
        self,
        config: RuntimeConfigService,
        providers: ProviderService,
        *,
        logger: Callable[[str], object] | None = None,
        capture_provider_selection: Callable[[], ProviderSelection] | None = None,
        cancel_token: object = None,
    ) -> None:
        self._config = config
        self._providers = providers
        self._logger = logger
        self._capture_provider_selection = capture_provider_selection
        self._cancel_token = cancel_token
        self._sdk_startup_selection = None
        self._startup_selection_bound = False

    def bind_startup_selection(self, selection: ProviderSelection | None) -> None:
        # Keep the exact SDK settings captured by the startup environment. A
        # subsequent run replaces this binding, including a switch away from SDK.
        self._sdk_startup_selection = selection if selection is not None and selection.provider_id == 'lmstudio_sdk' else None
        self._startup_selection_bound = True

    def connection_ready(self) -> bool:
        selection = self._selection()
        status = self._providers.runtime.check_connection(selection.provider_id)
        self._log(status.message)
        return bool(status.ok)

    def unload_local_models(self, *, reason: str) -> None:
        selected = self._sdk_startup_selection
        if not self._startup_selection_bound and not self._config.get('offline_replay_only', False):
            selected = self._selection()
        if selected is not None and selected.provider_id == 'lmstudio_sdk':
            if not self._providers.unload_selection_models(selected, reason=reason, cancel_token=self._cancel_token):
                raise RuntimeError('LM Studio SDK startup cleanup failed.')
            return
        # Local cleanup always addresses LM Studio, including cloud Personas.
        selection = self._providers.capture_selection(self._config.snapshot(), provider_id="lmstudio")
        self._providers.unload_lmstudio_models(
            reason,
            endpoint=selection.endpoint,
        )

    def prepare_local_chat_model(
        self,
        provider: str,
        model_name: str,
        *,
        reason: str,
        force_unload: bool,
    ) -> None:
        if provider == 'lmstudio_sdk':
            selection = self._selection(model_name=model_name)
            if not self._providers.prepare_model(selection,reason=reason,force_unload=force_unload,
                    initialize=True,cancel_token=self._cancel_token):
                raise RuntimeError('The selected SDK chat model could not be prepared.')
            return
        config = (self._capture_provider_selection().config
                  if self._capture_provider_selection is not None else self._config.snapshot())
        selection = self._providers.capture_selection(
            config,
            provider_id=provider,
            model_id=model_name,
        )
        self._providers.prepare_model(
            selection,
            reason=reason,
            force_unload=force_unload,
        )

    def load_local_model(self, model_name: str) -> None:
        selection = self._selection(model_name=model_name)
        if selection.provider_id == 'lmstudio_sdk':
            if not self._providers.prepare_model(selection,reason='LM Studio SDK chat startup',
                    initialize=True,cancel_token=self._cancel_token):
                raise RuntimeError('The selected SDK chat model could not be prepared.')
            return
        self._providers.load_lmstudio_model(
            model_name,
            endpoint=selection.endpoint,
        )

    def _selection(self, *, model_name: str | None = None):
        if self._sdk_startup_selection is not None:
            if model_name is not None and model_name != self._sdk_startup_selection.model_id:
                raise RuntimeError('SDK startup model no longer matches the captured selection.')
            return self._sdk_startup_selection
        if self._capture_provider_selection is not None:
            selection = self._capture_provider_selection()
            if model_name is None:
                return selection
            return self._providers.capture_selection(selection.config,
                provider_id=selection.provider_id, model_id=model_name)
        return self._providers.capture_selection(
            self._config.snapshot(),
            model_id=model_name,
        )

    def _log(self, message: object) -> None:
        if self._logger is not None:
            self._logger(str(message))


class ProductionAvatarStartupPort:
    """Attach and start one concrete avatar through ``AvatarService``."""

    def __init__(
        self,
        config: RuntimeConfigService,
        avatars: AvatarService,
        *,
        avatar_factory: Callable[[str], AvatarAdapter | None],
        set_active_avatar: Callable[[object | None], object],
        set_musetalk_idle: Callable[[], object],
    ) -> None:
        self._config = config
        self._avatars = avatars
        self._avatar_factory = avatar_factory
        self._set_active_avatar = set_active_avatar
        self._set_musetalk_idle = set_musetalk_idle

    def start(self, avatar_mode: str) -> object | None:
        candidate = self._avatar_factory(avatar_mode)
        stopped = self._avatars.stop()
        if not stopped.accepted:
            raise RuntimeError(_result_message(stopped, "Avatar cleanup failed."))
        attached = self._avatars.attach(candidate)
        if not attached.accepted:
            raise RuntimeError(_result_message(attached, "Avatar attach failed."))
        started = self._avatars.start(self._config.snapshot())
        if not started.accepted:
            raise RuntimeError(_result_message(started, "Avatar startup failed."))
        avatar = self._avatars.adapter()
        self._set_active_avatar(avatar)
        return avatar

    def warm_up(self, avatar: object) -> None:
        warmer = getattr(avatar, "warm_up", None)
        if not callable(warmer):
            raise TypeError("The selected MuseTalk avatar does not support warm_up().")
        warmer()

    def set_idle(self) -> None:
        self._set_musetalk_idle()

    def stop(self) -> CommandResult[None]:
        result = self._avatars.stop()
        if result.accepted:
            self._set_active_avatar(None)
        return result


class ProductionSpeechStartupPort:
    """Own TTS initialization and the two typed microphone entry paths."""

    def __init__(
        self,
        config: RuntimeConfigService,
        speech_input: SpeechInputService,
        *,
        initialize_tts: Callable[[], object],
        release_session_resources: Callable[[], CommandResult[None]] | None = None,
        finalize_session_resources: Callable[[], CommandResult[None]] | None = None,
    ) -> None:
        self._config = config
        self._speech_input = speech_input
        self._initialize_tts = initialize_tts
        self._release_session_resources = release_session_resources
        self._finalize_session_resources = finalize_session_resources

    def initialize_tts(self) -> bool:
        return bool(self._initialize_tts())

    def release_session_resources(self) -> CommandResult[None]:
        if self._release_session_resources is None:
            return CommandResult(True)
        return self._release_session_resources()

    def finalize_session_resources(self) -> CommandResult[None]:
        if self._finalize_session_resources is None:
            return CommandResult(True)
        return self._finalize_session_resources()

    def test_microphone(self) -> CommandResult[None]:
        try:
            microphone = self._speech_input.open_microphone(
                config=self._config.snapshot()
            )
            with microphone:
                pass
        except Exception as exc:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "microphone_unavailable",
                    str(exc) or type(exc).__name__,
                    cause=exc,
                ),
            )
        return CommandResult(True)

    def run_without_microphone(
        self,
        application: SynchronousConversationApplication,
    ) -> CommandResult[None]:
        return application.run(None)

    def run_with_microphone(
        self,
        application: SynchronousConversationApplication,
    ) -> CommandResult[None]:
        listening = self._speech_input.start_listening(self._config.snapshot())
        if not listening.accepted or listening.value is None:
            # ``main_loop`` historically kept typed/GUI chat available when the
            # long-lived microphone session could not be opened after its probe.
            return application.run(None)
        with listening.value as source:
            return application.run(source)


class ProductionRuntimeLifecyclePort:
    """Bridge stop state and input flags to the composed runtime lifecycle."""

    def __init__(
        self,
        lifecycle: RuntimeLifecycle,
        addons: AddonGateway,
        stop_event: EventState,
        *,
        listening_active: EventState,
        microphone_active: EventState,
        push_to_talk_held: EventState,
    ) -> None:
        self._lifecycle = lifecycle
        self._addons = addons
        self._stop_event = stop_event
        self._listening_active = listening_active
        self._microphone_active = microphone_active
        self._push_to_talk_held = push_to_talk_held

    def start(self) -> CommandResult[None]:
        return self._lifecycle.start()

    def stop(self) -> CommandResult[None]:
        # This ends a chat session, not the desktop application. The same
        # addon gateway must still route speech after the next Initialize.
        # Final application shutdown owns gateway closure.
        return self._lifecycle.stop()

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self) -> None:
        self._stop_event.set()

    def clear_input_state(self) -> None:
        self._listening_active.clear()
        self._microphone_active.clear()
        self._push_to_talk_held.clear()


class ProductionStartupNoticeSink:
    """Publish typed startup notices through the host's concrete logger."""

    def __init__(self, logger: Callable[[str], object]) -> None:
        self._logger = logger

    def publish(self, notice: StartupNotice) -> None:
        if not isinstance(notice, StartupNotice):
            raise TypeError("Startup notice sink requires StartupNotice.")
        self._logger(notice.message)


def _result_message(result: CommandResult[None], fallback: str) -> str:
    if result.failure is None:
        return fallback
    return result.failure.message or fallback


# Short aliases keep composition call sites readable while the longer exported
# names make the implemented startup contract explicit.
ProductionStartupEnvironment = ProductionStartupEnvironmentPort
ProductionProviderStartup = ProductionProviderStartupPort
ProductionAvatarStartup = ProductionAvatarStartupPort
ProductionSpeechStartup = ProductionSpeechStartupPort
ProductionRuntimeLifecycle = ProductionRuntimeLifecyclePort
ConsoleStartupNoticeSink = ProductionStartupNoticeSink


__all__ = [
    "ConsoleStartupNoticeSink",
    "EventState",
    "ProductionAvatarStartup",
    "ProductionAvatarStartupPort",
    "ProductionProviderStartup",
    "ProductionProviderStartupPort",
    "ProductionRuntimeLifecycle",
    "ProductionRuntimeLifecyclePort",
    "ProductionSpeechStartup",
    "ProductionSpeechStartupPort",
    "ProductionStartupEnvironment",
    "ProductionStartupEnvironmentPort",
    "ProductionStartupNoticeSink",
]
