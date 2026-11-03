"""Filesystem preparation shared by the renderer and transition-frame merge."""
import os
from pathlib import Path
import shutil


def prepare_render_directory(frame_dir):
    """Clear a segment's contents without removing its observable directory.

    Call only before rendering/merging this segment. The final sidecar is
    invalidated first; readers must still wait for a newly published final one.
    Cleanup failures propagate rather than mixing stale and new frames.
    """
    target = Path(os.path.abspath(frame_dir))
    if target == target.parent:
        raise ValueError('render directory cannot be a filesystem root')
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or getattr(target.lstat(), 'st_file_attributes', 0) & 0x400:
        raise ValueError('render directory cannot be a link or reparse point')
    for name in ('phone-delivery.json', 'phone-delivery-failure.json'):
        (target/name).unlink(missing_ok=True)
    for child in target.iterdir():
        if child.is_symlink():
            child.unlink()
        elif getattr(child.lstat(), 'st_file_attributes', 0) & 0x400:
            # Never traverse Windows junctions while clearing a render.
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
