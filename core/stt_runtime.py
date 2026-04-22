"""Speech-to-text runtime helpers for Whisper-backed hearing."""

from __future__ import annotations

import math
import re
import tempfile
import time


def whisper_runtime_config(runtime_config, *, cuda_available: bool):
    vram_mode = str(runtime_config.get("musetalk_vram_mode", "quality") or "quality").strip().lower()
    if not cuda_available:
        return "cpu", "int8"
    # Keep the current runtime behavior: main Whisper prefers CUDA whenever available.
    return "cuda", "float16"


def whisper_runtime_reason(runtime_config, *, cuda_available: bool):
    vram_mode = str(runtime_config.get("musetalk_vram_mode", "quality") or "quality").strip().lower()
    if not cuda_available:
        return "CUDA unavailable"
    if vram_mode in {"low", "very_low"}:
        return f"{vram_mode} VRAM mode prefers CPU"
    return f"{vram_mode} VRAM mode prefers CUDA"


def initialize_whisper_model(
    current_model,
    *,
    model_size: str,
    runtime_config,
    cuda_available: bool,
    model_factory,
    logger=print,
):
    if current_model is not None:
        logger("✓ Whisper model already loaded (Skipping reload)")
        device, compute_type = whisper_runtime_config(runtime_config, cuda_available=cuda_available)
        return current_model, device, compute_type

    device, compute_type = whisper_runtime_config(runtime_config, cuda_available=cuda_available)
    reason = whisper_runtime_reason(runtime_config, cuda_available=cuda_available)
    logger(f"Loading Whisper ({model_size}) on {device} [compute_type={compute_type}, reason={reason}]...")
    model = model_factory(model_size, device=device, compute_type=compute_type)
    logger(f"✓ Whisper model loaded on {device} ({compute_type})")
    return model, device, compute_type


def transcribe_audio_with_whisper(audio, *, model_getter, init_model, safe_delete_with_retry, language="en"):
    if model_getter() is None:
        init_model()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio.get_wav_data())
            temp_path = tmp.name
        segments, _info = model_getter().transcribe(temp_path, language=language)
        text = " ".join((segment.text or "").strip() for segment in segments).strip()
        return text or None
    finally:
        if temp_path:
            safe_delete_with_retry(temp_path)


def listen_for_speech(
    source,
    *,
    recognizer,
    microphone_active,
    transcribe_func,
    sr_module,
    settings,
    np_module=None,
    timeout=None,
    logger=print,
):
    recognizer.energy_threshold = settings["energy_threshold"]
    recognizer.dynamic_energy_threshold = settings["dynamic_energy_threshold"]
    recognizer.pause_threshold = settings["pause_threshold"]
    recognizer.non_speaking_duration = settings["non_speaking_duration"]
    recognizer.phrase_threshold = settings["phrase_threshold"]
    try:
        microphone_active.set()
        audio = recognizer.listen(source, timeout=timeout)
        if np_module is not None:
            _audio_data = np_module.frombuffer(audio.get_raw_data(), dtype=np_module.int16).astype(np_module.float32) / 32768.0
        text = transcribe_func(audio, language="en")
        if text and re.search(r"[a-zA-Z0-9]", text):
            return text
        return None
    except sr_module.WaitTimeoutError:
        return None
    except sr_module.UnknownValueError:
        return None
    except Exception as exc:
        logger(f"✗ Mic error: {exc}")
        return None
    finally:
        microphone_active.clear()


def listen_for_speech_push_to_talk(
    source,
    *,
    recognizer,
    microphone_active,
    transcribe_func,
    sr_module,
    is_push_to_talk_held,
    audio_data_factory,
    chunk_size=1024,
    max_seconds=300.0,
    tail_seconds=0.55,
    min_tail_chunks=8,
    trailing_chunks=None,
    logger=print,
):
    sample_rate = getattr(source, "SAMPLE_RATE", 16000)
    sample_width = getattr(source, "SAMPLE_WIDTH", 2)
    if trailing_chunks is None:
        chunk_seconds = float(chunk_size) / max(float(sample_rate), 1.0)
        trailing_chunks = max(min_tail_chunks, int(math.ceil(tail_seconds / max(chunk_seconds, 0.001))))
    frames = []
    deadline = (time.time() + float(max_seconds)) if max_seconds else None
    trailing = 0
    try:
        microphone_active.set()
        while deadline is None or time.time() < deadline:
            if source.stream is None:
                break
            try:
                data = source.stream.read(chunk_size)
            except Exception:
                break
            if data:
                frames.append(data)

            if is_push_to_talk_held():
                trailing = trailing_chunks
                continue

            if trailing > 0:
                trailing -= 1
                continue
            break

        if deadline is not None and time.time() >= deadline and is_push_to_talk_held():
            logger("⚠️ Push-to-talk reached the recording safety limit and stopped automatically.")

        if not frames:
            return None

        audio = audio_data_factory(b"".join(frames), sample_rate, sample_width)
        text = transcribe_func(audio, language="en")
        if text and re.search(r"[a-zA-Z0-9]", text):
            return text
        return None
    except sr_module.UnknownValueError:
        return None
    except Exception as exc:
        logger(f"✗ Push-to-talk mic error: {exc}")
        return None
    finally:
        microphone_active.clear()
