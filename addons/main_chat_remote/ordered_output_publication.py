"""Independent sequential publication; encoding never waits on this worker."""
from dataclasses import dataclass, field
from types import MappingProxyType
import threading

from .output_sequence import OutputChunk, OutputFrontier, OutputRejected


@dataclass(frozen=True, slots=True)
class PublicationAck:
    chunk: OutputChunk
    frontier: OutputFrontier
    timings: object = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self,'timings',MappingProxyType(dict(self.timings)))


class OrderedClipPublisher:
    def __init__(self,producer,buffer,*,origin,lifetime,on_published,on_failure):
        self.producer,self.buffer=producer,buffer
        self._frontier,self.lifetime=origin,lifetime
        self._on_published,self._on_failure=on_published,on_failure
        self._stop=threading.Event();self._current=None
        self._admission=threading.Lock()
        self.wait_reason='queue'

    def frontier(self):return self._frontier

    def stop(self):
        with self._admission:self._stop.set()
        self.buffer.stop()

    def _discard_current(self):
        clip=self._current
        if clip is not None and not self.producer.owns_file(clip.output.file):
            self.producer.discard_private_clip(clip)
            self._current=None

    def cleanup(self):
        # Retry after authoritative reconciliation; uncertain files stay pinned.
        self._discard_current()

    def run(self):
        try:
            while not self._stop.is_set():
                if self._current is None:self._current=self.buffer.take()
                if self._current is None:return
                # A short admission check, never a lock spanning Desktop HTTP.
                with self._admission:
                    if self._stop.is_set():break
                try:
                    self.wait_reason='commit'
                    with self.buffer.budget.condition:release_serial=self.buffer.budget.release_serial
                    ack=self.producer.commit_prepared(self._current,self._frontier)
                except OutputRejected as error:
                    if error.reason!='capacity':raise
                    self.wait_reason='capacity'
                    # Reader-joined release or Stop wakes this exact pending item.
                    with self.buffer.budget.condition:
                        while not self._stop.is_set() and release_serial==self.buffer.budget.release_serial:
                            self.buffer.budget.condition.wait()
                    continue
                self._frontier=ack.frontier;self._current=None
                self.wait_reason='queue'
                if not self._stop.is_set():self._on_published(ack)
        except BaseException as error:
            cancelled=self._stop.is_set()
            self.stop()
            if not cancelled:self._on_failure(error)
        finally:
            self._discard_current()
