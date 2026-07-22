from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))

import torch


def test_save_audio_recreates_missing_parent() -> None:
    import engine

    with tempfile.TemporaryDirectory(prefix="nc-tts-save-") as temp_dir:
        target = Path(temp_dir) / "removed" / "tts" / "sample.wav"

        engine.save_audio_file(target, torch.zeros(1, 240), 24000)

        assert target.is_file()


def test_tts_audio_paths_are_unique_across_overlapping_controllers() -> None:
    import engine

    with tempfile.TemporaryDirectory(prefix="nc-tts-path-") as temp_dir:
        output_dir = Path(temp_dir)

        first = engine._new_tts_audio_path(output_dir, 0)
        second = engine._new_tts_audio_path(output_dir, 0)

        assert first != second
        assert first.parent == output_dir
        assert second.parent == output_dir


def test_startup_cleanup_keeps_fresh_runtime_temp_entries() -> None:
    import engine

    with tempfile.TemporaryDirectory(prefix="nc-tts-cleanup-") as temp_dir:
        root = Path(temp_dir)
        fresh = root / "live-process"
        stale = root / "stale-process"
        fresh.mkdir()
        stale.mkdir()
        (fresh / "active.wav").write_bytes(b"active")
        (stale / "old.wav").write_bytes(b"old")
        now = time.time()
        old = now - 7200
        os.utime(stale / "old.wav", (old, old))
        os.utime(stale, (old, old))

        removed = engine._cleanup_stale_runtime_temp_entries(root, stale_after_seconds=3600, now=now)

        assert fresh.exists()
        assert not stale.exists()
        assert removed == 1


def run_all() -> None:
    test_save_audio_recreates_missing_parent()
    test_tts_audio_paths_are_unique_across_overlapping_controllers()
    test_startup_cleanup_keeps_fresh_runtime_temp_entries()


if __name__ == "__main__":
    run_all()
    print("smoke_tts_temp_safety: ok")
