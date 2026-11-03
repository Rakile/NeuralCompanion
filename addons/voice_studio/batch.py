"""Sequential jobs and a separate, account-bound cloud ownership ledger."""
from __future__ import annotations

from dataclasses import asdict
import copy
from pathlib import Path
import threading

from .library import LibraryRepository, atomic_json, read_json, pcm_wav
from .cloud_staging import recover_stage, retain_response
from .models import DesignRequest, ProviderError, VoiceCandidate


def candidate_from_dict(row: dict) -> VoiceCandidate:
    return VoiceCandidate(row['id'], row['path'], DesignRequest(**row['request']), row.get('generated_voice_id', ''))


class BatchCoordinator:
    def __init__(self, library: LibraryRepository):
        self.library = library
        self.path = library.storage / 'jobs.json'
        self._lock = threading.RLock()
        stored = read_json(self.path, [])
        self.jobs = {r['id']: r for r in stored if isinstance(r, dict) and isinstance(r.get('id'), str)} if isinstance(stored, list) else {}
        for row in self.jobs.values():
            if row.get('state') == 'generating':
                row.update(state='unknown', error='NC stopped during generation. Check the service before resolving this job.')

    def snapshot(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(list(self.jobs.values()))

    def _persist(self):
        atomic_json(self.path, list(self.jobs.values()))

    def remove_from_cast(self, identity: str) -> None:
        """Hide a finished character without deleting its job or audio history."""
        with self._lock:
            row = self.jobs.get(identity)
            if row is None:
                return
            if row.get('state') not in {'draft', 'saved', 'failed'}:
                raise ValueError('This character has unfinished generation work. Finish or resolve it before removing the draft.')
            previous = row.get('removed_from_cast')
            row['removed_from_cast'] = True
            try:
                self._persist()
            except Exception:
                if previous is None:
                    row.pop('removed_from_cast', None)
                else:
                    row['removed_from_cast'] = previous
                raise

    def run(self, requests, client, automatic: bool, cancel: threading.Event, pause: threading.Event, changed=lambda: None):
        requests = tuple(requests)
        with self._lock:
            for request in requests:
                if request.character_id not in self.jobs:
                    self.jobs[request.character_id] = {'id': request.character_id, 'request': asdict(request),
                        'state': 'queued', 'error': '', 'candidates': []}
            self._persist()
        for request in requests:
            if cancel.is_set() or pause.is_set():
                break
            with self._lock:
                row = self.jobs.get(request.character_id)
                if row and row['state'] not in {'queued', 'draft'}:
                    continue
                if row and row.get('resume_captured', True):
                    captured = DesignRequest(**row['request'])
                    if (captured.provider, captured.model_id, captured.endpoint) != (request.provider, request.model_id, request.endpoint):
                        raise ValueError('Queued work belongs to a different provider, model or address. Restore its settings before continuing.')
                    request = captured
                self.jobs[request.character_id] = row = {'id': request.character_id, 'request': asdict(request),
                    'state': 'generating', 'error': '', 'candidates': []}
                self._persist()
            changed()
            try:
                candidates = client.design(request)
                with self._lock:
                    row.update(state='review', candidates=[asdict(c) for c in candidates])
                    self._persist()
                if automatic and not cancel.is_set():
                    self.save(request.character_id, 0)
            except Exception as error:
                with self._lock:
                    row.update(state='unknown' if getattr(error, 'unknown', False) else 'failed', error=str(error))
                    self._persist()
                changed()
                # Unknown outcomes stop the batch, including local jobs that may still run.
                if row['state'] == 'unknown':
                    break
            changed()
            if not automatic and row['state'] == 'review':
                break

    def retry(self, identity: str, *, resolved=False):
        with self._lock:
            row = self.jobs[identity]
            if row['state'] == 'unknown' and not resolved:
                raise ValueError('Check completion in the provider before explicitly resolving an uncertain job.')
            if row['state'] not in {'failed', 'unknown', 'review', 'saved'}:
                raise ValueError('This job cannot be retried now.')
            row.update(state='queued', error='', resume_captured=False)
            self._persist()

    def candidate(self, identity: str, index: int) -> VoiceCandidate:
        with self._lock:
            row = self.jobs[identity]
            return candidate_from_dict(copy.deepcopy(row['candidates'][index]))

    def save(self, identity: str, index: int):
        candidate = self.candidate(identity, index)
        record = self.library.publish_audio(Path(candidate.path).read_bytes(), candidate.request.name,
                                            candidate.id, asdict(candidate.request))
        with self._lock:
            self.jobs[identity].update(state='saved', saved_path=record.path)
            self._persist()
        return record


class CloudDialogue:
    def __init__(self, library: LibraryRepository):
        self.library = library
        self.path = library.storage / 'cloud-ownership.json'
        stored = read_json(self.path, {})
        self._records = stored if isinstance(stored, dict) else {}

    def records(self) -> list[dict]:
        return copy.deepcopy(list(self._records.values()))

    def _persist(self):
        atomic_json(self.path, self._records)

    def generate(self, candidate: VoiceCandidate, text: str, model: str, client, cancel=None):
        if candidate.request.provider != 'elevenlabs' or not text.strip():
            raise ValueError('Longer dialogue needs an ElevenLabs candidate and text.')
        account = client.account()
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Dialogue cancelled before cloud creation.')
        row = self._records.get(candidate.id)
        if row and row['state'] == 'discarded':
            raise ValueError('This temporary voice was discarded. Generate a new candidate for new dialogue.')
        if row and row['account'] != account:
            raise ValueError('This temporary voice belongs to another ElevenLabs account.')
        if row and row['state'] in {'creation_intent', 'unknown'}:
            raise ProviderError('Cloud creation outcome is unknown. Review the ElevenLabs account; do not create again automatically.', unknown=True)
        if row and row['state'] == 'synthesis_intent':
            stage = self.library.storage / ('dialogue-' + candidate.id + '.wav')
            if recover_stage(stage, row, pcm_wav) is not None:
                row.update(state='audio_staged', staged_path=str(stage))
                self._persist()
        if row and row['state'] in {'synthesis_intent', 'synthesis_unknown'}:
            raise ProviderError('Dialogue outcome is uncertain. Review ElevenLabs generation history before making another paid request. The temporary voice is retained.', unknown=True)
        if row and row.get('saved_path'):
            record = self.library.inspect(Path(row['saved_path']))
            if record.fingerprint != row['fingerprint']:
                raise ValueError('Saved dialogue changed; automatic cleanup is blocked.')
            if row['state'] != 'cleaned':
                self.cleanup(candidate.id, client)
            return record
        if row is None:
            row = {'id': candidate.id, 'account': account, 'state': 'creation_intent', 'voice_id': '',
                   'name': candidate.request.name, 'text': text, 'model': model}
            self._records[candidate.id] = row
            self._persist()
            try:
                row['voice_id'] = client.create_voice(candidate, candidate.id)
                row['state'] = 'created'
                self._persist()
            except Exception:
                row['state'] = 'unknown'
                self._persist()
                raise
        # Resume the captured dialogue, never quietly substitute newly edited text.
        if row['state'] != 'audio_staged':
            if cancel is not None and cancel.is_set():
                raise RuntimeError('Dialogue cancelled. The tracked temporary voice is retained; resume or discard it in Settings.')
            row['state'] = 'synthesis_intent'
            self._persist()
            try:
                data = client.synthesize(row['voice_id'], row['text'], row['model'])
            except Exception as error:
                row['state'] = 'created' if isinstance(error, ProviderError) and not error.unknown else 'synthesis_unknown'
                self._persist()
                raise
            # Keep a verified, identity-bound response even if local conversion fails.
            stage = self.library.storage / ('dialogue-' + candidate.id + '.wav')
            retain_response(stage, row, data)
            recover_stage(stage, row, pcm_wav)
            row.update(state='audio_staged', staged_path=str(stage))
            self._persist()
        stage = Path(row['staged_path'])
        if recover_stage(stage, row, pcm_wav) is None:
            raise ValueError('Dialogue recovery audio is missing. Restore it before continuing.')
        data = stage.read_bytes()
        record = self.library.publish_audio(data, candidate.request.name + '_dialogue', candidate.id,
                                           {**asdict(candidate.request), 'preview_text': row['text']})
        row.update(state='cleanup_pending', saved_path=record.path, fingerprint=record.fingerprint)
        self._persist()
        try:
            self.cleanup(candidate.id, client)
        except Exception as error:
            row['error'] = str(error)
            self._persist()
        return record

    def cleanup(self, identity: str, client):
        row = self._records[identity]
        if row['state'] == 'cleaned':
            return
        if row['account'] != client.account():
            raise ValueError('Temporary voice account does not match the current connection.')
        if row['state'] != 'cleanup_pending' or not row.get('voice_id'):
            raise ValueError('Cleanup requires a verified saved dialogue and an exact owned voice ID.')
        record = self.library.inspect(Path(row['saved_path']))
        if record.fingerprint != row['fingerprint']:
            raise ValueError('Saved dialogue changed; cleanup is blocked.')
        client.delete_voice(row['voice_id'])
        row.update(state='cleaned', error='')
        self._persist()

    def discard(self, identity: str, client, *, confirmed=False):
        row = self._records[identity]
        if not confirmed or not row.get('voice_id') or row.get('saved_path'):
            raise ValueError('Explicitly confirm discarding the unsaved dialogue for this tracked temporary voice.')
        if row['account'] != client.account():
            raise ValueError('Temporary voice account does not match the current connection.')
        client.delete_voice(row['voice_id'])
        row.update(state='discarded', error='')
        self._persist()
