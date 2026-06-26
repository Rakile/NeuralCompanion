"""Smoke checks for Buffer Race telemetry refresh routing."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REAL_UI_BRIDGE = ROOT / "ui" / "runtime" / "real_ui_bridge.py"


def _module() -> ast.Module:
    return ast.parse(REAL_UI_BRIDGE.read_text(encoding="utf-8"))


def _function_node(name: str) -> ast.FunctionDef:
    for node in ast.walk(_module()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def test_lightweight_sync_includes_audio_only_pipeline_modes() -> None:
    node = _function_node("_should_lightweight_sync_for_pipeline_telemetry")
    constants = {item.value for item in ast.walk(node) if isinstance(item, ast.Constant)}
    assert "runtime.pipeline_snapshot" in constants
    assert "musetalk" in constants
    assert "vam" in constants
    assert "none" in constants
    assert "playing" in constants
    assert "buffered" in constants


def test_musetalk_preview_lightweight_sync_uses_pipeline_telemetry() -> None:
    node = _function_node("_should_lightweight_sync_for_musetalk_preview")
    calls_pipeline_helper = any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "_should_lightweight_sync_for_pipeline_telemetry"
        for item in ast.walk(node)
    )
    assert calls_pipeline_helper


def main() -> None:
    test_lightweight_sync_includes_audio_only_pipeline_modes()
    test_musetalk_preview_lightweight_sync_uses_pipeline_telemetry()
    print("Pipeline telemetry sync smoke checks passed.")


if __name__ == "__main__":
    main()
