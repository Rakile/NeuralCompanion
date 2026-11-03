"""Host adapters for automatic setup, reusing the manual job/media owners."""
from __future__ import annotations

import io
from pathlib import Path
import time
import wave

from addons.multi_persona_roleplay.chat_character_automatic import AutomaticCharacterWorker
from addons.multi_persona_roleplay.voice_routing import VOICE_REFERENCE_BACKENDS, normalize_tts_backend
from addons.voice_studio.library import inspect_wav


def valid_automatic_sample(path: Path) -> bool:
    """Technical audition only; never pretend text analysis ranks voice quality."""
    try:
        if path.stat().st_size > 100 * 1024 * 1024:
            return False
        data = path.read_bytes()
        inspect_wav(data)
        with wave.open(io.BytesIO(data), 'rb') as source:
            width = source.getsampwidth()
            pcm = source.readframes(source.getnframes())
        threshold = max(1, int((1 << (width * 8 - 1)) * .0005))
        return any(abs(int.from_bytes(pcm[i:i + width], 'little', signed=width != 1)
                       - (128 if width == 1 else 0)) > threshold
                   for i in range(0, len(pcm), width))
    except (OSError, ValueError, wave.Error, EOFError):
        return False


class AutomaticCharacterAdapter:
    def __init__(self, host, runtime):
        self.host, self.runtime = host, runtime
        self.worker = AutomaticCharacterWorker(runtime.store, runtime.conversation_id, runtime.spawn,
            runtime._propose, self.prepare, self.lookup, self.finish, self.cancel)

    def readiness(self, kind: str = '') -> str:
        if kind != 'portrait' and normalize_tts_backend(self.runtime.config_get('tts_backend', '')) not in VOICE_REFERENCE_BACKENDS:
            return 'Select a reference-capable desktop TTS engine for character voices.'
        if kind != 'portrait' and self.host._voice_getter() is None:
            return 'Load Voice Studio and configure ElevenLabs.'
        if kind != 'portrait' and not any(p['id'] == 'elevenlabs' for p in self.host._voice({'action': 'providers'})['providers']):
            return 'Configure ElevenLabs in Voice Studio first.'
        from addons.visual_reply.runtime_config import VisualReplyRuntime
        config = dict(self.host._config_snapshot())
        config.update(visual_replies_enabled=True, visual_reply_mode='auto')
        if kind != 'voice' and not VisualReplyRuntime(lambda: config).generation_available():
            return 'Configure a Visual Reply portrait provider first.'
        return ''

    def discover(self, candidate_ids):
        if not candidate_ids or not self.runtime.store.automatic_enabled(self.runtime.conversation_id()):
            return
        # Readiness is checked by the worker too; discovery stays independent of
        # remote provider calls and creates a visible recoverable card immediately.
        if self.runtime.store.accept_automatic(self.runtime.conversation_id(), candidate_ids):
            self.worker.kick()

    def lookup(self, kind, operation):
        rows = (self.host._voice({'action': 'list'})['jobs'] if kind == 'voice' else
                [job.public_dict() for job in self.host._portraits().jobs.snapshots()])
        return next((row for row in rows if row['operation_id'] == operation), None)

    def prepare(self, kind, card, operation):
        reason = self.readiness(kind)
        if reason:
            raise ValueError(reason)
        # Wait for manual jobs to free the existing bounded provider worker slots.
        deadline = time.monotonic() + 120
        while True:
            rows = (self.host._voice({'action': 'list'})['jobs'] if kind == 'voice' else
                    [job.public_dict() for job in self.host._portraits().jobs.snapshots()])
            if sum(j['status'] in {'queued', 'running'} for j in rows) < 2:
                break
            self.worker._check(card.id, card.automation['id'])
            if time.monotonic() >= deadline:
                raise ValueError('Generation queue is busy. Retry this stage after current jobs finish.')
            self.worker._stop.wait(.5)
        self.worker._check(card.id, card.automation['id'])
        if kind == 'voice':
            if not 20 <= len(card.voice_description.strip()) <= 1000 or not 100 <= len(card.preview_text.strip()) <= 1000:
                raise ValueError('Edit the voice prompt (20–1000 characters) and preview dialogue (100–1000), then Remake.')
            provider = next(p for p in self.host._voice({'action': 'providers'})['providers'] if p['id'] == 'elevenlabs')
            return self.host._voice({'action': 'submit', 'character_id': card.id, 'name': card.name,
                'expected_revision': card.revision, 'operation_id': operation, 'automatic': True,
                'provider': 'elevenlabs', 'model_id': provider['model_id'],
                'voice_description': card.voice_description, 'preview_text': card.preview_text})
        config = dict(self.host._config_snapshot())
        config.update(visual_replies_enabled=True, visual_reply_mode='auto')
        return self.host._portraits().submit(operation, card.id, card.revision,
            card.portrait_prompt or card.description, '', runtime_config=config).public_dict()

    def cancel(self, kind, job):
        if kind == 'voice':
            self.host._voice({'action': 'cancel', 'job_id': job['id']})
        else:
            self.host._portraits().jobs.cancel(job['id'])

    def finish(self, kind, job, card):
        if kind == 'portrait':
            candidate = next(iter(job['candidates']), None)
            if candidate is None:
                raise ValueError('No portrait was returned.')
            path = self.host._portraits().candidate_path(card.id, job['id'], candidate['id'])
            return candidate['id'], str(path)
        for candidate in job['candidates']:
            request = {'character_id': card.id, 'job_id': job['id'], 'candidate_id': candidate['id']}
            try:
                path = Path(self.host._voice({**request, 'action': 'media'})['path'])
            except (ValueError, OSError):
                continue
            if not valid_automatic_sample(path):
                continue
            self.worker._check(card.id, card.automation['id'])
            published = self.host._voice({**request, 'action': 'publish'})
            return self.runtime._voice_id(published['path']), published['path'], ''
        raise ValueError('No usable non-silent voice sample returned. Retry voice generation.')
