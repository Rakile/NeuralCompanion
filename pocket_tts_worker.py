#!/usr/bin/env python3
import json
import os
import sys
import argparse
import inspect

import numpy as np
from pocket_tts import TTSModel
from scipy.io import wavfile

LANGUAGE_ALIASES = {
    "en": "english",
    "english": "english",
    "english_2026-01": "english_2026-01",
    "english_2026-04": "english_2026-04",
    "fr": "french",
    "french": "french",
    "french_24l": "french_24l",
    "de": "german",
    "german": "german",
    "german_24l": "german_24l",
    "es": "spanish",
    "spanish": "spanish",
    "spanish_24l": "spanish_24l",
    "pt": "portuguese",
    "portuguese": "portuguese",
    "portuguese_24l": "portuguese_24l",
    "it": "italian",
    "italian": "italian",
    "italian_24l": "italian_24l",
}

POCKET_TTS_MODEL_LANGUAGE = {
    "english": "english",
    "english_2026-01": "english_2026-01",
    "english_2026-04": "english_2026-04",
    "french": "french_24l",
    "french_24l": "french_24l",
    "german": "german_24l",
    "german_24l": "german_24l",
    "spanish": "spanish_24l",
    "spanish_24l": "spanish_24l",
    "portuguese": "portuguese_24l",
    "portuguese_24l": "portuguese_24l",
    "italian": "italian_24l",
    "italian_24l": "italian_24l",
}


def _normalize_language(value):
    text = str(value or "").strip().lower()
    return LANGUAGE_ALIASES.get(text, text or "english")


def _model_language(value):
    return POCKET_TTS_MODEL_LANGUAGE.get(_normalize_language(value), _normalize_language(value))


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--language", default="english")
    parser.add_argument("--lsd-decode-steps", type=int, default=1)
    parser.add_argument("--eos-threshold", type=float, default=-4.0)
    args, _unknown = parser.parse_known_args()

    language = _normalize_language(args.language)
    model_language = _model_language(language)
    load_kwargs = {
        "temp": float(args.temperature or 0.7),
        "lsd_decode_steps": max(1, int(args.lsd_decode_steps or 1)),
        "eos_threshold": float(args.eos_threshold if args.eos_threshold is not None else -4.0),
    }
    language_applied = False
    try:
        signature = inspect.signature(TTSModel.load_model)
        parameters = signature.parameters
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
        if accepts_kwargs or "language" in parameters:
            load_kwargs["language"] = model_language
            language_applied = True
        elif accepts_kwargs or "lang" in parameters:
            load_kwargs["lang"] = model_language
            language_applied = True
    except Exception:
        pass
    if model_language != "english" and not language_applied:
        sys.stdout.write(
            json.dumps(
                {
                    "status": "error",
                    "error": (
                        "This PocketTTS runtime does not support multilingual model loading. "
                        "Reinstall the isolated PocketTTS runtime from kyutai-labs/pocket-tts main or choose English."
                    ),
                    "language": language,
                    "model_language": model_language,
                    "language_applied": False,
                }
            ) + "\n"
        )
        sys.stdout.flush()
        return
    try:
        model = TTSModel.load_model(**load_kwargs)
    except Exception as exc:
        sys.stdout.write(
            json.dumps(
                {
                    "status": "error",
                    "error": f"PocketTTS model load failed: {exc}",
                    "language": language,
                    "model_language": model_language,
                    "language_applied": language_applied,
                }
            ) + "\n"
        )
        sys.stdout.flush()
        return
    sample_rate = int(getattr(model, "sample_rate", 24000) or 24000)
    voice_states = {}
    sys.stdout.write(
        json.dumps(
            {
                "status": "ready",
                "sample_rate": sample_rate,
                "pid": os.getpid(),
                "language": language,
                "model_language": model_language,
                "language_applied": language_applied,
            }
        ) + "\n"
    )
    sys.stdout.flush()

    for line in sys.stdin:
        line = (line or "").strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            sys.stdout.write(json.dumps({"status": "error", "error": f"Bad JSON: {exc}"}) + "\n")
            sys.stdout.flush()
            continue

        cmd = payload.get("cmd")
        if cmd == "close":
            break
        if cmd != "synthesize":
            sys.stdout.write(json.dumps({"status": "error", "error": f"Unknown command: {cmd}"}) + "\n")
            sys.stdout.flush()
            continue

        try:
            text = str(payload.get("text", "") or "").strip()
            if not text:
                raise ValueError("Empty text")
            output_path = str(payload.get("output_path", "") or "").strip()
            if not output_path:
                raise ValueError("Missing output_path")
            voice_prompt = str(payload.get("voice_prompt", "") or "alba").strip() or "alba"
            voice_state = voice_states.get(voice_prompt)
            if voice_state is None:
                voice_state = model.get_state_for_audio_prompt(voice_prompt)
                voice_states[voice_prompt] = voice_state
            max_tokens = max(1, int(payload.get("max_tokens", 50) or 50))
            frames_after_eos = max(0, int(payload.get("frames_after_eos", 0) or 0))
            request_language = _normalize_language(payload.get("language", language))
            generation_kwargs = {
                "max_tokens": max_tokens,
                "frames_after_eos": frames_after_eos or None,
            }
            try:
                signature = inspect.signature(model.generate_audio)
                parameters = signature.parameters
                accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
                if request_language and "language" in parameters:
                    generation_kwargs["language"] = request_language
                elif request_language and "lang" in parameters:
                    generation_kwargs["lang"] = request_language
                elif request_language and "language_id" in parameters:
                    generation_kwargs["language_id"] = request_language
            except Exception:
                pass
            audio = model.generate_audio(
                voice_state,
                text,
                **generation_kwargs,
            )
            audio = np.asarray(audio, dtype=np.float32)
            if audio.ndim > 1:
                audio = audio.reshape(-1)
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if peak > 1.0:
                audio = audio / peak
            pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            wavfile.write(output_path, sample_rate, pcm)
            sys.stdout.write(json.dumps({"status": "ok", "output_path": output_path, "sample_rate": sample_rate}) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps({"status": "error", "error": str(exc)}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
