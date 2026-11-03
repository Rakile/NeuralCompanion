"""Desktop-authored speculative source chain, never a publication ledger."""
from collections import OrderedDict
from copy import deepcopy
import secrets
import re

from .ordered_prepared import PreparationCursor
from .output_sequence import FrameProvenance


class DesktopSourcePreparation:
    def __init__(self,binding):
        self.binding=binding; self.invalidate()

    def invalidate(self):
        self.origin=None; self.reply=None; self._rows=OrderedDict()
        self._successors={}; self._last=None; self._encoded_through=-1

    def _status(self,reply):
        status=self.binding.protocol.registry.status(self.binding._auth,reply)
        if status['phase'] in ('cancelled','expired','superseded') or status.get('playback_stop_requested'):
            raise ValueError('ordered_reply_cancelled')
        return status

    def acquire(self,after_plan_id):
        from .ordered_output_bridge import frontier_wire
        if after_plan_id is not None and (type(after_plan_id) is not str
                or not re.fullmatch('[a-f0-9]{32}',after_plan_id)):
            raise ValueError('ordered_preparation_cursor')
        b=self.binding; current=b.sequence.frontier()
        if self.origin is not None:
            if current.generation!=self.origin.generation or current.reply_id!=self.reply:
                raise ValueError('ordered_preparation_stale')
            status=self._status(self.reply)
        else:
            if after_plan_id is not None:raise ValueError('ordered_preparation_cursor')
            anchor=b._render_anchor
            if anchor is None:return dict(state='waiting',stage='audio',sequenceIndex=0)
            self.reply=anchor.reply_id; status=self._status(self.reply)
        if after_plan_id in self._successors:
            row=self._rows.get(self._successors[after_plan_id])
            if row is None or row['ticket']['plan'] is None:raise ValueError('ordered_preparation_consumed')
            return dict(state='ready',ticket=deepcopy(row['ticket']))
        if after_plan_id!=self._last:raise ValueError('ordered_preparation_cursor')
        previous=self._rows.get(after_plan_id)
        index=0 if previous is None else previous['index']+1
        if status['phase']=='complete' and (status['last_sequence_index'] is None
                or index>status['last_sequence_index']):
            return dict(state='complete',replyId=self.reply,generation=current.generation,
                lastSequenceIndex=status['last_sequence_index'])
        if index>63:raise ValueError('ordered_preparation_source_limit')
        # Remove settled compact records, retaining the immediate preparation tail.
        for key,row in tuple(self._rows.items()):
            if key!=self._last and row['encoded'] and row['end'].ordinal<=current.next_ordinal:
                del self._rows[key]
                self._successors={k:v for k,v in self._successors.items() if k!=key and v!=key}
        if sum(row['ticket']['plan'] is not None for row in self._rows.values())>=3 or len(self._rows)>=63:
            return dict(state='waiting',stage='preparation_capacity',sequenceIndex=index)
        if current.next_ordinal==0:return dict(state='waiting',stage='initial_visual',sequenceIndex=index)
        if b._speech_source is None:raise ValueError('ordered_speech_source_unavailable')
        plan_result=b._speech_source.plan(b._render_anchor,index)
        if plan_result['state']=='waiting':
            b._observe_preparation(plan_result['stage'],current,index)
            return plan_result
        if plan_result['state']!='ready':raise ValueError('ordered_speech_plan_state')
        plan=plan_result['plan']
        if index==0:
            if current.reply_id is None:
                result=b._admit_first_source(current,plan_result)
                from .ordered_output_bridge import parse_frontier
                current=parse_frontier(result['frontier']); plan=result['plan']
            else:
                if b.sequence.next_speech_sequence(current)!=0:raise ValueError('ordered_preparation_already_published')
                plan=b._transition_plan(plan,current)
            self.origin=current
            cursor=PreparationCursor(current.stream_id,current.generation,self.reply,0,
                current.next_ordinal,current.revision,current.last_frame)
        else:
            end=previous['end']
            cursor=PreparationCursor(end.stream_id,end.generation,end.reply_id,index,
                end.ordinal,end.revision,end.predecessor_frame)
            plan=b._transition_plan(plan,cursor,previous_kind='speech')
            b._observe_preparation('ready',current,index)
        frames=plan['frames']; last=frames[-1]['provenance']; chunks=(len(frames)+11)//12
        end=PreparationCursor(cursor.stream_id,cursor.generation,cursor.reply_id,index,
            cursor.ordinal+chunks,cursor.revision+chunks,
            FrameProvenance(last['sourceId'],last['frame'],last['sourceFrameCount']))
        plan_id=secrets.token_hex(16)
        ticket=dict(planId=plan_id,origin=frontier_wire(self.origin),cursor=cursor.to_wire(),plan=deepcopy(plan))
        self._rows[plan_id]=dict(ticket=ticket,end=end,index=index,encoded=False)
        self._successors[after_plan_id]=plan_id; self._last=plan_id
        return dict(state='ready',ticket=deepcopy(ticket))

    def release_private(self,plan_id,disposition):
        if type(plan_id) is not str or not re.fullmatch('[a-f0-9]{32}',plan_id):
            raise ValueError('ordered_preparation_cursor')
        row=self._rows.get(plan_id)
        if row is None:raise ValueError('ordered_preparation_cursor')
        if disposition=='discarded':
            # No surviving suffix may pretend its discarded predecessor exists.
            self.invalidate(); return
        if disposition!='encoded':raise ValueError('ordered_preparation_disposition')
        if row['encoded']:return
        if row['index']!=self._encoded_through+1:raise ValueError('ordered_preparation_release_order')
        row['encoded']=True; row['ticket']['plan']=None
        self._encoded_through=row['index']
