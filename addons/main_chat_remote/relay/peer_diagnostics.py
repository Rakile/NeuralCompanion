"""Failure-only peer evidence. No request bodies, credentials or exception text."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
import socket
import time
import urllib.error

from core.diagnostics.plan_trace import current_operation

_request = ContextVar('peer_failure_stage', default=None)
_STAGES = frozenset(('request.classify','request.buffered','request.state','request.av',
    'request.forward','request.arm','request.cancel','bridge.path','bridge_info.read',
    'bridge_info.parse','bridge_info.identity','bridge.client','bridge.body','bridge_http.build',
    'bridge_http.open','bridge_http.read','bridge_http.metadata','bridge_http.error_read',
    'bridge.response_size','bridge.health','response.observe','response.idle','response.decode',
    'response.send','response.file_start','response.file_chunk','response.file_end'))
_MODULES = frozenset(('addons.main_chat_remote.relay.peer','addons.main_chat_remote.remote_backend',
    'json','json.decoder','urllib.request','urllib.error','http.client','socket','ssl','pathlib',
    'asyncio.tasks','asyncio.threads','concurrent.futures.thread'))
_TYPES = (json.JSONDecodeError, urllib.error.HTTPError, urllib.error.URLError,
    PermissionError, FileNotFoundError, ConnectionRefusedError, ConnectionResetError,
    ConnectionAbortedError, BrokenPipeError, TimeoutError, OSError, ValueError, TypeError,
    KeyError, RuntimeError, AssertionError, ConnectionError, socket.gaierror, socket.herror)


@contextmanager
def request_scope():
    # to_thread copies this context; its mutable stage belongs to just this
    # request, not the peer (which serves concurrent wait/media/ACK requests).
    token=_request.set(dict(stage='request.classify',started=time.monotonic()))
    try:yield
    finally:_request.reset(token)


def mark(stage):
    state=_request.get()
    if state is not None and stage in _STAGES:state['stage']=stage


def _kind(error):
    return next((kind.__name__ for kind in _TYPES if type(error) is kind),'other')


def record_failure(trace,key,msg,error):
    """Best effort only: even a broken sink cannot suppress the original 502."""
    try:
        state=_request.get() or {};stage=state.get('stage','request.classify')
        path=msg.get('path');operation='other'
        if type(path) is str:
            operation=next((name for name in ('open','recover','wait','ack','close','halt','restart','started')
                if path=='/api/remote-output/'+name),'other')
        parent=current_operation()
        operation_id=parent['operation_id'] if parent else key+':handler'
        frames=[];tb=error.__traceback__
        while tb is not None:
            module=tb.tb_frame.f_globals.get('__name__');function=tb.tb_frame.f_code.co_name
            if module in _MODULES and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',function):
                frames.append(dict(module=module,function=function,line=tb.tb_lineno))
            tb=tb.tb_next
        cause=error.reason if isinstance(error,urllib.error.URLError) else error.__cause__
        facts={'operation':operation}
        for prefix,value in (('',error),('cause_',cause)):
            if not isinstance(value,BaseException):continue
            if prefix:facts['cause_type']=_kind(value)
            for name in ('errno','winerror'):
                number=getattr(value,name,None)
                if type(number) is int and -2147483648<=number<=2147483647:facts[prefix+name]=number
        # Small failure-only facts first, error marker last for protected capture.
        for name,value in facts.items():
            trace.observe(key,'backend.peer.handler.failure',name,None,value)
        trace.emitter.emit(dict(level='error',event_name='transaction.operation',
            trace_id=key,operation_id=operation_id,parent_operation_id=None,
            phase='decision',outcome='observed',basis='observed',links=[],context={'session_id':key},
            data=dict(site='backend.peer.handler.failure',condition=stage,expected=True,actual=False,
                exception_type=_kind(error),frames=frames[-8:],state_before=operation,
                duration_ms=round(max(0,time.monotonic()-state.get('started',time.monotonic()))*1000))))
    except Exception:pass
