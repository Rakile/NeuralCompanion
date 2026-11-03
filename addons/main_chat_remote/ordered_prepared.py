"""Private ordered handoff; storage credit follows custody through reader ACK.

Uses normal speech's reservation-aware condition/handoff model, without its
WAV deletion policy. A preparation cursor is never output authority.
"""
from collections import deque
from dataclasses import dataclass
from types import MappingProxyType
import re
import threading

from .output_sequence import OutputFrontier, FrameProvenance, MAX_CHUNKS, MAX_BYTES, MAX_MEDIA_BYTES


@dataclass(frozen=True, slots=True)
class PreparationCursor:
    stream_id: str
    generation: int
    reply_id: str
    sequence_index: int
    ordinal: int
    revision: int
    predecessor_frame: FrameProvenance | None

    def __post_init__(self):
        if (not isinstance(self.stream_id,str) or not re.fullmatch('[a-f0-9]{32}',self.stream_id)
                or not isinstance(self.reply_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',self.reply_id)
                or any(type(v) is not int or not 0<=v<=(1<<53)-1 for v in
                       (self.generation,self.ordinal,self.revision))
                or type(self.sequence_index) is not int or not 0<=self.sequence_index<=63
                or self.predecessor_frame is not None and type(self.predecessor_frame) is not FrameProvenance):
            raise ValueError('ordered_preparation_cursor')

    @property
    def next_ordinal(self):
        return self.ordinal  # Codec compatibility only; not an authoritative frontier.

    @property
    def last_frame(self):
        return self.predecessor_frame

    def to_wire(self):
        frame=self.predecessor_frame
        return dict(streamId=self.stream_id,generation=self.generation,replyId=self.reply_id,
            sequenceIndex=self.sequence_index,ordinal=self.ordinal,revision=self.revision,
            predecessorFrame=None if frame is None else dict(sourceId=frame.source_id,
                frame=frame.frame,sourceFrameCount=frame.source_frame_count))

    @classmethod
    def from_wire(cls,value):
        if type(value) is not dict or set(value)!={'streamId','generation','replyId','sequenceIndex','ordinal','revision','predecessorFrame'}:
            raise ValueError('ordered_preparation_cursor')
        frame=value['predecessorFrame']
        if frame is not None:
            if type(frame) is not dict or set(frame)!={'sourceId','frame','sourceFrameCount'}:
                raise ValueError('ordered_preparation_cursor')
            frame=FrameProvenance(frame['sourceId'],frame['frame'],frame['sourceFrameCount'])
        return cls(value['streamId'],value['generation'],value['replyId'],value['sequenceIndex'],
            value['ordinal'],value['revision'],frame)


@dataclass(frozen=True, slots=True)
class SourceTicket:
    plan_id: str
    origin: OutputFrontier
    cursor: PreparationCursor
    plan: object

    def __post_init__(self):
        if (not isinstance(self.plan_id,str) or not re.fullmatch('[a-f0-9]{32}',self.plan_id)
                or type(self.origin) is not OutputFrontier or type(self.cursor) is not PreparationCursor
                or (self.origin.stream_id,self.origin.generation,self.origin.reply_id)!=
                   (self.cursor.stream_id,self.cursor.generation,self.cursor.reply_id)
                or self.plan.kind!='speech' or self.plan.reply_id!=self.cursor.reply_id
                or self.plan.sequence_index!=self.cursor.sequence_index):
            raise ValueError('ordered_preparation_ticket')

    def to_wire(self):
        from .ordered_output_bridge import frontier_wire
        p=self.plan
        return dict(planId=self.plan_id,origin=frontier_wire(self.origin),cursor=self.cursor.to_wire(),
            plan=dict(kind=p.kind,sourceId=p.source_id,mediaId=p.media_id,samples=p.samples,
                wav=str(p.wav),replyId=p.reply_id,sequenceIndex=p.sequence_index,entryFadeMs=p.entry_fade_ms,
                frames=[dict(path=str(f.path),provenance=dict(sourceId=f.provenance.source_id,
                    frame=f.provenance.frame,sourceFrameCount=f.provenance.source_frame_count)) for f in p.frames]))

    @classmethod
    def from_wire(cls,value):
        from .ordered_output_bridge import parse_frontier
        from .ordered_output_encoding import OrderedSourcePlan
        if type(value) is not dict or set(value)!={'planId','origin','cursor','plan'}:
            raise ValueError('ordered_preparation_ticket')
        return cls(value['planId'],parse_frontier(value['origin']),
            PreparationCursor.from_wire(value['cursor']),OrderedSourcePlan.from_wire(value['plan']))


@dataclass(frozen=True, slots=True)
class PreparedClip:
    ticket: SourceTicket
    cursor: PreparationCursor
    output: object
    trim: object
    reservation: object

    def __post_init__(self):
        object.__setattr__(self,'trim',MappingProxyType(dict(self.trim)))


class _Reservation:
    __slots__=('budget','size','state','released')
    def __init__(self,budget,size,state):
        self.budget,self.size,self.state,self.released=budget,size,state,False


class PreparedBudget:
    def __init__(self,*,max_chunks=MAX_CHUNKS,max_bytes=MAX_BYTES):
        if (type(max_chunks) is not int or not 1<=max_chunks<=MAX_CHUNKS
                or type(max_bytes) is not int or not MAX_MEDIA_BYTES<=max_bytes<=MAX_BYTES):
            raise ValueError('ordered_prepared_limits')
        self.max_chunks,self.max_bytes=max_chunks,max_bytes
        self.condition=threading.Condition()
        self._tokens=set(); self._bytes=0;self.release_serial=0

    def _valid(self,token):
        if type(token) is not _Reservation or token.budget is not self:
            raise ValueError('ordered_prepared_reservation')

    def try_reserve(self):
        with self.condition:
            if len(self._tokens)>=self.max_chunks or self._bytes+MAX_MEDIA_BYTES>self.max_bytes:return None
            token=_Reservation(self,MAX_MEDIA_BYTES,'encoding')
            self._tokens.add(token); self._bytes+=token.size
            return token

    def retain(self,size,state='retained'):
        """Import already-owned media once, without reserving its maximum size."""
        if type(size) is not int or not 0<size<=MAX_MEDIA_BYTES or state not in ('retained','uncertain'):
            raise ValueError('ordered_prepared_import')
        with self.condition:
            if len(self._tokens)>=self.max_chunks or self._bytes+size>self.max_bytes:
                raise ValueError('ordered_prepared_import_capacity')
            token=_Reservation(self,size,state); self._tokens.add(token); self._bytes+=size
            return token

    def resize(self,token,actual_bytes):
        with self.condition:
            self._valid(token)
            if token.released or type(actual_bytes) is not int or not 0<actual_bytes<=token.size:
                raise ValueError('ordered_prepared_size')
            self._bytes+=actual_bytes-token.size; token.size=actual_bytes
            self.condition.notify_all()

    def transfer(self,token,state):
        with self.condition:
            self._valid(token)
            if token.released or state not in ('encoding','prepared','publishing','uncertain','retained'):
                raise ValueError('ordered_prepared_state')
            token.state=state

    def release(self,token):
        with self.condition:
            self._valid(token)
            if token.released:return
            self._tokens.remove(token); self._bytes-=token.size; token.released=True
            self.release_serial+=1
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            result=dict(chunks=len(self._tokens),bytes=self._bytes)
            for state in ('encoding','prepared','publishing','uncertain','retained'):
                result[state]=sum(t.state==state for t in self._tokens)
            return result


class PreparedClipBuffer:
    def __init__(self,budget):
        self.budget=budget; self._rows=deque(); self._stopped=False; self._done=False

    def reserve(self):
        with self.budget.condition:
            while not self._stopped:
                token=self.budget.try_reserve()
                if token is not None:return token
                self.budget.condition.wait()
            return None

    def put(self,clip):
        with self.budget.condition:
            if self._stopped or self._done:return False
            self.budget.transfer(clip.reservation,'prepared')
            self._rows.append(clip); self.budget.condition.notify_all()
            return True

    def take(self):
        with self.budget.condition:
            while not self._stopped:
                if self._rows:
                    clip=self._rows.popleft(); self.budget.transfer(clip.reservation,'publishing')
                    return clip
                if self._done:return None
                self.budget.condition.wait()
            return None

    def finish_input(self):
        with self.budget.condition:
            self._done=True; self.budget.condition.notify_all()

    def stop(self):
        with self.budget.condition:
            self._stopped=True; self.budget.condition.notify_all()

    def discard_private(self):
        while True:
            with self.budget.condition:
                if not self._rows:return
                clip=self._rows.popleft()
            try:clip.output.file.unlink(missing_ok=True)
            except BaseException:
                with self.budget.condition:self._rows.appendleft(clip)
                raise
            self.budget.release(clip.reservation)
