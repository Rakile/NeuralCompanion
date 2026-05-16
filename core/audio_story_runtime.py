"""Runtime hooks used by the Audio Story addon.

The addon calls this module instead of importing engine directly. Engine owns
the live STT/TTS objects and registers the callbacks during startup import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


_runtime_config: dict[str, Any] = {}
_update_runtime_config: Callable[[str, Any], Any] | None = None
_audio_segment_cls: Any = None
_whisper_model_getter: Callable[[], Any] | None = None
_init_whisper: Callable[[], Any] | None = None
_init_tts: Callable[[], bool] | None = None
_get_text_chunk_limits: Callable[[], Any] | None = None
_intelligent_chunk_text: Callable[[str, int, int], Any] | None = None
_tts_model_getter: Callable[[], Any] | None = None
_set_seed: Callable[[int], Any] | None = None
_save_wav: Callable[[str, Any, int], Any] | None = None
_safe_delete: Callable[[str], Any] | None = None
_apply_chat_provider_generation_fields: Callable[..., Any] | None = None
_ensure_chat_provider_model_ready: Callable[[str, str], Any] | None = None


def configure_runtime(
    *,
    runtime_config: dict[str, Any],
    update_runtime_config: Callable[[str, Any], Any],
    audio_segment_cls: Any,
    whisper_model_getter: Callable[[], Any],
    init_whisper: Callable[[], Any],
    init_tts: Callable[[], bool],
    get_text_chunk_limits: Callable[[], Any],
    intelligent_chunk_text: Callable[[str, int, int], Any],
    tts_model_getter: Callable[[], Any],
    set_seed: Callable[[int], Any],
    save_wav: Callable[[str, Any, int], Any],
    safe_delete: Callable[[str], Any],
    apply_chat_provider_generation_fields: Callable[..., Any] | None = None,
    ensure_chat_provider_model_ready: Callable[[str, str], Any] | None = None,
) -> None:
    global _runtime_config
    global _update_runtime_config
    global _audio_segment_cls
    global _whisper_model_getter
    global _init_whisper
    global _init_tts
    global _get_text_chunk_limits
    global _intelligent_chunk_text
    global _tts_model_getter
    global _set_seed
    global _save_wav
    global _safe_delete
    global _apply_chat_provider_generation_fields
    global _ensure_chat_provider_model_ready
    _runtime_config = runtime_config
    _update_runtime_config = update_runtime_config
    _audio_segment_cls = audio_segment_cls
    _whisper_model_getter = whisper_model_getter
    _init_whisper = init_whisper
    _init_tts = init_tts
    _get_text_chunk_limits = get_text_chunk_limits
    _intelligent_chunk_text = intelligent_chunk_text
    _tts_model_getter = tts_model_getter
    _set_seed = set_seed
    _save_wav = save_wav
    _safe_delete = safe_delete
    _apply_chat_provider_generation_fields = apply_chat_provider_generation_fields
    _ensure_chat_provider_model_ready = ensure_chat_provider_model_ready


def engine_loaded() -> bool:
    return callable(_init_tts)


def runtime_config() -> dict:
    return _runtime_config or {}


def runtime_config_value(key: str, default=None):
    return runtime_config().get(str(key), default)


def update_runtime_config(key: str, value):
    if not callable(_update_runtime_config):
        return None
    return _update_runtime_config(str(key), value)


def _audio_segment():
    if _audio_segment_cls is None:
        raise RuntimeError("Audio Story audio runtime is not configured.")
    return _audio_segment_cls


def audio_from_file(path: str):
    return _audio_segment().from_file(str(path))


def audio_from_wav(path: str):
    return _audio_segment().from_wav(str(path))


def audio_silent(duration: int = 0):
    return _audio_segment().silent(duration=int(duration))


def audio_duration_seconds(path: str) -> float:
    return float(audio_from_file(str(path)).duration_seconds or 0.0)


def ensure_whisper_ready() -> bool:
    if not callable(_whisper_model_getter) or not callable(_init_whisper):
        return False
    if _whisper_model_getter() is None:
        _init_whisper()
    return _whisper_model_getter() is not None


def transcribe_audio(path: str):
    if not ensure_whisper_ready():
        raise RuntimeError("Failed to initialize the local Whisper model.")
    return _whisper_model_getter().transcribe(str(path))


def init_tts() -> bool:
    return bool(_init_tts() if callable(_init_tts) else False)


def get_text_chunk_limits():
    if not callable(_get_text_chunk_limits):
        raise RuntimeError("Audio Story text chunk runtime is not configured.")
    return _get_text_chunk_limits()


def intelligent_chunk_text(text: str, target_chars: int, max_chars: int):
    if not callable(_intelligent_chunk_text):
        raise RuntimeError("Audio Story text chunk runtime is not configured.")
    return _intelligent_chunk_text(str(text), int(target_chars), int(max_chars))


def _tts_model():
    return _tts_model_getter() if callable(_tts_model_getter) else None


def tts_sample_rate(default: int = 24000) -> int:
    return int(getattr(_tts_model(), "sr", int(default)) or int(default))


def tts_voice_path() -> str:
    voice_path = str(runtime_config_value("voice_path", "") or "").strip()
    if voice_path and not Path(voice_path).exists():
        return ""
    return voice_path


def tts_seed() -> int:
    return int(runtime_config_value("tts_seed", 0) or 0)


def set_seed(seed: int):
    if not callable(_set_seed):
        return None
    return _set_seed(int(seed))


def tts_generation_kwargs() -> dict:
    return {
        "temperature": float(runtime_config_value("tts_temperature", 0.8) or 0.8),
        "top_p": float(runtime_config_value("tts_top_p", 0.9) or 0.9),
        "top_k": int(runtime_config_value("tts_top_k", 40) or 40),
        "repetition_penalty": float(runtime_config_value("tts_repeat_penalty", 1.2) or 1.2),
        "min_p": float(runtime_config_value("tts_min_p", 0.0) or 0.0),
        "norm_loudness": bool(runtime_config_value("tts_normalize_loudness", False)),
    }


def tts_settings_snapshot() -> dict:
    return {
        "backend": str(runtime_config_value("tts_backend", "chatterbox") or "chatterbox"),
        "voice_path": str(runtime_config_value("voice_path", "") or ""),
        "tts_seed": int(runtime_config_value("tts_seed", 0) or 0),
        "tts_temperature": float(runtime_config_value("tts_temperature", 0.8) or 0.8),
        "tts_top_p": float(runtime_config_value("tts_top_p", 0.9) or 0.9),
        "tts_top_k": int(runtime_config_value("tts_top_k", 40) or 40),
        "tts_repeat_penalty": float(runtime_config_value("tts_repeat_penalty", 1.2) or 1.2),
        "tts_min_p": float(runtime_config_value("tts_min_p", 0.0) or 0.0),
        "tts_normalize_loudness": bool(runtime_config_value("tts_normalize_loudness", False)),
    }


def generate_tts(text: str, **kwargs):
    model = _tts_model()
    if model is None:
        raise RuntimeError("Audio Story TTS model is not initialized.")
    return model.generate(str(text), **kwargs)


def save_tts_wav(path: str, wav, sample_rate: int):
    if not callable(_save_wav):
        raise RuntimeError("Audio Story WAV save runtime is not configured.")
    return _save_wav(str(path), wav, int(sample_rate))


def safe_delete(path: str):
    if callable(_safe_delete):
        return _safe_delete(str(path))
    return None


def apply_chat_provider_generation_fields(params: dict, additional_params: dict, *, provider: str | None = None):
    if callable(_apply_chat_provider_generation_fields):
        return _apply_chat_provider_generation_fields(params, additional_params, provider=provider)
    return None


def ensure_chat_provider_model_ready(provider: str, model: str):
    if callable(_ensure_chat_provider_model_ready):
        return _ensure_chat_provider_model_ready(str(provider or ""), str(model or ""))
    return False
