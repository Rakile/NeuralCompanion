"""Explicit chess-only sideband RPC; shares the existing worker's RelayAuth."""
import asyncio
import json


def validate_chess_rpc(message):
    if not isinstance(message,dict) or set(message)-{'jsonrpc','id','method','params'}:
        raise ValueError('Invalid chess RPC.')
    params=message.get('params',{})
    name=params.get('name','') if isinstance(params,dict) else ''
    if (message.get('jsonrpc')!='2.0' or message.get('method')!='tools/call'
            or not isinstance(message.get('id'),str) or not 1<=len(message['id'])<=128
            or set(params)-{'name','arguments','_meta'} or not isinstance(name,str)
            or not name.startswith(('chess_lobby_','chess_online_')) or len(name)>80
            or not isinstance(params.get('arguments',{}),dict)
            or len(json.dumps(message,allow_nan=False).encode())>65536):
        raise ValueError('Only explicit online chess tool calls are allowed.')
    meta=params.get('_meta',{})
    if not isinstance(meta,dict) or set(meta)-{'expectedAccount'} or not isinstance(meta.get('expectedAccount',''),str):
        raise ValueError('Invalid chess account binding.')
    return message


async def dispatch_chess_rpc(worker, message):
    request_id=message.get('request_id','')
    try:
        request=validate_chess_rpc(message.get('request'))
        if not worker.state.get('authenticated') or not worker.state.get('enabled'):
            raise RuntimeError('NC Relay is disconnected.')
        result=await asyncio.wait_for(worker.auth.authorized('/v1/chess/mcp',request),12)
        if not isinstance(result,dict): raise ValueError('Invalid chess response.')
        worker.emit(dict(kind='chess_response',request_id=request_id,result=result))
    except Exception:
        worker.emit(dict(kind='chess_response',request_id=request_id,error='Online chess unavailable. Reconnect and retry the same operation.'))
