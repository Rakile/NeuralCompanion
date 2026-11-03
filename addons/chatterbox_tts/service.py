from __future__ import annotations

import copy
import os
import inspect
import logging
import sys
import threading
import time
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any

from core.tts_latency_diagnostics import runtime_diagnostic_fields


class _SilentTqdm:
    def __init__(self, iterable=None, *args, **kwargs):
        self.iterable = iterable

    def __iter__(self):
        if self.iterable is None:
            return iter(())
        return iter(self.iterable)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, *args, **kwargs):
        return None

    def close(self):
        return None

    def set_description(self, *args, **kwargs):
        return None

    def set_postfix(self, *args, **kwargs):
        return None


def _silent_tqdm(iterable=None, *args, **kwargs):
    return _SilentTqdm(iterable, *args, **kwargs)


class _SuppressReferenceMelFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()
            muted_fragments = (
                "Reference mel length is not equal to 2 * reference token length.",
                "LlamaModel is using LlamaSdpaAttention",
                "We detected that you are passing `past_key_values` as a tuple of tuples.",
                "Xet Storage is enabled for this repo, but the 'hf_xet' package is not installed.",
                "`huggingface_hub` cache-system uses symlinks by default",
                "cache-system uses symlinks by default",
            )
            return not any(fragment in message for fragment in muted_fragments)
        except Exception:
            return True


def _suppress_chatterbox_console_noise():
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    for category, pattern in (
        (FutureWarning, r".*torch\.backends\.cuda\.sdp_kernel\(\).*deprecated.*"),
        (UserWarning, r".*`return_dict_in_generate` is NOT set to `True`, but `output_attentions` is.*"),
        (UserWarning, r".*past_key_values.*tuple of tuples.*deprecated.*"),
        (UserWarning, r".*cache-system uses symlinks by default.*"),
    ):
        try:
            warnings.filterwarnings("ignore", message=pattern, category=category)
        except Exception:
            pass
    try:
        root_logger = logging.getLogger()
        chatterbox_filter = next(
            (item for item in root_logger.filters if isinstance(item, _SuppressReferenceMelFilter)),
            None,
        )
        if chatterbox_filter is None:
            chatterbox_filter = _SuppressReferenceMelFilter()
            root_logger.addFilter(chatterbox_filter)
        for handler in list(root_logger.handlers):
            if not any(isinstance(item, _SuppressReferenceMelFilter) for item in handler.filters):
                handler.addFilter(chatterbox_filter)
    except Exception:
        pass
    for logger_name in (
        "chatterbox.models.t3.inference.alignment_stream_analyzer",
        "huggingface_hub.file_download",
        "transformers.generation.configuration_utils",
        "transformers.models.llama.modeling_llama",
    ):
        try:
            logging.getLogger(logger_name).setLevel(logging.ERROR)
        except Exception:
            pass
    for module_name in (
        "chatterbox.models.t3.t3",
        "chatterbox.models.s3gen.flow_matching",
    ):
        try:
            module = sys.modules.get(module_name)
            if module is not None:
                setattr(module, "tqdm", _silent_tqdm)
        except Exception:
            continue


def _disable_transformers_torchvision_probe():
    """Avoid optional torchvision import failures while loading Chatterbox text models."""
    try:
        import transformers.utils as transformers_utils
        import transformers.utils.import_utils as import_utils

        import_utils.is_torchvision_available = lambda: False
        transformers_utils.is_torchvision_available = lambda: False
    except Exception:
        pass


class _NoOpWatermarker:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


