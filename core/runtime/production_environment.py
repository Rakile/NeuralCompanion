"""Owned production startup workspace and sentence-tokenizer preparation."""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from core import text_chunking


class ProductionRuntimeWorkspace:
    """Prepare only transient runtime files required by a fresh engine run."""

    def __init__(
        self,
        app_root: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        logger: Callable[[str], object] = print,
        stale_after_seconds: float = 21600.0,
    ) -> None:
        self._app_root = Path(app_root).resolve()
        self._clock = clock
        self._logger = logger
        self._stale_after_seconds = max(60.0, float(stale_after_seconds))

    def prepare(self) -> int:
        runtime_dir = self._app_root / "runtime"
        if runtime_dir.is_dir():
            self._remove_partial_files(runtime_dir)
            self._clear_directory(runtime_dir / "sensory_feedback")
        removed = self._remove_stale_entries(runtime_dir / "temp")
        suffix = "entry" if removed == 1 else "entries"
        self._logger(f"[Startup] Removed {removed} stale runtime temp {suffix}.")
        return removed

    @staticmethod
    def _remove_partial_files(runtime_dir: Path) -> None:
        for target in runtime_dir.iterdir():
            if not target.is_file() or target.suffix.lower() not in {".tmp", ".part"}:
                continue
            try:
                target.unlink()
            except OSError:
                continue

    @staticmethod
    def _clear_directory(directory: Path) -> None:
        if not directory.is_dir():
            return
        for target in directory.iterdir():
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except OSError:
                continue

    def _remove_stale_entries(self, directory: Path) -> int:
        directory.mkdir(parents=True, exist_ok=True)
        cutoff = float(self._clock()) - self._stale_after_seconds
        removed = 0
        for target in tuple(directory.iterdir()):
            try:
                latest_mtime = float(target.stat().st_mtime)
                if target.is_dir():
                    for child in target.rglob("*"):
                        try:
                            latest_mtime = max(latest_mtime, float(child.stat().st_mtime))
                        except OSError:
                            continue
                if latest_mtime >= cutoff:
                    continue
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                removed += 1
            except OSError:
                continue
        return removed


class ProductionSentenceTokenizer:
    """Prepare NLTK once at startup and expose an IO-free frozen splitter."""

    _RESOURCES = (
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab", "punkt_tab"),
    )

    def __init__(
        self,
        nltk_module: object,
        *,
        logger: Callable[[str], object] = print,
    ) -> None:
        self._nltk = nltk_module
        self._logger = logger
        self._lock = threading.Lock()
        self._prepared = False
        self._splitter = text_chunking.IO_FREE_SENTENCE_SPLITTER

    def prepare(self) -> text_chunking.PreparedSentenceSplitter:
        with self._lock:
            if self._prepared:
                return self._splitter
            self._prepare_resources()
            try:
                data = self._nltk.data
                splitter = text_chunking.prepare_sentence_splitter(
                    lambda: data.load("tokenizers/punkt/english.pickle")
                )
            except Exception as exc:  # noqa: BLE001 - optional NLTK fallback boundary
                self._logger(
                    "NLTK sentence tokenizer unavailable, using fallback splitter: "
                    f"{exc}"
                )
                splitter = text_chunking.IO_FREE_SENTENCE_SPLITTER
            self._splitter = splitter
            self._prepared = True
            return splitter

    def splitter(self) -> text_chunking.PreparedSentenceSplitter:
        with self._lock:
            return self._splitter

    def _prepare_resources(self) -> None:
        data = self._nltk.data
        download = self._nltk.download
        for resource_path, resource_name in self._RESOURCES:
            find_failure: Exception | None = None
            try:
                data.find(resource_path)
                self._logger(f"NLTK {resource_name} tokenizer found")
                continue
            except Exception as exc:  # noqa: BLE001 - optional NLTK resource boundary
                find_failure = exc
            try:
                try:
                    download(resource_name, quiet=True, force=True)
                except TypeError:
                    download(resource_name, quiet=True)
                data.find(resource_path)
                self._logger(f"NLTK {resource_name} tokenizer downloaded")
            except Exception as exc:  # noqa: BLE001 - optional NLTK fallback boundary
                self._logger(
                    f"Failed to prepare NLTK {resource_name}, using fallback splitter: "
                    f"{find_failure}; {exc}"
                )


__all__ = ["ProductionRuntimeWorkspace", "ProductionSentenceTokenizer"]
