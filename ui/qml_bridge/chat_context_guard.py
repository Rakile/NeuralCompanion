"""Save / Don't Save / Cancel before replacing an unsaved desktop chat."""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from PySide6 import QtCore
from core.chat_context_safety import history_signature


class ChatContextGuard(QtCore.QObject):
    changed = QtCore.Signal()
    saved = QtCore.Signal()
    savePathRequested = QtCore.Signal()
    _finished = QtCore.Signal(object)
    _saved = QtCore.Signal(object)

    def __init__(self, application, parent=None):
        super().__init__(parent)
        self._application = application
        self._baseline = history_signature([])
        self._pending = None
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chat-save-guard')
        self._state = dict(active=False, busy=False, action='', error='', path='', saveOnly=False)
        self._finished.connect(self._complete)
        self._saved.connect(self.markSavedReceipt)

    @QtCore.Property('QVariantMap', notify=changed)
    def state(self):
        return dict(self._state)

    def markSaved(self, history):
        self.markSignatureSaved(history_signature(history))

    def isDirty(self):
        return history_signature(self._application.chat.history()) != self._baseline

    @QtCore.Slot(str)
    def markSignatureSaved(self, signature):
        if not self._closed:
            self._baseline = str(signature)

    def _generation(self):
        snapshot = getattr(self._application.chat, 'snapshot', None)
        return snapshot().session_generation if snapshot is not None else None

    @QtCore.Slot(object)
    def markSavedReceipt(self, receipt):
        signature, generation = receipt
        if generation is None or generation == self._generation():
            self.markSignatureSaved(signature)

    def memoryUpdated(self, payload):
        if payload and payload.get('context_history_signature'):
            self._saved.emit((str(payload['context_history_signature']), self._generation()))

    def request(self, action, continuation):
        if self._closed or self._pending is not None:
            return False
        if not self.isDirty():
            continuation()
            return True
        self._pending = continuation
        path = self._application.config.snapshot().values.get('active_chat_context_path', '')
        self._state.update(active=True, busy=False, action=str(action), error='', path=str(path or ''), saveOnly=False)
        self.changed.emit()
        return False

    def requestSave(self, action: str, continuation: Callable[[], None]) -> bool:
        """Explicit Save choice, sharing the existing save worker and receipt checks."""
        if self._closed or self._pending is not None:
            return False
        path = str(self._application.config.snapshot().values.get('active_chat_context_path', '') or '')
        self._pending = continuation
        self._state.update(active=True, busy=False, action=action, error='', path=path, saveOnly=True)
        self.changed.emit()
        if path:
            self.saveTo(path)
        else:
            self.savePathRequested.emit()
        return True

    @QtCore.Slot(str)
    def decide(self, decision):
        if self._state['busy'] or self._pending is None:
            return
        continuation = self._pending
        self._pending = None
        self._state.update(active=False, error='')
        self.changed.emit()
        if decision == 'discard':
            continuation()

    @QtCore.Slot(str)
    def saveTo(self, path):
        if self._pending is None or self._state['busy'] or not path:
            return
        self._state.update(busy=True, error='')
        self._save_generation = self._generation()
        self.changed.emit()
        def save():
            try:
                return (self._save(path), None)
            except Exception as error:
                return (None, str(error))
        future = self._executor.submit(save)
        future.add_done_callback(lambda task: None if self._closed else self._finished.emit(task.result()))

    def _save(self, path):
        from ui.qml_bridge.native_chat_context import save_chat_context
        from PySide6.QtCore import QUrl
        local = QUrl(path).toLocalFile() if str(path).startswith('file:') else path
        generation = self._application.chat.snapshot().session_generation
        result = save_chat_context(self._application, local,
            is_current=lambda: not self._closed and self._application.chat.snapshot().session_generation == generation)
        return result['saved_history_signature']

    @QtCore.Slot(object)
    def _complete(self, result):
        if self._closed:
            return
        history, error = result
        self._state['busy'] = False
        if not error and self._generation() != self._save_generation:
            error = 'The active conversation changed during saving. The requested action was cancelled.'
        if error:
            self._state['error'] = 'The conversation was not saved. ' + error
        else:
            if isinstance(history, str):
                self.markSignatureSaved(history)
            else:
                self.markSaved(history)
            self.saved.emit()
            if history_signature(self._application.chat.history()) != self._baseline:
                self._state['error'] = 'The conversation changed during saving. Save the new changes, Don’t Save, or Cancel.'
            else:
                continuation = self._pending
                self._pending = None
                self._state.update(active=False, error='')
                self.changed.emit()
                if continuation is not None:
                    continuation()
                return
        self.changed.emit()

    def close(self):
        self._closed = True
        self._pending = None
        self._executor.shutdown(wait=False, cancel_futures=True)
