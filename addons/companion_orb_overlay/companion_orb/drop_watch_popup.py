"""Small nonmodal QML offer, shown only after a right-drop snapshot is captured."""
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtGui, QtQuick

from .orb_popup import OrbPopupWindow


class DropWatchPopup(QtCore.QObject):
    changed = QtCore.Signal()
    finished = QtCore.Signal()

    def __init__(self, subject: str, scope: str, point: QtCore.QPoint, parent=None, *,
                 add_watch: Callable[[], dict], open_watches: Callable[[], None]):
        super().__init__(parent)
        self._subject, self._scope = subject, scope
        self._add_watch, self._open_watches = add_watch, open_watches
        self._status = ''
        self._added = False
        self._finished = False
        self.view = QtQuick.QQuickView()
        self.view.setTitle('Add a conversational watch')
        self.view.setFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.view.setColor(QtGui.QColor('transparent'))
        self.view.setResizeMode(QtQuick.QQuickView.SizeViewToRootObject)
        self.view.rootContext().setContextProperty('dropWatch', self)
        self.view.setSource(QtCore.QUrl.fromLocalFile(str(Path(__file__).parent / 'qml' / 'DropWatchPopup.qml')))
        if self.view.status() == QtQuick.QQuickView.Error:
            errors = '; '.join(error.toString() for error in self.view.errors())
            self.view.deleteLater()
            raise RuntimeError(errors)
        self.view.installEventFilter(self)
        self.view.setPosition(OrbPopupWindow._clamped_position(point, self.view.size()))
        self.view.heightChanged.connect(self._clamp_position)

    @QtCore.Slot()
    def _clamp_position(self):
        self.view.setPosition(OrbPopupWindow._clamped_position(self.view.position(), self.view.size()))

    @QtCore.Property(str, constant=True)
    def subject(self):
        return self._subject

    @QtCore.Property(str, notify=changed)
    def scope(self):
        return self._scope

    def set_scope(self, scope: str) -> None:
        if scope != self._scope:
            self._scope = scope
            self.changed.emit()

    @QtCore.Property(str, notify=changed)
    def status(self):
        return self._status

    @QtCore.Property(bool, notify=changed)
    def added(self):
        return self._added

    @QtCore.Slot()
    def addWatch(self):
        if self._finished or self._added:
            return
        try:
            result = self._add_watch()
            self._added = bool(result.get('ok'))
            reasons = result.get('paused_reasons', [])
            self._status = ('Watch added. Paused: ' + '; '.join(reasons) + '. Open watches to finish setup.'
                            if self._added and reasons else 'Watch added. It will comment on visible changes.'
                            if self._added else str(result.get('receipt') or 'Watch could not be added.'))
        except Exception:
            self._status = 'Watch could not be added. Open watches to check setup.'
        self.changed.emit()

    @QtCore.Slot()
    def openWatches(self):
        self.cancel()
        self._open_watches()

    @QtCore.Slot()
    def cancel(self):
        if self._finished:
            return
        self._finished = True
        self.view.hide()
        self.finished.emit()

    def show(self):
        self.view.show()

    def eventFilter(self, watched, event):
        if watched is self.view and event.type() == QtCore.QEvent.Close:
            self.cancel()
        return super().eventFilter(watched, event)

    def deleteLater(self):
        self.view.removeEventFilter(self)
        self.view.close()
        self.view.deleteLater()
        super().deleteLater()
