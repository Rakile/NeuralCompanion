from __future__ import annotations

import inspect
import importlib
import copy
import logging
import os
import threading
import warnings


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


class _SuppressChatterboxFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()
            muted_fragments = (
                "Reference mel length is not equal to 2 * reference token length.",
                "LlamaModel is using LlamaSdpaAttention",
                "We detected that you are passing `past_key_values` as a tuple of tuples.",
            )
            return not any(fragment in message for fragment in muted_fragments)
        except Exception:
            return True


def _suppress_chatterbox_console_noise():
    for category, pattern in (
        (FutureWarning, r".*torch\.backends\.cuda\.sdp_kernel\(\).*deprecated.*"),
        (UserWarning, r".*`return_dict_in_generate` is NOT set to `True`, but `output_attentions` is.*"),
        (UserWarning, r".*past_key_values.*tuple of tuples.*deprecated.*"),
    ):
        try:
            warnings.filterwarnings("ignore", message=pattern, category=category)
        except Exception:
            pass
    try:
        root_logger = logging.getLogger()
        if not any(isinstance(item, _SuppressChatterboxFilter) for item in root_logger.filters):
            root_logger.addFilter(_SuppressChatterboxFilter())
    except Exception:
        pass
    for logger_name in (
        "chatterbox.models.t3.inference.alignment_stream_analyzer",
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
            module = importlib.import_module(module_name)
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


class ChatterboxMultilingualTTSService:
    def __init__(self, context):
        _suppress_chatterbox_console_noise()
        self._context = context
        self._lock = threading.RLock()
        self._model = None
        self.sr = 24000

    def _runtime_config_service(self):
        return self._context.get_service("qt.runtime_config") if self._context is not None else None

    def _engine_attr(self, name: str, default=None):
        service = self._runtime_config_service()
        if service is not None and hasattr(service, "engine_attr"):
            return service.engine_attr(name, default)
        return default

    def _runtime_language(self):
        service = self._runtime_config_service()
        value = service.get("chatterbox_multilingual_language", "en") if service is not None else "en"
        return str(value or "en").strip().lower() or "en"

    def _runtime_bool(self, key: str, default: bool) -> bool:
        service = self._runtime_config_service()
        if service is None:
            return bool(default)
        value = service.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _runtime_generation_settings(self):
        service = self._runtime_config_service()
        getter = service.get if service is not None else (lambda _key, default=None: default)
        return {
            "seed": max(0, int(getter("chatterbox_multilingual_seed", 0) or 0)),
            "temperature": max(0.05, float(getter("chatterbox_multilingual_temperature", 0.8) or 0.8)),
            "top_p": max(0.0, min(1.0, float(getter("chatterbox_multilingual_top_p", 1.0) or 1.0))),
            "top_k": max(0, int(getter("chatterbox_multilingual_top_k", 40) or 40)),
            "repetition_penalty": max(1.0, float(getter("chatterbox_multilingual_repeat_penalty", 2.0) or 2.0)),
            "norm_loudness": self._runtime_bool("chatterbox_multilingual_normalize_loudness", False),
        }

    def _patch_alignment_analyzer_token_repetition_eos(self):
        try:
            analyzer_module = importlib.import_module("chatterbox.models.t3.inference.alignment_stream_analyzer")
            analyzer_cls = getattr(analyzer_module, "AlignmentStreamAnalyzer", None)
        except Exception:
            return
        if analyzer_cls is None or bool(getattr(analyzer_cls, "_nc_token_repetition_eos_patch", False)):
            return
        original_step = getattr(analyzer_cls, "step", None)
        if not callable(original_step):
            return

        def step_without_token_repetition_eos(self, logits, next_token=None):
            # The upstream multilingual analyzer treats two identical speech
            # tokens as a fatal repetition and forces EOS. Consecutive speech
            # tokens are normal for held phones, so clear only that heuristic's
            # history while preserving the analyzer's alignment/long-tail checks.
            try:
                self.generated_tokens = []
            except Exception:
                pass
            result = original_step(self, logits, next_token=next_token)
            try:
                self.generated_tokens = []
            except Exception:
                pass
            return result

        analyzer_cls._nc_original_step = original_step
        analyzer_cls.step = step_without_token_repetition_eos
        analyzer_cls._nc_token_repetition_eos_patch = True
        print("✓ Chatterbox Multilingual alignment analyzer patched: token repetition no longer forces EOS.")

    def _set_watermark_enabled(self, model, enabled: bool):
        if model is None:
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
                self._set_watermark_enabled(
                    self._model,
                    self._runtime_bool("chatterbox_multilingual_apply_watermark", True),
                )
                return self._model
            try:
                _disable_transformers_torchvision_probe()
                from chatterbox import mtl_tts as mtl_tts_module
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS
                self._patch_alignment_analyzer_token_repetition_eos()
            except Exception as exc:
                raise RuntimeError(
                    "Chatterbox Multilingual is not available in this Chatterbox install. "
                    "Use Install / Update Runtime to install the official GitHub package that includes "
                    f"chatterbox.mtl_tts, then restart NC. Import error: {exc}"
                ) from exc

            requested_device = str(self._engine_attr("TTS_DEVICE", "cpu") or "cpu")
            apply_watermark = self._runtime_bool("chatterbox_multilingual_apply_watermark", True)
            original_watermarker_cls = None
            if not apply_watermark:
                try:
                    original_watermarker_cls = mtl_tts_module.perth.PerthImplicitWatermarker
                    mtl_tts_module.perth.PerthImplicitWatermarker = _NoOpWatermarker
                except Exception:
                    original_watermarker_cls = None
            try:
                self._model = ChatterboxMultilingualTTS.from_pretrained(
                    device=requested_device
                )
            finally:
                if original_watermarker_cls is not None:
                    try:
                        mtl_tts_module.perth.PerthImplicitWatermarker = original_watermarker_cls
                    except Exception:
                        pass
            try:
                setattr(self._model, "_nc_builtin_conds", copy.deepcopy(getattr(self._model, "conds", None)))
            except Exception:
                setattr(self._model, "_nc_builtin_conds", getattr(self._model, "conds", None))
            self._set_watermark_enabled(self._model, apply_watermark)
            self.sr = int(getattr(self._model, "sr", self.sr) or self.sr or 24000)
            actual_device = str(getattr(self._model, "device", requested_device) or requested_device)
            print(f"✓ Chatterbox Multilingual model ready: language={self._runtime_language()}, device={actual_device}")
            return self._model

    def _use_cloned_voice(self):
        return self._runtime_bool("chatterbox_multilingual_use_cloned_voice", True)

    def _restore_builtin_conditionals(self, model):
        builtin = getattr(model, "_nc_builtin_conds", None)
        if builtin is None:
            return
        try:
            model.conds = copy.deepcopy(builtin)
        except Exception:
            model.conds = builtin

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

    def _generate_accepts(self, model, parameter_name: str) -> bool:
        try:
            signature = inspect.signature(model.generate)
        except Exception:
            return False
        if str(parameter_name or "") in signature.parameters:
            return True
        return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())

    def _filtered_request(self, model, kwargs):
        request = dict(kwargs or {})
        for key in ("backend_id", "backend_label", "tts_backend", "text", "min_p"):
            request.pop(key, None)
        for key, value in self._runtime_generation_settings().items():
            if key == "seed" and int(value or 0) <= 0:
                continue
            if self._generate_accepts(model, key):
                request[key] = value
        if self._generate_accepts(model, "language_id"):
            request["language_id"] = self._runtime_language()
        elif self._generate_accepts(model, "lang"):
            request["lang"] = self._runtime_language()
        elif self._generate_accepts(model, "language"):
            request["language"] = self._runtime_language()

        try:
            signature = inspect.signature(model.generate)
            if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
                return request
            allowed = set(signature.parameters)
            return {key: value for key, value in request.items() if key in allowed}
        except Exception:
            return request

    def warm_up(self):
        if not self._runtime_bool("chatterbox_multilingual_prewarm_on_start", True):
            return False
        with self._lock:
            try:
                model = self._ensure_model()
                if not self._use_cloned_voice():
                    self._restore_builtin_conditionals(model)
                request = self._filtered_request(
                    model,
                    {"audio_prompt_path": self._voice_prompt_path()},
                )
                if not request.get("audio_prompt_path"):
                    request.pop("audio_prompt_path", None)
                language = str(request.get("language_id") or self._runtime_language())
                model.generate("Ready.", **request)
                print(f"✓ Chatterbox Multilingual warmup complete (language={language})")
                return True
            except Exception as exc:
                print(f"⚠️ Chatterbox Multilingual warmup failed: {exc}")
                return False

    def generate(self, text, audio_prompt_path=None, **kwargs):
        model = self._ensure_model()
        request = self._filtered_request(model, kwargs)
        if not self._use_cloned_voice():
            request.pop("audio_prompt_path", None)
            self._restore_builtin_conditionals(model)
        elif audio_prompt_path is not None and self._generate_accepts(model, "audio_prompt_path"):
            request.setdefault("audio_prompt_path", audio_prompt_path)
        elif "audio_prompt_path" not in request and self._generate_accepts(model, "audio_prompt_path"):
            voice_path = self._voice_prompt_path()
            if voice_path:
                request["audio_prompt_path"] = voice_path
        language = str(request.get("language_id") or self._runtime_language())
        reference = "yes" if str(request.get("audio_prompt_path") or "").strip() else "built-in"
        input_text = str(text or "")
        print(
            f"[ChatterboxMultilingual] Generating speech: language={language}, "
            f"reference_voice={reference}, chars={len(input_text.strip())}, text={input_text[:140]!r}"
        )
        return model.generate(input_text, **request)

    def close(self):
        with self._lock:
            model = self._model
            self._model = None
        if model is not None:
            closer = getattr(model, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
