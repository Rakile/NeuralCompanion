"""Smoke checks that hosted provider stream setup is lazy."""

from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

from addons.deepseek_provider.main import Addon as DeepSeekAddon
from addons.ollama_provider.main import Addon as OllamaAddon
from addons.openai_provider.main import Addon as OpenAIAddon
from addons.xai_provider.main import Addon as XaiAddon


class _FakeDelta:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.delta = _FakeDelta(content)


class _FakeEvent:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls += 1
        self.requests.append(dict(kwargs))
        return [_FakeEvent("hello")]


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


def _assert_stream_is_lazy(addon, *, additional_params: dict[str, object] | None = None) -> None:
    completions = _FakeCompletions()
    addon._client = lambda: _FakeClient(completions)  # type: ignore[method-assign]
    if isinstance(addon, OllamaAddon):
        addon._last_model_name = ""

    stream = addon._stream_chat({"model": "test-model", "messages": []}, additional_params)

    assert completions.calls == 0
    assert "".join(stream) == "hello"
    assert completions.calls == 1
    assert completions.requests[0].get("stream") is True


def test_xai_stream_setup_is_lazy() -> None:
    _assert_stream_is_lazy(XaiAddon())


def test_openai_stream_setup_is_lazy() -> None:
    _assert_stream_is_lazy(OpenAIAddon())


def test_deepseek_stream_setup_is_lazy() -> None:
    _assert_stream_is_lazy(DeepSeekAddon())


def test_ollama_stream_setup_is_lazy() -> None:
    _assert_stream_is_lazy(OllamaAddon(), additional_params={"top_k": 40})


if __name__ == "__main__":
    test_xai_stream_setup_is_lazy()
    test_openai_stream_setup_is_lazy()
    test_deepseek_stream_setup_is_lazy()
    test_ollama_stream_setup_is_lazy()
    print("provider lazy stream smoke checks passed.")
