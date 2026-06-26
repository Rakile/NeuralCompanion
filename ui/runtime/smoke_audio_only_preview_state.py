"""Static smoke checks for audio-only Buffer Race preview-state ownership."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine.py"


def _module() -> ast.Module:
    return ast.parse(ENGINE.read_text(encoding="utf-8"))


def _function_node(name: str) -> ast.FunctionDef:
    for node in ast.walk(_module()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def test_audio_only_prebuffer_does_not_publish_current_preview_state() -> None:
    node = _function_node("speak_async")
    source = ast.unparse(node)
    assert "kind != 'none'" in source or 'kind != "none"' in source
    assert "set_current_musetalk_frame_data(current_state)" in source
    assert "stream_delegated_audio_progress" in source


def main() -> None:
    test_audio_only_prebuffer_does_not_publish_current_preview_state()
    print("Audio-only preview-state smoke checks passed.")


if __name__ == "__main__":
    main()