class ChatterboxTTSService:
    def __init__(self, context):
        _suppress_chatterbox_console_noise()
        self._context = context
        self._lock = threading.RLock()
        self._abort_event = threading.Event()
        self._model = None
        self._voice_conditionals_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._active_voice_conditionals_key: tuple[Any, ...] | None = None
        self._voice_conditionals_cache_limit = 8
        self._generation_owner_thread = ""
        self._active_diagnostic_call_id = ""
        self._active_diagnostic_chars = 0
        self._active_diagnostic_operation = ""
        self.sr = 24000

    def _record_latency_event(self, event: str, **fields: Any) -> None:
        context = self._context
        recorder = context.capabilities.diagnostics if context is not None else None
        if not callable(recorder):
            return
        try:
            recorder(str(event or ""), **dict(fields or {}))
        except Exception:
            pass

    @staticmethod
    def _model_device_label(model: Any) -> str:
        for candidate in (
            getattr(model, "device", None),
            getattr(getattr(model, "t3", None), "device", None),
            getattr(getattr(model, "s3gen", None), "device", None),
        ):
            value = str(candidate or "").strip()
            if value:
                return value[:80]
        return "unknown"

    @staticmethod
    def _voice_file_label(path: Any) -> str:
        value = str(path or "").strip()
        if not value:
            return ""
        return os.path.basename(os.path.normpath(value))[:160]

    @staticmethod
    def _token_count(value: Any) -> int:
        counter = getattr(value, "numel", None)
        if callable(counter):
            try:
                return max(0, int(counter()))
            except Exception:
                pass
        shape = getattr(value, "shape", None)
        if shape:
            try:
                count = 1
                for dimension in tuple(shape):
                    count *= int(dimension)
                return max(0, count)
            except Exception:
                pass
        try:
            return max(0, len(value))
        except Exception:
            return 0

    def _install_latency_phase_hooks(self, model: Any) -> None:
        def install(target: Any, method_name: str, event_name: str) -> None:
            if target is None:
                return
            marker = f"_nc_{event_name}_hook_installed"
            if bool(getattr(target, marker, False)):
                return
            original = getattr(target, method_name, None)
            if not callable(original):
                return

            def timed(*args, **kwargs):
                started_at = time.perf_counter()
                error_class = ""
                result = None
                try:
                    result = original(*args, **kwargs)
                    return result
                except Exception as exc:
                    error_class = type(exc).__name__
                    raise
                finally:
                    result_fields = {}
                    if event_name == "chatterbox_t3_inference" and not error_class:
                        result_fields["token_count"] = self._token_count(result)
                    self._record_latency_event(
                        event_name,
                        call_id=str(getattr(self, "_active_diagnostic_call_id", "") or ""),
                        chars=int(getattr(self, "_active_diagnostic_chars", 0) or 0),
                        operation=str(getattr(self, "_active_diagnostic_operation", "") or ""),
                        duration_ms=round((time.perf_counter() - started_at) * 1000.0, 3),
                        outcome="error" if error_class else "ok",
                        error_class=error_class,
                        **result_fields,
                    )

            try:
                setattr(target, method_name, timed)
                setattr(target, marker, True)
            except Exception:
                return

        install(model, "prepare_conditionals", "chatterbox_voice_conditioning")
        install(getattr(model, "t3", None), "inference_turbo", "chatterbox_t3_inference")
        install(getattr(model, "s3gen", None), "inference", "chatterbox_s3_inference")

    @contextmanager
    def _tracked_lock(self, operation: str):
        operation_name = str(operation or "operation").strip()[:80]
        call_id = f"{os.getpid()}-{threading.get_ident()}-{time.perf_counter_ns()}"
        observed_owner_thread = str(getattr(self, "_generation_owner_thread", "") or "")
        lock_started_at = time.perf_counter()
        with self._lock:
            lock_wait_ms = (time.perf_counter() - lock_started_at) * 1000.0
            previous_owner_thread = str(getattr(self, "_generation_owner_thread", "") or "")
            previous_call_id = str(getattr(self, "_active_diagnostic_call_id", "") or "")
            previous_chars = int(getattr(self, "_active_diagnostic_chars", 0) or 0)
            previous_operation = str(getattr(self, "_active_diagnostic_operation", "") or "")
            owner_thread = f"{threading.current_thread().name}:{operation_name}"
            self._generation_owner_thread = owner_thread
            self._active_diagnostic_call_id = call_id
            self._active_diagnostic_chars = 0
            self._active_diagnostic_operation = operation_name
            operation_started_at = time.perf_counter()
            self._record_latency_event(
                "chatterbox_lock_operation_start",
                call_id=call_id,
                operation=operation_name,
                lock_wait_ms=round(lock_wait_ms, 3),
                observed_owner_thread=observed_owner_thread,
            )
            try:
                yield
            finally:
                self._record_latency_event(
                    "chatterbox_lock_operation_end",
                    call_id=call_id,
                    operation=operation_name,
                    duration_ms=round((time.perf_counter() - operation_started_at) * 1000.0, 3),
                )
                self._generation_owner_thread = previous_owner_thread
                self._active_diagnostic_call_id = previous_call_id
                self._active_diagnostic_chars = previous_chars
                self._active_diagnostic_operation = previous_operation

    def _runtime_config_service(self):
        return self._context.capabilities.runtime_config if self._context is not None else None

    def _runtime_bool(self, key: str, default: bool) -> bool:
        service = self._runtime_config_service()
        if service is None:
            return bool(default)
        value = service.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _install_abort_hook(self, model):
        if bool(getattr(model, "_nc_abort_hook_installed", False)):
            return
        t3 = getattr(model, "t3", None)
        transformer = getattr(t3, "tfmr", None)
        original_forward = getattr(transformer, "forward", None)
        if not callable(original_forward):
            return

        abort_event = self._abort_event

        def guarded_forward(*args, **kwargs):
            if abort_event.is_set():
                raise RuntimeError("Chatterbox TTS generation cancelled during shutdown")
            return original_forward(*args, **kwargs)

        transformer.forward = guarded_forward
        setattr(model, "_nc_abort_hook_installed", True)

    def _generate_accepts(self, model, parameter_name: str) -> bool:
        try:
            signature = inspect.signature(model.generate)
        except Exception:
            return False
        return str(parameter_name or "") in signature.parameters

    def _set_watermark_enabled(self, model, enabled: bool):
        if model is None or self._generate_accepts(model, "apply_watermark"):
            return
        if not hasattr(model, "watermarker"):
            return
        original = getattr(model, "_nc_original_watermarker", None)
        if original is None:
            original = getattr(model, "watermarker", None)
            setattr(model, "_nc_original_watermarker", original)
        if enabled and isinstance(original, _NoOpWatermarker):
            try:
                import perth

                original = perth.PerthImplicitWatermarker()
                setattr(model, "_nc_original_watermarker", original)
            except Exception:
                original = getattr(model, "watermarker", original)
        model.watermarker = original if enabled else _NoOpWatermarker()

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                self._set_watermark_enabled(self._model, self._runtime_bool("tts_apply_watermark", False))
                return self._model
            _disable_transformers_torchvision_probe()
            from chatterbox import tts_turbo
            _suppress_chatterbox_console_noise()

            self._abort_event.clear()
            apply_watermark = self._runtime_bool("tts_apply_watermark", False)
            original_watermarker_cls = None
            if not apply_watermark:
                try:
                    original_watermarker_cls = tts_turbo.perth.PerthImplicitWatermarker
                    tts_turbo.perth.PerthImplicitWatermarker = _NoOpWatermarker
                except Exception:
                    original_watermarker_cls = None
            try:
                device = self._runtime_config_service()
                requested_device = device.tts_device() if device is not None else "cpu"
                self._model = tts_turbo.ChatterboxTurboTTS.from_pretrained(device=requested_device)
            finally:
                if original_watermarker_cls is not None:
                    try:
                        tts_turbo.perth.PerthImplicitWatermarker = original_watermarker_cls
                    except Exception:
                        pass
            try:
                setattr(self._model, "_nc_builtin_conds", copy.deepcopy(getattr(self._model, "conds", None)))
            except Exception:
                setattr(self._model, "_nc_builtin_conds", getattr(self._model, "conds", None))
            self._install_abort_hook(self._model)
            self._set_watermark_enabled(self._model, apply_watermark)
            self.sr = int(getattr(self._model, "sr", self.sr) or self.sr or 24000)
            return self._model

    def _use_cloned_voice(self):
        return self._runtime_bool("tts_use_cloned_voice", True)

    def _restore_builtin_conditionals(self, model):
        builtin = getattr(model, "_nc_builtin_conds", None)
        if builtin is None:
            return
        try:
            model.conds = copy.deepcopy(builtin)
        except Exception:
            model.conds = builtin
        self._active_voice_conditionals_key = None

    @staticmethod
    def _voice_conditionals_key(path: str, request: dict[str, Any]) -> tuple[Any, ...] | None:
        raw_path = str(path or "").strip()
        if not raw_path:
            return None
        try:
            resolved = os.path.normcase(os.path.realpath(raw_path))
            stat = os.stat(resolved)
        except OSError:
            return None
        return (
            resolved,
            int(stat.st_mtime_ns),
            int(stat.st_size),
            float(request.get("exaggeration", 0.0) or 0.0),
            bool(request.get("norm_loudness", True)),
        )

    def _cache_current_voice_conditionals(self, model, key: tuple[Any, ...]) -> None:
        self._active_voice_conditionals_key = key
        conditionals = getattr(model, "conds", None)
        if conditionals is None:
            return
        try:
            snapshot = copy.deepcopy(conditionals)
            mover = getattr(snapshot, "to", None)
            if callable(mover):
                snapshot = mover("cpu")
        except Exception:
            return
        self._voice_conditionals_cache[key] = snapshot
        self._voice_conditionals_cache.move_to_end(key)
        while len(self._voice_conditionals_cache) > self._voice_conditionals_cache_limit:
            self._voice_conditionals_cache.popitem(last=False)

    def _restore_cached_voice_conditionals(self, model, key: tuple[Any, ...]) -> bool:
        if self._active_voice_conditionals_key == key and getattr(model, "conds", None) is not None:
            return True
        cached = self._voice_conditionals_cache.get(key)
        if cached is None:
            return False
        try:
            conditionals = copy.deepcopy(cached)
            mover = getattr(conditionals, "to", None)
            if callable(mover):
                conditionals = mover(getattr(model, "device", "cpu"))
            model.conds = conditionals
        except Exception:
            self._voice_conditionals_cache.pop(key, None)
            return False
        self._voice_conditionals_cache.move_to_end(key)
        self._active_voice_conditionals_key = key
        return True

    def _voice_prompt_path(self):
        if not self._use_cloned_voice():
            return ""
        service = self._runtime_config_service()
        voice_path = str((service.get("voice_path", "") if service is not None else "") or "").strip()
        if voice_path and os.path.exists(voice_path):
            return voice_path
        if voice_path:
            print(f"⚠️ Voice file not found: {voice_path}. Continuing without a reference voice.")
        return ""

    def _generation_request(self, kwargs):
        # Direct requests/voice auditions use this provider's settings too.
        # Explicit captured-turn kwargs remain authoritative over current config.
        config = self._runtime_config_service()
        request = {}
        for setting, parameter, default, convert in (
            ("tts_temperature", "temperature", 0.8, float),
            ("tts_top_p", "top_p", 0.9, float),
            ("tts_top_k", "top_k", 40, int),
            ("tts_repeat_penalty", "repetition_penalty", 1.2, float),
        ):
            value = config.get(setting, default) if config is not None else default
            request[parameter] = convert(default if value in (None, "") else value)
            if parameter in ("temperature", "repetition_penalty") and request[parameter] == 0:
                # Older saved zero values used these defaults in normal speech.
                request[parameter] = default
        request["norm_loudness"] = self._runtime_bool("tts_normalize_loudness", False)
        request.update(dict(kwargs or {}))
        # These accepted API arguments are explicitly ignored by Turbo itself.
        for key in ("backend_id", "backend_label", "tts_backend", "text",
                    "min_p", "cfg_weight", "exaggeration"):
            request.pop(key, None)
        apply_watermark = self._runtime_bool("tts_apply_watermark", False)
        model = self._ensure_model()
        self._install_latency_phase_hooks(model)
        self._set_watermark_enabled(model, apply_watermark)
        if self._generate_accepts(model, "apply_watermark"):
            request["apply_watermark"] = apply_watermark
        return model, request

    def warm_up(self):
        if not self._runtime_bool("tts_prewarm_on_start", True):
            return False
        with self._tracked_lock("warm_up"):
            try:
                self._abort_event.clear()
                voice_path = self._voice_prompt_path()
                model, request = self._generation_request(
                    {
                        "audio_prompt_path": voice_path,
                        "temperature": 0.6,
                        "top_p": 0.9,
                        "top_k": 40,
                        "repetition_penalty": 1.2,
                        "min_p": 0.0,
                        "norm_loudness": False,
                    }
                )
                if not self._use_cloned_voice():
                    self._restore_builtin_conditionals(model)
                if not request.get("audio_prompt_path"):
                    request.pop("audio_prompt_path", None)
                model.generate("Ready.", **request)
                key = self._voice_conditionals_key(voice_path, request)
                if key is not None:
                    self._cache_current_voice_conditionals(model, key)
                print("✓ Chatterbox warmup complete")
                return True
            except Exception as exc:
                print(f"⚠️ Chatterbox warmup failed: {exc}")
                return False

    @property
    def audition_ready(self) -> bool:
        """Nonblocking UI hint; generate_reference rechecks under the model lock."""
        return self._model is not None and not self._abort_event.is_set()

    def generate_reference(self, text, audio_prompt_path, stop_event):
        """Audition an already-loaded model under its existing lifetime lock.

        Never starts/downloads a model or changes global voice settings. Waiting
        cancellation belongs to the caller; do not abort another generation.
        """
        while not stop_event.is_set():
            if self._lock.acquire(timeout=0.05):
                break
        else:
            raise InterruptedError("Voice audition cancelled.")
        try:
            if stop_event.is_set():
                raise InterruptedError("Voice audition cancelled.")
            if self._model is None or self._abort_event.is_set():
                raise RuntimeError("Load Chatterbox in NC before testing a voice.")
            if not os.path.isfile(audio_prompt_path):
                raise ValueError("Voice reference is missing.")
            model = self._model
            previous_conditionals = model.conds
            previous_voice_key = self._active_voice_conditionals_key
            try:
                return self.generate(text, audio_prompt_path=audio_prompt_path, use_cloned_voice=True)
            finally:
                # Audition conditioning must not change the next cached chat
                # voice, including when inference fails after conditioning.
                model.conds = previous_conditionals
                self._active_voice_conditionals_key = previous_voice_key
        finally:
            self._lock.release()

    def generate(self, text, audio_prompt_path=None, *, use_cloned_voice=None, **kwargs):
        requested_at = time.perf_counter()
        call_id = f"{os.getpid()}-{threading.get_ident()}-{time.perf_counter_ns()}"
        chars = len(str(text or "").strip())
        observed_owner_thread = str(getattr(self, "_generation_owner_thread", "") or "")
        self._record_latency_event(
            "chatterbox_generate_requested",
            call_id=call_id,
            chars=chars,
            voice_override=bool(audio_prompt_path),
            voice_file=self._voice_file_label(audio_prompt_path),
            observed_owner_thread=observed_owner_thread,
        )
        lock_started_at = time.perf_counter()
        with self._lock:
            lock_wait_ms = (time.perf_counter() - lock_started_at) * 1000.0
            owner_thread = threading.current_thread().name
            self._record_latency_event(
                "chatterbox_lock_acquired",
                call_id=call_id,
                chars=chars,
                lock_wait_ms=round(lock_wait_ms, 3),
                observed_owner_thread=observed_owner_thread,
            )
            previous_owner_thread = str(getattr(self, "_generation_owner_thread", "") or "")
            previous_call_id = str(getattr(self, "_active_diagnostic_call_id", "") or "")
            previous_chars = int(getattr(self, "_active_diagnostic_chars", 0) or 0)
            previous_operation = str(getattr(self, "_active_diagnostic_operation", "") or "")
            self._generation_owner_thread = owner_thread
            self._active_diagnostic_call_id = call_id
            self._active_diagnostic_chars = chars
            self._active_diagnostic_operation = "generate"
            generation_started_at = time.perf_counter()
            try:
                self._abort_event.clear()
                model, request = self._generation_request(kwargs)
                self._install_latency_phase_hooks(model)
                cloned_voice = bool(self._use_cloned_voice()) if use_cloned_voice is None else bool(use_cloned_voice)
                if not cloned_voice:
                    request.pop("audio_prompt_path", None)
                    self._restore_builtin_conditionals(model)
                elif audio_prompt_path is not None:
                    request.setdefault("audio_prompt_path", audio_prompt_path)
                elif "audio_prompt_path" not in request:
                    voice_path = self._voice_prompt_path()
                    if voice_path:
                        request["audio_prompt_path"] = voice_path

                voice_path = str(request.get("audio_prompt_path") or "").strip()
                conditionals_key = self._voice_conditionals_key(voice_path, request)
                restore_started_at = time.perf_counter()
                cache_hit = bool(
                    conditionals_key is not None
                    and self._restore_cached_voice_conditionals(model, conditionals_key)
                )
                restore_seconds = time.perf_counter() - restore_started_at
                if cache_hit:
                    request.pop("audio_prompt_path", None)

                model_started_at = time.perf_counter()
                setup_ms = (model_started_at - generation_started_at) * 1000.0
                model_device = self._model_device_label(model)
                self._record_latency_event(
                    "chatterbox_model_start",
                    call_id=call_id,
                    chars=chars,
                    setup_ms=round(setup_ms, 3),
                    restore_ms=round(restore_seconds * 1000.0, 3),
                    voice_cache_hit=cache_hit,
                    cloned_voice=cloned_voice,
                    voice_override=bool(voice_path),
                    voice_file=self._voice_file_label(voice_path),
                    model_device=model_device,
                    **runtime_diagnostic_fields(),
                )
                model_error_class = ""
                try:
                    result = model.generate(str(text or ""), **request)
                except Exception as exc:
                    model_error_class = type(exc).__name__
                    raise
                finally:
                    model_seconds = time.perf_counter() - model_started_at
                    self._record_latency_event(
                        "chatterbox_model_end",
                        call_id=call_id,
                        chars=chars,
                        model_ms=round(model_seconds * 1000.0, 3),
                        model_device=model_device,
                        outcome="error" if model_error_class else "ok",
                        error_class=model_error_class,
                        **runtime_diagnostic_fields(),
                    )
                if conditionals_key is not None and request.get("audio_prompt_path"):
                    self._cache_current_voice_conditionals(model, conditionals_key)
                total_seconds = time.perf_counter() - generation_started_at
                if str(os.environ.get("NC_TTS_TIMING", "") or "").strip().lower() in {"1", "true", "yes", "on"}:
                    print(
                        f"[TTS Timing] Chatterbox chars={chars} "
                        f"cache={'hit' if cache_hit else 'miss'} restore={restore_seconds:.3f}s "
                        f"model={model_seconds:.3f}s total={total_seconds:.3f}s"
                    )
                self._record_latency_event(
                    "chatterbox_generate_end",
                    call_id=call_id,
                    chars=chars,
                    lock_wait_ms=round(lock_wait_ms, 3),
                    model_ms=round(model_seconds * 1000.0, 3),
                    total_ms=round((time.perf_counter() - requested_at) * 1000.0, 3),
                    outcome="ok",
                )
                return result
            finally:
                self._generation_owner_thread = previous_owner_thread
                self._active_diagnostic_call_id = previous_call_id
                self._active_diagnostic_chars = previous_chars
                self._active_diagnostic_operation = previous_operation

    def prepare_voice(self, audio_prompt_path, **kwargs):
        path = str(audio_prompt_path or "").strip()
        if not self._use_cloned_voice() or not path or not os.path.isfile(path):
            return False
        with self._tracked_lock("prepare_voice"):
            self._abort_event.clear()
            model, request = self._generation_request(kwargs)
            key = self._voice_conditionals_key(path, request)
            if key is None:
                return False
            if self._restore_cached_voice_conditionals(model, key):
                return True
            preparer = getattr(model, "prepare_conditionals", None)
            if not callable(preparer):
                return False
            preparer(
                path,
                exaggeration=float(request.get("exaggeration", 0.0) or 0.0),
                norm_loudness=bool(request.get("norm_loudness", True)),
            )
            self._cache_current_voice_conditionals(model, key)
            return True

    def resources_snapshot(self):
        with self._lock:
            if self._model is None:
                return []
            return [{"id": str(id(self._model)), "name": "Chatterbox",
                     "model": "Chatterbox Turbo", "owner": "NC · text-to-speech",
                     "device": str(getattr(self._model, "device", "Unavailable")), "canUnload": True,
                     "processId": os.getpid(), "processLabel": "NeuralCompanion"}]

    def unload_resource(self, instance_id):
        with self._lock:
            if self._model is None or str(id(self._model)) != str(instance_id):
                return False
            self.close_strict()
            return True

    def close_strict(self):
        self._abort_event.set()
        with self._tracked_lock("close"):
            closer = getattr(self._model, "close", None)
            if callable(closer):
                result = closer()
                if result is False or getattr(result, "accepted", True) is False:
                    raise RuntimeError("Chatterbox model rejected cleanup.")
            self._model = None
            self._voice_conditionals_cache.clear()
            self._active_voice_conditionals_key = None

    def close(self):
        self._abort_event.set()
        with self._tracked_lock("close"):
            model = self._model
            self._model = None
            self._voice_conditionals_cache.clear()
            self._active_voice_conditionals_key = None
        if model is not None:
            closer = getattr(model, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
