"""Presentation-only theme preferences, independent of runtime configuration."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable

from PySide6 import QtCore


DEFAULT_COLORS = {
    "accent": "#31d5f4", "window": "#07111d",
    "surface": "#0c1928", "text": "#f4f8fc",
}
PRESETS = frozenset({"midnight", "dark_gray", "forest"})


def validated_colors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Choose an accent, background, panel and text color.")
    colors: dict[str, str] = {}
    for key in DEFAULT_COLORS:
        color = value.get(key)
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Colors must use six-digit hex values, such as #31d5f4.")
        colors[key] = color.lower()
    return colors


class _Result(QtCore.QObject):
    finished = QtCore.Signal(object, str)


class _Job(QtCore.QRunnable):
    def __init__(self, operation: Callable[[], dict[str, Any]]) -> None:
        super().__init__()
        self.operation = operation
        self.result = _Result()

    def run(self) -> None:
        try:
            state, error = self.operation(), ""
        except Exception as exc:
            state, error = None, str(exc)
        self.result.finished.emit(state, error)


class AppearanceController(QtCore.QObject):
    """Save asynchronously; publish a palette only after its atomic write succeeds."""

    stateChanged = QtCore.Signal()
    statusChanged = QtCore.Signal()
    saved = QtCore.Signal()

    def __init__(self, path: Path, *, read_only: bool = False,
                 parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._path = Path(path)
        self._read_only = read_only
        self._selection = ""
        self._colors = dict(DEFAULT_COLORS)
        self._busy = False
        self._error = ""
        self._saving = False
        self._job: _Job | None = None
        self._start(self._read)

    @QtCore.Property(str, notify=stateChanged)
    def selection(self) -> str:
        return self._selection

    @QtCore.Property("QVariantMap", notify=stateChanged)
    def colors(self) -> dict[str, str]:
        return dict(self._colors)

    @QtCore.Property(bool, notify=statusChanged)
    def busy(self) -> bool:
        return self._busy

    @QtCore.Property(str, notify=statusChanged)
    def error(self) -> str:
        return self._error

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"selection": "", "colors": dict(DEFAULT_COLORS)}
        if not isinstance(raw, dict) or raw.get("selection") not in PRESETS | {"custom", ""}:
            raise ValueError("Saved appearance is invalid. Choose a preset or save new colors.")
        return {"selection": raw["selection"], "colors": validated_colors(raw.get("colors"))}

    def _start(self, operation: Callable[[], dict[str, Any]]) -> None:
        self._busy, self._error = True, ""
        self._job = _Job(operation)
        self._job.result.finished.connect(self._finished, QtCore.Qt.ConnectionType.QueuedConnection)
        self.statusChanged.emit()
        QtCore.QThreadPool.globalInstance().start(self._job)

    @QtCore.Slot(object, str)
    def _finished(self, state: dict[str, Any] | None, error: str) -> None:
        saving = self._saving
        self._saving = False
        self._busy, self._error = False, error
        self._job = None
        if state is not None:
            self._selection = state["selection"]
            self._colors = state["colors"]
            self.stateChanged.emit()
        self.statusChanged.emit()
        if saving and state is not None:
            self.saved.emit()

    def _save(self, selection: str, colors: dict[str, str]) -> None:
        if self._busy:
            return
        if self._read_only:
            self._error = "Appearance settings are read-only in this session."
            self.statusChanged.emit()
            return
        state = {"selection": selection, "colors": dict(colors)}
        path = self._path

        def write() -> dict[str, Any]:
            path.parent.mkdir(parents=True, exist_ok=True)
            output = QtCore.QSaveFile(str(path))
            if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            data = (json.dumps(state, indent=2) + "\n").encode("utf-8")
            if output.write(data) != len(data):
                output.cancelWriting()
                raise OSError("Could not write appearance preferences.")
            if not output.commit():
                raise OSError(output.errorString())
            return state

        self._saving = True
        self._start(write)

    @QtCore.Slot("QVariantMap")
    def saveCustom(self, colors: dict[str, Any]) -> None:
        if self._busy:
            return
        try:
            normalized = validated_colors(colors)
        except ValueError as exc:
            self._error = str(exc)
            self.statusChanged.emit()
            return
        self._save("custom", normalized)

    @QtCore.Slot(str)
    def selectPreset(self, preset: str) -> None:
        if preset in PRESETS:
            self._save(preset, self._colors)
