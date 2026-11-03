"""In-process invalidation only: no frames, snapshots, Qt calls or polling."""
from functools import wraps
import logging
import threading


class ChangeNotifications:
    def __init__(self):
        self._lock = threading.Lock()
        self._callbacks = {}
        self._next_token = 0

    def subscribe(self, callback):
        if not callable(callback):
            raise TypeError('Ditto change subscriber must be callable.')
        with self._lock:
            self._next_token += 1
            token = self._next_token
            self._callbacks[token] = callback

        def unsubscribe(*unused):
            with self._lock:
                self._callbacks.pop(token, None)
        return unsubscribe

    def notify(self):
        # Subscribers only enqueue invalidation; they must never read service
        # state or operate on UI here, as the producer may hold the service lock.
        with self._lock:
            callbacks = tuple(self._callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logging.getLogger(__name__).exception('Ditto change notification failed')


def notify_after(method):
    """Publish operation completion (including errors) from any producer thread."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        finally:
            self.changes.notify()
    return wrapped
