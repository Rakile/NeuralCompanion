"""Process console capture owned by the native QML shell."""

from __future__ import annotations

import sys
from typing import TextIO

from PySide6 import QtCore

from ui.qml_bridge.console_stream import QtConsoleBridge, QtTextRedirector


class NativeConsoleCapture(QtCore.QObject):
    """Tee stdout/stderr into QML while preserving their original streams."""

    textReady = QtCore.Signal(str)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._previous_stdout: TextIO | object = sys.stdout
        self._previous_stderr: TextIO | object = sys.stderr
        self._bridge = QtConsoleBridge(self)
        self._bridge.text_ready.connect(self.textReady)
        self._redirector = QtTextRedirector(
            self._bridge,
            mirror_stream=self._previous_stdout,
        )
        self._installed = False

    def install(self) -> None:
        if self._installed:
            return
        sys.stdout = self._redirector
        sys.stderr = self._redirector
        self._installed = True

    def close(self) -> None:
        if not self._installed:
            return
        try:
            self._redirector.flush()
        except Exception:
            pass
        if sys.stdout is self._redirector:
            sys.stdout = self._previous_stdout
        if sys.stderr is self._redirector:
            sys.stderr = self._previous_stderr
        self._installed = False


__all__ = ["NativeConsoleCapture"]
