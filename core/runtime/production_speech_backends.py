"""Explicit production ownership for mutable STT and TTS backend state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import gc
import threading
from typing import Protocol

from core import stt_runtime, text_tags, tts_runtime
from core.runtime.contracts import CommandResult, RuntimeFailure


class SpeechBackendConfig(Protocol):
    """Provide the current immutable runtime configuration snapshot."""

    def snapshot(self) -> object: ...


class ProductionSpeechBackendOwner:
    """Own production speech adapters and their addon-manager dependency."""

    __slots__ = (
        "_addon_manager_getter",
        "_config",
        "_lock",
        "_logger",
        "_stt_backend_name",
        "_stt_model",
        "_tts_backend_name",
        "_tts_device_name",
        "_tts_model",
        "_tts_reinitialization_lock",
    )

    def __init__(
        self,
        *,
        config: SpeechBackendConfig,
        tts_device: str | None = None,
        logger: Callable[[str], object] | None = None,
    ) -> None:
        if not callable(getattr(config, "snapshot", None)):
            raise TypeError(
                "Speech backend ownership requires a config snapshot source."
            )
        self._config = config
        self._tts_device_name = str(tts_device or _default_tts_device())
        self._logger = logger or print
        self._lock = threading.RLock()
        self._addon_manager_getter: Callable[[], object | None] | None = None
        self._stt_model: object | None = None
        self._stt_backend_name: str | None = None
        self._tts_model: object | None = None
        self._tts_backend_name: str | None = None
        self._tts_reinitialization_lock = threading.Lock()

    def bind_addon_manager_getter(
        self,
        getter: Callable[[], object | None],
    ) -> Callable[[], None]:
        """Bind the late-created addon manager and return its exact unbinder."""

        if not callable(getter):
            raise TypeError("Addon manager binding requires a callable getter.")
        with self._lock:
            self._addon_manager_getter = getter

        def unbind() -> None:
            with self._lock:
                if self._addon_manager_getter is getter:
                    self._addon_manager_getter = None

        return unbind

    def stt_backend_catalog(self) -> list[dict[str, object]]:
        return stt_runtime.list_available_stt_backends(
            self._addon_manager,
            logger=self._log,
        )

    def tts_backend_catalog(self) -> list[dict[str, object]]:
        return tts_runtime.list_available_tts_backends(
            self._addon_manager,
            logger=self._log,
        )

    def list_available_stt_backends(self) -> list[dict[str, object]]:
        return self.stt_backend_catalog()

    def list_available_tts_backends(self) -> list[dict[str, object]]:
        return self.tts_backend_catalog()

    def resolve_stt_backend(self, backend_id: str):
        """Resolve one addon service for ``SpeechInputCapabilities``."""

        return stt_runtime.resolve_addon_stt_backend(
            backend_id,
            self._addon_manager,
        )

    def reinitialize_stt_backend(self) -> bool:
        with self._lock:
            state = stt_runtime.initialize_stt_backend(
                runtime_config=self._runtime_config(),
                current_model=self._stt_model,
                current_backend_name=self._stt_backend_name,
                addon_resolver=self.resolve_stt_backend,
                addon_adapter_cls=stt_runtime.AddonSTTBackendAdapter,
                logger=self._log,
            )
            self._stt_model = state.model
            self._stt_backend_name = state.backend_name
            return bool(state.ok)

    def reinitialize_tts_backend(self) -> bool:
        # Backend creation and warmup can take several seconds. Keep those
        # operations serialized without holding the state lock that UI/status
        # readers use; otherwise a routine readiness read can freeze Qt for the
        # entire Chatterbox load. Publishing before warmup also preserves the
        # legacy engine's adapter visibility semantics.
        with self._tts_reinitialization_lock:
            with self._lock:
                current_model = self._tts_model
                current_backend_name = self._tts_backend_name
            state = tts_runtime.initialize_tts_backend(
                runtime_config=self._runtime_config(),
                current_model=current_model,
                current_backend_name=current_backend_name,
                addon_resolver=self.resolve_tts_backend,
                addon_adapter_cls=tts_runtime.AddonTTSBackendAdapter,
                logger=self._log,
            )
            with self._lock:
                self._tts_model = state.model
                self._tts_backend_name = state.backend_name
            model = state.model
            if state.ok and model is not None:
                warmer = getattr(model, "warm_up", None)
                if callable(warmer):
                    try:
                        warmer()
                    except Exception as exc:
                        self._log(f"TTS warmup failed: {exc}")
            return bool(state.ok)

    def resolve_tts_backend(self, backend_id: str):
        return tts_runtime.resolve_addon_tts_backend(
            backend_id,
            self._addon_manager,
        )

    def current_tts_adapter(self, _config: object = None) -> object | None:
        """Return the adapter expected by ``SpeechOutputCapabilities``."""

        with self._lock:
            return self._tts_model

    def current_stt_adapter(self, _config: object = None) -> object | None:
        """Return the initialized adapter associated with speech input."""

        with self._lock:
            return self._stt_model

    @property
    def stt_backend_name(self) -> str | None:
        with self._lock:
            return self._stt_backend_name

    @property
    def tts_backend_name(self) -> str | None:
        with self._lock:
            return self._tts_backend_name

    def stt_ready(self) -> bool:
        return self.current_stt_adapter() is not None

    def tts_ready(self) -> bool:
        return self.current_tts_adapter() is not None

    def ready(self) -> bool:
        """Report speech-output readiness for production addon owners."""

        return self.tts_ready()

    def ensure_ready(self) -> bool:
        # Startup may succeed silently with TTS disabled/unavailable; a caller
        # requesting speech needs an actual adapter, not just startup success.
        return self.tts_ready() or (self.reinitialize_tts_backend() and self.tts_ready())

    def tts_sample_rate(self, default: int = 24000) -> int:
        fallback = int(default)
        with self._lock:
            model = self._tts_model
            try:
                return int(getattr(model, "sr", fallback) or fallback)
            except (TypeError, ValueError):
                return fallback

    def sample_rate(self, default: int = 24000) -> int:
        return self.tts_sample_rate(default)

    def tts_device(self) -> str:
        return self._tts_device_name or "cpu"

    def supported_sound_tag_names(self) -> set[str]:
        """Return tags declared by the selected TTS backend."""

        values = self._runtime_config()
        backend = str(values.get("tts_backend", "") or "").strip().lower()
        if not backend or backend == "none":
            return set()
        manager = self._addon_manager()
        catalog = getattr(manager, "list_registered_services", None)
        entries = list(catalog() or ()) if callable(catalog) else []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            metadata = dict(entry.get("metadata") or {})
            kind = str(metadata.get("kind", "") or "").strip().lower()
            if kind not in {"tts", "tts_backend", "text_to_speech"}:
                continue
            service_name = str(entry.get("name", "") or "").strip().lower()
            candidate_id = str(
                metadata.get("backend_id") or service_name
            ).strip().lower()
            candidate_label = str(metadata.get("label", "") or "").strip().lower()
            if backend not in {candidate_id, service_name, candidate_label}:
                continue
            raw_tags = (
                metadata.get("supported_speech_tags")
                or metadata.get("supported_sound_tags")
                or metadata.get("supported_tts_tags")
                or ()
            )
            if isinstance(raw_tags, str):
                raw_tags = (raw_tags,)
            return {
                text_tags.normalize_bracket_tag(item)
                or str(item or "").strip().lower()
                for item in raw_tags
                if text_tags.normalize_bracket_tag(item)
                or str(item or "").strip()
            }
        if backend in {"chatterbox", "chatterbox_multilingual"}:
            return set(text_tags.SOUND_TAG_NAMES)
        return set()

    def release_session_resources(self) -> CommandResult[None]:
        """Close this session's adapters, retaining failures and addon binding."""
        failures = []
        with self._tts_reinitialization_lock:
            with self._lock:
                for label, model_field, name_field in (
                    ("TTS", "_tts_model", "_tts_backend_name"),
                    ("STT", "_stt_model", "_stt_backend_name"),
                ):
                    adapter = getattr(self, model_field)
                    if adapter is None:
                        continue
                    try:
                        closer = getattr(adapter, "close_strict", None) or getattr(adapter, "close", None)
                        if not callable(closer):
                            raise RuntimeError("Adapter has no cleanup operation.")
                        result = closer()
                        if result is False or isinstance(result, CommandResult) and not result.accepted:
                            raise RuntimeError(str(getattr(result, "failure", result)))
                    except BaseException as exc:
                        failures.append(f"{label}: {exc}")
                        continue
                    setattr(self, model_field, None)
                    setattr(self, name_field, None)
        if failures:
            return CommandResult(False, failure=RuntimeFailure("speech_cleanup_failed", "; ".join(failures)))
        return CommandResult(True)

    def finalize_session_resources(self) -> CommandResult[None]:
        """Reclaim unreachable models/cache only after the host confirms quiescence."""
        with self._tts_reinitialization_lock:
            with self._lock:
                if self._tts_model is not None or self._stt_model is not None:
                    return CommandResult(False, failure=RuntimeFailure(
                        "speech_cleanup_pending", "Speech adapters still require cleanup."))
                try:
                    cuda = tts_runtime.torch.cuda
                    initialized = cuda.is_initialized()
                    # Do not create a CUDA context merely to clean a CPU session.
                    before = {
                        device: (cuda.memory_allocated(device), cuda.memory_reserved(device))
                        for device in range(cuda.device_count())
                    } if initialized else {}
                    # Chatterbox hooks capture bound model methods, so clearing
                    # the owning adapter alone need not destroy those cycles.
                    gc.collect()
                    if initialized:
                        cuda.empty_cache()
                        for device, (allocated, reserved) in before.items():
                            self._log(
                                f"[Shutdown] CUDA {device}: allocated "
                                f"{allocated / 1024**2:.1f} -> {cuda.memory_allocated(device) / 1024**2:.1f} MiB; "
                                f"reserved {reserved / 1024**2:.1f} -> {cuda.memory_reserved(device) / 1024**2:.1f} MiB "
                                "after model/cache cleanup (remaining allocated memory is still live)."
                            )
                except Exception as exc:
                    return CommandResult(False, failure=RuntimeFailure(
                        "speech_memory_cleanup_failed", str(exc) or type(exc).__name__))
        return CommandResult(True)

    def shutdown(self) -> None:
        """Detach and close both adapters; repeated calls are harmless."""

        with self._tts_reinitialization_lock:
            with self._lock:
                tts_model = self._tts_model
                stt_model = self._stt_model
                self._tts_model = None
                self._tts_backend_name = None
                self._stt_model = None
                self._stt_backend_name = None
                self._addon_manager_getter = None
        self._close_adapter("TTS", tts_model)
        self._close_adapter("STT", stt_model)

    def _runtime_config(self) -> Mapping[str, object]:
        snapshot = self._config.snapshot()
        values = getattr(snapshot, "values", snapshot)
        if not isinstance(values, Mapping):
            raise TypeError(
                "Speech backend config snapshots must expose mapping values."
            )
        return values

    def _addon_manager(self) -> object | None:
        with self._lock:
            getter = self._addon_manager_getter
        if getter is None:
            return None
        try:
            return getter()
        except Exception as exc:
            self._log(f"[Addons] Failed to resolve addon manager: {exc}")
            return None

    def _close_adapter(self, label: str, adapter: object | None) -> None:
        closer = getattr(adapter, "close", None)
        if not callable(closer):
            return
        try:
            closer()
        except Exception as exc:
            self._log(f"{label} backend shutdown error: {exc}")

    def _log(self, message: str) -> None:
        self._logger(str(message))


def _default_tts_device() -> str:
    """Preserve the legacy CUDA-first device policy at its new owner."""

    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


__all__ = [
    "ProductionSpeechBackendOwner",
    "SpeechBackendConfig",
]
