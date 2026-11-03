"""Bounded loopback MCP Streamable HTTP (JSON response mode, no event stream)."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
from uuid import uuid4

from jsonschema import Draft202012Validator
from .game import Game, ChessError


def _string(maximum: int = 256) -> dict:
    return {'type':'string','maxLength':maximum}


MUTATION = {'game_id':_string(64), 'expected_revision':{'type':'integer','minimum':0}, 'operation_id':_string(160)}


def _tool(name: str, description: str, fields: dict, required: list[str], mutation: bool = False) -> dict:
    return dict(name=name, description=description, inputSchema=dict(type='object',
                properties={**(MUTATION if mutation else {}), **fields},
                required=(list(MUTATION) if mutation else [])+required, additionalProperties=False))


TOOLS = [
    _tool('chess_get_state','Read the authoritative chess board. Does not reveal private turn tickets.',{},[]),
    _tool('chess_game_control','Desktop controls only. Apply one explicit game or physical-board action.',{
        'action':{'type':'string','enum':['new','move','pause','resume','takeback','resign','end','hardware','reconcile','physical','continue_desktop']},
        'human':{'type':'string','enum':['white','black']}, 'fen':_string(128), 'uci':_string(5),
        'persona_id':_string(128),'enabled':{'type':'boolean'},'square':{'type':'string','pattern':'^[a-h][1-8]$'},
        'engine_path':_string(2048),'skill':{'type':'integer','minimum':0,'maximum':20}},['action'],True),
    _tool('chess_prepare_turn','Desktop only. Prepare a turn for the selected persona; engine work runs in the background.',
          {'persona_id':_string(128)},['persona_id'],True),
    _tool('chess_get_candidates','Read engine candidates for the exact private turn ticket supplied by the host.',
          {'ticket':_string(128)},['ticket']),
    _tool('chess_choose_move','Choose exactly one offered candidate. Returns a pending move; never confirms physical movement.',
          {'ticket':_string(128),'candidate_id':_string(5)},['ticket','candidate_id'],True),
    _tool('chess_finalize_move','Desktop only. Acknowledge queued or explicitly skipped speech before digital/physical completion.',
          {'announcement':{'type':'string','enum':['queued','skipped']}},['announcement'],True),
    _tool('chess_get_operation','Desktop only. Resolve an uncertain operation by its original ID.',
          {'operation_id':_string(160)},['operation_id']),
]


class ChessHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str,int], game: Game, token: str, installation_id: str):
        if address[0] != '127.0.0.1': raise ValueError('Companion Chess only listens on IPv4 loopback.')
        if len(token) < 32: raise ValueError('A strong bearer credential is required.')
        self.game, self.token = game, token
        self.identity = dict(service='companion-chess', protocol=1, installation_id=installation_id, instance_id=uuid4().hex)
        self._slots = threading.BoundedSemaphore(16)
        super().__init__(address, _Handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self._slots.release()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server: ChessHttpServer

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def _reply(self, status: int, body: object = None) -> None:
        encoded = b'' if body is None else json.dumps(body,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(encoded)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        try: self.wfile.write(encoded)
        except (BrokenPipeError,ConnectionError): pass

    def _authorized(self) -> bool:
        expected = 'Bearer '+self.server.token
        if not secrets.compare_digest(self.headers.get('Authorization',''),expected):
            self._reply(401)
            return False
        if self.headers.get('Origin') or self.headers.get('Host') not in {
            f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
            self._reply(403)
            return False
        return True

    def do_GET(self):
        if not self._authorized(): return
        self._reply(200,self.server.identity) if self.path=='/health' else self._reply(405)

    def do_DELETE(self):
        if self._authorized(): self._reply(200)

    def do_POST(self):
        if not self._authorized():
            self.close_connection = True
            return
        if self.path not in {'/mcp','/shutdown'}: self._reply(404); return
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 65536: raise ValueError()
            if self.headers.get('Transfer-Encoding'): raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError()
            if self.path=='/mcp' and data.get('jsonrpc') != '2.0': raise ValueError()
        except (ValueError,UnicodeError,TimeoutError):
            self.close_connection=True
            self._reply(400)
            return
        if self.path=='/shutdown':
            if data.get('instance_id')!=self.server.identity['instance_id']:
                self._reply(409)
                return
            self._reply(200,dict(stopping=True))
            threading.Thread(target=self.server.shutdown,name='chess-stop',daemon=True).start()
            return
        method, request_id = data.get('method'), data.get('id')
        if request_id is None:
            self._reply(202)
            return
        if method == 'initialize':
            requested = (data.get('params') or {}).get('protocolVersion')
            version = requested if requested in {'2025-11-25','2025-06-18','2025-03-26'} else '2025-06-18'
            result = dict(protocolVersion=version,capabilities={'tools':{}},
                          serverInfo=dict(name='companion-chess',version='1.0.0',_meta=self.server.identity))
        elif method == 'ping': result = {}
        elif method == 'tools/list': result = dict(tools=TOOLS)
        elif method == 'tools/call':
            params = data.get('params') or {}
            tool = next((t for t in TOOLS if t['name']==params.get('name')),None)
            try:
                if tool is None: raise ChessError('Unknown chess tool.')
                arguments = params.get('arguments',{})
                if not isinstance(arguments,dict): raise ChessError('Arguments must be an object.')
                error = next(Draft202012Validator(tool['inputSchema']).iter_errors(arguments),None)
                if error: raise ChessError('Arguments do not match the chess tool schema.')
                value = self.server.game.execute(tool['name'],arguments)
                if tool['name']=='chess_get_state': value['server_identity']=dict(self.server.identity)
                result = dict(content=[dict(type='text',text=json.dumps(value))],structuredContent=value,isError=False)
            except (ChessError,ValueError) as exc:
                result = dict(content=[dict(type='text',text=str(exc)[:300])],isError=True)
            except OSError:
                result = dict(content=[dict(type='text',text='Game storage is unavailable; no move was committed.')],isError=True)
        else:
            self._reply(200,dict(jsonrpc='2.0',id=request_id,error=dict(code=-32601,message='Method not found')))
            return
        self._reply(200,dict(jsonrpc='2.0',id=request_id,result=result))
