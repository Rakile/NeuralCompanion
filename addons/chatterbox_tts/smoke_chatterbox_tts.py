"""Focused smoke checks for Chatterbox reference-voice preparation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from addons.chatterbox_tts.service import ChatterboxTTSService
from core.tts_runtime import AddonTTSBackendAdapter


class _RuntimeConfig:
    def get(self, key, default=None):
        if key == "tts_use_cloned_voice":
            return True
        if key == "tts_apply_watermark":
            return False
        return default

    def engine_attr(self, _name, default=None):
        return default


class _Context:
    def __init__(self):
        self.runtime_config = _RuntimeConfig()

    def get_service(self, name):
        return self.runtime_config if name == "qt.runtime_config" else None


class _Conditionals:
    def __init__(self, voice: str):
        self.voice = voice
        self.device = "cpu"

    def to(self, device):
        self.device = str(device)
        return self


class _FakeModel:
    def __init__(self):
        self.device = "cpu"
        self.conds = _Conditionals("builtin")
        self.prepare_calls: list[str] = []
        self.generate_calls: list[dict[str, str | None]] = []

    def prepare_conditionals(self, path, exaggeration=0.0, norm_loudness=True):
        self.prepare_calls.append(str(path))
        self.conds = _Conditionals(str(path))

    def generate(self, text, audio_prompt_path=None, **_kwargs):
        if audio_prompt_path:
            self.prepare_conditionals(audio_prompt_path)
        self.generate_calls.append({"text": str(text), "audio_prompt_path": audio_prompt_path})
        return str(text)


def test_reference_voice_conditionals_are_reused_across_chunks_and_switches() -> None:
    with tempfile.TemporaryDirectory(prefix="nc-chatterbox-cache-") as temp_dir:
        first_voice = Path(temp_dir) / "first.wav"
        second_voice = Path(temp_dir) / "second.wav"
        first_voice.write_bytes(b"first")
        second_voice.write_bytes(b"second")

        service = ChatterboxTTSService(_Context())
        model = _FakeModel()
        service._ensure_model = lambda: model

        service.generate("First chunk.", audio_prompt_path=str(first_voice), norm_loudness=False)
        service.generate("Second chunk.", audio_prompt_path=str(first_voice), norm_loudness=False)
        service.generate("Other voice.", audio_prompt_path=str(second_voice), norm_loudness=False)
        service.generate("First voice again.", audio_prompt_path=str(first_voice), norm_loudness=False)

        assert model.prepare_calls == [str(first_voice), str(second_voice)]
        assert model.generate_calls[0]["audio_prompt_path"] == str(first_voice)
        assert model.generate_calls[1]["audio_prompt_path"] is None
        assert model.generate_calls[2]["audio_prompt_path"] == str(second_voice)
        assert model.generate_calls[3]["audio_prompt_path"] is None
        assert model.conds.voice == str(first_voice)


def test_prepare_voice_populates_cache_without_generating_audio() -> None:
    with tempfile.TemporaryDirectory(prefix="nc-chatterbox-prepare-") as temp_dir:
        voice_path = Path(temp_dir) / "prepared.wav"
        voice_path.write_bytes(b"voice")

        service = ChatterboxTTSService(_Context())
        model = _FakeModel()
        service._ensure_model = lambda: model

        assert service.prepare_voice(str(voice_path), norm_loudness=False) is True
        service.generate("Ready to speak.", audio_prompt_path=str(voice_path), norm_loudness=False)

        assert model.prepare_calls == [str(voice_path)]
        assert model.generate_calls == [{"text": "Ready to speak.", "audio_prompt_path": None}]


def test_tts_adapter_forwards_optional_voice_preparation() -> None:
    calls = []

    class _Service:
        sr = 24000

        def prepare_voice(self, path, **kwargs):
            calls.append((path, dict(kwargs)))
            return True

    adapter = AddonTTSBackendAdapter("fake", "Fake", _Service())

    assert adapter.prepare_voice("Q:/voices/mira.wav", norm_loudness=False) is True
    assert calls == [("Q:/voices/mira.wav", {"norm_loudness": False})]


def main() -> None:
    test_reference_voice_conditionals_are_reused_across_chunks_and_switches()
    test_prepare_voice_populates_cache_without_generating_audio()
    test_tts_adapter_forwards_optional_voice_preparation()
    print("smoke_chatterbox_tts: ok")


if __name__ == "__main__":
    main()
