"""Opt-in, full-text local communication recording. Never changes request payloads."""
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields, is_dataclass
from datetime import datetime
import base64
import hashlib
import io
import json
from pathlib import Path
import queue
import re
import threading
import time
import uuid

_CORRELATION=ContextVar('nc_communication_correlation',default={})

@contextmanager
def correlation_scope(value):
    token=_CORRELATION.set(dict(_CORRELATION.get(),**value))
    try: yield
    finally: _CORRELATION.reset(token)

def current_correlation():
    return dict(_CORRELATION.get())

def record_to(sink,stage,payload,correlation=None):
    if sink is None:
        return False
    try:
        return sink.record(stage,payload,correlation=correlation if correlation is not None else current_correlation())
    except Exception:
        return False


def _snapshot(value):
    if isinstance(value,Mapping):
        return {str(k): '[REDACTED]' if _secret(str(k)) else _snapshot(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [_snapshot(v) for v in value]
    if is_dataclass(value):
        return _snapshot({f.name:getattr(value,f.name) for f in fields(value)})
    if isinstance(value,(str,int,float,bool)) or value is None:
        return value
    if isinstance(value,Path):
        return str(value)
    if isinstance(value,BaseException):
        return dict(type=type(value).__name__,message=str(value))
    raise TypeError(f'Unsupported communication payload: {type(value).__name__}')


def _secret(key):
    normalized=re.sub('[^a-z0-9]','',key.lower())
    return normalized in {'authorization','proxyauthorization','apikey','accesstoken','refreshtoken',
        'password','secret','clientsecret','cookie','setcookie','credentials','credential','authheaders'} or normalized.endswith(('apikey','password','clientsecret'))


def lease_correlation(lease, **extra):
    return dict(run_id=str(lease.run_id.value),session_id=str(lease.session_generation.value),**extra)


class CommunicationTrace:
    def __init__(self,root:Path,max_bytes=1073741824,*,queue_capacity=256):
        self.root=Path(root); self.max_bytes=max_bytes; self._capacity=queue_capacity
        self._lock=threading.RLock(); self._state='off'; self._reason=''; self._path=None
        self._bytes=0; self._sequence=0; self._thread=None; self._stop=threading.Event()
        self._queue=queue.Queue(maxsize=queue_capacity); self._recording_id=''

    def start(self,recording_id=None):
        recording_id=recording_id or datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:12]
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}',recording_id):
            raise ValueError('Invalid recording directory name.')
        self.stop()
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError('Previous recording is still flushing.')
            path=self.root/recording_id
            path.mkdir(parents=True,exist_ok=False)
            self._path=path; self._recording_id=recording_id; self._state='recording'; self._reason=''
            self._bytes=0; self._sequence=0; self._queue=queue.Queue(maxsize=self._capacity)
            self._stop=threading.Event()
            self._thread=threading.Thread(target=self._write,name='NC communication log',daemon=True)
            self._thread.start()
        self.record('recording.started',dict(note='Only traffic while enabled is recorded; earlier traffic is unavailable.'),correlation={})

    def snapshot(self):
        with self._lock:
            return dict(state=self._state,path=str(self._path or ''),byte_count=self._bytes,
                incomplete_reason=self._reason,max_bytes=self.max_bytes,recording_id=self._recording_id)

    def _fail(self,reason):
        with self._lock:
            self._state='incomplete'; self._reason=str(reason); self._stop.set()

    def record(self,stage,payload,*,correlation):
        with self._lock:
            if self._state!='recording':
                return False
            try:
                event=dict(schema_version=1,sequence=self._sequence+1,
                    timestamp=datetime.now().astimezone().isoformat(),monotonic=time.monotonic(),
                    recording_id=self._recording_id,stage=str(stage),
                    correlation=_snapshot(correlation),payload=_snapshot(payload))
                self._queue.put_nowait(event)
                self._sequence+=1
                return True
            except queue.Full:
                self._fail('Writer queue overflow; recording incomplete.')
            except Exception as exc:
                self._fail(f'Payload snapshot failed: {type(exc).__name__}: {exc}')
            return False

    def stop(self, *, wait=True):
        with self._lock:
            if self._state=='recording':
                self._state='stopping'
            self._stop.set(); thread=self._thread
        if wait and thread and thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._lock:
            if self._state=='stopping' and (not thread or not thread.is_alive()):
                self._state='off'

    def _images(self,value,assets):
        if isinstance(value,str) and value.startswith('data:image/') and ';base64,' in value:
            header,encoded=value.split(',',1)
            data=base64.b64decode(encoded,validate=True)
            digest=hashlib.sha256(data).hexdigest()
            suffix={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}.get(header[5:].split(';')[0],'.img')
            relative='assets/'+digest+suffix
            if not (self._path/relative).exists():
                assets[relative]=data
            dimensions=[]
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as image: dimensions=list(image.size)
            except (OSError,ValueError):
                pass
            return dict(asset=relative,sha256=digest,byte_count=len(data),dimensions=dimensions)
        if isinstance(value,dict):
            return {k:self._images(v,assets) for k,v in value.items()}
        if isinstance(value,list):
            return [self._images(v,assets) for v in value]
        return value

    def _write(self):
        try:
            with (self._path/'communication.jsonl').open('xb') as output:
                while not self._stop.is_set() or not self._queue.empty():
                    try: event=self._queue.get(timeout=.05)
                    except queue.Empty: continue
                    assets={}
                    event=self._images(event,assets)
                    line=(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')
                    amount=len(line)+sum(len(data) for data in assets.values())
                    if self._bytes+amount>self.max_bytes:
                        self._fail('Recording limit reached (including image assets); no messages were truncated.')
                        break
                    for relative,data in assets.items():
                        asset=self._path/relative; asset.parent.mkdir(exist_ok=True)
                        with asset.open('xb') as handle: handle.write(data)
                    output.write(line); output.flush()
                    with self._lock: self._bytes+=amount
        except Exception as exc:
            self._fail(f'Writer failed: {type(exc).__name__}: {exc}')
        finally:
            try:
                with self._lock:
                    if self._state == 'stopping':
                        self._state = 'off'
                status=self.snapshot()
                (self._path/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception:
                pass

    def export(self):
        snapshot=self.snapshot()
        if not snapshot['path']:
            raise RuntimeError('No communication recording exists yet.')
        return str(export_transcript(Path(snapshot['path'])))


def export_transcript(recording_dir:Path):
    root=Path(recording_dir)
    output=root/'transcript.txt'
    with (root/'communication.jsonl').open(encoding='utf-8') as source,output.open('w',encoding='utf-8') as target:
        target.write('NeuralCompanion application communication log. Image assets are relative to this folder.\n\n')
        for line in source:
            try: event=json.loads(line)
            except json.JSONDecodeError:
                target.write('\n[Incomplete final record]\n'); break
            target.write(f"[{event['sequence']}] {event['timestamp']} {event['stage']}\n")
            target.write(json.dumps(event['correlation'],ensure_ascii=False)+'\n')
            target.write(json.dumps(event['payload'],ensure_ascii=False,indent=2)+'\n\n')
    return output
