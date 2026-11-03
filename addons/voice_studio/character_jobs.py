"""Durable request-scoped candidate jobs, independent of the desktop UI draft."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Callable
import uuid
from .library import atomic_json, read_json, voice_reference_id
from .models import DesignRequest
from .models import ProviderError


@dataclass(frozen=True)
class CharacterJob:
    id: str
    operation_id: str
    character_id: str
    source_revision: int
    kind: str
    status: str
    candidates: tuple[dict, ...] = ()
    error: str = ''

    def public_dict(self):
        return {**asdict(self), 'candidates': [{'id': c['id'], 'name': c.get('name', ''),
            'saved': bool(c.get('saved_path')),
            'voice_id': voice_reference_id(c['saved_path']) if c.get('saved_path') else '',
            'available': Path(c.get('saved_path') or c.get('path', '')).is_file()} for c in self.candidates]}


class CharacterJobs:
    def __init__(self, path: Path, spawn: Callable):
        self.path, self.spawn = path, spawn
        self._lock = threading.RLock()
        self._closed = False
        self._state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'jobs': {}}
        if self._state.get('version') != 1 or not isinstance(self._state.get('jobs'), dict):
            raise ValueError('Unsupported character job storage.')
        recovered = copy.deepcopy(self._state)
        for row in recovered['jobs'].values():
            if row['status'] in {'queued', 'running'}:
                row.update(status='unknown', error='NC restarted before completion was confirmed. Check the provider before trying again.')
        if recovered != self._state:
            self._commit(recovered)

    def _commit(self, state):
        atomic_json(self.path, state)
        self._state = state

    def snapshot(self, identity: str) -> CharacterJob:
        with self._lock:
            row = self._state['jobs'].get(identity)
            if row is None:
                raise KeyError('Character job not found.')
            values = {key: copy.deepcopy(row[key]) for key in CharacterJob.__dataclass_fields__}
            values['candidates'] = tuple(values['candidates'])
            return CharacterJob(**values)

    def snapshots(self):
        with self._lock:
            return tuple(self.snapshot(identity) for identity in self._state['jobs'])

    def submit(self, operation_id: str, character_id: str, expected_revision: int,
               kind: str, request: dict, generate: Callable) -> CharacterJob:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', operation_id) or kind not in {'voice', 'portrait'}:
            raise ValueError('Invalid character job request.')
        captured = copy.deepcopy(request)
        fingerprint = hashlib.sha256(json.dumps([character_id, expected_revision, kind, captured],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            if self._closed:
                raise ValueError('Character jobs are shutting down.')
            previous = next((row for row in self._state['jobs'].values() if row['operation_id'] == operation_id), None)
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise ValueError('Operation identity already used for a different request.')
                return self.snapshot(previous['id'])
            if sum(row['status'] in {'queued', 'running'} for row in self._state['jobs'].values()) >= 2:
                raise ValueError('Two character generations are already pending. Wait for them to finish.')
            job = CharacterJob(uuid.uuid4().hex, operation_id, character_id, expected_revision, kind, 'queued')
            state = copy.deepcopy(self._state)
            state['jobs'][job.id] = {**asdict(job), 'fingerprint': fingerprint}
            self._commit(state)  # Durable intent before any provider submission.

        def run(*_args):
            with self._lock:
                if self._closed or self.snapshot(job.id).status != 'queued':
                    return
                self._change(job.id, status='running')
            completed = False
            try:
                candidates = generate(captured)
                completed = True
                if not candidates:
                    raise ValueError('No candidates returned.')
                with self._lock:
                    if not self._closed and self.snapshot(job.id).status == 'running':
                        self._change(job.id, status='ready', candidates=list(candidates))
            except Exception as exc:
                with self._lock:
                    if self.snapshot(job.id).status == 'running':
                        unknown = completed or bool(getattr(exc, 'unknown', False))
                        # Provider bodies can contain private details. Only surface our own
                        # validation messages or the fixed HTTP status from the client.
                        reason = str(exc).strip()[:240] if type(exc) is ValueError else ''
                        if isinstance(exc, ProviderError) and exc.status in {401, 403, 409, 422, 429}:
                            reason = f'Voice provider HTTP {exc.status}. ' + {
                                401: 'Check credentials.', 403: 'Check API permissions.',
                                409: 'Voice design or model is unavailable.',
                                422: 'Check voice description and preview dialogue.',
                                429: 'Rate limit or quota reached.',
                            }[exc.status]
                        self._change(job.id, status='unknown' if unknown else 'failed',
                            error='Provider outcome is uncertain. Check before trying again.' if unknown
                            else reason or 'Generation failed. Check the configured provider and try a new request.')
        try:
            self.spawn('chat-character-' + kind + ':' + job.id, run)
        except Exception:
            with self._lock:
                self._change(job.id, status='failed', error='Could not start the generation worker.')
        return self.snapshot(job.id)

    def _change(self, identity, **patch):
        state = copy.deepcopy(self._state)
        state['jobs'][identity].update(patch)
        self._commit(state)

    def cancel(self, identity):
        with self._lock:
            job = self.snapshot(identity)
            if job.status in {'queued', 'running'}:
                self._change(identity, status='cancelled', candidates=[])
            return self.snapshot(identity)

    def close(self):
        with self._lock:
            self._closed = True
            for identity in tuple(self._state['jobs']):
                self.cancel(identity)


class CharacterVoiceJobs:
    """Request-local adapter over the existing creation clients and library."""
    def __init__(self, controller):
        self.controller = controller
        self.jobs = CharacterJobs(controller.library.storage / 'chat-character-jobs.json', controller.context.tasks.spawn)

    def _configuration(self):
        # Read settings without loading/replacing the desktop's editable cast/draft.
        saved = read_json(self.controller.library.storage / 'settings.json', {})
        current = self.controller.snapshot()
        return {**current, **saved} if self.controller.batch is None else current

    def invoke(self, payload):
        action = payload.get('action')
        if action == 'list':
            return {'jobs': [job.public_dict() for job in self.jobs.snapshots()]}
        if action == 'providers':
            state = self._configuration()
            cloud = self.controller._cloud_client(state)
            providers = []
            if cloud._key:
                providers.append({'id': 'elevenlabs', 'label': 'ElevenLabs',
                                  'model_id': state['model_id'], 'instruction_mode': 'freeform'})
            for engine in state.get('engines', []):
                if engine.get('ready') and engine.get('id') in {'omnivoice', 'omnivoice-subprocess', 'voxcpm2'}:
                    providers.append({'id': 'local', 'label': engine.get('label', engine['id']),
                        'model_id': engine['id'], 'instruction_mode': engine.get('instruction_mode', 'freeform'),
                        'vocabulary': engine.get('vocabulary', [])})
            return {'providers': providers}
        if action == 'submit':
            state = self._configuration()
            provider = str(payload.get('provider', 'elevenlabs'))
            model = str(payload.get('model_id', state['model_id'] if provider == 'elevenlabs' else state['engine']))
            available = self.invoke({'action': 'providers'})['providers']
            if not any(p['id'] == provider and p['model_id'] == model for p in available):
                raise ValueError('Configure and check this voice-design provider in Voice Studio first.')
            from .voicestudio_client import VoiceStudioClient
            client = (VoiceStudioClient(state['local_url'], self.controller.library.storage)
                      if provider == 'local' else self.controller._cloud_client(state))
            request = DesignRequest(str(payload['character_id']), str(payload['name'])[:80],
                str(payload['voice_description'])[:5000], str(payload['preview_text'])[:5000],
                provider, model, client.endpoint, str(payload.get('instruction', ''))[:5000],
                language=str(payload.get('language', 'en'))[:40])
            def generate(captured):
                candidates = client.design(DesignRequest(**captured))
                result = []
                for index, candidate in enumerate(candidates, 1):
                    active = next((j for j in self.jobs.snapshots() if j.operation_id == payload['operation_id']), None)
                    if active is None or active.status != 'running':
                        return []
                    name = f"{captured['name']} — Voice {index}"
                    if payload.get('automatic') is True:
                        # Keep alternatives as job candidates. Auto mode publishes only
                        # its selected valid sample through the existing publish action.
                        result.append({**asdict(candidate), 'name': name})
                        continue
                    record = self.controller.library.publish_audio(Path(candidate.path).read_bytes(),
                        name, candidate.id, captured)
                    result.append({**asdict(candidate), 'name': record.name, 'saved_path': record.path})
                return result
            return self.jobs.submit(str(payload['operation_id']), request.character_id,
                int(payload['expected_revision']), 'voice', asdict(request), generate).public_dict()
        job = self.jobs.snapshot(str(payload.get('job_id', '')))
        if action == 'get':
            return job.public_dict()
        if action == 'cancel':
            return self.jobs.cancel(job.id).public_dict()
        if job.character_id != payload.get('character_id') or job.status != 'ready':
            raise ValueError('The voice candidate does not belong to this character or is not ready.')
        candidate = next((c for c in job.candidates if c['id'] == payload.get('candidate_id')), None)
        if candidate is None:
            raise ValueError('Voice candidate not found.')
        path = Path(candidate.get('saved_path') or candidate['path']).resolve()
        expected_root = self.controller.library.root if candidate.get('saved_path') else self.controller.library.storage / 'candidates'
        if path.parent != expected_root.resolve() or not path.is_file():
            raise ValueError('Voice candidate is unavailable.')
        if action == 'media':
            return {'path': str(path)}  # Host-internal; never serialized to a phone.
        if action == 'publish':
            record = (self.controller.library.inspect(path) if candidate.get('saved_path') else
                self.controller.library.publish_audio(path.read_bytes(), candidate.get('name') or candidate['request']['name'],
                    candidate['id'], candidate['request']))
            return {'path': record.path, 'name': record.name}
        raise ValueError('Unknown character voice operation.')
