"""Persistent, explicit paid jobs. Unknown submissions are never automatically retried."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
from uuid import uuid4

from addons.voice_studio.models import ProviderError
from .elevenlabs import generation_request
from .library import SoundLibrary
from .media import convert_sound, file_hash
from .models import identity, metadata
from .state import atomic_json

_UNKNOWN = 'The provider may have completed this request. It will not be retried automatically.'


class SoundGenerationJobs:
    def __init__(self, root: Path, client_factory, library: SoundLibrary, *, converter=convert_sound,
                 executor=None, clock=time.time):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self._path=self.root/'jobs.json'; self._client=client_factory; self._library=library
        self._convert=converter; self._clock=clock; self._lock=threading.RLock(); self._closed=False
        self._executor=executor or ThreadPoolExecutor(max_workers=1,thread_name_prefix='nc-sound-generation')
        self._data={'version':1,'jobs':{}}
        self._active=set()
        self._last_expire=None
        if self._path.exists():
            data=json.loads(self._path.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('jobs'),dict):
                raise ValueError('Sound generation journal is damaged.')
            for key,job in data['jobs'].items():
                if not isinstance(job,dict) or job.get('id')!=key:raise ValueError('Sound generation journal is damaged.')
                identity(key,asset=True); identity(job['owner']); identity(job['request_id'])
                if job['state'] in ('submitting','converting','saving'):
                    job['state']='outcome_unknown'; job['error']=_UNKNOWN
                elif job['state']=='queued':
                    job['state']='cancelled'; job['error']='Desktop restarted before this request was submitted.'
            self._data=data; atomic_json(self._path,data)
        self.expire()

    def _commit(self, data):
        atomic_json(self._path,data); self._data=data

    def _job(self, owner, job_id):
        identity(job_id,asset=True)
        job=self._data['jobs'].get(job_id)
        if not job or job['owner']!=owner: raise ValueError('Sound generation request is unavailable.')
        return job

    def snapshot(self, owner: str, job_id: str) -> dict:
        self.expire()
        with self._lock:
            job=self._job(owner,job_id)
            return copy.deepcopy({k:v for k,v in job.items() if k not in ('owner','fingerprint','request_id','request')})

    def submit(self, owner: str, client_request_id: str, request: dict) -> dict:
        self.expire()
        identity(owner); identity(client_request_id); request=generation_request(request)
        fingerprint=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        with self._lock:
            if self._closed: raise ValueError('Sound generation is shutting down.')
            for job in self._data['jobs'].values():
                if job['owner']==owner and job['request_id']==client_request_id:
                    if job['fingerprint']!=fingerprint: raise ValueError('Generation request ID was reused for a different prompt.')
                    return self.snapshot(owner,job['id'])
            if sum(j['state'] in ('queued','submitting','converting') for j in self._data['jobs'].values())>=20:
                raise ValueError('Sound generation queue is full.')
            if len(self._data['jobs'])>=10000:raise ValueError('Sound generation journal is full.')
            job_id=uuid4().hex
            job={'id':job_id,'owner':owner,'request_id':client_request_id,'fingerprint':fingerprint,
                 'request':request,'created':self._clock(),'state':'queued','error':''}
            data=copy.deepcopy(self._data); data['jobs'][job_id]=job; self._commit(data)
            self._executor.submit(self._run,owner,job_id)
            return self.snapshot(owner,job_id)

    def _transition(self, owner, job_id, allowed, **values) -> bool:
        with self._lock:
            job=self._job(owner,job_id)
            if job['state'] not in allowed: return False
            data=copy.deepcopy(self._data); data['jobs'][job_id].update(values); self._commit(data)
            logging.getLogger('nc.soundscape').info('generation id=%s state=%s',job_id,values.get('state',job['state']))
            return True

    def _cancelled(self, owner, job_id):
        with self._lock: return self._closed or self._job(owner,job_id)['state'] in ('cancelled','expired')

    def _run(self, owner, job_id):
        submitted=False
        try:
            with self._lock:
                if self._closed or self._job(owner,job_id)['state']!='queued': return
                self._active.add(job_id)
                request=copy.deepcopy(self._job(owner,job_id)['request'])
            client=self._client()  # Resolve credentials before the durable submission boundary.
            if self._cancelled(owner,job_id): return
            if not self._transition(owner,job_id,{'queued'},state='submitting'): return
            submitted=True
            response=client.generate(request)
            if not self._transition(owner,job_id,{'submitting'},state='converting'): return
            folder=self.root/job_id; folder.mkdir(exist_ok=True)
            original=folder/'original.mp3'; encoded=folder/'preview.ogg'
            original.write_bytes(response.data)
            media=self._convert(original,encoded,lambda:self._cancelled(owner,job_id))
            SoundLibrary._validate_descriptor(media)
            if media['sha256']!=file_hash(encoded) or media['byte_length']!=encoded.stat().st_size:
                raise ValueError('Sound integrity verification failed.')
            preview={**media,'asset_id':job_id,'source_hash':file_hash(original),
                     'url_path':'/api/soundscape/media/'+media['sha256']}
            self._transition(owner,job_id,{'converting'},state='ready',preview=preview)
        except Exception as exc:
            if isinstance(exc,ProviderError):
                unknown=bool(exc.unknown); message=(_UNKNOWN if unknown else 'ElevenLabs rejected this request. Check credentials, permissions and quota.')
            else:
                unknown=submitted; message=_UNKNOWN if submitted else 'Configure the ElevenLabs provider on the desktop and try a new request.'
            self._transition(owner,job_id,{'queued','submitting','converting'},state='outcome_unknown' if unknown else 'failed',error=message)
        finally:
            with self._lock:
                self._active.discard(job_id)
                if self._job(owner,job_id)['state'] in ('cancelled','failed','outcome_unknown'):
                    self._remove_files(job_id)

    def cancel(self, owner: str, job_id: str) -> dict:
        with self._lock:
            if self._job(owner,job_id)['state'] in ('saving','saved'):
                raise ValueError('This sound is being saved or is already in the library.')
            self._transition(owner,job_id,{'queued','submitting','converting','ready'},state='cancelled',preview=None)
            if job_id not in self._active:self._remove_files(job_id)
            return self.snapshot(owner,job_id)

    def read_media(self, owner, sha256, offset, length):
        from .uploads import PART_BYTES
        if type(offset) is not int or type(length) is not int or offset<0 or not 1<=length<=PART_BYTES:
            raise ValueError('Invalid sound media part.')
        with self._lock:
            job=next((j for j in self._data['jobs'].values() if j['owner']==owner and j['state'] in ('ready','saved')
                      and (j.get('preview') or {}).get('sha256')==sha256),None)
            if job is None or offset>=job['preview']['byte_length']: raise ValueError('Sound draft is unavailable.')
            with (self.root/job['id']/'preview.ogg').open('rb') as stream:
                stream.seek(offset); return stream.read(min(length,job['preview']['byte_length']-offset))

    def save(self, owner: str, job_id: str, details: dict) -> dict:
        details=metadata(details)
        with self._lock:
            job=self._job(owner,job_id)
            if job['state']=='saved':
                if metadata(job['saved_metadata'])!=details: raise ValueError('This draft was already saved with different details.')
                return self._library.get(job['saved_asset_id'])
            if job['state']!='ready': raise ValueError('Wait for a ready sound before saving.')
            preview=copy.deepcopy(job['preview'])
            self._transition(owner,job_id,{'ready'},state='saving')
        try:
            folder=self.root/job_id
            result=self._library.save_generated(folder/'original.mp3',folder/'preview.ogg',preview,details,'generated-'+job_id,owner=owner)
        except Exception:
            self._transition(owner,job_id,{'saving'},state='ready')
            raise
        self._transition(owner,job_id,{'saving'},state='saved',saved_asset_id=result['id'],saved_metadata=details)
        with self._lock:self._remove_files(job_id)
        return result

    def _remove_files(self, job_id):
        folder=self.root/identity(job_id,asset=True)
        for name in ('original.mp3','preview.ogg'):
            (folder/name).unlink(missing_ok=True)
        if folder.is_dir() and not any(folder.iterdir()): folder.rmdir()

    def discard(self, owner: str, job_id: str) -> dict:
        with self._lock:
            state=self._job(owner,job_id)['state']
            if state in ('submitting','converting','saving'): raise ValueError('Cancel generation before discarding this draft.')
            if state=='saved': raise ValueError('Remove a saved sound from the library.')
            self.cancel(owner,job_id)
            if job_id not in self._active:self._remove_files(job_id)
            return self.snapshot(owner,job_id)

    def expire(self):
        with self._lock:
            now=self._clock()
            if self._last_expire is not None and 0<=now-self._last_expire<60:return
            data=copy.deepcopy(self._data); changed=False
            for job in data['jobs'].values():
                if job['id'] not in self._active and self._clock()-job['created']>7*86400 and job['state'] in ('ready','failed','outcome_unknown','cancelled'):
                    self._remove_files(job['id']); job.update(state='expired',preview=None); job.pop('request',None); changed=True
            if changed: self._commit(data)
            self._last_expire=now

    def close(self):
        with self._lock:
            if self._closed: return
            self._closed=True
            data=copy.deepcopy(self._data)
            for job in data['jobs'].values():
                if job['state']=='queued': job['state']='cancelled'
                elif job['state'] in ('submitting','converting'): job.update(state='outcome_unknown',error=_UNKNOWN)
            self._commit(data)
        self._executor.shutdown(wait=False,cancel_futures=True)
