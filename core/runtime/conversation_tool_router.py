"""Compose optional native tool owners without mixing their authority."""
from dataclasses import asdict
import threading
from uuid import uuid4

from core.conversation_tools import ToolOutcome


class ConversationToolRouter:
    def __init__(self,orb,mcp):
        self.orb,self.mcp=orb,mcp
        self._lock=threading.RLock()
        self._tickets={}

    def __call__(self,operation,fields):
        if operation=='offer':
            sources=[]; tools=[]; aliases={}; mcp_model_unsupported=False
            for kind,callback in (('orb',self.orb if fields.get('orb_enabled') else None),('mcp',self.mcp)):
                if callback is None: continue
                offer=callback('offer',fields)
                if not offer or not offer.get('available'): continue
                if kind=='mcp' and fields.get('model_supports_tools') is False:
                    mcp_model_unsupported=bool(offer.get('tools'))
                    continue
                source=(kind,callback,offer['ticket'],offer)
                for tool in offer['tools']:
                    if tool['name'] in aliases: raise ValueError('Native tool alias collision.')
                    aliases[tool['name']]=source
                    tools.append(tool)
                sources.append(source)
            if not sources: return dict(available=False,mcp_model_unsupported=mcp_model_unsupported)
            ticket=uuid4().hex
            with self._lock:
                self._tickets[ticket]=(sources,aliases)
                while len(self._tickets)>32: self._tickets.pop(next(iter(self._tickets)))
            return dict(available=True,ticket=ticket,tools=tools,
                context='\n'.join(source[3]['context'] for source in sources),
                orb=any(source[0]=='orb' for source in sources),mcp=any(source[0]=='mcp' for source in sources),
                mcp_model_unsupported=mcp_model_unsupported)
        with self._lock: item=self._tickets.get(fields.get('ticket'))
        if item is None: return dict(current=False) if operation=='current' else None
        sources,aliases=item
        states=[callback('current',dict(ticket=ticket)) or {} for _,callback,ticket,_ in sources]
        valid=all(state.get('current') for state in states)
        if operation=='current':
            return dict(current=valid,watches=next((state.get('watches',[]) for source,state in zip(sources,states)
                                                   if source[0]=='orb'),[]))
        if operation=='execute':
            call=fields['call']; source=aliases.get(call['name'])
            if not valid or source is None:
                return asdict(ToolOutcome(call['call_id'],False,dict(error='Tool request is stale or was not offered.'),
                    'Tool request is stale or was not offered.'))
            return source[1]('execute',dict(ticket=source[2],call=call))
        if operation=='publish' and valid:
            # Each owner retains its own publication guard (including Orb's lock).
            publish=fields['publish']
            for _,callback,ticket,_ in reversed(sources):
                downstream=publish
                publish=lambda cb=callback,t=ticket,fn=downstream:cb('publish',dict(ticket=t,publish=fn))
            return publish()
        return None
