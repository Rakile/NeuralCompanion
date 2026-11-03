"""Typed synchronous startup and shutdown orchestration for production runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Protocol

from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.runtime_use import RuntimeUseBusy, RuntimeUseGate


@dataclass(frozen=True, slots=True)
class StartupSettings:
    """The finite startup decisions frozen after applying an override."""

    audio_input_device: str
    audio_output_device: str
    offline_replay_only: bool
    avatar_mode: str
    chat_provider: str
    model_name: str
    stt_backend: str


class StartupNoticeKind(str, Enum):
    STARTING = "starting"
    AUDIO_DEVICES = "audio_devices"
    OFFLINE_REPLAY = "offline_replay"
    PROVIDER_WARNING = "provider_warning"
    AVATAR_CONNECTING = "avatar_connecting"
    AVATAR_WARNING = "avatar_warning"
    TTS_FAILURE = "tts_failure"
    RUNTIME_FAILURE = "runtime_failure"
    MICROPHONE_TESTING = "microphone_testing"
    MICROPHONE_READY = "microphone_ready"
    MICROPHONE_FAILURE = "microphone_failure"
    CRITICAL_LOOP_FAILURE = "critical_loop_failure"
    STOPPING = "stopping"
    SHUTDOWN_WARNING = "shutdown_warning"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class StartupNotice:
    kind: StartupNoticeKind
    message: str
    cause: BaseException | None = None


class StartupNoticeSink(Protocol):
    def publish(self, notice: StartupNotice) -> None: ...


class StartupEnvironmentPort(Protocol):
    def apply_config_override(self, override: Mapping[str, object]) -> None: ...
    def settings(self) -> StartupSettings: ...
    def reset_run_state(self) -> None: ...
    def prepare_runtime_files(self) -> None: ...
    def prepare_sentence_tokenizer(self) -> None: ...


class ProviderStartupPort(Protocol):
    def connection_ready(self) -> bool: ...
    def unload_local_models(self, *, reason: str) -> None: ...
    def prepare_local_chat_model(
        self,
        provider: str,
        model_name: str,
        *,
        reason: str,
        force_unload: bool,
    ) -> None: ...
    def load_local_model(self, model_name: str) -> None: ...


class AvatarStartupPort(Protocol):
    def start(self, avatar_mode: str) -> object | None: ...
    def warm_up(self, avatar: object) -> None: ...
    def set_idle(self) -> None: ...
    def stop(self) -> CommandResult[None] | None: ...


class SpeechStartupPort(Protocol):
    def initialize_tts(self) -> bool: ...
    def test_microphone(self) -> CommandResult[None]: ...
    def run_without_microphone(
        self,
        application: SynchronousConversationApplication,
    ) -> CommandResult[None]: ...
    def run_with_microphone(
        self,
        application: SynchronousConversationApplication,
    ) -> CommandResult[None]: ...


class RuntimeLifecyclePort(Protocol):
    def start(self) -> CommandResult[None]: ...
    def stop(self) -> CommandResult[None]: ...
    def stop_requested(self) -> bool: ...
    def request_stop(self) -> None: ...
    def clear_input_state(self) -> None: ...


class SynchronousConversationApplication(Protocol):
    def run(self, source: object | None) -> CommandResult[None]: ...


@dataclass(frozen=True, slots=True)
class ProductionStartupComposition:
    """Explicit production owners required by startup orchestration."""

    environment: StartupEnvironmentPort
    providers: ProviderStartupPort
    avatar: AvatarStartupPort
    speech: SpeechStartupPort
    lifecycle: RuntimeLifecyclePort
    application: SynchronousConversationApplication
    notices: StartupNoticeSink
    runtime_use: RuntimeUseGate = field(default_factory=RuntimeUseGate)


@dataclass(frozen=True, slots=True)
class _ReadyConversationApplication:
    """Speech calls this boundary only after STT setup and mic calibration."""

    application: SynchronousConversationApplication
    runtime_use: RuntimeUseGate
    reservation: str

    def run(self, source: object | None) -> CommandResult[None]:
        if not self.runtime_use.mark_ready(self.reservation):
            return CommandResult(True)
        return self.application.run(source)


class ProductionStartupOrchestrator:
    """Run production startup synchronously inside the caller-owned thread."""

    def __init__(self, composition: ProductionStartupComposition) -> None:
        self._environment = composition.environment
        self._providers = composition.providers
        self._avatar = composition.avatar
        self._speech = composition.speech
        self._lifecycle = composition.lifecycle
        self._application = composition.application
        self._notices = composition.notices
        self._runtime_use = composition.runtime_use
        self._cleanup_lock = RLock()
        self._reservation: str | None = None
        self._cleanup_pending = False

    def run(
        self,
        config_override: Mapping[str, object] | None = None,
        *,
        reservation: str | None = None,
    ) -> CommandResult[None]:
        try:
            token = reservation if reservation is not None else self._runtime_use.reserve("chat")
            self._runtime_use.claim(token, "chat")
        except RuntimeUseBusy as exc:
            state = self._runtime_use.snapshot()
            return _failure("creator_busy" if state.owner == "creator" else "runtime_busy", str(exc))
        self._reservation = token
        try:
            outcome = self._run_reserved(config_override)
        except BaseException as exc:
            outcome = _failure("production_startup_failed", str(exc) or type(exc).__name__, cause=exc)
        cleanup = self._cleanup()
        if not cleanup.accepted:
            if outcome.failure is not None:
                return _failure(outcome.failure.category,
                    outcome.failure.message + " Cleanup incomplete: " + cleanup.failure.message,
                    cause=outcome.failure.cause)
            return cleanup
        return outcome

    def retry_cleanup(self) -> CommandResult[None]:
        with self._cleanup_lock:
            if not self._cleanup_pending:
                if self._reservation is not None:
                    return _failure("runtime_busy", "The chat session is still running.")
                return CommandResult(True)
            return self._cleanup()

    def _cleanup(self) -> CommandResult[None]:
        with self._cleanup_lock:
            token = self._reservation
            self._runtime_use.begin_cleanup(token)
            failures = []
            operations = [
                self._lifecycle.request_stop,
                self._lifecycle.clear_input_state,
                self._lifecycle.stop,
                self._avatar.stop,
            ]
            release = getattr(self._speech, "release_session_resources", None)
            if callable(release):
                operations.append(release)
            try:
                self._publish(StartupNoticeKind.STOPPING, "Engine stopping...")
            except BaseException as exc:
                failures.append(str(exc) or type(exc).__name__)
            for operation in operations:
                try:
                    result = operation()
                    if isinstance(result, CommandResult) and not result.accepted:
                        failures.append(_result_message(result, "Runtime cleanup rejected."))
                    elif result is False:
                        failures.append("Runtime cleanup rejected.")
                except BaseException as exc:
                    failures.append(str(exc) or type(exc).__name__)
            # Resource finalization must not race workers whose stop timed out.
            # Keep admission held until this phase also succeeds (including retry).
            finalize = getattr(self._speech, "finalize_session_resources", None)
            if not failures and callable(finalize):
                try:
                    result = finalize()
                    if isinstance(result, CommandResult) and not result.accepted:
                        failures.append(_result_message(result, "Runtime memory cleanup rejected."))
                    elif result is False:
                        failures.append("Runtime memory cleanup rejected.")
                except BaseException as exc:
                    failures.append(str(exc) or type(exc).__name__)
            reason = "; ".join(failures)
            self._cleanup_pending = bool(failures)
            if not failures:
                self._reservation = None
            self._runtime_use.finish(token, cleanup_ok=not failures, reason=reason)
            if failures:
                try:
                    self._publish(StartupNoticeKind.SHUTDOWN_WARNING, "Runtime shutdown incomplete: " + reason)
                except BaseException:
                    pass  # The typed result and retained gate carry the failure.
                return _failure("runtime_cleanup_failed", reason)
            try:
                self._publish(StartupNoticeKind.STOPPED, "Engine Shutdown Complete.")
            except BaseException:
                pass  # Resource exit is confirmed even if notification fails.
            return CommandResult(True)

    def _run_reserved(self, config_override: Mapping[str, object] | None) -> CommandResult[None]:
        if self._runtime_use.startup_cancelled(self._reservation):
            return self._finish_cancelled_startup()
        if config_override:
            self._environment.apply_config_override(config_override)
        settings = self._environment.settings()
        if (not settings.offline_replay_only and settings.chat_provider == "lmstudio_sdk"
                and not str(settings.model_name or "").strip()):
            message = ("No chat model selected. Select a model in Runtime > LLM > LM Studio, "
                       "then start chat again.")
            self._publish(StartupNoticeKind.PROVIDER_WARNING, message)
            return _failure("chat_model_missing", message)
        self._publish(StartupNoticeKind.STARTING, "Starting Companion Engine")
        self._publish(
            StartupNoticeKind.AUDIO_DEVICES,
            "Audio devices: "
            f"input={settings.audio_input_device!r}, "
            f"output={settings.audio_output_device!r}",
        )

        self._environment.reset_run_state()
        if self._cancelled():
            return self._finish_cancelled_startup()
        self._environment.prepare_runtime_files()
        if self._cancelled():
            return self._finish_cancelled_startup()
        self._environment.prepare_sentence_tokenizer()
        if self._cancelled():
            return self._finish_cancelled_startup()

        if settings.offline_replay_only:
            self._publish(
                StartupNoticeKind.OFFLINE_REPLAY,
                "Offline replay mode: skipping chat-provider startup check.",
            )
            try:
                self._providers.unload_local_models(reason="offline replay")
            except Exception as exc:
                self._publish(
                    StartupNoticeKind.PROVIDER_WARNING,
                    f"Offline replay could not unload active LM Studio models: {exc}",
                    exc,
                )
        elif not self._providers.connection_ready():
            if self._cancelled():
                return self._finish_cancelled_startup()
            return _failure(
                "chat_provider_unavailable",
                "The selected chat provider did not pass its startup check.",
            )

        if self._cancelled():
            return self._finish_cancelled_startup()

        if settings.avatar_mode == "musetalk" and not settings.offline_replay_only:
            try:
                self._providers.unload_local_models(reason="MuseTalk warmup")
            except Exception as exc:
                self._publish(
                    StartupNoticeKind.PROVIDER_WARNING,
                    f"Could not unload active models before MuseTalk warmup: {exc}",
                    exc,
                )
        elif settings.chat_provider in {"lmstudio", "lmstudio_sdk"} and not settings.offline_replay_only:
            self._providers.prepare_local_chat_model(
                settings.chat_provider,
                settings.model_name,
                reason="LM Studio chat startup",
                force_unload=False,
            )

        if self._cancelled():
            return self._finish_cancelled_startup()

        self._publish(
            StartupNoticeKind.AVATAR_CONNECTING,
            f"Connecting to Avatar Engine: {settings.avatar_mode.upper()}",
        )
        avatar: object | None = None
        try:
            avatar = self._avatar.start(settings.avatar_mode)
            if self._cancelled():
                return self._finish_cancelled_startup()
            if avatar is not None and settings.avatar_mode == "musetalk":
                try:
                    self._avatar.warm_up(avatar)
                except Exception as exc:
                    self._publish(
                        StartupNoticeKind.AVATAR_WARNING,
                        f"MuseTalk warmup exception: {exc}",
                        exc,
                    )
                if self._cancelled():
                    return self._finish_cancelled_startup()
                self._avatar.set_idle()
        except Exception as exc:
            if self._cancelled():
                return self._finish_cancelled_startup()
            self._publish(
                StartupNoticeKind.AVATAR_WARNING,
                f"Could not connect to Avatar Engine: {exc}",
                exc,
            )
            stopped = self._avatar.stop()
            if isinstance(stopped, CommandResult) and not stopped.accepted:
                return stopped
            avatar = None

        if self._cancelled():
            return self._finish_cancelled_startup()

        if (
            settings.avatar_mode == "musetalk"
            and settings.model_name
            and not settings.offline_replay_only
            and settings.chat_provider in {"lmstudio", "lmstudio_sdk"}
        ):
            self._providers.load_local_model(settings.model_name)

        if self._cancelled():
            return self._finish_cancelled_startup()

        if not self._speech.initialize_tts():
            if self._cancelled():
                return self._finish_cancelled_startup()
            self._publish(
                StartupNoticeKind.TTS_FAILURE, "Failed to initialize TTS. Exiting."
            )
            return _failure("tts_startup_failed", "TTS initialization failed.")

        if self._cancelled():
            return self._finish_cancelled_startup()

        started = self._lifecycle.start()
        if not started.accepted:
            message = _result_message(started, "unknown runtime error")
            self._publish(
                StartupNoticeKind.RUNTIME_FAILURE,
                f"Runtime startup failed: {message}",
                started.failure.cause if started.failure is not None else None,
            )
            return started

        application = _ReadyConversationApplication(
            self._application, self._runtime_use, self._reservation or ""
        )
        outcome = CommandResult(True)
        try:
            if self._cancelled():
                pass
            elif settings.offline_replay_only:
                self._publish(
                    StartupNoticeKind.OFFLINE_REPLAY,
                    "Replay runtime ready (no microphone or Whisper initialization needed).",
                )
                outcome = application.run(None)
            elif settings.stt_backend == "none":
                outcome = self._speech.run_without_microphone(application)
            else:
                self._publish(
                    StartupNoticeKind.MICROPHONE_TESTING, "Testing microphone..."
                )
                microphone = self._speech.test_microphone()
                if self._cancelled():
                    return self._finish_cancelled_startup()
                if not microphone.accepted:
                    message = _result_message(microphone, "unknown microphone error")
                    self._publish(
                        StartupNoticeKind.MICROPHONE_FAILURE,
                        f"Microphone error: {message}",
                        microphone.failure.cause
                        if microphone.failure is not None
                        else None,
                    )
                    outcome = microphone
                else:
                    if not self._cancelled():
                        self._publish(
                            StartupNoticeKind.MICROPHONE_READY, "Microphone ready"
                        )
                        outcome = self._speech.run_with_microphone(application)
        except Exception as exc:
            self._publish(
                StartupNoticeKind.CRITICAL_LOOP_FAILURE,
                f"CRITICAL ERROR IN LOOP: {exc}",
                exc,
            )
            outcome = _failure(
                "production_loop_failed",
                "The production conversation loop failed.",
                cause=exc,
            )
        return outcome

    def _cancelled(self) -> bool:
        return (self._runtime_use.startup_cancelled(self._reservation)
                or self._lifecycle.stop_requested())

    def _finish_cancelled_startup(self) -> CommandResult[None]:
        """Complete a user-cancelled pre-runtime startup without reporting failure."""

        return CommandResult(True)

    def _publish(
        self,
        kind: StartupNoticeKind,
        message: str,
        cause: BaseException | None = None,
    ) -> None:
        self._notices.publish(StartupNotice(kind, message, cause))


def _failure(
    category: str,
    message: str,
    *,
    cause: BaseException | None = None,
) -> CommandResult[None]:
    return CommandResult(
        False,
        failure=RuntimeFailure(category, message, cause=cause),
    )


def _result_message(result: CommandResult[None], fallback: str) -> str:
    if result.failure is None:
        return fallback
    return result.failure.message or fallback


__all__ = [
    "AvatarStartupPort",
    "ProductionStartupComposition",
    "ProductionStartupOrchestrator",
    "ProviderStartupPort",
    "RuntimeLifecyclePort",
    "SpeechStartupPort",
    "StartupEnvironmentPort",
    "StartupNotice",
    "StartupNoticeKind",
    "StartupNoticeSink",
    "StartupSettings",
    "SynchronousConversationApplication",
]
