"""Storage and display actions for the native Visual Reply workspace."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_EMPTY_DETAIL = "No visual reply yet.\nWhen NC creates an image, it will appear here."


class VisualReplyLibrary:
    """Own Visual Reply history actions without constructing UI widgets."""

    def __init__(
        self,
        storage_dir: str | Path,
        state_getter: Callable[[], dict[str, Any]],
        state_setter: Callable[[dict[str, Any]], None],
        state_updater: Callable[..., None],
    ) -> None:
        self._storage_dir = Path(storage_dir)
        self._state_getter = state_getter
        self._state_setter = state_setter
        self._state_updater = state_updater

    def ensure_storage(self) -> Path:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        return self._storage_dir.resolve()

    def _image_paths(self) -> list[Path]:
        if not self._storage_dir.is_dir():
            return []
        try:
            entries = [
                item.resolve()
                for item in self._storage_dir.iterdir()
                if not item.is_symlink() and item.is_file() and item.suffix.lower() in _IMAGE_SUFFIXES
            ]
            entries.sort(key=lambda item: (item.stat().st_mtime, item.name.lower()))
            return entries
        except OSError:
            return []

    def _current_index(self, entries: list[Path]) -> int:
        current_path = str(self._state_getter().get("image_path") or "").strip()
        if current_path:
            try:
                current = Path(current_path).resolve()
                return entries.index(current)
            except (OSError, ValueError):
                pass
        return len(entries) - 1 if entries else -1

    @staticmethod
    def _caption_from_image(path: Path) -> str:
        try:
            with Image.open(path) as image:
                metadata = dict(getattr(image, "info", {}) or {})
                text = getattr(image, "text", None)
                if isinstance(text, dict):
                    metadata.update(text)
                for key in (
                    "Comment",
                    "comment",
                    "Description",
                    "description",
                    "Prompt",
                    "prompt",
                ):
                    value = metadata.get(key)
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="replace")
                    caption = str(value or "").strip()
                    if caption:
                        return caption
        except (OSError, ValueError):
            pass
        return ""

    @staticmethod
    def _format_bytes(value: int) -> str:
        amount = float(max(0, value))
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        unit_index = 0
        while amount >= 1024.0 and unit_index < len(units) - 1:
            amount /= 1024.0
            unit_index += 1
        return (
            f"{int(amount)} {units[unit_index]}"
            if unit_index == 0
            else f"{amount:.1f} {units[unit_index]}"
        )

    def snapshot(self) -> dict[str, Any]:
        result = dict(self._state_getter() or {})
        entries = self._image_paths()
        total_bytes = 0
        for item in entries:
            try:
                total_bytes += item.stat().st_size
            except OSError:
                pass
        index = self._current_index(entries)
        if entries:
            summary = f"Storage: {len(entries)} image(s), {self._format_bytes(total_bytes)} total"
            if index >= 0:
                summary += f" | Current: {index + 1}/{len(entries)}"
        else:
            summary = "Storage: empty"
        result.update(
            {
                "storage_count": len(entries),
                "storage_index": index + 1 if index >= 0 else 0,
                "storage_bytes": total_bytes,
                "storage_summary": summary,
                "has_current_image": bool(
                    str(result.get("image_path") or "").strip()
                    and Path(str(result.get("image_path"))).is_file()
                ),
            }
        )
        return result

    def load_image(self, image_path: str | Path, *, status_text: str = "Visual Reply") -> bool:
        path = Path(image_path).expanduser()
        try:
            path = path.resolve(strict=True)
            if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
                return False
            with Image.open(path) as image:
                image.verify()
        except (OSError, ValueError):
            return False
        self._state_setter(
            {
                "status": "ready",
                "status_text": str(status_text or "Visual Reply"),
                "detail_text": "",
                "image_path": str(path),
                "caption": self._caption_from_image(path),
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        return True

    def navigate(self, offset: int) -> bool:
        entries = self._image_paths()
        if not entries:
            return False
        current_index = self._current_index(entries)
        if current_index < 0:
            current_index = len(entries) - 1 if int(offset) < 0 else 0
        target_index = max(0, min(len(entries) - 1, current_index + int(offset)))
        return self.load_image(entries[target_index], status_text="Visual Reply history")

    def set_caption(self, caption: str) -> bool:
        current = self.snapshot()
        if not current.get("has_current_image"):
            return False
        self._state_updater(caption=str(caption or "").strip())
        return True

    def clear(
        self,
        *,
        status_text: str = "Visual Reply idle",
        detail_text: str = _EMPTY_DETAIL,
    ) -> bool:
        self._state_setter(
            {
                "status": "idle",
                "status_text": str(status_text or "Visual Reply idle"),
                "detail_text": str(detail_text or _EMPTY_DETAIL),
                "image_path": "",
                "caption": "",
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        return True

    def delete_current(self, *, expected_path: str | None = None) -> bool:
        current_path = str(self._state_getter().get("image_path") or "").strip()
        if not current_path:
            return False
        if expected_path is not None and current_path != expected_path:
            return False
        path = Path(current_path)
        entries = self._image_paths()
        try:
            resolved = path.resolve(strict=True)
            current_index = entries.index(resolved) if resolved in entries else -1
            resolved.unlink()
        except (OSError, ValueError):
            return False
        if current_index >= 0:
            remaining = self._image_paths()
            if remaining:
                if self.load_image(
                    remaining[min(current_index, len(remaining) - 1)],
                    status_text="Visual Reply history",
                ):
                    return True
        return self.clear(status_text="Visual Reply image deleted")

    def delete_all(self) -> int:
        removed = 0
        for item in self._image_paths():
            try:
                item.unlink()
                removed += 1
            except OSError:
                pass
        if removed:
            self.clear(status_text="Visual Reply storage cleared")
        return removed
