"""Native QML ownership for the long-running NeuralCompanion session."""

from __future__ import annotations

from collections.abc import Mapping
import threading
from typing import Any

from PySide6 import QtCore
from core.runtime.stop_diagnostics import record_runtime_event


_REPLAY_ACTIONS = frozenset({"replay_last_assistant", "replay_chat_session"})
_RUNTIME_ACTIONS = frozenset(
    {
        "interrupt_response",
        "regenerate_response",
        "retry_user_input",
        "pause_speech",
        "skip_speech",
        "skip_user_reply",
        *_REPLAY_ACTIONS,
    }
)


def _failure_message(result: Any, fallback: str) -> str:
    failure = getattr(result, "failure", None)
    return str(getattr(failure, "message", "") or fallback)


class NativeRuntimeController(QtCore.QObject):
    """Run the production facade without a hidden QWidget lifecycle owner.

    The production run loop is synchronous by contract, so this owner gives it
    one dedicated Python thread. All UI notifications return through queued Qt
    signals and start requests are duplicate-safe.
    """

    runningChanged = QtCore.Signal()
    startupRequested = QtCore.Signal()
    finished = QtCore.Signal(bool, str)

    def __init__(self, application_facade: Any, parent: QtCore.QObject | None = None,
                 *, creator_startup_handoff=None, start_guard=None) -> None:
        super().__init__(parent)
        self._application = application_facade
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stopping = False
        self._cancelling = False
        self._closing = False
        self._starting = False
        self._last_initializing = False
        self._creator_startup_handoff = creator_startup_handoff
        self._start_guard = start_guard
        self._shutdown_pending = False
        self._startup_cancelled = False
        self._startup_done = threading.Event()
        self._startup_done.set()

    def set_shutdown_pending(self, pending: bool) -> None:
        """Cancel admission before shutdown; the caller waits only off the GUI."""
        with self._lock:
            self._shutdown_pending = bool(pending)
            if pending and self._starting:
                self._startup_cancelled = True

    def wait_for_startup(self) -> None:
        self._startup_done.wait()

    @QtCore.Property(bool, notify=runningChanged)
    def starting(self) -> bool:
        with self._lock:
            return self._starting

    @QtCore.Property(bool, notify=runningChanged)
    def initializing(self) -> bool:
        with self._lock:
            starting, running, stopping = self._starting, self._running, self._stopping
        if stopping:
            return False
        if starting:
            return True
        if not running:
            return False
        # Legacy test/application bindings without readiness retain their contract.
        readiness = getattr(self._application.lifecycle, "runtime_ready", None)
        return callable(readiness) and not bool(readiness())

    @QtCore.Slot()
    def refresh_readiness(self) -> None:
        """Cheap snapshot check; the bridge's existing GUI timer owns polling."""
        initializing = self.initializing
        if initializing != self._last_initializing:
            self._last_initializing = initializing
            self.runningChanged.emit()

    @QtCore.Property(bool, notify=runningChanged)
    def running(self) -> bool:
        with self._lock:
            return bool(self._running)

    @QtCore.Property(bool, notify=runningChanged)
    def stopping(self) -> bool:
        with self._lock:
            return self._stopping

    @QtCore.Property(bool, notify=runningChanged)
    def cancelling(self) -> bool:
        with self._lock:
            return self._cancelling

    @QtCore.Property(bool, notify=runningChanged)
    def cleanup_pending(self) -> bool:
        state = self._application.lifecycle.runtime_use_snapshot()
        return state["owner"] == "chat" and state["phase"] == "cleanup_failed"

    def start(self, *, offline_replay_only: bool = False) -> bool:
        return self._start(offline_replay_only=offline_replay_only)

    def _start(self, *, offline_replay_only: bool = False, replay_action: str | None = None) -> bool:
        if self._start_guard is not None and not self._start_guard():
            self.finished.emit(False, 'Stop the Local room before initializing normal chat.')
            return False
        if self._creator_startup_handoff is not None:
            return self._start_with_handoff(offline_replay_only, replay_action)
        with self._lock:
            if self._closing or self._running or self._shutdown_pending:
                return False
            reserved = self._application.lifecycle.reserve_run()
            if not reserved.accepted:
                self.finished.emit(False, _failure_message(reserved, "Runtime is busy."))
                return False
            token = reserved.value
            try:
                config = dict(self._application.config.snapshot().values)
                config["offline_replay_only"] = bool(offline_replay_only)
                if replay_action is not None:
                    staged = self._application.interaction.stage(replay_action, source="qml_offline_replay_bootstrap")
                    if not staged.accepted:
                        raise RuntimeError(_failure_message(staged, "Replay was not staged."))
                worker = threading.Thread(
                    target=self._run,
                    args=(config, token),
                    name="nc-qml-runtime",
                    daemon=True,
                )
                self._running = True
                self._thread = worker
                worker.start()
            except BaseException as error:
                if token is not None:
                    self._application.lifecycle.cancel_reserved_run(token)
                if self._thread is None or not self._thread.is_alive():
                    self._running = False
                    self._thread = None
                self.finished.emit(False, str(error) or type(error).__name__)
                self.runningChanged.emit()
                return False
        self.runningChanged.emit()
        return True

    def _start_with_handoff(self, offline_replay_only: bool, replay_action: str | None) -> bool:
        with self._lock:
            if self._closing or self._running or self._starting or self._shutdown_pending:
                return False
            self._starting = True
            self._startup_cancelled = False
            self._startup_done.clear()
        # Invalidate a departure choice on the GUI lane before the worker can
        # request mandatory release. Pending state already rejects duplicates.
        self.startupRequested.emit()
        try:
            worker = threading.Thread(target=self._prepare_and_run,
                                      args=(offline_replay_only, replay_action),
                                      name="nc-qml-startup", daemon=True)
            with self._lock:
                self._thread = worker
            worker.start()
        except BaseException as error:
            with self._lock:
                self._starting = False
                self._stopping = False
                self._cancelling = False
                self._thread = None
                closing = self._closing
            if closing:
                self._application.lifecycle.shutdown()
            else:
                self.finished.emit(False, str(error) or type(error).__name__)
            self.runningChanged.emit()
            self._startup_done.set()
            return False
        self.runningChanged.emit()
        return True

    def _prepare_and_run(self, offline_replay_only: bool, replay_action: str | None) -> None:
        token = None
        handed_to_run = False
        message = ""
        try:
            with self._creator_startup_handoff():
                with self._lock:
                    if self._closing or self._startup_cancelled:
                        return
                    reserved = self._application.lifecycle.reserve_run()
                    if not reserved.accepted:
                        raise RuntimeError(_failure_message(reserved, "Runtime is busy."))
                    token = reserved.value
            with self._lock:
                if self._closing or self._startup_cancelled:
                    return
                config = dict(self._application.config.snapshot().values)
                config["offline_replay_only"] = bool(offline_replay_only)
                if replay_action is not None:
                    staged = self._application.interaction.stage(replay_action, source="qml_offline_replay_bootstrap")
                    if not staged.accepted:
                        raise RuntimeError(_failure_message(staged, "Replay was not staged."))
                self._starting = False
                self._running = True
                handed_to_run = True
            self.runningChanged.emit()
            self._startup_done.set()
            self._run(config, token)
        except BaseException as error:
            message = str(error) or type(error).__name__
        finally:
            if not handed_to_run:
                if token is not None:
                    self._application.lifecycle.cancel_reserved_run(token)
                with self._lock:
                    self._starting = False
                    self._stopping = False
                    self._cancelling = False
                    self._thread = None
                    closing = self._closing
                if closing:
                    self._application.lifecycle.shutdown()
                else:
                    self.runningChanged.emit()
                    self.finished.emit(False, message)
                self._startup_done.set()

    def _run(self, config: Mapping[str, object], reservation: str | None = None) -> None:
        accepted = False
        message = ""
        record_runtime_event("runtime_run_started")
        try:
            result = self._application.lifecycle.run(dict(config), reservation=reservation)
            accepted = bool(getattr(result, "accepted", False))
            if not accepted:
                message = _failure_message(result, "Companion runtime failed.")
                failure = getattr(result, "failure", None)
                record_runtime_event("runtime_run_failed", error=getattr(failure, "cause", None))
        except BaseException as error:
            message = str(error) or type(error).__name__
            record_runtime_event("runtime_run_exception", error=error)
        finally:
            with self._lock:
                stop_requested = self._stopping
                self._running = False
                self._stopping = False
                self._cancelling = False
                self._thread = None
                closing = self._closing
            record_runtime_event("runtime_run_exited", accepted=accepted,
                reason="closing" if closing else "stop_requested" if stop_requested else "returned_without_ui_stop")
            if closing:
                self._application.lifecycle.shutdown()
            else:
                self.runningChanged.emit()
                self.finished.emit(bool(accepted), message)

    def request_stop(self) -> bool:
        record_runtime_event("ui_stop_requested", caller=True)
        with self._lock:
            if self._stopping:
                return True
            starting = self._starting
            if starting:
                self._startup_cancelled = True
                self._stopping = True
                self._cancelling = True
            running = bool(self._running)
        if starting:
            self.runningChanged.emit()
            return True
        if not running:
            if self.cleanup_pending:
                result = self._application.lifecycle.stop()
                self.runningChanged.emit()
                if not result.accepted:
                    raise RuntimeError(_failure_message(result, "Runtime cleanup remains incomplete."))
                return True
            return False
        initializing = self.initializing
        result = self._application.lifecycle.request_stop(engine_running=True)
        if not bool(getattr(result, "accepted", False)):
            raise RuntimeError(_failure_message(result, "Could not stop companion runtime."))
        with self._lock:
            # The worker may already have completed while request_stop returned.
            self._stopping = bool(self._running)
            self._cancelling = bool(self._running and initializing)
        self.runningChanged.emit()
        return True

    def trigger_action(self, action: str) -> dict[str, object]:
        action_key = str(action or "").strip()
        if self.starting:
            return {"accepted": False, "action": action_key,
                    "message": "Waiting for MuseTalk cleanup before runtime startup."}
        if action_key not in _RUNTIME_ACTIONS and not action_key.startswith(
            "replay_chat_session_from:"
        ):
            return {
                "accepted": False,
                "action": action_key,
                "message": "Unsupported runtime action.",
            }
        if action_key == "interrupt_response":
            try:
                detail = dict(
                    self._application.addon_speech.interrupt(
                        reason="qml_runtime_control",
                        cancel_llm_streams=True,
                    )
                    or {}
                )
            except BaseException as error:
                return {
                    "accepted": False,
                    "action": action_key,
                    "message": str(error) or "Could not interrupt the active response.",
                }
            return {"accepted": True, "action": action_key, "interrupt": detail}

        replay_action = action_key in _REPLAY_ACTIONS or action_key.startswith(
            "replay_chat_session_from:"
        )
        if not self.running:
            if not replay_action:
                return {
                    "accepted": False,
                    "action": action_key,
                    "message": "Initialize NeuralCompanion first.",
                }
            if not self._application.replay.chat_entries():
                return {
                    "accepted": False,
                    "action": action_key,
                    "message": "There are no replayable assistant messages.",
                }
            if not self._start(offline_replay_only=True, replay_action=action_key):
                return {
                    "accepted": False,
                    "action": action_key,
                    "message": "The runtime is already starting.",
                }
            return {"accepted": True, "action": action_key, "offlineReplay": True}

        replay_cancelled = False
        if action_key in {"regenerate_response", "retry_user_input", "skip_user_reply"}:
            cancel_replays = getattr(getattr(self._application, "replay", None), "cancel_all", None)
            if callable(cancel_replays):
                cancelled = cancel_replays("new_speech_action")
                if not cancelled.accepted:
                    return {"accepted": False, "action": action_key,
                            "message": _failure_message(cancelled, "Could not stop replay.")}
                replay_cancelled = bool(cancelled.value)

        if action_key in {"skip_speech", "skip_user_reply"}:
            playback_active = False
            try:
                runtime_snapshot = self._application.status.snapshot()
                playback = runtime_snapshot.playback
                playback_active = bool(
                    getattr(playback, "current", None)
                    or getattr(playback, "next", None)
                    or getattr(playback, "stopping", False)
                )
            except Exception:
                pass
            expected_phases = (
                ("speaking", "replay")
                if playback_active and not (action_key == "skip_user_reply" and replay_cancelled)
                else ("listening",)
            )
            result = None
            if action_key == "skip_speech":
                replay_commands = getattr(self._application, "replay", None)
                skip_active_message = getattr(
                    replay_commands, "skip_active_message", None
                )
                if callable(skip_active_message):
                    replay_skip = skip_active_message()
                    if not bool(getattr(replay_skip, "accepted", False)):
                        return {"accepted": False, "action": action_key,
                                "message": _failure_message(replay_skip, "Could not stop replay.")}
                    if bool(getattr(replay_skip, "accepted", False)) and bool(
                        getattr(replay_skip, "value", False)
                    ):
                        result = replay_skip
            if result is None:
                result = self._application.interaction.submit(
                    action_key,
                    payload={"expected_phases": expected_phases},
                    source="qml_runtime_control",
                )
        else:
            result = self._application.interaction.submit_manual(action_key)
        return {
            "accepted": bool(getattr(result, "accepted", False)),
            "action": action_key,
            "message": (
                ""
                if bool(getattr(result, "accepted", False))
                else _failure_message(result, "The runtime action was rejected.")
            ),
        }

    def queue_image_turn(
        self,
        image_path: str,
        *,
        image_paths: list[str] | None = None,
        content: str | None = None,
        source: str = "qml_conversation",
    ) -> None:
        from core.image_attachments import set_image_paths
        metadata = {"attachment_source": str(source or "qml_conversation")}
        set_image_paths(metadata, image_paths if image_paths is not None else [image_path])
        fallback = ("Please respond to the images I just sent you." if len(image_paths or []) > 1
                    else "Please respond to the image I just sent you.")
        result = self._application.chat.queue_typed(
            str(content or "").strip() or fallback,
            role="user",
            metadata=metadata,
        )
        if bool(getattr(result, "accepted", False)) and bool(
            dict(getattr(result, "value", {}) or {}).get("queued", False)
        ):
            return
        raise RuntimeError(_failure_message(result, "Could not queue image input."))

    def reset_conversation(self) -> None:
        record_runtime_event("conversation_reset_requested", caller=True)
        result = self._application.chat.reset_session()
        if not bool(getattr(result, "accepted", False)):
            raise RuntimeError(_failure_message(result, "Could not reset the conversation."))

    def close(self) -> None:
        record_runtime_event("runtime_close_requested", caller=True)
        with self._lock:
            if self._closing:
                return
            self._closing = True
            running = bool(self._running)
            starting = self._starting
        if running:
            try:
                self._application.lifecycle.request_stop(engine_running=True)
            except BaseException:
                pass
        elif not starting:
            # An active session performs final cleanup in _run's finally block.
            # Idle NC still owns the addon gateway and must close it on exit.
            self._application.lifecycle.shutdown()


__all__ = ["NativeRuntimeController"]
