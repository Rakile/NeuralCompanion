"""Explicit, supervised server launch with authenticated installation identity."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import URLError
from uuid import uuid4


class ServerLauncher:
    def __init__(self, context):
        self.context=context
        self.process=None
        self.token=''
        self.identity=None
        self.port=0

    def _health(self, port: int, token: str) -> dict:
        request=Request(f'http://127.0.0.1:{port}/health',headers={'Authorization':'Bearer '+token})
        with build_opener(ProxyHandler({})).open(request,timeout=.5) as response:
            return json.loads(response.read(4096))

    def start(self, port: int, stop) -> dict:
        if not 1024<=port<=65535: raise ValueError('Choose a port from 1024 to 65535.')
        path=self.context.storage.resolve('installation-id.txt')
        try:
            with path.open('x',encoding='utf-8') as stream:
                identity=uuid4().hex
                stream.write(identity)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            identity=path.read_text(encoding='utf-8').strip()
        if not re.fullmatch('[a-f0-9]{32}',identity):
            raise ValueError('The saved chess installation identity is damaged. Restore it before starting the server.')
        host=self.context.capabilities.chess_personas
        if host is None: raise RuntimeError('The updated NC chess host integration is unavailable.')
        self.token=host.server_credential(identity)
        def verify(value):
            if value.get('service')!='companion-chess' or value.get('protocol')!=1 or value.get('installation_id')!=identity:
                raise ValueError('Another service or installation owns this port. Select another port.')
            self.identity=value
            return dict(endpoint=f'http://127.0.0.1:{port}/mcp',identity=value)
        try: return verify(self._health(port,self.token))
        except URLError as exc:
            if getattr(exc,'code',None): raise ValueError('The port belongs to a server with different credentials.') from None
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('The owned server is still starting. Try refresh shortly.')
        environment=dict(os.environ,NC_CHESS_BEARER_TOKEN=self.token,PYTHONDONTWRITEBYTECODE='1')
        arguments=[sys.executable,'-B','-m','addons.companion_chess.server','--storage',str(path.parent),
                   '--installation-id',identity,'--port',str(port)]
        self.process=subprocess.Popen(arguments,cwd=self.context.paths.app_root,env=environment,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.port=port
        try: self.context.tasks.register_process('companion-chess-server',self.process,graceful_stop=self.close)
        except Exception:
            self.close()
            raise
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and not stop.is_set():
            if self.process.poll() is not None:
                raise RuntimeError('Chess server could not start. Check Python 3.11 chess/jsonschema dependencies and the chosen port.')
            try: return verify(self._health(port,self.token))
            except URLError: stop.wait(.15)
        raise RuntimeError('Chess server startup timed out.')

    def close(self):
        process,self.process=self.process,None
        if process is not None and process.poll() is None:
            if self.identity and self.port:
                try:
                    request=Request(f'http://127.0.0.1:{self.port}/shutdown',
                        data=json.dumps(dict(instance_id=self.identity['instance_id'])).encode(),
                        headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
                    with build_opener(ProxyHandler({})).open(request,timeout=1): pass
                except (URLError,OSError): pass
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Windows venv python.exe can be a redirector with a child interpreter.
                # Kill only this still-owned process tree if graceful shutdown failed.
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else: process.kill()
                process.wait(timeout=2)
