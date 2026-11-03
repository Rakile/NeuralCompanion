"""Trusted, bounded sound/context feedback; never learns from client supplied text."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import threading
import time

from .models import identity
from .state import atomic_json


class SoundFeedbackStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = {'version': 1, 'conversations': {}, 'receipts': {}}
        if self.path.exists():
            if self.path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('Sound feedback storage exceeds its limit.')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(data, dict) or data.get('version') != 1
                    or not isinstance(data.get('conversations'), dict) or not isinstance(data.get('receipts'), dict)
                    or len(data['conversations']) > 128 or len(data['receipts']) > 512):
                raise ValueError('Invalid sound feedback storage.')
            for cid, value in data['conversations'].items():
                identity(cid)
                if not isinstance(value, dict) or set(value) != {'choices', 'feedback'}:
                    raise ValueError('Invalid sound feedback history.')
                for field in ('choices', 'feedback'):
                    if not isinstance(value[field], list) or len(value[field]) > 128:
                        raise ValueError('Invalid sound feedback history.')
                for choice in value['choices']:
                    if self._choice(choice) != choice or choice['conversation_id'] != cid:
                        raise ValueError('Invalid sound choice history.')
                for record in value['feedback']:
                    if (not isinstance(record, dict) or type(record.get('good')) is not bool
                            or type(record.get('skip')) is not bool or record.get('choice', {}).get('conversation_id') != cid):
                        raise ValueError('Invalid sound rating history.')
                    self._choice(record['choice'])
            self._data = data

    @staticmethod
    def _choice(value: dict) -> dict:
        fields = {'id', 'conversation_id', 'session_generation', 'reply_id', 'cue_id', 'layer',
                  'asset_id', 'asset_revision', 'excerpt', 'tokens'}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError('Invalid sound choice.')
        out = copy.deepcopy(value)
        for field in ('id', 'conversation_id', 'reply_id', 'cue_id'):
            identity(out[field])
        identity(out['asset_id'], asset=True)
        if out['layer'] not in ('ambience', 'music', 'effect'):
            raise ValueError('Invalid sound choice layer.')
        if any(type(out[k]) is not int or out[k] < 0 for k in ('session_generation', 'asset_revision')):
            raise ValueError('Invalid sound choice revision.')
        if not isinstance(out['excerpt'], str) or not isinstance(out['tokens'], list):
            raise ValueError('Invalid sound context.')
        if len(out['tokens']) > 128 or any(not isinstance(t, str) or not t or len(t) > 32 for t in out['tokens']):
            raise ValueError('Invalid sound context tokens.')
        out['excerpt'] = out['excerpt'][:500]
        out['tokens'] = list(dict.fromkeys(out['tokens']))
        return out

    def _commit(self, data):
        while len(data['conversations']) > 128:
            del data['conversations'][next(iter(data['conversations']))]
        while len(data['receipts']) > 512:
            del data['receipts'][next(iter(data['receipts']))]
        atomic_json(self.path, data)
        self._data = data

    def snapshot(self, conversation_id: str) -> dict:
        identity(conversation_id)
        with self._lock:
            return copy.deepcopy(self._data['conversations'].get(conversation_id, {'choices': [], 'feedback': []}))

    def record_choice(self, choice: dict) -> dict:
        choice = self._choice(choice)
        with self._lock:
            data = copy.deepcopy(self._data)
            conversation = data['conversations'].setdefault(choice['conversation_id'], {'choices': [], 'feedback': []})
            prior = next((row for row in conversation['choices'] if row['id'] == choice['id']), None)
            if prior is not None:
                if prior != choice: raise ValueError('Sound choice identity was reused.')
                return copy.deepcopy(prior)
            conversation['choices'].append(choice)
            conversation['choices'] = conversation['choices'][-128:]
            self._commit(data)
            return copy.deepcopy(choice)

    def get_choice(self, conversation_id: str, choice_id: str) -> dict:
        identity(choice_id)
        result = next((row for row in self.snapshot(conversation_id)['choices'] if row['id'] == choice_id), None)
        if result is None: raise ValueError('This sound choice expired. Refresh the sounds menu.')
        return result

    def record(self, conversation_id: str, choice_id: str, decision: str, request_id: str, owner: str) -> dict:
        identity(owner); identity(request_id)
        if decision not in ('good', 'skip'): raise ValueError('Choose Good match or Skip.')
        fingerprint = hashlib.sha256(json.dumps([conversation_id, choice_id, decision]).encode()).hexdigest()
        key = json.dumps([owner, request_id])
        with self._lock:
            prior = self._data['receipts'].get(key)
            if prior:
                if prior['fingerprint'] != fingerprint: raise ValueError('Sound rating request was reused.')
                return copy.deepcopy(prior['result'])
            choice = self.get_choice(conversation_id, choice_id)
            data = copy.deepcopy(self._data)
            records = data['conversations'][conversation_id]['feedback']
            record = next((r for r in records if r['choice']['id'] == choice_id), None)
            if record is None:
                record = {'choice': choice, 'good': False, 'skip': False, 'updated_at': time.time()}
                records.append(record)
            record[decision] = True
            record['updated_at'] = time.time()
            data['conversations'][conversation_id]['feedback'] = records[-128:]
            result = {'choice_id': choice_id, 'good': record['good'], 'skip': record['skip']}
            data['receipts'][key] = {'fingerprint': fingerprint, 'result': result}
            self._commit(data)
            return result

    def latest(self, conversation_id: str) -> list[dict]:
        latest = {}
        for row in self.snapshot(conversation_id)['choices']:
            latest[row['layer']] = row
        return list(latest.values())

    def suppressed(self, conversation_id: str, session: int, reply_id: str, layer: str) -> bool:
        return any(r['skip'] and r['choice']['session_generation'] == session
                   and r['choice']['reply_id'] == reply_id and r['choice']['layer'] == layer
                   for r in self.snapshot(conversation_id)['feedback'])

    def bonus(self, asset_id: str, tokens: set[str]) -> int:
        with self._lock:
            return 2 if any(r['good'] and r['choice']['asset_id'] == asset_id
                            and tokens.intersection(r['choice']['tokens'])
                            for c in self._data['conversations'].values() for r in c['feedback']) else 0
