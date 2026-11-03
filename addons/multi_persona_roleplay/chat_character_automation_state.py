"""Transactions for automatic card setup; provider work never runs under this lock."""
from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid

from .models import PersonaConfig


def _guard(card) -> str:
    # Notice dismissals and progress updates are not user identity/asset edits.
    values = [card.name, card.description, card.persona.role, card.persona.system_prompt,
              card.aliases, card.voice_description, card.preview_text, card.portrait_prompt,
              card.voice_id, card.portrait_asset_id, card.persona.voice.sample_path,
              card.persona.character_image_path, card.conversation_id]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


class AutomaticCharacterState:
    def automatic_enabled(self, conversation_id: str) -> bool:
        settings = self.snapshot(conversation_id)
        return bool(settings.character_voices_enabled and settings.allow_new_characters
                    and settings.automatic_add_enabled)

    def accept_automatic(self, conversation_id: str, candidate_ids=None) -> list:
        from .chat_characters import _key
        with self._lock:
            if not self.automatic_enabled(conversation_id):
                return []
            state = copy.deepcopy(self._state)
            snapshot = self.snapshot(conversation_id)
            capacity = max(0, snapshot.max_characters - len(snapshot.characters))
            accepted = []
            for candidate in self.candidates(conversation_id):
                if not capacity:
                    break
                if candidate_ids is not None and candidate['id'] not in candidate_ids:
                    continue
                # Cross-story names alone cannot establish identity. Leave a suggestion
                # for manual selection instead of charging for a possible duplicate.
                if any(_key(candidate['name']) in {_key(c.name), *map(_key, c.aliases)}
                       for c in self.snapshot().characters):
                    continue
                identity = candidate['id']
                operation = uuid.uuid4().hex
                persona = PersonaConfig(id=identity, display_name=candidate['name'], behavior_mode='RPG character')
                state['characters'][identity] = dict(id=identity, conversation_id=conversation_id,
                    revision=1, persona=persona.to_dict(), aliases=[], created_at=time.time(),
                    automation={'id': operation, 'mode': 'create', 'status': 'queued',
                        'voice_status': 'queued', 'portrait_status': 'queued',
                        'added_event_id': operation, 'added_at': time.time(),
                        'excerpt': candidate.get('excerpt', ''),
                        'epoch': state['conversations'][conversation_id].get('automatic_epoch', 0)})
                state.setdefault('candidate_receipts', {})[conversation_id + '/' + identity] = identity
                accepted.append(identity)
                capacity -= 1
            if accepted:
                state['candidates'][conversation_id] = [c for c in state['candidates'].get(conversation_id, [])
                                                       if c['id'] not in accepted]
                # Compute guards before the single durable transaction.
                from .chat_characters import ChatCharacterRecord
                for identity in accepted:
                    row = state['characters'][identity]
                    row['automation']['guard'] = _guard(ChatCharacterRecord.from_dict(row))
                self._commit(state)
            return [self.get(identity) for identity in accepted]

    def automatic_current(self, character_id: str, operation_id: str):
        from .chat_characters import CharacterRevisionConflict
        with self._lock:
            card = self.get(character_id)
            auto = card.automation
            epoch = self._state['conversations'].get(card.conversation_id, {}).get('automatic_epoch', 0)
            if (auto.get('id') != operation_id or auto.get('guard') != _guard(card)
                    or auto.get('status') == 'cancelled' or auto.get('epoch') != epoch
                    or not self.automatic_enabled(card.conversation_id)):
                raise CharacterRevisionConflict('Automatic setup was superseded. Your current character is kept.')
            return card

    def automatic_progress(self, character_id: str, operation_id: str, **patch):
        with self._lock:
            card = self.get(character_id)
            if card.automation.get('id') != operation_id:
                return card
            state = copy.deepcopy(self._state)
            state['characters'][character_id]['automation'].update(copy.deepcopy(patch))
            self._commit(state)
            return self.get(character_id)

    def automatic_enrich(self, character_id: str, operation_id: str, proposal: dict):
        with self._lock:
            card = self.automatic_current(character_id, operation_id)
            card = self.enrich(card.id, card.revision, proposal)
            return self.automatic_progress(card.id, operation_id, guard=_guard(card), enriched=True)

    def automatic_commit(self, character_id: str, operation_id: str, *, voice=None, portrait=None):
        """Host-validated paths only. Both replacements commit together for Remake."""
        with self._lock:
            card = self.automatic_current(character_id, operation_id)
            if card.automation.get('mode') == 'remake' and (voice is None or portrait is None):
                raise ValueError('Remake requires both replacements before assignment.')
            state = copy.deepcopy(self._state)
            row = state['characters'][character_id]
            if voice is not None:
                identity, path, language = voice
                row['voice_id'] = identity
                row['persona']['voice'].update(enabled=True, sample_path=path, language=language, backend='inherit')
            if portrait is not None:
                identity, path = portrait
                row['portrait_asset_id'] = identity
                row['portrait_revision'] = row.get('portrait_revision', 0) + 1
                row['persona']['character_image_path'] = path
            row['revision'] += 1
            from .chat_characters import ChatCharacterRecord
            row['automation']['guard'] = _guard(ChatCharacterRecord.from_dict(row))
            self._commit(state)
            return self.get(character_id)

    def begin_remake(self, character_id: str, expected_revision: int, operation_id: str):
        from .chat_characters import CharacterRevisionConflict, _text
        operation_id = _text(operation_id, 120)
        if not operation_id:
            raise ValueError('An operation identity is required.')
        with self._lock:
            card = self.get(character_id)
            if card.automation.get('id') == operation_id:
                return card
            if not card.automation or not self.automatic_enabled(card.conversation_id):
                raise ValueError('Enable automatic characters in this conversation first.')
            if card.revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before remaking.')
            if card.automation.get('status') in {'queued', 'running'}:
                raise ValueError('This character is already being prepared.')
            state = copy.deepcopy(self._state)
            row = state['characters'][character_id]
            row['automation'] = {'id': operation_id, 'mode': 'remake', 'status': 'queued',
                'voice_status': 'queued', 'portrait_status': 'queued', 'enriched': True,
                'added_event_id': card.automation.get('added_event_id', ''),
                'added_at': card.automation.get('added_at', 0), 'guard': _guard(card),
                'epoch': state['conversations'][card.conversation_id].get('automatic_epoch', 0)}
            row['revision'] += 1
            self._commit(state)
            return self.get(character_id)
