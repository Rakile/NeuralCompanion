"""Owner-bound resumable parts. One conversion worker, no giant relay requests."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from .media import MAX_BYTES, file_hash
from .models import identity, metadata

PART_BYTES=256*1024


class SoundUploads:
    def __init__(self, root: Path, library, *, executor=None, clock=time.monotonic):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self._library=library; self._clock=clock; self._lock=threading.RLock(); self._closed=False
        self._jobs={}; self._receipts={}
        self._executor=executor or ThreadPoolExecutor(max_workers=1,thread_name_prefix='nc-sound-import')
        # Uploads are session-bound; no old partial can be resumed after restart.
        for path in self.root.glob('*.part'):
            if re.fullmatch('[0-9a-f]{32}\\.part',path.name) and path.is_file():path.unlink(missing_ok=True)
        self._futures={}

    def _path(self, key): return self.root/(identity(key,asset=True)+'.part')

    def _expire(self):
        for job in self._jobs.values():
            if job['state']=='uploading' and self._clock()-job['touched']>300:
                self._path(job['id']).unlink(missing_ok=True); job['state']='expired'

    def _job(self, owner, key):
        identity(owner); identity(key,asset=True); self._expire()
        job=self._jobs.get(key)
        if not job or job['owner']!=owner or job['state']=='expired': raise ValueError('Upload is unavailable or expired.')
        return job

    def status(self, owner, key):
        with self._lock:
            job=self._job(owner,key)
            return copy.deepcopy({**{k:job[k] for k in ('id','state','received','next_index','byte_length','result','error')},'existing':job.get('existing',False)})

    def begin(self, owner, client_request_id, filename, byte_length, sha256, details):
        identity(owner); identity(client_request_id); details=metadata(details)
        if type(byte_length) is not int or not 0<byte_length<=MAX_BYTES: raise ValueError('Audio must be between 1 byte and 100 MiB.')
        if not isinstance(sha256,str) or not re.fullmatch('[0-9a-f]{64}',sha256): raise ValueError('Invalid audio hash.')
        if (not isinstance(filename,str) or len(filename)>180 or '/' in filename or '\\' in filename
                or Path(filename).suffix.lower() not in ('.mp3','.m4a','.aac','.ogg','.opus')):
            raise ValueError('Import MP3, M4A, AAC or Ogg/Opus on the phone. Import WAV/FLAC on the desktop.')
        fingerprint=hashlib.sha256(json.dumps([filename,byte_length,sha256,details],sort_keys=True).encode()).hexdigest()
        receipt=(owner,client_request_id)
        with self._lock:
            if self._closed: raise ValueError('Sound imports are shutting down.')
            self._expire()
            if receipt in self._receipts:
                old=self._jobs[self._receipts[receipt]]
                if old['fingerprint']!=fingerprint: raise ValueError('Upload request ID was reused for different audio.')
                return self.status(owner,old['id'])
            if sum(j['state'] in ('uploading','converting') for j in self._jobs.values())>=2: raise ValueError('Two sound imports are already active.')
            # Bounded session receipts; old IDs cannot silently become new submissions.
            if len(self._jobs)>=512: raise ValueError('This desktop session has reached its import limit.')
            key=uuid4().hex; self._path(key).touch(exist_ok=False)
            self._jobs[key]={'id':key,'owner':owner,'request_id':client_request_id,'fingerprint':fingerprint,
                'byte_length':byte_length,'sha256':sha256,'metadata':details,'state':'uploading','received':0,
                'next_index':0,'chunks':[],'touched':self._clock(),'result':None,'error':''}
            self._receipts[receipt]=key
            existing=next((item for item in self._library.list_assets() if item['content_hash']==sha256),None)
            if existing:
                self._path(key).unlink(missing_ok=True)
                self._jobs[key].update(state='ready',result=existing,existing=True)
            return {**self.status(owner,key),'chunk_size':PART_BYTES}

    def chunk(self, owner, key, index, sha256, data):
        if type(index) is not int or index<0 or not isinstance(data,str) or len(data)>4*((PART_BYTES+2)//3):
            raise ValueError('Invalid sound upload part.')
        try: block=base64.b64decode(data,validate=True)
        except (ValueError,TypeError) as exc: raise ValueError('Invalid sound upload encoding.') from exc
        if not 0<len(block)<=PART_BYTES or hashlib.sha256(block).hexdigest()!=sha256:
            raise ValueError('Sound upload part failed integrity verification.')
        with self._lock:
            job=self._job(owner,key)
            if job['state']!='uploading': raise ValueError('Upload is not accepting parts.')
            if index<job['next_index']:
                if job['chunks'][index]!=(sha256,len(block)): raise ValueError('Upload part conflicts with received bytes.')
                job['touched']=self._clock(); return self.status(owner,key)
            remaining=job['byte_length']-job['received']
            if index!=job['next_index'] or len(block)!=min(remaining,PART_BYTES): raise ValueError('Upload part is out of order or has the wrong length.')
            with self._path(key).open('r+b') as stream:
                stream.seek(job['received'])
                try: stream.write(block); stream.flush()
                except OSError:
                    stream.truncate(job['received']); raise
            job['chunks'].append((sha256,len(block))); job['received']+=len(block); job['next_index']+=1; job['touched']=self._clock()
            return self.status(owner,key)

    def finalize(self, owner, key):
        with self._lock:
            job=self._job(owner,key)
            if job['state'] in ('converting','ready','failed'): return self.status(owner,key)
            if job['state']!='uploading' or job['received']!=job['byte_length']: raise ValueError('The upload is incomplete.')
            job['state']='converting'; self._futures[key]=self._executor.submit(self._convert,owner,key)
            return self.status(owner,key)

    def _cancelled(self, owner, key):
        with self._lock: return self._closed or self._job(owner,key)['state']=='cancelled'

    def _convert(self, owner, key):
        try:
            with self._lock:
                job=copy.deepcopy(self._job(owner,key))
                if job['state']!='converting' or self._closed: return
            if file_hash(self._path(key))!=job['sha256']: raise ValueError('Upload hash mismatch.')
            result=self._library.import_file(self._path(key),job['metadata'],'upload-'+key,owner=owner,
                cancelled=lambda:self._cancelled(owner,key))
            with self._lock:
                current=self._job(owner,key)
                if current['state']=='converting': current.update(state='ready',result=result)
        except Exception:
            with self._lock:
                job=self._jobs[key]
                if job['state']=='converting': job.update(state='failed',error='Sound import failed. Check the file and try a new import.')
        finally: self._path(key).unlink(missing_ok=True)

    def abort(self, owner, key):
        with self._lock:
            job=self._job(owner,key); prior=job['state']
            if prior in ('uploading','converting'): job['state']='cancelled'
            if prior=='uploading': self._path(key).unlink(missing_ok=True)
            return self.status(owner,key)

    def close(self):
        with self._lock:
            self._closed=True
            for job in self._jobs.values():
                if job['state']=='uploading': self._path(job['id']).unlink(missing_ok=True); job['state']='cancelled'
                elif job['state']=='converting':
                    job['state']='cancelled'
                    future=self._futures.get(job['id'])
                    if future is not None and future.cancel(): self._path(job['id']).unlink(missing_ok=True)
        self._executor.shutdown(wait=False,cancel_futures=True)
