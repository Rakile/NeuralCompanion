"""Smoke checks for the Ollama chat provider addon."""

from __future__ import annotations

import contextlib
import io
import sys
import types
from pathlib import Path
from urllib.error import URLError


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

from addons.ollama_provider.main import Addon


def test_offline_lifecycle_unload_stays_quiet():
    addon = Addon()
    addon._last_unload_at = 0.0
    addon._last_model_name = ""
    addon._running_model_names = lambda: (_ for _ in ()).throw(URLError("timed out"))  # type: ignore[method-assign]

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        unloaded = addon._unload_running_models(reason="engine_start", force=True)

    assert unloaded == 0
    assert "Could not unload running model" not in output.getvalue()


def test_unexpected_unload_error_still_warns():
    addon = Addon()
    addon._last_unload_at = 0.0
    addon._last_model_name = ""
    addon._running_model_names = lambda: (_ for _ in ()).throw(RuntimeError("unexpected parse failure"))  # type: ignore[method-assign]

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        unloaded = addon._unload_running_models(reason="engine_start", force=True)

    assert unloaded == 0
    assert "Could not unload running model" in output.getvalue()


if __name__ == "__main__":
    test_offline_lifecycle_unload_stays_quiet()
    test_unexpected_unload_error_still_warns()
    print("ollama_provider smoke checks passed.")
