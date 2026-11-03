"""Speech-order model admission; postprocessing remains independently parallel."""
from collections import deque
import threading


class SynthesisOrder:
    def __init__(self):
        self._condition = threading.Condition()
        self._pending = deque()

    def reserve(self, count):
        # Reserve synchronously in text order, before any worker can race ahead.
        with self._condition:
            reservations = tuple(_Reservation(self) for _ in range(count))
            self._pending.extend(reservations)
            return reservations


class _Reservation:
    def __init__(self, order):
        self._order = order
        self._claimed = self._released = False

    def acquire(self, *, cancel_tokens=()):
        order = self._order
        cancelled = [False]
        def wake_cancel():
            with order._condition:
                cancelled[0] = True
                order._condition.notify_all()
        subscriptions = [token.subscribe(wake_cancel) for token in cancel_tokens if token is not None]
        try:
            with order._condition:
                order._condition.wait_for(lambda: cancelled[0] or self._released
                    or (order._pending and order._pending[0] is self))
                if cancelled[0] or self._released:
                    self._release_locked()
                    return False
                self._claimed = True
                return True
        finally:
            for unsubscribe in subscriptions:
                unsubscribe()

    def _release_locked(self):
        if not self._released:
            self._released = True
            self._order._pending.remove(self)
            self._order._condition.notify_all()

    def release(self):
        with self._order._condition:
            self._release_locked()

    def discard_unclaimed(self):
        # A ready header can outlive preparation while its PCM is still produced.
        with self._order._condition:
            if not self._claimed:
                self._release_locked()
