"""Filesystem ownership for generated MuseTalk frame assets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import shutil
import threading
import time


class MuseTalkAssetStore:
    """Prune rendered chunks and export transition diagnostics."""

    def __init__(
        self,
        runtime_root: Path,
        *,
        seam_debug_root: Path | None = None,
        minimum_age_seconds: float = 5.0,
        clock=time.time,
    ) -> None:
        self._runtime_root = Path(runtime_root).expanduser().resolve()
        self._seam_debug_root = (
            Path(seam_debug_root).expanduser().resolve()
            if seam_debug_root is not None
            else self._runtime_root.parent / "seam_debug"
        )
        self._minimum_age_seconds = max(0.0, float(minimum_age_seconds))
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def runtime_root(self) -> Path:
        return self._runtime_root

    def cleanup(
        self,
        keep_frame_dirs: Iterable[str | Path] = (),
        *,
        max_keep: int = 64,
        force: bool = False,
    ) -> tuple[Path, ...]:
        """Delete only old, unprotected child directories of the runtime root."""

        root = self._runtime_root
        if not root.is_dir():
            return ()
        protected = {
            Path(item).expanduser().resolve()
            for item in keep_frame_dirs
            if str(item or "").strip()
        }
        keep_count = max(0, int(max_keep))
        removed: list[Path] = []
        with self._lock:
            existing: list[tuple[Path, float]] = []
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                resolved = child.resolve()
                if resolved.parent != root:
                    continue
                try:
                    existing.append((resolved, child.stat().st_mtime))
                except FileNotFoundError:
                    continue
            existing.sort(key=lambda item: item[1], reverse=True)
            protected.update(path for path, _mtime in existing[:keep_count])
            now = float(self._clock())
            for path, modified_at in existing:
                if path in protected:
                    continue
                if not force and now - modified_at < self._minimum_age_seconds:
                    continue
                try:
                    shutil.rmtree(path)
                except FileNotFoundError:
                    continue
                removed.append(path)
        return tuple(removed)

    def save_transition_frames(
        self,
        previous_state: Mapping[str, object],
        current_state: Mapping[str, object],
    ) -> tuple[Path, Path] | None:
        """Copy the exact outgoing/incoming source frames for seam diagnosis."""

        previous = dict(previous_state or {})
        current = dict(current_state or {})
        previous_chunk = str(previous.get("chunk_id") or "").strip()
        current_chunk = str(current.get("chunk_id") or "").strip()
        if not previous_chunk or not current_chunk:
            return None
        previous_sequence = _integer(previous.get("sequence_index"))
        current_sequence = _integer(current.get("sequence_index"))
        previous_index = _integer(previous.get("preview_frame_index"), default=-1)
        if previous_sequence is None or current_sequence is None or previous_index < 0:
            return None
        previous_dir_text = str(previous.get("frame_dir") or "").strip()
        current_dir_text = str(current.get("frame_dir") or "").strip()
        if not previous_dir_text or not current_dir_text:
            return None
        previous_dir = Path(previous_dir_text).expanduser()
        current_dir = Path(current_dir_text).expanduser()
        previous_raw = previous_index + _integer(
            previous.get("trim_start_frames"), default=0
        )
        current_raw = _integer(current.get("trim_start_frames"), default=0)
        outgoing = previous_dir / f"{previous_raw:08d}.png"
        incoming = current_dir / f"{current_raw:08d}.png"
        if not outgoing.is_file() or not incoming.is_file():
            return None
        with self._lock:
            self._seam_debug_root.mkdir(parents=True, exist_ok=True)
            outgoing_copy = self._seam_debug_root / (
                f"chunk_{previous_sequence}_out.png"
            )
            incoming_copy = self._seam_debug_root / (
                f"chunk_{current_sequence}_in.png"
            )
            shutil.copy2(outgoing, outgoing_copy)
            shutil.copy2(incoming, incoming_copy)
        return outgoing_copy, incoming_copy


def _integer(value: object, *, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = ["MuseTalkAssetStore"]
