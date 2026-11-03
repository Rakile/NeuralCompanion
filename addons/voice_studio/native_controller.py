"""Thread-safe addon state. Blocking actions are called only by native workers."""
from __future__ import annotations

import copy
from collections import deque
from dataclasses import asdict
from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit
import uuid

from .audition import AuditionService
from .batch import BatchCoordinator, CloudDialogue
from .elevenlabs_client import ElevenLabsDesignClient
from .library import LibraryRepository, atomic_json, read_json
from .models import DesignRequest, EngineCapabilities
from .prompts import PromptService
from .voicestudio_client import VoiceStudioClient

SAMPLE = 'Keep the lantern steady. We have crossed harder country than this, and I intend to bring every one of you home. Tell me what you saw beyond the ridge.'
ACTION_NAMES = ('refresh', 'save_voice_details', 'remove_voice', 'restore_voice', 'draft', 'save_cast', 'load_cast', 'remove_character', 'add_character', 'generate', 'generate_all', 'save_candidate', 'play_candidate',
                'play_original', 'test', 'play_test', 'export_test', 'refine_test', 'refine_voice', 'apply_refinement',
                'keep_original', 'adapt_voice', 'check_cloud', 'check_local', 'save_settings', 'dialogue', 'cleanup', 'discard_cloud', 'retry', 'resolve', 'stop', 'pause')


