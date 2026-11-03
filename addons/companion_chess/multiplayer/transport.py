"""Private relay-to-MCP HTTP boundary. Never expose this listener publicly."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
from uuid import UUID

from jsonschema import Draft202012Validator
from .store import FIELDS, READ_TOOLS, OnlineError, OnlineStore


PROPERTIES = {
    'search': dict(type='string',maxLength=64), 'offset': dict(type='integer',minimum=0,maximum=100000),
    'enabled': dict(type='boolean'), 'accept': dict(type='boolean'),
    'side': dict(type='string',enum=['white','black','either']),
    'action': dict(type='string',enum=['offer','accept','decline','claim']),
    'uci': dict(type='string',pattern='^[a-h][1-8][a-h][1-8][qrbn]?$'),
    'expected_revision': dict(type='integer',minimum=0),
    **{k:dict(type='string',minLength=1,maxLength=160) for k in ('player_id','challenge_id','match_id','code','operation_id')},
}
OPTIONAL = {'side','search','offset'}
TOOLS = []
for name, fields in FIELDS.items():
    keys = fields | ({'operation_id'} if name not in READ_TOOLS else set())
    TOOLS.append(dict(name=name,description='Online chess: '+name.replace('chess_','').replace('_',' ')+'. Host user action only; never give write tools to a commentator.',
                      inputSchema=dict(type='object',properties={key:PROPERTIES[key] for key in sorted(keys)},
                                       required=sorted(keys-OPTIONAL),additionalProperties=False)))


class OnlineMcpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, store: OnlineStore, gateway_key: str, *, private_container_network=False):
        if address[0]!='127.0.0.1' and not (address[0]=='0.0.0.0' and private_container_network):
            raise ValueError('Public binding requires an explicit private-container network; never publish its port.')
        if len(gateway_key)<32: raise ValueError('A private gateway key of at least 32 characters is required.')
        self.store, self.gateway_key = store, gateway_key
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request,client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request,client_address)
        finally: self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server: OnlineMcpServer
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args): pass

    def reply(self, status, body):
        raw=json.dumps(body,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.reply(200 if self.path=='/health' else 404,dict(service='companion-chess-online'))

    def do_POST(self):
        self.close_connection=True
        if self.path!='/mcp': self.reply(404,{}); return
        token=self.headers.get('Authorization','')
        if not secrets.compare_digest(token.encode(),('Bearer '+self.server.gateway_key).encode()):
            self.reply(401,{}); return
        actor=self.headers.get('X-NC-Account',''); name=self.headers.get('X-NC-Username','')
        try:
            UUID(actor)
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{2,31}',name): raise ValueError()
            length=int(self.headers.get('Content-Length','0'))
            if self.headers.get('Transfer-Encoding') or not 0<length<=65536: raise ValueError()
            message=json.loads(self.rfile.read(length))
            if not isinstance(message,dict) or message.get('jsonrpc')!='2.0': raise ValueError()
        except (ValueError,UnicodeError,TimeoutError): self.reply(400,{}); return
        rid=message.get('id')
        if rid is None: self.reply(202,{}); return
        method=message.get('method')
        if method=='initialize':
            result=dict(protocolVersion='2025-06-18',capabilities=dict(tools={}),serverInfo=dict(name='companion-chess-online',version='1.0.0'))
        elif method=='ping': result={}
        elif method=='tools/list': result=dict(tools=TOOLS)
        elif method=='tools/call':
            try:
                params=message.get('params',{})
                if not isinstance(params,dict): raise OnlineError('Invalid tool call.')
                tool=next((t for t in TOOLS if t['name']==params.get('name')),None)
                args=params.get('arguments',{})
                if not tool or next(Draft202012Validator(tool['inputSchema']).iter_errors(args),None):
                    raise OnlineError('Arguments do not match the tool schema.')
                args=dict(args); operation=args.pop('operation_id','')
                value=self.server.store.execute(actor,name,tool['name'],args,operation_id=operation)
                result=dict(content=[dict(type='text',text=json.dumps(value))],structuredContent=value,isError=False)
            except OnlineError as exc: result=dict(content=[dict(type='text',text=str(exc))],isError=True)
            except Exception: result=dict(content=[dict(type='text',text='Online service unavailable; retry the same operation ID.')],isError=True)
        else:
            self.reply(200,dict(jsonrpc='2.0',id=rid,error=dict(code=-32601,message='Method not found')))
            return
        self.reply(200,dict(jsonrpc='2.0',id=rid,result=result))
