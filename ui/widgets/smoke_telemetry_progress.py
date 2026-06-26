"""Static smoke checks for Buffer Race progress behavior."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TELEMETRY = ROOT / "ui" / "widgets" / "telemetry.py"


def _module() -> ast.Module:
    return ast.parse(TELEMETRY.read_text(encoding="utf-8"))


def _function_node(class_name: str, function_name: str) -> ast.FunctionDef:
    for node in ast.walk(_module()):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == function_name:
                    return item
    raise AssertionError(f"Missing function: {class_name}.{function_name}")


def test_preview_progress_has_monotonic_guard() -> None:
    init_node = _function_node("ChunkProgressTelemetryBar", "__init__")
    preview_node = _function_node("ChunkProgressTelemetryBar", "_preview_progress")
    set_snapshot_node = _function_node("ChunkProgressTelemetryBar", "set_snapshot")
    source = "\n".join(
        [
            ast.unparse(init_node),
            ast.unparse(preview_node),
            ast.unparse(set_snapshot_node),
        ]
    )
    assert "_last_preview_progress" in source
    assert "_last_preview_reply_id" in source
    assert "max(raw_progress" in source or "max(self._last_preview_progress" in source


def test_preview_progress_ignores_non_playing_preview_state() -> None:
    raw_node = _function_node("ChunkProgressTelemetryBar", "_raw_preview_progress")
    chunk_node = _function_node("ChunkProgressTelemetryBar", "_chunk_preview_progress")
    elapsed_node = _function_node("ChunkProgressTelemetryBar", "_chunk_audio_elapsed_progress")
    source = "\n".join([ast.unparse(raw_node), ast.unparse(chunk_node)])
    assert "_chunk_by_sequence_index" in source
    assert "_chunk_audio_elapsed_progress" in source
    assert "playback_state" in source
    assert "playing" in source
    assert "engine_mode" in source
    assert "'none'" in source or '"none"' in source
    elapsed_source = ast.unparse(elapsed_node)
    assert "audio_started_at" in elapsed_source
    assert "duration_seconds" in elapsed_source
    assert "time.time" in elapsed_source


def main() -> None:
    test_preview_progress_has_monotonic_guard()
    test_preview_progress_ignores_non_playing_preview_state()
    print("Telemetry progress smoke checks passed.")


if __name__ == "__main__":
    main()
