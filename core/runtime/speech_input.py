"""Owned microphone, capture, and speech-to-text runtime coordination."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
import re
import threading
import time
from types import MappingProxyType
import uuid

from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerHandle, WorkerSupervisor
from core.stt_runtime import (
    AddonSTTBackendAdapter,
    initialize_stt_backend,
    stt_backend_runtime_config,
)


Logger = Callable[[str], None]
ConfigSnapshot = Callable[[], RuntimeConfigSnapshot]
LeaseFactory = Callable[[], WorkLease]
LeaseCheck = Callable[[WorkLease], bool]


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _freeze_config(
    config: RuntimeConfigSnapshot | Mapping[str, object] | None,
) -> RuntimeConfigSnapshot:
    if isinstance(config, RuntimeConfigSnapshot):
        return config
    return RuntimeConfigSnapshot(
        revision=0,
        values=MappingProxyType(
            {str(key): _freeze(value) for key, value in (config or {}).items()}
        ),
    )


def _failure(category: str, message: str, cause=None):
    return CommandResult(
        False,
        failure=RuntimeFailure(str(category), str(message), cause),
    )


def _has_information(text: object) -> bool:
    return bool(text and re.search(r"[a-zA-Z0-9]", str(text)))


@dataclass(frozen=True, slots=True)
class SpeechInputTuning:
    energy_threshold: float = 500.0
    dynamic_energy_threshold: bool = True
    pause_threshold: float = 2.2
    non_speaking_duration: float = 0.35
    phrase_threshold: float = 0.2
    ambient_calibration_seconds: float = 0.6
    sample_rate: int = 16000
    push_to_talk_max_seconds: float = 300.0
    push_to_talk_tail_seconds: float = 0.55
    push_to_talk_min_tail_chunks: int = 8
    barge_in_reset_seconds: float = 0.25
    barge_in_consecutive_chunks: int = 2


@dataclass(frozen=True, slots=True)
class SpeechInputCapabilities:
    """Explicit host capabilities used by the speech-input owner."""

    recognizer: object | None = None
    microphone_factory: Callable[..., object] | None = None
    microphone_names: Callable[[], object] | None = None
    addon_resolver: Callable[[str], object] | None = None
    transcribe: Callable[..., object] | None = None
    speech_module: object | None = None
    audio_data_factory: Callable[..., object] | None = None
    microphone_active: object | None = None
    push_to_talk_held: Callable[[], bool] | None = None
    set_push_to_talk_hold: Callable[[bool], object] | None = None
    np_module: object | None = None
    pcm_callback: Callable[[bytes, int, int], object] | None = None


@dataclass(frozen=True, slots=True)
class SpeechInputSnapshot:
    running: bool
    listening: bool
    push_to_talk: bool
    active_captures: int
    backend_name: str | None
    config_revision: int
    device_label: str
    calibrated_energy_threshold: float | None


@dataclass(frozen=True, slots=True)
class FinalTranscript:
    text: str
    lease: WorkLease


class SpeechCapture:
    """One supervised capture with an immutable originating lease."""

    def __init__(self, lease: WorkLease, worker_lease: WorkLease) -> None:
        self.lease = lease
        self.worker_lease = worker_lease
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._result: CommandResult[FinalTranscript] | None = None
        self._worker: WorkerHandle | None = None

    @property
    def worker(self) -> WorkerHandle | None:
        with self._lock:
            return self._worker

    def _set_worker(self, worker: WorkerHandle) -> None:
        with self._lock:
            self._worker = worker

    def complete(self, text: object) -> FinalTranscript | None:
        transcript = (
            FinalTranscript(str(text).strip(), self.lease)
            if _has_information(text)
            else None
        )
        if self._finish(CommandResult(True, value=transcript)):
            return transcript
        with self._lock:
            if self._result is not None and self._result.accepted:
                return self._result.value
        return None

    def fail(self, failure: RuntimeFailure) -> None:
        self._finish(CommandResult(False, failure=failure))

    def result(self, timeout: float | None = None) -> CommandResult[FinalTranscript]:
        if not self._done.wait(timeout):
            return _failure(
                "speech_input_pending",
                "Speech input capture has not completed",
            )
        with self._lock:
            assert self._result is not None
            return self._result

    def _finish(self, result: CommandResult[FinalTranscript]) -> bool:
        with self._lock:
            if self._result is not None:
                return False
            self._result = result
            self._done.set()
            return True


class SpeechListeningSession:
    """Idempotent owner for one entered microphone context."""

    def __init__(self, service, manager, source, config: RuntimeConfigSnapshot) -> None:
        self._service = service
        self._manager = manager
        self.source = source
        self.config = config
        self._lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def __enter__(self):
        return self.source

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        self._service._close_listening_session(self)

    def _close_owned(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        exit_context = getattr(self._manager, "__exit__", None)
        if callable(exit_context):
            exit_context(None, None, None)
            return
        close = getattr(self._manager, "close", None)
        if callable(close):
            close()


class _PcmTapStream:
    """Transparent stream proxy that mirrors PCM already read by STT."""

    def __init__(self, stream, callback, sample_rate: int, sample_width: int) -> None:
        self._stream = stream
        self._callback = callback
        self._sample_rate = int(sample_rate)
        self._sample_width = int(sample_width)

    def read(self, *args, **kwargs):
        data = self._stream.read(*args, **kwargs)
        if data:
            try:
                self._callback(data, self._sample_rate, self._sample_width)
            except BaseException:
                # Visualization is optional and must never affect STT capture.
                pass
        return data

    def finish_activity(self) -> None:
        try:
            self._callback(b"", self._sample_rate, self._sample_width)
        except BaseException:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


class SpeechInputService:
    """Own microphone, recognizer, PTT, backend, and capture lifecycle state."""

    name = "speech_input"

    def __init__(
        self,
        *,
        workers: WorkerSupervisor,
        config_snapshot: ConfigSnapshot,
        lease_factory: LeaseFactory,
        lease_is_current: LeaseCheck | None = None,
        capabilities: SpeechInputCapabilities | None = None,
        tuning: SpeechInputTuning | None = None,
        logger: Logger | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._workers = workers
        self._config_snapshot = config_snapshot
        self._lease_factory = lease_factory
        self._lease_is_current = lease_is_current or (lambda _lease: True)
        self._capabilities = capabilities or SpeechInputCapabilities()
        self._tuning = tuning or SpeechInputTuning()
        self._logger = logger
        self._clock = clock
        self._lock = threading.RLock()
        self._worker_registration_lock = threading.Lock()
        self._worker_registration_condition = threading.Condition(
            self._worker_registration_lock
        )
        self._worker_registrations_inflight = 0
        self._worker_identity = object()
        self._backend_lock = threading.RLock()
        self._backend_version = 0
        self._running = False
        self._stopping = False
        self._config = _freeze_config(None)
        self._listening: SpeechListeningSession | None = None
        self._device_label = ""
        self._calibrated_energy_threshold: float | None = None
        self._captures: dict[str, SpeechCapture] = {}
        self._push_to_talk_capture: SpeechCapture | None = None
        self._push_to_talk_active = threading.Event()
        self._backend_model = None
        self._backend_name: str | None = None
        self._barge_in_streak = 0
        self._barge_in_last_sample_at = 0.0
        self._barge_in_suppressed_until_quiet = False
        microphone_active = self._capabilities.microphone_active
        self._microphone_active = (
            microphone_active if microphone_active is not None else threading.Event()
        )

    @property
    def workers(self) -> WorkerSupervisor:
        return self._workers

    @property
    def recognizer(self):
        return self._capabilities.recognizer

    @property
    def microphone_active(self):
        return self._microphone_active

    @property
    def backend_model(self):
        with self._backend_lock:
            return self._backend_model

    @property
    def backend_name(self) -> str | None:
        with self._backend_lock:
            return self._backend_name

    def snapshot(self) -> SpeechInputSnapshot:
        with self._lock:
            listening = self._listening
            return SpeechInputSnapshot(
                running=self._running,
                listening=listening is not None and not listening.closed,
                push_to_talk=self._push_to_talk_active.is_set(),
                active_captures=len(self._captures),
                backend_name=self.backend_name,
                config_revision=self._config.revision,
                device_label=self._device_label,
                calibrated_energy_threshold=self._calibrated_energy_threshold,
            )

    def start(
        self,
        config: RuntimeConfigSnapshot | Mapping[str, object] | None = None,
    ) -> CommandResult[None]:
        frozen = self._capture_config(config)
        with self._worker_registration_condition:
            with self._lock:
                if self._stopping:
                    return _failure(
                        "speech_input_stopping",
                        "Speech input is still stopping",
                    )
                self._config = frozen
                self._running = True
        return CommandResult(True)

    def start_listening(
        self,
        config: RuntimeConfigSnapshot | Mapping[str, object] | None = None,
    ) -> CommandResult[SpeechListeningSession]:
        frozen = self._capture_config(config)
        started = self.start(frozen)
        if not started.accepted:
            return CommandResult(False, failure=started.failure)
        with self._lock:
            current = self._listening
            if current is not None and not current.closed:
                return CommandResult(True, value=current)
        if str(frozen.values.get("stt_backend", "none") or "none").strip().lower() == "none":
            return _failure(
                "speech_input_disabled",
                "Speech input is disabled by the selected STT backend",
            )
        backend = self.initialize_backend(frozen)
        if not backend.accepted:
            return CommandResult(False, failure=backend.failure)
        opened = self._open_microphone(frozen, sample_rate=self._tuning.sample_rate)
        if not opened.accepted or opened.value is None:
            return CommandResult(False, failure=opened.failure)
        manager, source = opened.value
        try:
            self._log(
                "Calibrating microphone noise floor "
                f"({self._tuning.ambient_calibration_seconds:.1f}s)..."
            )
            self._calibrate(source)
            self._log(
                "Mic calibrated "
                f"(energy threshold {float(getattr(self.recognizer, 'energy_threshold', 0.0) or 0.0):.0f})"
            )
        except BaseException as exc:
            self._log(f"Mic calibration skipped: {exc}")
        self._install_pcm_tap(source)
        session = SpeechListeningSession(self, manager, source, frozen)
        stopped_while_opening = False
        with self._lock:
            if not self._running:
                stopped_while_opening = True
            else:
                self._config = frozen
                self._device_label = str(
                    frozen.values.get("audio_input_device", "Default Input")
                    or "Default Input"
                ).strip()
                self._listening = session
        if stopped_while_opening:
            session._close_owned()
            return _failure(
                "speech_input_stopped",
                "Speech input stopped while opening the microphone",
            )
        return CommandResult(True, value=session)

    def capture_once(
        self,
        lease: WorkLease,
        *,
        source=None,
        timeout: float | None = None,
    ) -> SpeechCapture:
        return self._start_capture(
            lease,
            source=source,
            timeout=timeout,
            push_to_talk=False,
        )

    def begin_push_to_talk(self, lease: WorkLease) -> CommandResult[None]:
        with self._lock:
            current = self._push_to_talk_capture
            listening = self._listening
        if current is not None:
            return _failure(
                "push_to_talk_active",
                "A push-to-talk capture is already active",
            )
        if listening is None or listening.closed:
            opened = self.start_listening()
            if not opened.accepted or opened.value is None:
                return CommandResult(False, failure=opened.failure)
            listening = opened.value
        self._push_to_talk_active.set()
        self._set_external_push_to_talk(True)
        capture = self._start_capture(
            lease,
            source=listening.source,
            push_to_talk=True,
        )
        immediate = capture.result(0)
        if not immediate.accepted and immediate.failure is not None and immediate.failure.category != "speech_input_pending":
            self._push_to_talk_active.clear()
            self._set_external_push_to_talk(False)
            return CommandResult(False, failure=immediate.failure)
        with self._lock:
            self._push_to_talk_capture = capture
        return CommandResult(True)

    def end_push_to_talk(self) -> CommandResult[FinalTranscript]:
        with self._lock:
            capture = self._push_to_talk_capture
        if capture is None:
            return _failure(
                "push_to_talk_inactive",
                "No push-to-talk capture is active",
            )
        self._push_to_talk_active.clear()
        self._set_external_push_to_talk(False)
        result = capture.result(self._tuning.push_to_talk_max_seconds + 1.0)
        with self._lock:
            if self._push_to_talk_capture is capture:
                self._push_to_talk_capture = None
        return result

    def stop(self) -> CommandResult[None]:
        with self._worker_registration_condition:
            with self._lock:
                if self._stopping:
                    return _failure(
                        "speech_input_stopping",
                        "Speech input is already stopping",
                    )
                self._stopping = True
                self._running = False
                captures = tuple(self._captures.values())
                listening = self._listening
                self._listening = None
                self._push_to_talk_capture = None
                self._push_to_talk_active.clear()
            self._worker_registration_condition.wait_for(
                lambda: self._worker_registrations_inflight == 0
            )

        result = CommandResult(True)
        try:
            self._set_external_push_to_talk(False)
            failure = RuntimeFailure(
                "speech_input_stopped",
                "Speech input stopped before capture completed",
            )
            for capture in captures:
                capture.fail(failure)
            if listening is not None:
                self._unblock_source(listening.source)
                listening._close_owned()
            workers = self._owned_worker_handles()
            self._workers.cancel_handles(workers, "speech_input_stopped")
            self._workers.join_handles(workers)
            remaining = self._owned_worker_handles()
            if remaining:
                result = _failure(
                    "speech_input_stop_timeout",
                    f"{len(remaining)} speech input worker(s) did not stop within the supervisor timeout",
                )
            else:
                self.release_backend()
        finally:
            with self._worker_registration_condition:
                with self._lock:
                    self._stopping = False
                self._worker_registration_condition.notify_all()
        return result

    def initialize_backend(
        self,
        config: RuntimeConfigSnapshot | Mapping[str, object] | None = None,
    ) -> CommandResult[object]:
        frozen = self._capture_config(config)
        desired = str(frozen.values.get("stt_backend", "none") or "none").strip().lower()
        if self._capabilities.transcribe is not None:
            with self._backend_lock:
                self._backend_name = desired
            return CommandResult(True, value=self._capabilities.transcribe)
        if self._capabilities.addon_resolver is None:
            return _failure(
                "stt_backend_unavailable",
                f"STT backend '{desired}' is unavailable",
            )
        claim, current_model, current_name = self._claim_backend_transition()
        try:
            state = initialize_stt_backend(
                runtime_config=frozen.values,
                current_model=current_model,
                current_backend_name=current_name,
                addon_resolver=self._capabilities.addon_resolver,
                addon_adapter_cls=AddonSTTBackendAdapter,
                logger=self._log,
            )
        except BaseException as exc:
            self._finish_backend_transition(claim, None, None)
            return _failure(
                "stt_backend_unavailable",
                f"STT backend '{desired}' failed during initialization: {exc}",
                exc,
            )
        if not self._finish_backend_transition(
            claim,
            state.model,
            state.backend_name,
        ):
            return _failure(
                "stt_backend_superseded",
                f"STT backend '{desired}' lost its transition claim",
            )
        if not state.ok:
            return _failure(
                "stt_backend_unavailable",
                f"STT backend '{desired}' is unavailable",
            )
        return CommandResult(True, value=state.model)

    def release_backend(self, *, close: bool = True):
        claim, model, _backend_name = self._claim_backend_transition()
        if close and model is not None:
            closer = getattr(model, "close", None)
            if callable(closer):
                try:
                    closer()
                except BaseException as exc:
                    self._log(f"STT backend shutdown error: {exc}")
        self._finish_backend_transition(claim, None, None)
        return model

    def transcribe_audio(self, audio, *, language=None, config=None):
        frozen = self._capture_config(config)
        return self._transcribe(audio, frozen, language=language)

    def transcribe_file(self, path, *, language=None, raw: bool = False, config=None):
        frozen = self._capture_config(config)
        initialized = self.initialize_backend(frozen)
        if not initialized.accepted:
            return ((), None) if raw else None
        model = self.backend_model
        if model is None:
            return ((), None) if raw else None
        selected_language = (
            language if language is not None
            else stt_backend_runtime_config(frozen.values).get("stt_language")
        )
        if raw:
            transcriber = getattr(model, "transcribe_file_raw", None)
            if callable(transcriber):
                return transcriber(str(path), language=selected_language)
        transcriber = getattr(model, "transcribe_file", None)
        if not callable(transcriber):
            return ((), None) if raw else None
        text = transcriber(str(path), language=selected_language)
        return ((), {"text": text or ""}) if raw else text

    def listen_for_speech(self, source, *, timeout=None, lease=None):
        result = self.capture_once(
            lease or self._lease_factory(),
            source=source,
            timeout=timeout,
        ).result()
        return self._publish_capture_result(result)

    def listen_for_speech_push_to_talk(
        self,
        source,
        *,
        chunk_size: int = 1024,
        max_seconds: float | None = None,
        trailing_chunks: int | None = None,
        lease=None,
    ):
        result = self._start_capture(
            lease or self._lease_factory(),
            source=source,
            push_to_talk=True,
            chunk_size=chunk_size,
            max_seconds=max_seconds,
            trailing_chunks=trailing_chunks,
        ).result()
        return self._publish_capture_result(result)

    def transcript_is_current(self, transcript: FinalTranscript) -> bool:
        return (
            isinstance(transcript, FinalTranscript)
            and _has_information(transcript.text)
            and self._capture_lease_is_current(transcript.lease)
        )

    def selected_microphone_device_index(self, config=None) -> int | None:
        frozen = self._capture_config(config)
        label = str(
            frozen.values.get("audio_input_device", "Default Input")
            or "Default Input"
        ).strip()
        if not label or label == "Default Input":
            return None
        names = self._capabilities.microphone_names
        if names is not None:
            try:
                match = self._match_device_label(label, names() or ())
                if match is not None:
                    return int(match)
            except BaseException as exc:
                self._log(f"Could not enumerate microphone devices: {exc}")
        self._log(f"Audio input device '{label}' was not found; using default input.")
        return None

    def open_microphone(self, *, sample_rate=None, config=None):
        frozen = self._capture_config(config)
        factory = self._capabilities.microphone_factory
        if factory is None:
            raise RuntimeError("Microphone input is unavailable")
        kwargs = {}
        device_index = self.selected_microphone_device_index(frozen)
        if device_index is not None:
            kwargs["device_index"] = device_index
        if sample_rate is not None:
            kwargs["sample_rate"] = sample_rate
        return factory(**kwargs)

    def check_for_barge_in(
        self,
        source,
        *,
        energy_threshold: float = 800.0,
        chunk_size: int = 1024,
    ) -> bool:
        np_module = self._capabilities.np_module
        if np_module is None:
            return False
        try:
            if source.stream is None:
                with self._lock:
                    self._barge_in_streak = 0
                    self._barge_in_suppressed_until_quiet = False
                return False
            data = source.stream.read(chunk_size)
            if not data:
                with self._lock:
                    self._barge_in_streak = 0
                    self._barge_in_suppressed_until_quiet = False
                return False
            audio_data = np_module.frombuffer(data, dtype=np_module.int16)
            energy = np_module.sqrt(
                np_module.mean(audio_data.astype(np_module.int64) ** 2)
            )
            now = self._clock()
            calibrated_floor = float(
                getattr(self.recognizer, "energy_threshold", 0.0) or 0.0
            )
            effective_threshold = max(float(energy_threshold), calibrated_floor * 1.6)
            with self._lock:
                if now - self._barge_in_last_sample_at > self._tuning.barge_in_reset_seconds:
                    self._barge_in_streak = 0
                self._barge_in_last_sample_at = now
                if energy > effective_threshold:
                    if self._barge_in_suppressed_until_quiet:
                        self._barge_in_streak = 0
                        return False
                    self._barge_in_streak += 1
                    if self._barge_in_streak >= self._tuning.barge_in_consecutive_chunks:
                        self._barge_in_streak = 0
                        return True
                else:
                    self._barge_in_streak = 0
                    self._barge_in_suppressed_until_quiet = False
        except BaseException:
            return False
        return False

    def suppress_barge_in_until_quiet(self) -> None:
        """Discard the current detector utterance without starting STT."""
        with self._lock:
            self._barge_in_streak = 0
            self._barge_in_suppressed_until_quiet = True

    def _capture_config(self, config=None) -> RuntimeConfigSnapshot:
        return _freeze_config(self._config_snapshot() if config is None else config)

    def _claim_backend_transition(self):
        with self._backend_lock:
            self._backend_version += 1
            claim = self._backend_version
            current_model = self._backend_model
            current_name = self._backend_name
            self._backend_model = None
            self._backend_name = None
            return claim, current_model, current_name

    def _finish_backend_transition(self, claim, model, backend_name) -> bool:
        with self._backend_lock:
            current = self._backend_version == claim
            if current:
                self._backend_model = model
                self._backend_name = backend_name
            return current

    def _open_microphone(self, config, *, sample_rate):
        try:
            manager = self.open_microphone(sample_rate=sample_rate, config=config)
            enter_context = getattr(manager, "__enter__", None)
            source = enter_context() if callable(enter_context) else manager
            return CommandResult(True, value=(manager, source))
        except BaseException as exc:
            return _failure(
                "microphone_open_failed",
                f"Could not open microphone input: {exc}",
                exc,
            )

    def _calibrate(self, source) -> None:
        recognizer = self.recognizer
        if recognizer is None:
            raise RuntimeError("Speech recognizer is unavailable")
        recognizer.dynamic_energy_threshold = self._tuning.dynamic_energy_threshold
        recognizer.adjust_for_ambient_noise(
            source,
            duration=self._tuning.ambient_calibration_seconds,
        )
        with self._lock:
            self._calibrated_energy_threshold = float(
                getattr(recognizer, "energy_threshold", 0.0) or 0.0
            )

    def _install_pcm_tap(self, source) -> None:
        callback = self._capabilities.pcm_callback
        stream = getattr(source, "stream", None)
        if not callable(callback) or stream is None or isinstance(stream, _PcmTapStream):
            return
        try:
            sample_rate = int(getattr(source, "SAMPLE_RATE", self._tuning.sample_rate))
            sample_width = int(getattr(source, "SAMPLE_WIDTH", 2))
            source.stream = _PcmTapStream(
                stream,
                callback,
                sample_rate,
                sample_width,
            )
        except BaseException as exc:
            self._log(f"Microphone visualization tap unavailable: {exc}")

    def _start_capture(
        self,
        lease: WorkLease,
        *,
        source,
        timeout: float | None = None,
        push_to_talk: bool,
        chunk_size: int = 1024,
        max_seconds: float | None = None,
        trailing_chunks: int | None = None,
    ) -> SpeechCapture:
        with self._lock:
            running = self._running
            listening = self._listening
        if not running:
            started = self.start()
            if not started.accepted:
                capture = SpeechCapture(lease, lease)
                capture.fail(
                    started.failure
                    or RuntimeFailure(
                        "speech_input_stopped",
                        "Speech input is stopped",
                    )
                )
                return capture
        selected_source = source
        if selected_source is None and listening is not None and not listening.closed:
            selected_source = listening.source
        worker_lease = lease
        capture = SpeechCapture(lease, worker_lease)
        if selected_source is None:
            opened = self.start_listening()
            if not opened.accepted or opened.value is None:
                capture.fail(
                    opened.failure
                    or RuntimeFailure(
                        "microphone_not_listening",
                        "No microphone source is available for speech capture",
                    )
                )
                return capture
            listening = opened.value
            selected_source = listening.source
        frozen = (
            listening.config
            if listening is not None and selected_source is listening.source
            else self._capture_config()
        )
        capture_id = uuid.uuid4().hex

        def cancel_capture(_reason: str) -> None:
            capture.fail(
                RuntimeFailure(
                    "speech_input_stopped",
                    "Speech input stopped before capture completed",
                )
            )
            self._unblock_source(selected_source)

        def run(token) -> None:
            try:
                if token.cancelled:
                    cancel_capture(token.reason)
                    return
                if push_to_talk:
                    text = self._capture_push_to_talk(
                        selected_source,
                        token,
                        frozen,
                        chunk_size=chunk_size,
                        max_seconds=max_seconds,
                        trailing_chunks=trailing_chunks,
                    )
                else:
                    text = self._capture_recognized(
                        selected_source,
                        token,
                        frozen,
                        timeout=timeout,
                    )
                if token.cancelled:
                    cancel_capture(token.reason)
                    return
                if _has_information(text) and not self._capture_lease_is_current(
                    capture.lease
                ):
                    capture.fail(self._stale_lease_failure())
                    return
                capture.complete(text)
            finally:
                self._capture_finished(capture_id, capture)

        with self._worker_registration_condition:
            with self._lock:
                if not self._running or self._stopping:
                    capture.fail(
                        RuntimeFailure(
                            "speech_input_stopped",
                            "Speech input is stopped",
                        )
                    )
                    return capture
                self._captures[capture_id] = capture
            self._worker_registrations_inflight += 1

        registration_finished = False
        try:
            worker = self._workers.spawn(
                name="nc-speech-input",
                lease=worker_lease,
                target=run,
                on_cancel=cancel_capture,
                identity=(self._worker_identity, capture),
            )
            capture._set_worker(worker)
            with self._worker_registration_condition:
                with self._lock:
                    stale_registration = not self._running or self._stopping
                    if stale_registration:
                        self._captures.pop(capture_id, None)
                if not stale_registration:
                    self._worker_registrations_inflight -= 1
                    registration_finished = True
                    self._worker_registration_condition.notify_all()
            if stale_registration:
                capture.fail(
                    RuntimeFailure(
                        "speech_input_stopped",
                        "Speech input stopped while registering its worker",
                    )
                )
                self._workers.cancel_handles((worker,), "speech_input_stopped")
                self._workers.join_handles((worker,))
        except BaseException as exc:
            with self._lock:
                self._captures.pop(capture_id, None)
            capture.fail(
                RuntimeFailure(
                    "speech_input_worker_start_failed",
                    f"Could not start speech input worker: {exc}",
                    exc,
                )
            )
        finally:
            if not registration_finished:
                with self._worker_registration_condition:
                    self._worker_registrations_inflight -= 1
                    self._worker_registration_condition.notify_all()
        return capture

    def _capture_recognized(self, source, token, config, *, timeout):
        recognizer = self.recognizer
        speech_module = self._capabilities.speech_module
        if recognizer is None or speech_module is None:
            return None
        recognizer.energy_threshold = self._tuning.energy_threshold
        recognizer.dynamic_energy_threshold = self._tuning.dynamic_energy_threshold
        recognizer.pause_threshold = self._tuning.pause_threshold
        recognizer.non_speaking_duration = self._tuning.non_speaking_duration
        recognizer.phrase_threshold = self._tuning.phrase_threshold
        self._microphone_active.set()
        try:
            audio = recognizer.listen(source, timeout=timeout)
            if token.cancelled:
                return None
            return self._transcribe(audio, config)
        except speech_module.WaitTimeoutError:
            return None
        except speech_module.UnknownValueError:
            return None
        except BaseException as exc:
            if not token.cancelled:
                self._log(f"Mic error: {exc}")
            return None
        finally:
            self._microphone_active.clear()
            self._finish_pcm_activity(source)

    def _capture_push_to_talk(
        self,
        source,
        token,
        config,
        *,
        chunk_size,
        max_seconds,
        trailing_chunks,
    ):
        speech_module = self._capabilities.speech_module
        audio_data_factory = self._capabilities.audio_data_factory
        if speech_module is None or audio_data_factory is None:
            return None
        sample_rate = getattr(source, "SAMPLE_RATE", self._tuning.sample_rate)
        sample_width = getattr(source, "SAMPLE_WIDTH", 2)
        if trailing_chunks is None:
            chunk_seconds = float(chunk_size) / max(float(sample_rate), 1.0)
            trailing_chunks = max(
                self._tuning.push_to_talk_min_tail_chunks,
                int(
                    math.ceil(
                        self._tuning.push_to_talk_tail_seconds
                        / max(chunk_seconds, 0.001)
                    )
                ),
            )
        limit = (
            self._tuning.push_to_talk_max_seconds
            if max_seconds is None
            else float(max_seconds)
        )
        deadline = self._clock() + limit if limit else None
        frames = []
        trailing = 0
        self._microphone_active.set()
        try:
            while not token.cancelled and (
                deadline is None or self._clock() < deadline
            ):
                if source.stream is None:
                    break
                try:
                    data = source.stream.read(chunk_size)
                except BaseException:
                    break
                if data:
                    frames.append(data)
                if self._push_to_talk_is_held():
                    trailing = trailing_chunks
                    continue
                if trailing > 0:
                    trailing -= 1
                    continue
                break
            if (
                deadline is not None
                and self._clock() >= deadline
                and self._push_to_talk_is_held()
            ):
                self._log(
                    "Push-to-talk reached the recording safety limit and stopped automatically."
                )
            if token.cancelled or not frames:
                return None
            audio = audio_data_factory(b"".join(frames), sample_rate, sample_width)
            return self._transcribe(audio, config)
        except speech_module.UnknownValueError:
            return None
        except BaseException as exc:
            if not token.cancelled:
                self._log(f"Push-to-talk mic error: {exc}")
            return None
        finally:
            self._microphone_active.clear()
            self._finish_pcm_activity(source)

    @staticmethod
    def _finish_pcm_activity(source) -> None:
        stream = getattr(source, "stream", None)
        finish = getattr(stream, "finish_activity", None)
        if callable(finish):
            finish()

    def _transcribe(self, audio, config, *, language=None):
        selected_language = (
            language if language is not None
            else stt_backend_runtime_config(config.values).get("stt_language")
        )
        transcriber = self._capabilities.transcribe
        if transcriber is not None:
            try:
                return transcriber(audio, language=selected_language)
            except TypeError:
                return transcriber(audio)
        initialized = self.initialize_backend(config)
        if not initialized.accepted:
            return None
        model = self.backend_model
        if model is None:
            return None
        return model.transcribe(audio, language=selected_language)

    def _capture_finished(self, capture_id: str, capture: SpeechCapture) -> None:
        with self._lock:
            if self._captures.get(capture_id) is capture:
                self._captures.pop(capture_id, None)

    def _capture_lease_is_current(self, lease: WorkLease) -> bool:
        try:
            return bool(self._lease_is_current(lease))
        except BaseException as exc:
            self._log(f"Speech input lease validation failed: {exc}")
            return False

    @staticmethod
    def _stale_lease_failure() -> RuntimeFailure:
        return RuntimeFailure(
            "speech_input_stale_lease",
            "Speech input no longer owns its originating session or turn route",
        )

    def _publish_capture_result(
        self,
        result: CommandResult[FinalTranscript],
    ) -> CommandResult[FinalTranscript]:
        transcript = result.value
        if not result.accepted or transcript is None:
            return result
        if not self.transcript_is_current(transcript):
            return CommandResult(False, failure=self._stale_lease_failure())
        return result

    def _owned_worker_handles(self) -> tuple[WorkerHandle, ...]:
        handles = self._workers.active_for(lambda _lease: True)
        return tuple(
            handle
            for handle in handles
            if isinstance(handle, WorkerHandle)
            and isinstance(handle.identity, tuple)
            and len(handle.identity) == 2
            and handle.identity[0] is self._worker_identity
        )

    def _close_listening_session(self, session: SpeechListeningSession) -> None:
        with self._lock:
            if self._listening is session:
                self._listening = None
        session._close_owned()

    def _push_to_talk_is_held(self) -> bool:
        if self._push_to_talk_active.is_set():
            return True
        held = self._capabilities.push_to_talk_held
        if held is None:
            return False
        try:
            return bool(held())
        except BaseException:
            return False

    def _set_external_push_to_talk(self, active: bool) -> None:
        setter = self._capabilities.set_push_to_talk_hold
        if setter is None:
            return
        try:
            setter(bool(active))
        except BaseException as exc:
            self._log(f"Push-to-talk state update failed: {exc}")

    @staticmethod
    def _unblock_source(source) -> None:
        stream = getattr(source, "stream", None)
        if stream is None:
            return
        for name in ("stop_stream", "abort", "close"):
            operation = getattr(stream, name, None)
            if not callable(operation):
                continue
            try:
                operation()
            except BaseException:
                pass

    @staticmethod
    def _match_device_label(label: object, names) -> int | None:
        wanted = str(label or "").strip().casefold()
        if not wanted:
            return None
        normalized = [
            (str(name or "").strip().casefold(), index)
            for index, name in enumerate(list(names or ()))
        ]
        for name, index in normalized:
            if name == wanted:
                return index
        for name, index in normalized:
            if wanted in name or name in wanted:
                return index
        return None

    def _log(self, message: str) -> None:
        if self._logger is None:
            return
        try:
            self._logger(str(message))
        except BaseException:
            pass


__all__ = [
    "FinalTranscript",
    "SpeechCapture",
    "SpeechInputCapabilities",
    "SpeechInputService",
    "SpeechInputSnapshot",
    "SpeechInputTuning",
    "SpeechListeningSession",
]