class VoiceStudioController:
    def __init__(self, context):
        self.context = context
        self.library = LibraryRepository(context.paths.app_root, context.paths.storage_root)
        self.prompts = PromptService(context.capabilities)
        self.audition = AuditionService(self.library, context.services,
                                       getattr(context.capabilities, 'runtime_config', None))
        self.batch: BatchCoordinator | None = None
        self.cloud: CloudDialogue | None = None
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._cancel = threading.Event()
        self._active_request = ''
        self._cancelled_requests: deque[str] = deque(maxlen=32)
        self._pause = threading.Event()
        self._session_key = ''
        self._proposal = None
        self._revision = 0
        self._voice_revision = 0
        self._closed = False
        self._state = {
            'busy': False, 'closed': False, 'status': 'Ready. Refresh the library to discover NC WAVs.',
            'tab': 'Create Voices', 'provider': 'elevenlabs', 'model_id': 'eleven_ttv_v3',
            'tts_model': 'eleven_multilingual_v2', 'local_url': 'http://127.0.0.1:3900',
            'engine': '', 'instruction': '', 'language': 'en', 'automatic': False,
            'key_source': 'nc', 'key_present': False, 'brief': '', 'count': 10,
            'characters': [self.new_character()], 'character_index': 0, 'jobs': [], 'candidate_index': 0,
            'voices': [], 'selected_voice': '', 'test_text': '', 'test_result': {}, 'refinement': '',
            'dialogue_text': '', 'cleanup_records': [], 'engines': [], 'local_status': 'Not connected. Install and start VoiceStudio yourself later.',
            'cloud_status': 'Not checked', 'destination': str(self.library.root),
            'cast_path': str(self.library.storage / 'cast.json'),
        }

    @staticmethod
    def new_character():
        return {'id': uuid.uuid4().hex, 'name': 'New character', 'description': '',
                'voice_description': 'A warm, clear character voice with natural, measured delivery.', 'preview_text': SAMPLE}

    def snapshot(self):
        with self._lock:
            state = copy.deepcopy(self._state)
        label, backend = self.audition.loaded_backend()
        state['audition_ready'] = backend is not None
        state['audition_backend_label'] = label
        return state

    def _update(self, **values):
        with self._lock:
            if not self._closed:
                self._state.update(values)

    def set_value(self, key, value):
        with self._lock:
            if self._closed:
                return
            if key == 'session_key':
                self._session_key = str(value)
                self._state['key_present'] = bool(value)
                return
            editable = {'tab', 'provider', 'model_id', 'tts_model', 'local_url', 'engine', 'instruction', 'language',
                        'automatic', 'key_source', 'brief', 'count', 'character_index', 'candidate_index', 'selected_voice',
                        'test_text', 'dialogue_text'}
            if key.startswith('character.'):
                if self._state['busy']:
                    return
                field = key.split('.', 1)[1]
                if field not in {'name', 'description', 'voice_description', 'preview_text', 'local_instruction'}:
                    raise ValueError('Unknown character field.')
                self._state['characters'][self._state['character_index']][field] = str(value)[:5000]
                self._voice_revision += 1
                return
            if key not in editable:
                raise ValueError('Unknown Voice Studio field.')
            if key in {'provider', 'engine', 'character_index', 'model_id', 'local_url'} and self._state['busy']:
                return
            if key in {'character_index', 'candidate_index', 'count'}:
                value = int(value)
                if key == 'count': value = max(1, min(50, value))
                elif value < 0: return
                if key == 'character_index' and value >= len(self._state['characters']): return
            if key == 'test_text': self._revision += 1
            if key == 'character_index':
                self._voice_revision += 1
                self._state['candidate_index'] = 0
            if key in {'provider', 'engine', 'language'}:
                self._voice_revision += 1
            if key == 'provider' and value not in {'elevenlabs', 'local'}: return
            self._state[key] = value

    def close(self):
        self._cancel.set()
        with self._lock:
            self._closed = True
            self._session_key = ''
            self._state.update(closed=True, busy=False, refinement='', status='Addon closed.')

    def _load(self):
        if self.batch is not None:
            return
        self.batch = BatchCoordinator(self.library)
        self.cloud = CloudDialogue(self.library)
        settings = read_json(self.library.storage / 'settings.json', {})
        allowed = {'provider', 'model_id', 'tts_model', 'local_url', 'engine', 'language', 'automatic', 'key_source'}
        if isinstance(settings, dict):
            self._update(**{k: v for k, v in settings.items() if k in allowed})
        cast = read_json(self.library.storage / 'cast.json', [])
        restored = self._cast_characters(cast if self._valid_cast(cast) else [])
        if restored:
            self._update(characters=restored, character_index=0)
        self._sync_jobs()

    @staticmethod
    def _valid_cast(cast: object) -> bool:
        return (isinstance(cast, list) and bool(cast)
                and all(isinstance(row, dict) and all(isinstance(row.get(key), str)
                        for key in ('id', 'name', 'description', 'voice_description', 'preview_text'))
                        and bool(row['id']) and isinstance(row.get('local_instruction', ''), str) for row in cast)
                and len({row['id'] for row in cast}) == len(cast))

    def _cast_characters(self, cast: list[dict]) -> list[dict]:
        # Restore captured drafts for review, never auto-run stored jobs.
        rows = self.batch.snapshot()
        removed = {row['id'] for row in rows if row.get('removed_from_cast') is True}
        restored = []
        for row in rows:
            if row['id'] in removed:
                continue
            request = row.get('request', {})
            if all(key in request for key in ('character_id', 'name', 'voice_description', 'preview_text')):
                restored.append({'id': request['character_id'], 'name': request['name'], 'description': '',
                                 'voice_description': request['voice_description'], 'preview_text': request['preview_text'],
                                 'local_instruction': request.get('instruction', '')})
        if cast:
            # Preserve archived jobs too: unresolved requests must stay reachable.
            ids = {r['id'] for r in cast}
            restored = [r for r in cast if r['id'] not in removed] + [r for r in restored if r['id'] not in ids]
        return restored

    def _sync_jobs(self):
        self._update(jobs=self.batch.snapshot(), cleanup_records=self.cloud.records())

    def _refresh(self):
        rows = [r.to_dict() for r in self.library.scan()]
        state = self.snapshot()
        selected = state['selected_voice']
        if selected not in [r['path'] for r in rows]:
            selected = next((r['path'] for r in rows if r['valid'] and not r['archived']), '')
        self._update(voices=rows, selected_voice=selected)

    def _cloud_key(self, state=None):
        state = self.snapshot() if state is None else state
        key = self._session_key if state['key_source'] == 'session' else ''
        if state['key_source'] == 'nc':
            service = self.context.services.get('elevenlabs_tts')
            getter = getattr(service, 'snapshot', None)
            if callable(getter): key = str(getter().get('api_key') or '')
        return key

    def _cloud_client(self, state=None):
        return ElevenLabsDesignClient(self._cloud_key(state), self.library.storage)

    def soundscape_client(self):
        """Internal provider port. Credentials never cross the phone gateway."""
        from addons.main_chat_remote.soundscape.elevenlabs import ElevenLabsSoundClient
        return ElevenLabsSoundClient(self._cloud_key())

    def _client(self, state):
        if state['provider'] == 'local':
            return VoiceStudioClient(state['local_url'], self.library.storage)
        return self._cloud_client()

    def _selected_candidate(self, state):
        character = state['characters'][state['character_index']]
        return self.batch.candidate(character['id'], state['candidate_index'])

    def action(self, name: str, payload=None):
        if name not in ACTION_NAMES:
            raise ValueError('Unknown Voice Studio action.')
        payload = dict(payload or {})
        request_id = str(payload.get('request_id') or '')
        if name == 'stop':
            with self._lock:
                if request_id and request_id != self._active_request:
                    # The worker may not have started yet. Never stop a different job.
                    self._cancelled_requests.append(request_id)
                    return
                self._cancel.set()
            self._update(status='Stopping playback / finishing any in-flight generation. Completed work is retained.')
            return
        if name == 'pause':
            self._pause.set()
            self._update(status='Paused after the current character. Generate all continues queued work.')
            return
        if self._closed or not self._operation.acquire(blocking=False):
            return
        with self._lock:
            self._active_request = request_id
            self._cancel.clear()
            if request_id and request_id in self._cancelled_requests:
                self._cancelled_requests.remove(request_id)
                self._cancel.set()
        self._pause.clear()
        self._update(busy=True, status='Working…')
        try:
            if self._cancel.is_set():
                self._update(status='Preview cancelled before it started.')
                return
            self._load()
            self._execute(name, payload)
            atomic_json(self.library.storage / 'cast.json', self.snapshot()['characters'])
            self._sync_jobs()
        except Exception as error:
            self._update(status=str(error))
            if self.batch is not None:
                self._sync_jobs()
        finally:
            with self._lock:
                self._active_request = ''
            self._update(busy=False)
            self._operation.release()

    def _execute(self, name, payload):
        state = self.snapshot()
        character = state['characters'][state['character_index']]
        if name == 'refresh':
            self._refresh()
            self._update(status='Voice Library refreshed.')
        elif name in {'save_voice_details', 'remove_voice', 'restore_voice'}:
            reference = Path(str(payload.get('reference', state['selected_voice'])))
            if name == 'save_voice_details':
                self.library.update_metadata(reference, description=payload.get('description'), notes=payload.get('notes'))
                status = 'Voice description and notes saved.'
            else:
                self.library.update_metadata(reference, archived=name == 'remove_voice')
                status = ('Voice removed from library. Recording retained for saved personas; Show removed to restore.'
                          if name == 'remove_voice' else 'Voice restored to library.')
            self._refresh()
            self._update(status=status)
        elif name == 'add_character':
            rows = state['characters'] + [self.new_character()]
            self._update(characters=rows, character_index=len(rows)-1, candidate_index=0, status='Edit the new character.')
        elif name == 'save_cast':
            self._update(status='Character drafts saved locally.')
        elif name == 'load_cast':
            if payload.get('confirmed') is not True:
                raise ValueError('Confirm replacing current edits with the saved cast first.')
            cast = read_json(self.library.storage / 'cast.json', None)
            if not self._valid_cast(cast):
                raise ValueError('The saved cast is missing or invalid. Current drafts were kept.')
            rows = self._cast_characters(cast)
            self._voice_revision += 1
            self._proposal = None
            self._update(characters=rows or [self.new_character()], character_index=0, candidate_index=0,
                         refinement='', status='Saved cast drafts loaded. No voices generated.')
        elif name == 'remove_character':
            if payload.get('confirmed') is not True:
                raise ValueError('Confirm removing the selected draft first.')
            identity = str(payload.get('character_id') or '')
            if not identity or not any(row['id'] == identity for row in state['characters']):
                raise ValueError('The selected draft is no longer in this cast.')
            self.batch.remove_from_cast(identity)
            rows = [row for row in state['characters'] if row['id'] != identity] or [self.new_character()]
            selected = next((i for i, row in enumerate(rows) if row['id'] == character['id']),
                            min(state['character_index'], len(rows) - 1))
            self._voice_revision += 1
            self._proposal = None
            self._update(characters=rows, character_index=selected, candidate_index=0, refinement='',
                         status='Character draft removed. Saved recordings and job history were kept.')
        elif name == 'draft':
            if any(row['state'] == 'unknown' for row in self.batch.snapshot()):
                raise ValueError('Resolve uncertain character jobs before replacing the cast.')
            captured = self.prompts.capture()
            rows = self.prompts.draft(state['brief'], int(state['count']), captured)
            if self._cancel.is_set():
                self._update(status='Draft cancelled; existing characters kept.')
                return
            self._voice_revision += 1
            self._update(characters=[asdict(row) for row in rows], character_index=0, candidate_index=0, status='Drafts ready for editing. No voices generated yet.')
        elif name in {'generate', 'generate_all', 'retry', 'resolve'}:
            atomic_json(self.library.storage / 'cast.json', state['characters'])
            if name in {'retry', 'resolve'}:
                self.batch.retry(character['id'], resolved=name == 'resolve')
            if any(row['state'] == 'unknown' for row in self.batch.snapshot()):
                raise ValueError('An earlier request has an uncertain outcome. Check the provider, then use “Allow retry after checking”.')
            if name == 'generate':
                selected_job = next((row for row in self.batch.snapshot()
                                     if row['id'] == character['id']), {})
                if selected_job.get('state') == 'failed':
                    self.batch.retry(character['id'])
            characters = state['characters'] if name == 'generate_all' else [character]
            client = self._client(state)
            requests = [DesignRequest(row['id'], row['name'], row['voice_description'], row['preview_text'], state['provider'],
                        state['engine'] if state['provider'] == 'local' else state['model_id'],
                        state['local_url'] if state['provider'] == 'local' else client.endpoint,
                        row.get('local_instruction', ''), uuid.uuid4().int % 2147483647, state['language']) for row in characters]
            self.batch.run(requests, client, bool(state['automatic']), self._cancel, self._pause, self._sync_jobs)
            self._refresh()
            self._update(status='Batch stopped. Review character status; successful recordings are retained.')
        elif name == 'save_candidate':
            record = self.batch.save(character['id'], state['candidate_index'])
            self._refresh()
            self._update(selected_voice=record.path, status='Saved and verified: ' + Path(record.path).name)
        elif name == 'dialogue':
            candidate = self._selected_candidate(state)
            record = self.cloud.generate(candidate, state['dialogue_text'], state['tts_model'], self._cloud_client(), self._cancel)
            self._refresh()
            self._update(selected_voice=record.path, status='Dialogue saved. Check temporary-voice cleanup status in Settings.')
        elif name == 'cleanup':
            self.cloud.cleanup(str(payload.get('id', '')), self._cloud_client())
            self._update(status='Temporary cloud voice cleanup completed.')
        elif name == 'discard_cloud':
            self.cloud.discard(str(payload.get('id', '')), self._cloud_client(), confirmed=payload.get('confirmed') is True)
            self._update(status='Tracked temporary voice deleted. Generate a new candidate for new dialogue.')
        elif name in {'play_original', 'play_candidate', 'play_test'}:
            if name == 'play_original':
                path = self.library.inspect(Path(str(payload.get('reference', state['selected_voice'])))).path
            elif name == 'play_candidate': path = self._selected_candidate(state).path
            else: path = state['test_result'].get('path', '')
            if not path: raise ValueError('Generate/select a recording first.')
            self.audition.play(path, self._cancel)
            self._update(status='Playback stopped.' if self._cancel.is_set() else 'Playback finished.')
        elif name == 'test':
            # Persona auditions capture their own input without editing Studio's draft.
            result = self.audition.generate(str(payload.get('reference', state['selected_voice'])),
                                           str(payload.get('text', state['test_text'])), self._revision, self._cancel)
            self._update(test_result=asdict(result), status='Test ready. Play it separately from the original reference.')
        elif name == 'export_test':
            source = state['test_result'].get('path', '')
            parsed = urlsplit(str(payload.get('path', '')))
            target = unquote(parsed.path).lstrip('/') if parsed.scheme == 'file' else str(payload.get('path', ''))
            target = Path(target)
            if not source or not target.is_absolute() or target.suffix.lower() != '.wav':
                raise ValueError('Choose a new absolute WAV filename for the test recording.')
            with target.open('xb') as output:
                output.write(Path(source).read_bytes())
            self._update(status='Test recording exported separately.')
        elif name in {'refine_test', 'refine_voice', 'adapt_voice'}:
            purpose = 'voice' if name == 'refine_voice' else 'speech'
            if name == 'adapt_voice': purpose = 'instruction'
            text = character['voice_description'] if purpose != 'speech' else state['test_text']
            revision = self._voice_revision if purpose != 'speech' else self._revision
            if purpose == 'instruction':
                engine = next((EngineCapabilities(**e) for e in state['engines'] if e['id'] == state['engine']), None)
                if engine is None: raise ValueError('Check the local connection and select a supported engine first.')
                proposal = self.prompts.adapt(text, revision, engine, state['language'])
            else:
                proposal = self.prompts.refine(text, revision, purpose)
            with self._lock:
                if not self._closed and not self._cancel.is_set():
                    self._proposal = proposal
                    self._state.update(refinement=proposal.suggested, status='Review the suggestion before applying it.')
        elif name == 'apply_refinement':
            proposal = self._proposal
            if proposal is None: raise ValueError('Refine text first.')
            with self._lock:
                if proposal.purpose in {'voice', 'instruction'}:
                    row = self._state['characters'][self._state['character_index']]
                    field = 'local_instruction' if proposal.purpose == 'instruction' else 'voice_description'
                    row[field] = proposal.apply(self._voice_revision, row['voice_description'])
                    self._voice_revision += 1
                else:
                    self._state['test_text'] = proposal.apply(self._revision, self._state['test_text'])
                    self._revision += 1
            self._proposal = None
            self._update(refinement='', status='Refinement applied. Speech starts only when you generate a test.')
        elif name == 'keep_original':
            self._proposal = None
            self._update(refinement='', status='Original text kept.')
        elif name == 'check_cloud':
            self._cloud_client().account()
            self._update(cloud_status='Connected. Generation uses ElevenLabs credits.', status='ElevenLabs connection checked.')
        elif name == 'check_local':
            client = VoiceStudioClient(state['local_url'], self.library.storage)
            engines = client.capabilities()
            selected = state['engine'] if state['engine'] in [e.id for e in engines] else next((e.id for e in engines), '')
            self._update(engines=[asdict(e) for e in engines], engine=selected,
                         local_status=f'VoiceStudio {client.version}. Engines must be installed and loaded manually.', status='Local connection checked; nothing installed or started.')
        elif name == 'save_settings':
            keys = ('provider', 'model_id', 'tts_model', 'local_url', 'engine', 'language', 'automatic', 'key_source')
            atomic_json(self.library.storage / 'settings.json', {k: state[k] for k in keys})
            self._update(status='Settings saved. Session-only API keys are never stored.')
