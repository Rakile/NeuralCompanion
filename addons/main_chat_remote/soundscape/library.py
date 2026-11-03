"""Managed original/Opus assets. Call I/O operations from workers, never Qt slots."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import tempfile
import threading
from uuid import uuid4

from .media import BLOCK, MAX_BYTES, MAX_SECONDS, convert_sound, file_hash
from .models import identity, metadata
from .state import atomic_json


class SoundLibrary:
    def __init__(self, root: Path, *, converter=convert_sound):
        self.root = Path(root)
        for name in ('originals', 'media', 'staging'):
            (self.root/name).mkdir(parents=True, exist_ok=True)
        self._path = self.root/'index.json'
        self._lock = threading.RLock()
        self._conversion = threading.Lock()
        self._pins: dict[str, int] = {}
        self._converter = converter
        self._data = {'version': 1, 'assets': {}, 'receipts': {}}
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('assets'), dict) or not isinstance(data.get('receipts'), dict):
                raise ValueError('Sound library index is damaged.')
            for key, value in data['assets'].items():
                identity(key, asset=True)
                if not isinstance(value, dict) or value.get('id') != key:
                    raise ValueError('Sound library index is damaged.')
                if not isinstance(value.get('content_hash'),str) or not re.fullmatch('[0-9a-f]{64}',value['content_hash']):
                    raise ValueError('Sound library index is damaged.')
                self._validate_descriptor(value['media'])
                details = metadata({k: value[k] for k in ('title', 'description', 'kind', 'tags', 'loop')}
                                   | {k: value[k] for k in ('category', 'gain', 'discarded') if k in value})
                value.update(details)
            self._data = data

    @staticmethod
    def _validate_descriptor(value):
        import re
        if not isinstance(value, dict): raise ValueError('Invalid sound media.')
        if not isinstance(value.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
            raise ValueError('Invalid sound hash.')
        for key, limit in [('byte_length', MAX_BYTES), ('duration_ms', MAX_SECONDS*1000)]:
            if type(value.get(key)) is not int or not 0 < value[key] <= limit: raise ValueError('Invalid sound size or duration.')
        if (type(value.get('channels')) is not int or value['channels'] not in (1,2)
                or value.get('sample_rate') != 48000 or value.get('content_type') != 'audio/ogg'
                or value.get('profile') != ('opus48-mono64-v1' if value['channels']==1 else 'opus48-stereo96-v1')):
            raise ValueError('Invalid sound encoding.')

    def list_assets(self) -> list[dict]:
        with self._lock: return copy.deepcopy(list(self._data['assets'].values()))

    def get(self, asset_id: str) -> dict:
        identity(asset_id, asset=True)
        with self._lock:
            if asset_id not in self._data['assets']: raise ValueError('Sound is no longer in the library.')
            return copy.deepcopy(self._data['assets'][asset_id])

    def _commit(self, data):
        if len(data['assets'])>2000 or len(data['receipts'])>10000:
            raise ValueError('Sound library operation limit reached.')
        atomic_json(self._path, data)
        self._data = data

    def import_file(self, path: Path, details: dict, client_request_id: str, *, owner='desktop', cancelled=lambda: False) -> dict:
        return self._import_file(path, details, client_request_id, owner=owner, cancelled=cancelled)

    def save_generated(self, original: Path, encoded: Path, descriptor: dict, details: dict,
                       client_request_id: str, *, owner: str) -> dict:
        return self._import_file(original, details, client_request_id, owner=owner,
                                 ready=(encoded, descriptor))

    def _import_file(self, path: Path, details: dict, client_request_id: str, *, owner='desktop',
                     cancelled=lambda: False, ready=None) -> dict:
        details = metadata(details); identity(client_request_id); identity(owner)
        path = Path(path)
        if path.is_symlink() or not path.is_file(): raise ValueError('Choose a regular audio file.')
        # One conversion pipeline; hashing/copying also stay on this worker.
        with self._conversion, tempfile.TemporaryDirectory(prefix='import-', dir=self.root/'staging') as folder:
            original, encoded = Path(folder)/'original', Path(folder)/'encoded.ogg'
            digest = hashlib.sha256(); total = 0
            with path.open('rb') as source, original.open('xb') as output:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode): raise ValueError('Choose a regular audio file.')
                for block in iter(lambda: source.read(BLOCK), b''):
                    if cancelled(): raise RuntimeError('Import cancelled.')
                    total += len(block)
                    if total > MAX_BYTES: raise ValueError('Audio exceeds 100 MiB.')
                    digest.update(block); output.write(block)
            if not total: raise ValueError('The file is empty.')
            source_hash = digest.hexdigest()
            fingerprint = hashlib.sha256(json.dumps([source_hash, details], sort_keys=True).encode()).hexdigest()
            key = json.dumps([owner, client_request_id])
            with self._lock:
                receipt = self._data['receipts'].get(key)
                if receipt:
                    legacy_details = {field: details[field] for field in ('title', 'description', 'kind', 'tags', 'loop')}
                    legacy_fingerprint = hashlib.sha256(json.dumps([source_hash, legacy_details], sort_keys=True).encode()).hexdigest()
                    previous = {k:v for k,v in details.items() if k != 'discarded'}
                    previous_fingerprint = hashlib.sha256(json.dumps([source_hash, previous], sort_keys=True).encode()).hexdigest()
                    if receipt['fingerprint'] not in (fingerprint, legacy_fingerprint, previous_fingerprint):
                        raise ValueError('Import request ID was reused for different audio.')
                    return self.get(receipt['asset_id'])
            if ready is None:
                media = self._converter(original, encoded, cancelled)
            else:
                shutil.copyfile(ready[0], encoded)
                media = copy.deepcopy(ready[1])
            self._validate_descriptor(media)
            if media['byte_length'] != encoded.stat().st_size or media['sha256'] != file_hash(encoded):
                raise ValueError('Converted audio failed integrity verification.')
            if cancelled(): raise RuntimeError('Import cancelled.')
            asset_id = uuid4().hex
            media = {**media, 'asset_id': asset_id, 'source_hash': source_hash,
                     'url_path': '/api/soundscape/media/'+media['sha256']}
            asset = {**details, 'id': asset_id, 'revision': 0, 'source': 'elevenlabs' if ready else 'import', 'content_hash': source_hash,
                     'duration_ms': media['duration_ms'], 'media': media}
            # Content-addressed files can survive an index failure as harmless orphans.
            for source, target in [(original, self.root/'originals'/source_hash), (encoded, self.root/'media'/(media['sha256']+'.ogg'))]:
                try: os.link(source, target)
                except FileExistsError:
                    if file_hash(source) != file_hash(target): raise ValueError('Managed audio failed integrity verification.')
            with self._lock:
                data = copy.deepcopy(self._data); data['assets'][asset_id] = asset
                data['receipts'][key] = {'fingerprint': fingerprint, 'asset_id': asset_id}
                self._commit(data)
            return copy.deepcopy(asset)

    def _operation(self, owner, request_id, payload):
        if request_id is None: return None, None, None
        identity(owner); identity(request_id)
        key=json.dumps([owner, request_id])
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
        prior=self._data['receipts'].get(key)
        if prior and prior['fingerprint']!=digest: raise ValueError('Sound operation ID was reused.')
        return key,digest,prior

    def update(self, asset_id: str, revision: int, patch: dict, *, request_id=None, owner='desktop') -> dict:
        with self._lock:
            key,digest,prior=self._operation(owner,request_id,['update',asset_id,revision,patch])
            if prior: return copy.deepcopy(prior['result'])
            item = self.get(asset_id)
            if type(revision) is not int or revision != item['revision']: raise ValueError('Sound details changed. Refresh and try again.')
            if not isinstance(patch, dict) or set(patch)-{'title','description','kind','category','gain','tags','loop','discarded'}: raise ValueError('Invalid sound details.')
            details = metadata({**{k:item[k] for k in ('title','description','kind','category','gain','tags','loop','discarded')}, **patch})
            item.update(details); item['revision'] += 1
            data = copy.deepcopy(self._data); data['assets'][asset_id] = item
            if key: data['receipts'][key]={'fingerprint':digest,'result':item}
            self._commit(data)
            return item

    def remove(self, asset_id: str, *, request_id=None, owner='desktop') -> None:
        # Match import lock order: deletion cannot race between linking a blob
        # and publishing another asset which shares it.
        with self._conversion, self._lock:
            key,digest,prior=self._operation(owner,request_id,['remove',asset_id])
            if prior: return
            item=self.get(asset_id)
            if self._pins.get(asset_id): raise ValueError('Sound is being saved. Try again shortly.')
            data = copy.deepcopy(self._data); del data['assets'][asset_id]
            if key: data['receipts'][key]={'fingerprint':digest,'result':True}
            self._commit(data)
            self._remove_unreferenced(item)

    def _remove_unreferenced(self, item):
        if not re.fullmatch('[0-9a-f]{64}',item['content_hash']):raise ValueError('Invalid original sound hash.')
        live=self._data['assets'].values()
        if not any(a['media']['sha256']==item['media']['sha256'] for a in live):
            (self.root/'media'/(item['media']['sha256']+'.ogg')).unlink(missing_ok=True)
        if not any(a['content_hash']==item['content_hash'] for a in live):
            (self.root/'originals'/item['content_hash']).unlink(missing_ok=True)

    def read_media(self, sha256: str, offset: int, length: int) -> bytes:
        from .uploads import PART_BYTES
        if type(offset) is not int or type(length) is not int or offset<0 or not 1<=length<=PART_BYTES:
            raise ValueError('Invalid sound media part.')
        with self._lock:
            asset=next((a for a in self._data['assets'].values() if a['media']['sha256']==sha256),None)
            if asset is None or offset>=asset['media']['byte_length']: raise ValueError('Sound is unavailable.')
            with (self.root/'media'/(sha256+'.ogg')).open('rb') as stream:
                stream.seek(offset); return stream.read(min(length,asset['media']['byte_length']-offset))

    def export_assets(self, asset_ids: list[str], destination: Path) -> list[dict]:
        with self._lock:
            assets = [self.get(key) for key in dict.fromkeys(asset_ids)]
            for item in assets: self._pins[item['id']] = self._pins.get(item['id'], 0)+1
        try:
            destination.mkdir(parents=True, exist_ok=True)
            for item in assets:
                shutil.copyfile(self.root/'media'/(item['media']['sha256']+'.ogg'), destination/(item['id']+'.ogg'))
                if file_hash(destination/(item['id']+'.ogg')) != item['media']['sha256']:
                    raise ValueError('Saved sound failed integrity verification.')
            return assets
        finally:
            with self._lock:
                for item in assets:
                    self._pins[item['id']] -= 1
                    if not self._pins[item['id']]: del self._pins[item['id']]
