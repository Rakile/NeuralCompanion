"""Thin encoded-media pipeline over the existing normal-chat source lifetime."""
from collections import deque
from dataclasses import replace
import threading
import time

from .ordered_output_encoding import OrderedClipEncoder
from .ordered_output_publication import OrderedClipPublisher
from .ordered_prepared import PreparedClipBuffer, SourceTicket


class OrderedSpeechPipeline:
    def __init__(self,worker,*,acquire,release,finish,on_published,on_failure,budget):
        self.worker,self.acquire,self.release,self.finish=worker,acquire,release,finish
        self._on_published,self._on_failure=on_published,on_failure
        self.buffer=PreparedClipBuffer(budget)
        self._stop=threading.Event();self._condition=threading.Condition()
        self._plans=deque();self._releases=deque();self._source_done=False
        self._error=None;self._threads=[];self.encoder=None;self.publisher=None
        self._handoff=None
        self.lifetime=object()
        self._encoder_wait='first_source';self._source_wait='source'

    def stop(self):
        self._stop.set();self.buffer.stop()
        if self.encoder is not None:self.encoder.stop()
        if self.publisher is not None:self.publisher.stop()
        with self._condition:self._condition.notify_all()

    def _failed(self,error):
        with self._condition:
            if self._error is None:self._error=error
        self.stop()

    def _get_sources(self,after):
        try:
            while not self._stop.is_set():
                with self._condition:
                    releases=tuple(self._releases);self._releases.clear()
                for plan_id in releases:
                    if self._stop.is_set():return
                    self.release(plan_id,'encoded')
                with self._condition:
                    if len(self._plans)>=2:
                        self._condition.wait();continue
                result=self.acquire(after)
                if self._stop.is_set():return
                if result.get('state')=='waiting':
                    self._source_wait=result.get('stage') if result.get('stage') in (
                        'audio','render','preparation_capacity') else 'source'
                    with self._condition:
                        if not self._stop.is_set():self._condition.wait(0.05)
                    continue
                if result.get('state')=='complete':
                    with self._condition:
                        self._source_done=True;self._condition.notify_all()
                    return
                if result.get('state')!='ready':raise ValueError('ordered_preparation_response')
                ticket=SourceTicket.from_wire(result['ticket'])
                self._source_wait='ready'
                with self._condition:
                    if self._stop.is_set():return
                    self._plans.append(ticket);after=ticket.plan_id
                    self._condition.notify_all()
        except BaseException as error:
            if not self._stop.is_set():self._failed(error)

    def _published(self,ack):
        # Existing publication site, now produced by the independent commit role.
        expected=replace(ack.frontier,next_ordinal=ack.chunk.ordinal,revision=ack.frontier.revision-1)
        self.worker._event('published',expected,sequence_index=ack.chunk.sequence_index,**dict(ack.timings))
        if not self._stop.is_set() and self._on_published is not None:self._on_published(ack)

    def _spawn(self,name,target):
        thread=threading.Thread(target=target,name=name,daemon=True)
        self._threads.append(thread);thread.start()

    def run(self):
        try:
            # One initial handshake; every later source request is on its own role.
            first=self.acquire(None)
            if self._stop.is_set():return
            if first.get('state')!='ready':raise ValueError('ordered_preparation_first_source')
            ticket=SourceTicket.from_wire(first['ticket'])
            self.encoder=OrderedClipEncoder(ffmpeg=self.worker.ffmpeg,root=self.worker.producer.root,
                source_roots=self.worker.roots,quality=self.worker.quality,cancelled=self._stop.is_set,
                verify_media=self.worker.verify_media,on_event=self.worker._on_event)
            self.encoder.seed_tail(self.worker._pixel_tail)
            self.publisher=OrderedClipPublisher(self.worker.producer,self.buffer,origin=ticket.origin,
                lifetime=self.lifetime,on_published=self._published,on_failure=self._failed)
            self._spawn('nc-ordered-source',lambda:self._get_sources(ticket.plan_id))
            self._spawn('nc-ordered-publish',self.publisher.run)
            while not self._stop.is_set():
                self.encoder.begin(ticket)
                while not self.encoder.source_complete() and not self._stop.is_set():
                    self._encoder_wait='buffer'
                    token=self.buffer.budget.try_reserve()
                    if token is None:
                        self.encoder._event('backpressure',ticket.cursor,capacity_kind='prepared_media')
                        token=self.buffer.reserve()
                    if token is None:break
                    clip=None
                    try:
                        self._encoder_wait='encoding'
                        clip=self.encoder.prepare_next(token)
                        self._handoff=clip
                        self.buffer.budget.resize(token,clip.output.file.stat().st_size)
                        if not self.buffer.put(clip):
                            self._discard_handoff()
                        else:self._handoff=None
                    except BaseException:
                        if self._handoff is None and not self.encoder.owns_private(token):
                            self.buffer.budget.release(token)
                        raise
                with self._condition:
                    self._encoder_wait='input'
                    self._releases.append(ticket.plan_id);self._condition.notify_all()
                    while not self._plans and not self._source_done and not self._stop.is_set():
                        self._condition.wait()
                    if self._stop.is_set():break
                    if not self._plans:break
                    ticket=self._plans.popleft();self._condition.notify_all()
            self.buffer.finish_input()
            self._encoder_wait='publication_drain'
            # Healthy transport/backpressure may take arbitrarily long. Only an
            # explicit Stop imposes the caller's bounded shutdown join deadline.
            while not self._stop.is_set() and not self.close(0.1):pass
            if self._error is not None:raise self._error
            if not self._stop.is_set():
                # Authenticated Desktop finish is after publication, not encoding.
                self.finish(ticket.cursor.reply_id)
                self.worker._pixel_tail=self.encoder.tail_state()
                self.worker._fade=None
        except InterruptedError as error:
            if not self._stop.is_set():
                self._error=self._error or error;self.stop()
        except BaseException as error:
            self._error=self._error or error;self.stop()
        finally:
            operations=[self._discard_handoff,self.worker._forget_source,self.buffer.discard_private]
            if self.encoder is not None:operations.insert(0,self.encoder.close)
            for operation in operations:
                try:operation()
                except BaseException as error:
                    if self._error is None:self._error=error
                    else:self._error.add_note('ordered_pipeline_cleanup: '+type(error).__name__)
            if self._error is not None:raise self._error

    def close(self,timeout=5):
        deadline=time.monotonic()+timeout
        for thread in tuple(self._threads):
            if thread is not threading.current_thread():thread.join(max(0,deadline-time.monotonic()))
        return not any(thread.is_alive() for thread in self._threads)

    def cleanup(self):
        if any(t.is_alive() for t in self._threads):raise ValueError('ordered_service_encoder_join_pending')
        self._discard_handoff()
        if self.publisher is not None:self.publisher.cleanup()
        self.buffer.discard_private()

    def _discard_handoff(self):
        if self._handoff is not None:
            clip=self._handoff
            clip.output.file.unlink(missing_ok=True)
            self.buffer.budget.release(clip.reservation)
            self._handoff=None

    def diagnostic_state(self):
        condition=self.buffer.budget.condition
        if not condition.acquire(blocking=False):return {'pipeline.state':'lock_busy'}
        try:
            facts=self.buffer.budget.snapshot()
            return {**{'pipeline.'+k:v for k,v in facts.items()},
                'pipeline.roles_alive':sum(t.is_alive() for t in self._threads),
                'pipeline.stopped':self._stop.is_set(), 'pipeline.encoder_wait':self._encoder_wait,
                'pipeline.source_wait':self._source_wait,
                'pipeline.publisher_wait':self.publisher.wait_reason if self.publisher is not None else 'not_started'}
        finally:condition.release()
