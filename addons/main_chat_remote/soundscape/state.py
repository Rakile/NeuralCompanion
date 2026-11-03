"""Atomic conversation preferences with bounded idempotent mutation receipts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from .models import apply_patch, defaults, identity


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.soundscape-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class SoundscapeStateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = {'version': 1, 'states': {}, 'receipts': {}}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('states'), dict) or not isinstance(data.get('receipts'), dict):
                raise ValueError('Soundscape settings are damaged.')
            for cid, value in data['states'].items():
                validated = self._validated(cid, value)
                if validated != value and set(value) != set(validated)-{'effects'}:
                    raise ValueError('Soundscape settings are damaged.')
                data['states'][cid] = validated
            for key, receipt in data['receipts'].items():
                if (not isinstance(key, str) or not isinstance(receipt, dict)
                        or set(receipt) != {'fingerprint', 'result'} or not isinstance(receipt['fingerprint'], str)):
                    raise ValueError('Soundscape receipts are damaged.')
                try:
                    parts = json.loads(key)
                    if not isinstance(parts, list) or len(parts) != 2:
                        raise ValueError('Invalid receipt identity.')
                    identity(parts[0])
                    identity(parts[1])
                    receipt['result'] = self._validated(parts[0], receipt['result'])
                except (TypeError, KeyError, ValueError) as exc:
                    raise ValueError('Soundscape receipts are damaged.') from exc
            self._data = data

    @staticmethod
    def _validated(cid: str, value: object) -> dict:
        keys=set(defaults(cid))
        if not isinstance(value, dict) or set(value) not in (keys,keys-{'effects'}) or type(value.get('version')) is not int or value['version'] != 1 or value.get('conversation_id') != cid:
            raise ValueError('Invalid soundscape snapshot.')
        if type(value['revision']) is not int or value['revision'] < 0:
            raise ValueError('Invalid soundscape revision.')
        out = defaults(cid)
        apply_patch(out, {k: v for k, v in value.items() if k not in ('version', 'conversation_id', 'revision')}, manual=False)
        out['revision'] = value['revision']
        return out

    def snapshot(self, conversation_id: str) -> dict:
        identity(conversation_id)
        with self._lock:
            return copy.deepcopy(self._data['states'].get(conversation_id, defaults(conversation_id)))

    def references(self, asset_id: str) -> bool:
        identity(asset_id, asset=True)
        with self._lock:
            return any(state[layer]['asset_id'] == asset_id for state in self._data['states'].values()
                       for layer in ('ambience', 'music'))

    def update(self, conversation_id: str, expected_revision: int, client_request_id: str, patch: dict,
               *, manual: bool = True) -> dict:
        identity(conversation_id)
        identity(client_request_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('Invalid soundscape revision.')
        # Validate before serializing so non-finite numbers and invalid fields never earn receipts.
        apply_patch(defaults(conversation_id), patch, manual=manual)
        receipt_input = [expected_revision, patch] if manual else [expected_revision, patch, 'automatic']
        fingerprint = hashlib.sha256(json.dumps(receipt_input, sort_keys=True, allow_nan=False).encode()).hexdigest()
        key = json.dumps([conversation_id, client_request_id])
        with self._lock:
            prior = self._data['receipts'].get(key)
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise ValueError('Soundscape request ID was reused for different settings.')
                return copy.deepcopy(prior['result'])
            current = self.snapshot(conversation_id)
            if current['revision'] != expected_revision:
                raise ValueError('Soundscape settings changed. Refresh and try again.')
            apply_patch(current, patch, manual=manual)
            current['revision'] += 1
            data = copy.deepcopy(self._data)
            data['states'][conversation_id] = current
            data['receipts'][key] = {'fingerprint': fingerprint, 'result': current}
            while len(data['receipts']) > 512:
                del data['receipts'][next(iter(data['receipts']))]
            atomic_json(self.path, data)
            self._data = data
            return copy.deepcopy(current)

    def restore(self, conversation_id: str, saved: dict) -> dict:
        original = self._validated(saved.get('conversation_id', ''), saved)
        with self._lock:
            original['conversation_id'] = identity(conversation_id)
            original['revision'] = self.snapshot(conversation_id)['revision'] + 1
            original['paused'] = True
            data = copy.deepcopy(self._data)
            data['states'][conversation_id] = original
            atomic_json(self.path, data)
            self._data = data
            return copy.deepcopy(original)

    def clear_asset(self, asset_id: str) -> None:
        identity(asset_id, asset=True)
        with self._lock:
            data = copy.deepcopy(self._data)
            changed = False
            for state in data['states'].values():
                matches = [layer for layer in ('ambience','music') if state[layer]['asset_id'] == asset_id]
                for layer in matches: state[layer]['asset_id'] = None
                if matches: state['revision'] += 1; changed = True
            if changed:
                atomic_json(self.path, data)
                self._data = data
