"""Typed native streaming: user answer deltas plus one validated terminal round."""
from __future__ import annotations

import json

from core.conversation_tools import decode_tool_round,encode_tool_round,strict_arguments
from core.native_tool_calls import _json,extract_round,trace_response


class AnswerPrefixFilter:
    """Hold only an ambiguous prefix, so split legacy tool markup stays silent."""
    def __init__(self):
        self.pending='';self.decided=False;self.blocked=False

    def feed(self,text):
        if self.blocked:return ''
        if self.decided:return text
        self.pending+=text
        prefix=self.pending.lstrip()
        if not prefix or '<tool_call>'.startswith(prefix):return ''
        if prefix.startswith('<tool_call>'):
            self.blocked=True;self.pending='';return ''
        self.decided=True
        text=self.pending;self.pending=''
        return text


def _event(kind,value):
    return json.dumps(dict(version=1,type=kind,value=value),ensure_ascii=False,allow_nan=False)


def decode_event(raw):
    value=strict_arguments(raw)
    if set(value)!={'version','type','value'} or type(value['version']) is not int or value['version']!=1 or not isinstance(value['value'],str):
        raise ValueError('Invalid native stream frame.')
    if value['type']=='text':return 'text',value['value']
    if value['type']=='round':return 'round',decode_tool_round(value['value'])
    raise ValueError('Unknown native stream frame.')


def trace_event(raw):
    try:
        kind,value=decode_event(raw)
        if kind=='text':return raw
        return _event('round',trace_response(encode_tool_round(value)))
    except (ValueError,TypeError,KeyError):return '[invalid native stream frame omitted]'


def sse_events(lines):
    data=[]
    for raw in lines:
        line=raw.decode('utf-8') if isinstance(raw,bytes) else raw
        line=line.rstrip('\r\n')
        if not line:
            if data:
                body='\n'.join(data);data=[]
                if body=='[DONE]':return
                yield json.loads(body)
        elif line.startswith('data:'):data.append(line[5:].lstrip())
    if data and '\n'.join(data)!='[DONE]':yield json.loads('\n'.join(data))


def stream_events(events,protocol):
    """Never expose tool argument/thinking deltas as answer text."""
    text=[];calls={};blocks={};arguments={};finish=None;completed=None
    for event in events:
        event=_json(event)
        if not isinstance(event,dict):raise ValueError('Invalid native stream event.')
        if event.get('type')=='error':
            from core.provider_limits import limit_message
            raise ValueError(limit_message((event.get('error') or {}).get('message','')) or 'Invalid native stream event.')
        if protocol=='responses':
            kind=event.get('type')
            if kind=='response.output_text.delta':
                delta=event.get('delta')
                if not isinstance(delta,str):raise ValueError('Invalid answer delta.')
                yield _event('text',delta)
            elif kind=='response.completed':
                completed=extract_round(event.get('response'),protocol);break
            elif kind in {'response.failed','response.incomplete'}:
                response=event.get('response') or {}
                from core.provider_limits import limit_message
                reason=(response.get('incomplete_details') or {}).get('reason','')
                error=(response.get('error') or {}).get('message','')
                raise ValueError(limit_message(reason or error) or 'Native response did not complete.')
        elif protocol=='chat_completions':
            choices=event.get('choices',[])
            if not choices:continue  # Optional usage-only event.
            if len(choices)!=1:raise ValueError('Expected one streaming choice.')
            choice=choices[0];delta=choice.get('delta') or {}
            if delta.get('content') is not None:
                if not isinstance(delta['content'],str):raise ValueError('Invalid answer delta.')
                text.append(delta['content']);yield _event('text',delta['content'])
            if delta.get('reasoning_content') is not None:
                blocks['reasoning_content']=blocks.get('reasoning_content','')+delta['reasoning_content']
            for part in delta.get('tool_calls') or []:
                index=part.get('index')
                if type(index) is not int or not 0<=index<32:raise ValueError('Invalid streaming tool index.')
                item=calls.setdefault(index,dict(id='',type='function',function=dict(name='',arguments='')))
                if part.get('type','function')!='function':raise ValueError('Unsupported streaming tool.')
                item['id']+=part.get('id') or ''
                function=part.get('function') or {}
                for key in ('name','arguments'):item['function'][key]+=function.get(key) or ''
            if choice.get('finish_reason') is not None:
                finish=choice['finish_reason'];break
        elif protocol=='anthropic':
            kind=event.get('type')
            if kind=='content_block_start':
                index=event['index']
                if type(index) is not int or not 0<=index<64 or index in blocks:raise ValueError('Invalid content block index.')
                blocks[index]=event['content_block']
            elif kind=='content_block_delta':
                index=event['index'];block=blocks[index];delta=event['delta'];delta_kind=delta['type']
                if delta_kind=='text_delta':
                    block['text']=block.get('text','')+delta['text'];yield _event('text',delta['text'])
                elif delta_kind=='input_json_delta':arguments[index]=arguments.get(index,'')+delta['partial_json']
                elif delta_kind=='thinking_delta':block['thinking']=block.get('thinking','')+delta['thinking']
                elif delta_kind=='signature_delta':block['signature']=block.get('signature','')+delta['signature']
                else:raise ValueError('Unsupported native content delta.')
            elif kind=='message_delta':finish=event.get('delta',{}).get('stop_reason') or finish
            elif kind=='message_stop':
                for index,raw in arguments.items():blocks[index]['input']=strict_arguments(raw)
                completed=extract_round(dict(stop_reason=finish,content=[blocks[i] for i in sorted(blocks)]),protocol);break
        else:raise ValueError('Unknown native streaming protocol.')
    if protocol=='chat_completions' and finish is not None:
        message=dict(role='assistant',content=''.join(text),**blocks)
        if calls:message['tool_calls']=[calls[i] for i in sorted(calls)]
        completed=extract_round(dict(choices=[dict(finish_reason=finish,message=message)]),protocol)
    if completed is None:raise ValueError('Native stream ended before a completed response.')
    yield _event('round',encode_tool_round(completed))
