"""Visibility-scoped, bounded background resource monitoring for Qt Quick."""
from __future__ import annotations

from copy import deepcopy
from PySide6 import QtCore
from .native_commands import NativeCommandRunner


class ResourceMonitor(QtCore.QObject):
    shutdownFinished = QtCore.Signal()
    snapshotChanged = QtCore.Signal()
    busyChanged = QtCore.Signal()
    refreshingChanged = QtCore.Signal()
    refreshIntervalChanged = QtCore.Signal()

    def __init__(self, service, parent=None, *, settings=None, read_only=False):
        super().__init__(parent)
        self._service = service
        self._settings = settings
        self._read_only = read_only
        self._closed = False
        self._shutdown_requested = False
        self._active = 0
        self._operation = ''
        self._pending_action = None
        self._has_snapshot = False
        self._snapshot = {'resources': [], 'memory': {'ram': {}, 'gpus': []},
                          'errors': [], 'message': '', 'updatedAt': None}
        self._runner = NativeCommandRunner(self, max_workers=1)
        self._runner.completed.connect(self._complete)
        self._timer = QtCore.QTimer(self)
        try:
            seconds = int(settings.value('refreshIntervalSeconds', 3)) if settings is not None else 3
        except (TypeError, ValueError, OverflowError):
            seconds = 3
        self._timer.setInterval(max(1, min(59, seconds)) * 1000)
        self._timer.timeout.connect(self._poll)

    @QtCore.Property(int, notify=refreshIntervalChanged)
    def refreshIntervalSeconds(self):
        return self._timer.interval() // 1000

    @QtCore.Slot(int)
    def setRefreshIntervalSeconds(self, seconds):
        seconds = max(1, min(59, seconds))
        if seconds == self.refreshIntervalSeconds:
            return
        self._timer.setInterval(seconds * 1000)
        if self._settings is not None and not self._read_only:
            self._settings.setValue('refreshIntervalSeconds', seconds)
        self.refreshIntervalChanged.emit()

    @QtCore.Property('QVariantMap', notify=snapshotChanged)
    def snapshot(self):
        return deepcopy(self._snapshot)

    @QtCore.Property(bool, notify=busyChanged)
    def busy(self):
        return self._operation in ('unload', 'free') or self._pending_action is not None

    @QtCore.Property(bool, notify=refreshingChanged)
    def refreshing(self):
        return self._operation == 'refresh'

    def _notify(self):
        self.busyChanged.emit()
        self.refreshingChanged.emit()

    @QtCore.Slot(bool)
    def setActive(self, active):
        if self._closed:
            return
        self._active = max(0, self._active + (1 if active else -1))
        if self._active and not self._shutdown_requested:
            self._timer.start()
            self._submit('poll' if self._has_snapshot else 'refresh')
        else:
            self._timer.stop()

    def refreshIfActive(self):
        self._poll()

    def _poll(self):
        if self._active:
            self._submit('poll')

    @QtCore.Slot()
    def refresh(self):
        self._submit('refresh')

    @QtCore.Slot(str)
    def unload(self, resource_id):
        if str(resource_id):
            self._submit('unload', str(resource_id))

    @QtCore.Slot()
    def freeUnused(self):
        self._submit('free')

    def _submit(self, operation, resource_id=''):
        if self._closed or self._shutdown_requested:
            return
        if self._operation:
            if self._operation == 'poll' and self._pending_action is None:
                if operation == 'refresh':
                    # Reuse this read for an explicit Refresh click.
                    self._operation = 'refresh'
                    self._notify()
                elif operation in ('unload', 'free'):
                    # Polling is silent, so its buttons remain available. Keep
                    # one user action and run it after the current read drains.
                    self._pending_action = (operation, resource_id)
                    self._notify()
            return
        self._operation = operation
        self._notify()
        service = self._service
        def run():
            if service is None:
                raise RuntimeError('Resource inspection is unavailable in this runtime.')
            result = None
            if operation == 'unload':
                result = service.unload(resource_id)
            elif operation == 'free':
                result = service.free_unused()
            return {'snapshot': service.snapshot(), 'result': result}
        if not self._runner.submit('resources', run):
            self._operation = ''
            self._notify()

    @QtCore.Slot(str, bool, object, str)
    def _complete(self, key, accepted, value, error):
        if self._closed:
            return
        self._operation = ''
        if accepted:
            self._snapshot = dict(value['snapshot'])
            self._has_snapshot = True
            if value.get('result'):
                self._snapshot['message'] = str(value['result'].get('message') or '')
        else:
            self._snapshot['errors'] = [str(error or 'Resource inspection failed.')]
            # Previously seen resources remain visible, but stale data must
            # never advertise cleanup as safe.
            for row in self._snapshot.get('resources', ()):
                row['canUnload'] = False
                row['unloadReason'] = 'Inspection unavailable; refresh before unloading.'
        self._notify()
        self.snapshotChanged.emit()
        if self._shutdown_requested:
            self.shutdownFinished.emit()
        elif self._pending_action is not None:
            pending, self._pending_action = self._pending_action, None
            self._submit(*pending)

    def beginShutdown(self):
        self._shutdown_requested = True
        self._pending_action = None
        self._timer.stop()
        self._notify()
        return not self._operation

    def cancelShutdown(self):
        if self._closed:
            return
        self._shutdown_requested = False
        if self._active:
            self._timer.start()

    def close(self):
        self._closed = True
        self._pending_action = None
        self._timer.stop()
        self._runner.close()
