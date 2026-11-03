"""Bounded background execution for native QML actions."""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6 import QtCore


class _CommandSignals(QtCore.QObject):
    completed = QtCore.Signal(str, int, bool, object, str)


class _CommandTask(QtCore.QRunnable):
    def __init__(
        self,
        key: str,
        generation: int,
        callback: Callable[[], Any],
    ) -> None:
        super().__init__()
        self.key = key
        self.generation = generation
        self.callback = callback
        self.signals = _CommandSignals()

    def run(self) -> None:
        try:
            result = self.callback()
        except BaseException as error:
            self.signals.completed.emit(
                self.key,
                self.generation,
                False,
                None,
                str(error),
            )
            return
        self.signals.completed.emit(
            self.key,
            self.generation,
            True,
            result,
            "",
        )


class NativeCommandRunner(QtCore.QObject):
    """Run named actions off the UI thread with duplicate suppression."""

    pendingChanged = QtCore.Signal()
    completed = QtCore.Signal(str, bool, object, str)

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        *,
        max_workers: int = 2,
    ) -> None:
        super().__init__(parent)
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(max(1, int(max_workers)))
        self._pool.setExpiryTimeout(15_000)
        self._lock = threading.RLock()
        self._generation = 0
        self._pending: dict[str, int] = {}
        self._closed = False

    @QtCore.Property("QStringList", notify=pendingChanged)
    def pendingKeys(self) -> list[str]:
        with self._lock:
            return sorted(self._pending)

    def submit(self, key: str, callback: Callable[[], Any]) -> bool:
        command_key = str(key or "").strip()
        if not command_key:
            raise ValueError("Native command key is required.")
        if not callable(callback):
            raise TypeError("Native command callback must be callable.")
        with self._lock:
            if self._closed or command_key in self._pending:
                return False
            self._generation += 1
            generation = self._generation
            self._pending[command_key] = generation
        task = _CommandTask(command_key, generation, callback)
        task.signals.completed.connect(
            self._finish,
            QtCore.Qt.QueuedConnection,
        )
        self._pool.start(task)
        self.pendingChanged.emit()
        return True

    def cancel(self, key: str) -> bool:
        command_key = str(key or "").strip()
        with self._lock:
            removed = self._pending.pop(command_key, None)
        if removed is not None:
            self.pendingChanged.emit()
            return True
        return False

    @QtCore.Slot(str, int, bool, object, str)
    def _finish(
        self,
        key: str,
        generation: int,
        accepted: bool,
        result: object,
        error: str,
    ) -> None:
        with self._lock:
            if self._pending.get(key) != generation:
                return
            self._pending.pop(key, None)
            closed = self._closed
        self.pendingChanged.emit()
        if not closed:
            self.completed.emit(key, bool(accepted), result, str(error or ""))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._pending.clear()
        self._pool.clear()
        self.pendingChanged.emit()


__all__ = ["NativeCommandRunner"]
