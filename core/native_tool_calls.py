"""JSON codecs for native tool rounds; no client, credentials or execution ownership."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json

from core.conversation_tools import ToolCall, ToolRound, plain_json

PROTOCOLS=frozenset({'responses','chat_completions','anthropic','openai'})
CONTINUATION='_nc_native_tool_continuation'


def provider_protocol(provider):
    value=(getattr(provider,'metadata',None) or {}).get('native_tool_protocol_v1','')
    return value if isinstance(value,str) and value in PROTOCOLS else ''


def prompt_payload(params,protocol):
    payload=params.get('lmstudio_responses_payload',params)
    if not isinstance(payload,dict): raise ValueError('Invalid frozen native tool payload.')
    actual=('responses' if 'input' in payload else 'chat_completions') if protocol=='openai' else protocol
    if actual not in PROTOCOLS: raise ValueError('Provider has no declared native tool protocol.')
    key='input' if actual=='responses' else 'messages'
    messages=payload.get(key)
    if not isinstance(messages,list): raise ValueError('Native tools require prepared message history.')
    return payload,messages,actual


def add_instruction(payload,messages,instruction,protocol,*,replace=False,user_text=''):
    if protocol=='anthropic':
        if replace:
            payload['system']=instruction; messages[:]=[dict(role='user',content=user_text)]
        elif isinstance(payload.get('system'),list):
            payload['system'].append(dict(type='text',text=instruction))
        else: payload['system']=str(payload.get('system') or '')+'\n'+instruction
    elif replace: messages[:]=[dict(role='system',content=instruction),dict(role='user',content=user_text)]
    elif messages and messages[0].get('role') in {'system','developer'} and isinstance(messages[0].get('content'),str):
        messages[0]['content']+='\n'+instruction
    else: messages.insert(0,dict(role='system',content=instruction))


def _json(value):
    if hasattr(value,'model_dump'):value=value.model_dump(exclude_none=True)
    if isinstance(value,Mapping):return {k:_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_json(v) for v in value]
    if hasattr(value,'__dict__'):return _json(vars(value))
    return plain_json(value)


def _image(part,protocol):
    if part.get('type')=='input_text':return dict(type='text',text=part['text'])
    if part.get('type')=='input_image':
        url=part['image_url']
        if protocol=='chat_completions':return dict(type='image_url',image_url=dict(url=url))
        if not isinstance(url,str) or not url.startswith('data:') or ';base64,' not in url:
            raise ValueError('Claude inspection requires a base64 image.')
        media,data=url[5:].split(';base64,',1)
        return dict(type='image',source=dict(type='base64',media_type=media,data=data))
    raise ValueError('Unsupported tool-loop message content.')


def build_payload(params,options,protocol):
    payload=plain_json(params);options=plain_json(options)
    if (set(options) not in ({'tools','input'},{'tools','input','final_only'}) or
            not isinstance(options['tools'],list) or not isinstance(options['input'],list) or
            type(options.get('final_only',False)) is not bool):raise ValueError('Invalid native tool options.')
    _,messages,protocol=prompt_payload(payload,protocol)
    if any(key in payload for key in ('tools','response_format','output_format','output_config')) or (
            isinstance(payload.get('text'),dict) and 'format' in payload['text']):
        raise ValueError('Native tools cannot override existing structured output or tools.')
    definitions=[]
    for tool in options['tools']:
        if (not isinstance(tool,dict) or tool.get('type')!='function' or not isinstance(tool.get('name'),str)
                or not isinstance(tool.get('parameters'),dict)):raise ValueError('Invalid function schema.')
        if protocol=='responses':definitions.append(dict(tool,strict=False))
        elif protocol=='anthropic':definitions.append(dict(name=tool['name'],description=tool.get('description',''),input_schema=tool['parameters']))
        else:definitions.append(dict(type='function',function=dict(name=tool['name'],description=tool.get('description',''),parameters=tool['parameters'])))
    final=options.get('final_only',False) or not definitions
    if definitions:payload['tools']=definitions
    if protocol=='anthropic':
        # With no definitions, omit tool_choice too. This works on older Messages endpoints.
        if definitions:payload['tool_choice']=dict(type='none' if final else 'auto')
    elif protocol!='chat_completions' or definitions:payload['tool_choice']='none' if final else 'auto'
    payload['stream']=False
    for item in options['input']:
        kind=item.get('type')
        if kind==CONTINUATION:
            if item.get('protocol')!=protocol:raise ValueError('Native continuation protocol changed.')
            native=deepcopy(item['payload'])
            if protocol=='responses':messages.extend(native)
            else:messages.append(dict(role='assistant',**({'content':native} if protocol=='anthropic' else native)))
        elif kind=='function_call_output':
            if protocol=='responses':messages.append(item)
            elif protocol=='chat_completions':messages.append(dict(role='tool',tool_call_id=item['call_id'],content=item['output']))
            else:
                result=dict(type='tool_result',tool_use_id=item['call_id'],content=item['output'])
                if messages and messages[-1].get('role')=='user' and isinstance(messages[-1].get('content'),list) and all(
                        b.get('type')=='tool_result' for b in messages[-1]['content']):messages[-1]['content'].append(result)
                else:messages.append(dict(role='user',content=[result]))
        elif kind=='function_call':
            # Legacy LM-style canonical calls are valid Responses input only.
            if protocol!='responses':raise ValueError('Missing provider-native assistant continuation.')
            messages.append(item)
        elif item.get('role')=='user':
            content=item.get('content')
            if protocol!='responses' and isinstance(content,list):content=[_image(part,protocol) for part in content]
            messages.append(dict(role='user',content=content))
        else:raise ValueError('Unsupported native tool-loop item.')
    return payload


def extract_round(response,protocol):
    value=_json(response)
    if not isinstance(value,dict):raise ValueError('Invalid native model response.')
    calls=[];text=[]
    def call(identity,name,arguments):
        if (not all(isinstance(v,str) and v for v in (identity,name)) or not isinstance(arguments,str)
                or identity in {c.call_id for c in calls}):raise ValueError('Invalid native call identity.')
        calls.append(ToolCall(identity,name,arguments))
    if protocol=='responses':
        if (value.get('incomplete_details') or {}).get('reason')=='max_output_tokens':
            raise ValueError('Model output token limit reached.')
        if value.get('status','completed')!='completed' or value.get('error') or not isinstance(value.get('output'),list):
            raise ValueError('Incomplete native Responses output.')
        native=[]
        for item in value['output']:
            if not isinstance(item,dict):raise ValueError('Invalid native Responses item.')
            kind=item.get('type')
            if kind=='function_call':
                if item.get('status','completed')!='completed':raise ValueError('Incomplete function call.')
                call(item.get('call_id'),item.get('name'),item.get('arguments'));native.append(item)
            elif kind=='reasoning':native.append(item)
            elif kind=='message':
                if item.get('role','assistant')!='assistant' or item.get('status','completed')!='completed':raise ValueError('Invalid assistant message.')
                for block in item.get('content',[]):
                    if block.get('type')=='output_text' and isinstance(block.get('text'),str):text.append(block['text'])
                    elif block.get('type')=='refusal' and isinstance(block.get('refusal'),str):text.append(block['refusal'])
                    else:raise ValueError('Unsupported assistant output.')
                native.append(item)  # Protocol continuation only; never displayed or spoken.
            else:raise ValueError('Unsupported native Responses item.')
    elif protocol=='chat_completions':
        choices=value.get('choices')
        if not isinstance(choices,list) or len(choices)!=1:raise ValueError('Expected one native completion choice.')
        choice=choices[0]
        if not isinstance(choice,dict):raise ValueError('Invalid native completion choice.')
        if choice.get('finish_reason')=='length':raise ValueError('Model output token limit reached.')
        if choice.get('finish_reason') not in {'stop','tool_calls'}:raise ValueError('Incomplete native completion.')
        message=choice.get('message')
        if not isinstance(message,dict) or message.get('role','assistant')!='assistant':raise ValueError('Invalid assistant message.')
        content=message.get('content')
        if content is not None and not isinstance(content,str):raise ValueError('Unsupported assistant content.')
        text.append(content or str(message.get('refusal') or ''))
        native=dict(content=content or '')
        if message.get('reasoning_content') is not None:
            if not isinstance(message['reasoning_content'],str):raise ValueError('Invalid reasoning continuation.')
            native['reasoning_content']=message['reasoning_content']
        rawcalls=message.get('tool_calls') or []
        if not isinstance(rawcalls,list):raise ValueError('Invalid native tool call list.')
        for item in rawcalls:
            if not isinstance(item,dict) or not isinstance(item.get('function'),dict):raise ValueError('Invalid native function call.')
            if item.get('type')!='function':raise ValueError('Unsupported tool call type.')
            function=item.get('function',{})
            call(item.get('id'),function.get('name'),function.get('arguments'))
        if rawcalls:native['tool_calls']=rawcalls
    elif protocol=='anthropic':
        if value.get('stop_reason')=='max_tokens':raise ValueError('Model output token limit reached.')
        if value.get('stop_reason') not in {'end_turn','tool_use','stop_sequence','refusal'} or not isinstance(value.get('content'),list):
            raise ValueError('Incomplete native Messages response.')
        native=value['content']
        for block in native:
            if not isinstance(block,dict):raise ValueError('Invalid native Messages block.')
            kind=block.get('type')
            if kind=='tool_use':
                if not isinstance(block.get('input'),dict):raise ValueError('Tool input must be an object.')
                call(block.get('id'),block.get('name'),json.dumps(block['input'],allow_nan=False))
            elif kind=='text' and isinstance(block.get('text'),str):text.append(block['text'])
            elif kind not in {'thinking','redacted_thinking'}:raise ValueError('Unsupported Messages content.')
    else:raise ValueError('Unknown native tool protocol.')
    output=(dict(type=CONTINUATION,protocol=protocol,payload=native),) if calls else ()
    return ToolRound(''.join(text).strip(),tuple(calls),output)


def continuation_items(response):
    """Accept only a codec's explicit envelope; legacy rounds retain canonical calls."""
    wrappers=[item for item in response.output if item.get('type')==CONTINUATION]
    if not wrappers:return [dict(type='function_call',call_id=c.call_id,name=c.name,arguments=c.arguments) for c in response.calls]
    if len(wrappers)!=1 or len(response.output)!=1:raise ValueError('Invalid native continuation envelope.')
    wrapper=wrappers[0];protocol=wrapper.get('protocol');native=wrapper.get('payload')
    if protocol=='responses':parsed=extract_round(dict(output=native),'responses')
    elif protocol=='chat_completions':parsed=extract_round(dict(choices=[dict(finish_reason='tool_calls',message=native)]),protocol)
    elif protocol=='anthropic':parsed=extract_round(dict(stop_reason='tool_use',content=native),protocol)
    else:raise ValueError('Invalid native continuation protocol.')
    if parsed.calls!=response.calls:raise ValueError('Native continuation does not match accepted calls.')
    return [deepcopy(wrapper)]


def trace_options(additional):
    from core.conversation_tools import TOOL_OPTION
    if TOOL_OPTION not in additional:return additional
    result=dict(additional);options=deepcopy(result[TOOL_OPTION])
    options['input']=[dict(type=CONTINUATION,protocol=item.get('protocol'),payload='[private continuation omitted]')
        if item.get('type')==CONTINUATION else item for item in options.get('input',[])]
    result[TOOL_OPTION]=options
    return result


def trace_response(raw):
    from core.conversation_tools import decode_tool_round,encode_tool_round
    try:
        round=decode_tool_round(raw)
        return encode_tool_round(ToolRound(round.text,round.calls,()))
    except (ValueError,TypeError,KeyError):return '[invalid native tool response omitted]'
