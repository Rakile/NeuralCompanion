from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import lmstudio_runtime


def test_lmstudio_base_url_locality_detection() -> None:
    assert lmstudio_runtime.is_local_base_url("http://127.0.0.1:1234/v1") is True
    assert lmstudio_runtime.is_local_base_url("http://localhost:1234/v1") is True
    assert lmstudio_runtime.is_local_base_url("http://192.168.2.46:1234/v1") is False


def test_remote_lifecycle_never_uses_local_cli() -> None:
    original_get_sdk = lmstudio_runtime.get_sdk
    original_run_lms_cli = lmstudio_runtime.run_lms_cli
    calls = []

    try:
        lmstudio_runtime.get_sdk = lambda: None

        def _run_lms_cli(args, timeout=300):
            calls.append((list(args), timeout))
            return True, "local cli should not be used"

        lmstudio_runtime.run_lms_cli = _run_lms_cli

        logs = []
        unload_ok = lmstudio_runtime.unload_models(
            base_url="http://192.168.2.46:1234/v1",
            logger=logs.append,
        )
        load_ok = lmstudio_runtime.load_model(
            "remote-model",
            base_url="http://192.168.2.46:1234/v1",
            logger=logs.append,
        )

        assert unload_ok is False
        assert load_ok is False
        assert calls == []
        assert any("local lms CLI fallback disabled" in line for line in logs)
    finally:
        lmstudio_runtime.get_sdk = original_get_sdk
        lmstudio_runtime.run_lms_cli = original_run_lms_cli


def test_local_lifecycle_keeps_cli_fallback() -> None:
    original_get_sdk = lmstudio_runtime.get_sdk
    original_run_lms_cli = lmstudio_runtime.run_lms_cli
    calls = []

    try:
        lmstudio_runtime.get_sdk = lambda: None

        def _run_lms_cli(args, timeout=300):
            calls.append((list(args), timeout))
            return True, "ok"

        lmstudio_runtime.run_lms_cli = _run_lms_cli

        assert lmstudio_runtime.unload_models(base_url="http://127.0.0.1:1234/v1", logger=lambda _line: None) is True
        assert calls == [(["unload", "--all"], 180)]
    finally:
        lmstudio_runtime.get_sdk = original_get_sdk
        lmstudio_runtime.run_lms_cli = original_run_lms_cli


def main() -> int:
    test_lmstudio_base_url_locality_detection()
    test_remote_lifecycle_never_uses_local_cli()
    test_local_lifecycle_keeps_cli_fallback()
    print("smoke_lmstudio_runtime: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
