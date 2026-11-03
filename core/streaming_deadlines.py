"""Owned text-channel shutdown and one-shot speech flush deadlines.

No provider iteration or inference runs here. Input, timer and final emission share
one lock; cancellation only signals the wakeup so callbacks never wait on it.
"""
from __future__ import annotations

from collections import deque
from queue import Empty
import threading
import time


class SubscribableEvent(threading.Event):
    """Event-compatible scoped cancellation with removable wakeup callbacks."""

    def __init__(self):
        super().__init__()
        self._subscriber_lock = threading.Lock()
        self._subscribers = set()

    def subscribe(self, callback):
        with self._subscriber_lock:
            ready = self.is_set()
            if not ready:
                self._subscribers.add(callback)
        if ready:
            callback()
        def unsubscribe():
            with self._subscriber_lock:
                self._subscribers.discard(callback)
        return unsubscribe

    def set(self):
        with self._subscriber_lock:
            super().set()
            callbacks = tuple(self._subscribers)
            self._subscribers.clear()
        for callback in callbacks:
            callback()


class TextStreamChannel:
    """Unbounded queue-compatible text channel with explicit, waking close.

    None ends input after queued items. close() revokes unread items immediately.
    Values, including typed voice segments, are never converted or copied.
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._items = deque()
        self._ended = False
        self._closed = False

    def put(self, item, block=True, timeout=None):
        del block, timeout
        with self._condition:
            if self._closed or self._ended:
                return
            if item is None:
                self._ended = True
            else:
                self._items.append(item)
            self._condition.notify_all()

    def get(self, block=True, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._items and not self._ended and not self._closed:
                if not block:
                    raise Empty
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise Empty
                self._condition.wait(remaining)
            if self._closed:
                return None
            if self._items:
                return self._items.popleft()
            return None

    def close(self):
        with self._condition:
            self._closed = True
            self._items.clear()
            self._condition.notify_all()


class StreamingDeadlinePublisher:
    """Serialize assembler input, deadline publication and terminal draining."""

    def __init__(self, assembler, publish, *, cancellation=None):
        self._assembler = assembler
        self._publish = publish
        self._cancellation = cancellation
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._error = None
        self._unsubscribe = lambda: None
        self._thread = threading.Thread(target=self._run,
            name='nc-speech-text-deadline', daemon=True)
        subscribe = getattr(cancellation, 'subscribe', None)
        if callable(subscribe):
            self._unsubscribe = subscribe(self._request_close)
        self._thread.start()

    def _cancelled(self):
        return self._stopped.is_set() or bool(getattr(self._cancellation, 'cancelled', False))

    def _request_close(self):
        # Cancellation may originate inside transaction/addon locks. Do not
        # acquire the publication lock or join from its notification callback.
        self._stopped.set()
        self._wake.set()

    def _emit(self, text, *, final=False):
        for chunk in self._assembler.feed(text, final=final):
            if self._cancelled():
                return
            self._publish(chunk)

    def feed(self, text):
        with self._lock:
            if self._error is not None:
                raise self._error
            if not self._cancelled():
                self._emit(text)
                self._wake.set()

    def finish(self):
        try:
            with self._lock:
                if self._error is not None:
                    raise self._error
                if not self._cancelled():
                    self._emit('', final=True)
                self._request_close()
        finally:
            self.close()

    def close(self):
        self._request_close()
        # Join outside the publication lock. finish/cancel may race a due timer.
        if threading.current_thread() is not self._thread:
            self._thread.join()
        self._unsubscribe()

    def _run(self):
        try:
            while True:
                with self._lock:
                    self._wake.clear()
                    if self._cancelled():
                        return
                    deadline = self._assembler.next_flush_deadline()
                    remaining = None if deadline is None else max(0.0, deadline - self._assembler.clock())
                    if remaining == 0:
                        self._emit('')
                        continue
                self._wake.wait(remaining)
        except BaseException as exc:
            with self._lock:
                self._error = exc
                self._request_close()
        finally:
            self._unsubscribe()
