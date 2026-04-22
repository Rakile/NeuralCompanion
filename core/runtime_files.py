"""Small filesystem helpers shared by runtime subsystems."""

from __future__ import annotations

import os
import time


def safe_delete(file_path, *, logger=print):
    """Delete a file if it exists, without crashing on cleanup races."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as exc:
        logger(f"⚠️ [Cleanup] Could not remove {file_path}: {exc}")


def safe_delete_with_retry(file_path, *, retries=5, delay=0.1, logger=print):
    """Delete a file, retrying briefly when another process still has it open."""
    if not file_path or not os.path.exists(file_path):
        return

    for _attempt in range(retries):
        try:
            os.remove(file_path)
            return
        except OSError:
            time.sleep(delay)

    logger(f"⚠️ [Cleanup] Final attempt failed for {os.path.basename(file_path)}")


def list_png_frames(frame_dir):
    """Return sorted PNG frame paths for generated avatar frame directories."""
    if not frame_dir or not os.path.isdir(frame_dir):
        return []
    return sorted(
        os.path.join(frame_dir, name)
        for name in os.listdir(frame_dir)
        if name.lower().endswith(".png")
    )
