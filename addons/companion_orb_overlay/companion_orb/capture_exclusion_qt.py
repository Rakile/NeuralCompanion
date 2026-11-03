"""Qt-owned affinity changes, with cancellation-aware worker acknowledgements."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
import threading
from PySide6 import QtCore, QtGui
from .capture_exclusion import CaptureExclusionManager, WindowAffinityBackend

@dataclass
class _Request:
    serial: int
    operation: str
    lease: object = None
    done: threading.Event = field(default_factory=threading.Event)
    lock: object = field(default_factory=threading.Lock)
    cancelled: bool = False
    error: object = None

class QtCaptureExclusion(QtCore.QObject):
    requested = QtCore.Signal(object)

    def __init__(self, parent=None, *, backend=None, process_id=None, windows=None, timeout=2.):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._serial = 0
        self._closed = False
        self._timeout = timeout
        self._status = dict(state='not_requested', message='Off; capture exclusion has not been requested.', supported=False)
        self._manager = None
        self._native_windows = {}  # QWindow identity -> current native incarnation
        self._tracked_windows = set()
        try:
            backend = backend or WindowAffinityBackend()
            self._manager = CaptureExclusionManager(backend, process_id or os.getpid())
            self._status['supported'] = True
        except Exception as exc:
            self._status.update(state='unavailable', message=str(exc))
        self._windows = windows or self._discover_windows
        self.requested.connect(self._execute, QtCore.Qt.ConnectionType.QueuedConnection)

    def _discover_windows(self):
        windows = []
        for window in QtGui.QGuiApplication.topLevelWindows():
            if window.isVisible():
                identity = self._manager.backend.identity(int(window.winId()))
                if identity and identity.process_id == self._manager.process_id:
                    key = id(window)
                    prior = self._native_windows.get(key)
                    if prior is not None and prior != identity:
                        self._manager.retire_window(prior)
                    if key not in self._tracked_windows:
                        window.installEventFilter(self)
                        window.destroyed.connect(lambda _=None, k=key: self._window_destroyed(k))
                        self._tracked_windows.add(key)
                    self._native_windows[key] = identity
                    windows.append(identity)
        return tuple(windows)

    def _retire_native_window(self, key):
        identity = self._native_windows.pop(key, None)
        if identity is not None and self._manager is not None:
            self._manager.retire_window(identity)

    def _window_destroyed(self, key):
        self._retire_native_window(key)
        self._tracked_windows.discard(key)

    def eventFilter(self, watched, event):
        if (event.type() == QtCore.QEvent.Type.PlatformSurface and
                event.surfaceEventType() == QtGui.QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed):
            self._retire_native_window(id(watched))
        return False

    def _status_update(self, state, message):
        with self._lock:
            self._status.update(state=state, message=message)

    def status_snapshot(self):
        with self._lock:
            return dict(self._status)

    @QtCore.Slot(object)
    def _execute(self, request):
        with request.lock:
            try:
                if self._manager is None:
                    raise OSError(self.status_snapshot()['message'])
                if request.operation == 'acquire':
                    if request.cancelled or self._closed:
                        return
                    request.lease = self._manager.acquire(self._windows())
                    self._status_update('applied', 'NC exclusion affinity applied; captured pixels need verification.')
                elif request.operation == 'release':
                    self._manager.release(request.lease)
                    self._status_update('restored', 'Prior NC affinity restored; captured pixels need verification.')
                elif request.operation == 'shutdown':
                    self._closed = True
                    self._manager.restore_all()
                    self._status_update('restored', 'Prior NC affinity restored on shutdown.')
            except Exception as exc:
                request.error = exc
                self._status_update('failed', f'NC capture exclusion failed: {exc}')
            finally:
                request.done.set()

    def _call(self, operation, lease=None):
        with self._lock:
            self._serial += 1
            request = _Request(self._serial, operation, lease)
        if QtCore.QThread.currentThread() == self.thread():
            self._execute(request)
        else:
            self.requested.emit(request)
            if not request.done.wait(self._timeout):
                with request.lock:
                    request.cancelled = True
                    acquired = request.lease if operation == 'acquire' else None
                if acquired is not None:
                    # A just-completed acquisition still owns cleanup, never orphan it.
                    cleanup = _Request(request.serial, 'release', acquired)
                    self.requested.emit(cleanup)
                    cleanup.done.wait(self._timeout)
                self._status_update('failed', 'NC exclusion UI acknowledgement timed out; pending acquisition cancelled.')
                raise TimeoutError('NC exclusion UI acknowledgement timed out.')
        if request.error:
            raise request.error
        if operation == 'acquire' and request.lease is None:
            raise RuntimeError('NC exclusion is shutting down.')
        return request.lease

    @contextmanager
    def capture_scope(self, enabled):
        if not enabled:
            yield
            return
        self._status_update('requested', 'Requesting temporary NC capture exclusion.')
        lease = self._call('acquire')
        try:
            yield
        finally:
            self._call('release', lease)

    def shutdown(self):
        self._call('shutdown')
