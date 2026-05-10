from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _engine():
    return importlib.import_module("engine")


def engine_loaded() -> bool:
    return "engine" in sys.modules


def runtime_config() -> dict:
    return getattr(_engine(), "RUNTIME_CONFIG", {}) or {}


def runtime_config_value(key: str, default=None):
    return runtime_config().get(str(key), default)


def update_runtime_config(key: str, value):
    return _engine().update_runtime_config(str(key), value)


def audio_from_file(path: str):
    return _engine().AudioSegment.from_file(str(path))


def audio_from_wav(path: str):
    return _engine().AudioSegment.from_wav(str(path))


def audio_silent(duration: int = 0):
    return _engine().AudioSegment.silent(duration=int(duration))


def audio_duration_seconds(path: str) -> float:
    return float(audio_from_file(str(path)).duration_seconds or 0.0)


def ensure_whisper_ready() -> bool:
    engine = _engine()
    if getattr(engine, "whisper_model", None) is None:
        engine.init_whisper()
    return getattr(engine, "whisper_model", None) is not None


def transcribe_audio(path: str):
    engine = _engine()
    if not ensure_whisper_ready():
        raise RuntimeError("Failed to initialize the local Whisper model.")
    return engine.whisper_model.transcribe(str(path))


def init_tts() -> bool:
    return bool(_engine().init_tts())


def get_text_chunk_limits():
    return _engine().get_text_chunk_limits()


def intelligent_chunk_text(text: str, target_chars: int, max_chars: int):
    return _engine().intelligent_chunk_text(str(text), int(target_chars), int(max_chars))


def tts_sample_rate(default: int = 24000) -> int:
    return int(getattr(_engine().tts_model, "sr", int(default)) or int(default))


def tts_voice_path() -> str:
    voice_path = str(runtime_config_value("voice_path", "") or "").strip()
    if voice_path and not Path(voice_path).exists():
        return ""
    return voice_path


def tts_seed() -> int:
    return int(runtime_config_value("tts_seed", 0) or 0)


def set_seed(seed: int):
    return _engine().set_seed(int(seed))


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
    return _engine().tts_model.generate(str(text), **kwargs)


def save_tts_wav(path: str, wav, sample_rate: int):
    return _engine().ta.save(str(path), wav.cpu(), int(sample_rate))


def safe_delete(path: str):
    return _engine().safe_delete_with_retry(str(path))
