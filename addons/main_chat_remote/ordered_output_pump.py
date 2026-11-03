"""One independently scheduled encoder per authenticated ordered session.

No player, phone preparation request or chat dispatch is performed here. Storage
ACKs and control messages can wake work early; a bounded wait also observes the
existing atomic render sidecars when an inference worker finishes a source.
"""
import threading
import time


class OrderedOutputPump:
    def __init__(self, worker, *, on_published=None, on_failure=None,
                 acquire_source=None,release_source=None,finish_reply=None):
        self.worker = worker
        self._on_published = on_published
        self._on_failure = on_failure
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._failure = None
        self._acquire_source,self._release_source,self._finish_reply=acquire_source,release_source,finish_reply
        self._pipeline=None;self._pipelines=[]
        if acquire_source is not None:
            from .ordered_prepared import PreparedBudget
            worker.producer.attach_budget(worker.producer.budget or PreparedBudget())
            worker.defer_speech=True

    @property
    def failure(self):
        with self._lock:
            return self._failure

    def diagnostic_state(self):
        if not self._lock.acquire(blocking=False): return {'pump.state':'lock_busy'}
        try:
            result={'pump.state':'observed', 'pump.stop_requested':self._stop.is_set(),
                    'pump.thread_alive':self._thread is not None and self._thread.is_alive(),
                    'pump.failed':self._failure is not None}
            if self._pipeline is not None:result.update(self._pipeline.diagnostic_state())
            return result
        finally: self._lock.release()

    def start(self):
        with self._lock:
            if self._stop.is_set():
                raise ValueError('ordered_pump_closed')
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name='nc-ordered-output', daemon=True)
            self._thread.start()

    def wake(self):
        self._wake.set()

    def _run(self):
        try:
            while not self._stop.is_set():
                # Clear before work: an ACK/Stop racing the operation cannot be
                # lost between a failed capacity check and the following wait.
                self._wake.clear()
                result = self.worker.step()
                if result=='speech_ready':
                    from .ordered_speech_pipeline import OrderedSpeechPipeline
                    pipeline=OrderedSpeechPipeline(self.worker,acquire=self._acquire_source,
                        release=self._release_source,finish=self._finish_reply,
                        on_published=self._on_published,on_failure=self._on_failure,
                        budget=self.worker.producer.budget)
                    self._pipeline=pipeline;self._pipelines.append(pipeline)
                    if self._stop.is_set():pipeline.stop()
                    pipeline.run()
                    # Stop may leave an HTTP role joining. Keep its handle for
                    # close()/cleanup() retry; cancellation is not a failure.
                    if self._stop.is_set():break
                    pipeline.cleanup();self._pipelines.remove(pipeline);self._pipeline=None
                    continue
                if result == 'cancelled':
                    break
                if result == 'published':
                    if self._on_published is not None:
                        # The worker already committed the chunk. Wake availability
                        # immediately; its authenticated read obtains current state.
                        self._on_published(None)
                    continue
                if result == 'stale':
                    continue
                self._wake.wait(0.05 if result == 'waiting' else 0.25)
            self.worker.stop()
            self.worker.step()  # Join owned encoder scratch; never reader-owned MP4s.
        except Exception as error:
            self.worker.stop()
            if self._pipeline is not None:self._pipeline.stop()
            with self._lock:
                if self._failure is None:
                    self._failure = error
            if self._on_failure is not None:
                try:
                    self._on_failure(error)
                except Exception:
                    pass  # First production failure is retained, not replaced.

    def stop(self):
        self.worker.stop()
        self._stop.set()
        self._wake.set()
        if self._pipeline is not None:self._pipeline.stop()

    def close(self, *, timeout=5):
        self.stop()
        deadline=time.monotonic()+timeout
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(max(0,deadline-time.monotonic()))
        settled=not thread.is_alive()
        for pipeline in tuple(self._pipelines):
            settled=pipeline.close(max(0,deadline-time.monotonic())) and settled
        return settled

    def cleanup(self):
        self.worker.step()
        for pipeline in tuple(self._pipelines):pipeline.cleanup()
