"""Candidate-only portraits; selecting one is a separate revision-checked action."""
from __future__ import annotations

from pathlib import Path
import uuid
from core.runtime.config import RuntimeConfigService
from .chat_characters import CharacterRevisionConflict


class ChatCharacterPortraits:
    def __init__(self, store, jobs, generate, asset_root: Path):
        self.store, self.jobs, self.generate = store, jobs, generate
        self.asset_root = asset_root.resolve()

    def submit(self, operation_id, character_id, expected_revision, prompt, style, *, runtime_config=None):
        card = self.store.get(character_id)
        if card.revision != expected_revision:
            raise CharacterRevisionConflict('Character changed. Refresh before generating.')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 5000:
            raise ValueError('Enter a portrait prompt under 5001 characters.')
        if style not in {'natural', 'painted', 'illustrated', ''}:
            raise ValueError('Unknown portrait style.')
        # NC snapshots contain nested mapping proxies, which deepcopy cannot copy.
        config = RuntimeConfigService(runtime_config).to_dict() if runtime_config is not None else None
        def generate(captured):
            if config is not None:
                captured = {**captured, 'runtime_config': config}
            path = Path(self.generate(captured)).resolve()
            if not path.is_relative_to(self.asset_root) or not path.is_file():
                raise ValueError('Portrait output is not in managed storage.')
            return [{'id': 'portrait_' + uuid.uuid4().hex, 'path': str(path)}]
        return self.jobs.submit(operation_id, character_id, expected_revision, 'portrait',
                                {'prompt': prompt, 'style': style}, generate)

    def candidate_path(self, character_id, job_id, candidate_id):
        job = self.jobs.snapshot(job_id)
        if job.character_id != character_id or job.kind != 'portrait' or job.status != 'ready':
            raise ValueError('Portrait candidate does not belong to this character or is not ready.')
        candidate = next((c for c in job.candidates if c['id'] == candidate_id), None)
        if candidate is None:
            raise ValueError('Portrait candidate not found.')
        path = Path(candidate['path']).resolve()
        if not path.is_relative_to(self.asset_root) or not path.is_file():
            raise ValueError('Portrait candidate is unavailable.')
        return path

    def use_candidate(self, character_id, expected_revision, job_id, candidate_id, operation_id):
        path = self.candidate_path(character_id, job_id, candidate_id)
        return self.store.use_portrait(character_id, expected_revision, candidate_id,
                                      operation_id, asset_path=str(path))
