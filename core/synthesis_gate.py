"""One synthesis/seed owner with signalled cancellation for incremental jobs."""
import threading
import time


class SynthesisGate:
    def __init__(self):
        self._condition=threading.Condition()
        self._locked=False

    def _wake(self):
        with self._condition:self._condition.notify_all()

    def acquire(self, blocking=True, timeout=-1, *, cancel_tokens=()):
        tokens=tuple(token for token in cancel_tokens if token is not None)
        subscriptions=[token.subscribe(self._wake) for token in tokens]
        deadline=None if timeout is None or timeout<0 else time.monotonic()+timeout
        try:
            with self._condition:
                while self._locked:
                    if any(token.cancelled for token in tokens) or not blocking:return False
                    remaining=None if deadline is None else deadline-time.monotonic()
                    if remaining is not None and remaining<=0:return False
                    self._condition.wait(remaining)
                if any(token.cancelled for token in tokens):return False
                self._locked=True
                return True
        finally:
            for unsubscribe in subscriptions:unsubscribe()

    def release(self):
        with self._condition:
            if not self._locked:raise RuntimeError('Synthesis gate is not held')
            self._locked=False;self._condition.notify_all()

    def __enter__(self):self.acquire();return self
    def __exit__(self,*_args):self.release()
