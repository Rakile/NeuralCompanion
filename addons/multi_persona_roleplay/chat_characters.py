"""Conversation-scoped cast owned by MPRC, independent of active roleplay state."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Mapping
import unicodedata
import uuid

from .models import PersonaConfig
from .storage import RoleplayStorage
from .chat_character_automation_state import AutomaticCharacterState


class CharacterRevisionConflict(ValueError):
    """The caller edited an older card or collection revision."""


ChatCharacterPatch = Mapping[str, object]


def _text(value: object, limit: int = 5000) -> str:
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError('Invalid character text.')
    return value.strip()


def _key(value: str) -> str:
    value = unicodedata.normalize('NFKC', value).strip().strip('"\'“”‘’«»').strip()
    return ' '.join(value.translate(str.maketrans({'’': "'", '‘': "'"})).split()).casefold()


def _speaker_name(value: object) -> str:
    name = ' '.join(_text(value, 80).split())
    if (re.fullmatch(r'cc_[a-f0-9]{32}', _key(name))
            or not any(c.isalpha() for c in name)
            or any(c in name for c in '<>[]{}\n\r:/\\')
            or _key(name) in {'i', 'you', 'he', 'she', 'they', 'it', 'someone',
                              'somebody', 'narrator', 'assistant', 'user', 'unknown'}):
        raise ValueError('An identified speaking character is required.')
    return name


@dataclass(frozen=True)
class ChatCharacterRecord:
    id: str
    conversation_id: str
    revision: int
    persona: PersonaConfig
    aliases: tuple[str, ...] = ()
    source_message_id: str = ''
    source_character_id: str = ''
    created_at: float = 0
    voice_description: str = ''
    preview_text: str = ''
    voice_id: str = ''
    portrait_prompt: str = ''
    portrait_asset_id: str = ''
    portrait_revision: int = 0
    copied_persona_id: str = ''
    notice_dismissed: bool = False
    jobs: Mapping[str, str] = field(default_factory=dict)
    automation: Mapping[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.persona.display_name

    @property
    def description(self) -> str:
        return self.persona.description

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> ChatCharacterRecord:
        values = dict(row)
        values['persona'] = PersonaConfig.from_dict(values['persona'])
        values['aliases'] = tuple(values.get('aliases', ()))
        return cls(**values)

    def public_dict(self) -> dict[str, Any]:
        """No paths or internal provider settings cross the phone boundary."""
        return {key: copy.deepcopy(getattr(self, key)) for key in (
            'id', 'conversation_id', 'revision', 'aliases', 'source_message_id', 'source_character_id',
            'created_at', 'voice_description', 'preview_text', 'voice_id',
            'portrait_prompt', 'portrait_asset_id', 'portrait_revision',
            'copied_persona_id', 'notice_dismissed', 'jobs')
        } | {'name': self.name, 'role': self.persona.role, 'description': self.description,
             'system_prompt': self.persona.system_prompt,
             'automation': {k: copy.deepcopy(v) for k, v in self.automation.items()
                            if k in {'id', 'mode', 'status', 'voice_status', 'portrait_status',
                                     'added_event_id', 'added_at', 'error'}}}


@dataclass(frozen=True)
class ChatCharacterSnapshot:
    revision: int
    conversation_id: str | None
    allow_new_characters: bool
    characters: tuple[ChatCharacterRecord, ...]
    max_characters: int = 6
    character_voices_enabled: bool = False
    automatic_add_enabled: bool = False
    automatic_add_sound: bool = True


class ChatCharacterService(AutomaticCharacterState):
    def __init__(self, storage: RoleplayStorage):
        self.storage = storage
        self._lock = threading.RLock()
        self._state = storage.load_chat_characters()
        self._repair_internal_names()

    def _repair_internal_names(self) -> None:
        """Recover legacy ID-as-name artifacts only from an exact saved ID."""
        state = copy.deepcopy(self._state)
        changed = False
        for row in state['characters'].values():
            previous = row.get('persona', {}).get('display_name', '')
            if not re.fullmatch(r'cc_[a-f0-9]{32}', _key(previous)):
                continue
            original = state['characters'].get(_key(previous))
            if original is None or original['id'] == row['id']:
                continue
            try:
                name = _speaker_name(original.get('persona', {}).get('display_name', ''))
            except ValueError:
                continue
            conversation = row.get('conversation_id', '')
            # Preserve the original fields, profile, voice and portrait for
            # recovery. A proven same-chat duplicate remains in the library.
            state.setdefault('internal_name_repairs', {})[row['id']] = {
                'previous_name': previous, 'previous_conversation_id': conversation}
            row['persona']['display_name'] = name
            row['revision'] += 1
            if conversation and original.get('conversation_id') == conversation:
                row['conversation_id'] = ''
                if row.get('automation', {}).get('status') in {'queued', 'running'}:
                    row['automation'].update(status='cancelled', error='Duplicate internal-name record repaired.')
                for key, destination in state.get('candidate_receipts', {}).items():
                    if key.startswith(conversation + '/') and destination == row['id']:
                        state['candidate_receipts'][key] = original['id']
            changed = True
        if changed:
            self._commit(state)

    def _commit(self, state: dict[str, Any]) -> None:
        state['revision'] += 1
        self.storage.save_chat_characters(state)
        self._state = state

    def snapshot(self, conversation_id: str | None = None) -> ChatCharacterSnapshot:
        with self._lock:
            rows = [ChatCharacterRecord.from_dict(copy.deepcopy(row))
                    for row in self._state['characters'].values()
                    if conversation_id is None or row['conversation_id'] == conversation_id]
            return ChatCharacterSnapshot(self._state['revision'], conversation_id,
                self._state['conversations'].get(conversation_id, {}).get('allow_new_characters', False),
                tuple(rows), self._state['conversations'].get(conversation_id, {}).get('max_characters', 6),
                self._state['conversations'].get(conversation_id, {}).get('character_voices_enabled', False) is True,
                self._state['conversations'].get(conversation_id, {}).get('automatic_add_enabled', False) is True,
                self._state['conversations'].get(conversation_id, {}).get('automatic_add_sound', True) is True)

    def export_story_snapshot(self, conversation_id: str) -> dict[str, Any]:
        """Return private, conversation-scoped card data for a named story save."""
        if not conversation_id:
            raise ValueError('An active conversation is required.')
        with self._lock:
            settings = self._state['conversations'].get(conversation_id, {})
            return {
                'version': 1,
                'revision': self._state['revision'],
                'settings': {
                    'allow_new_characters': settings.get('allow_new_characters', False) is True,
                    'max_characters': settings.get('max_characters', 6),
                    'character_voices_enabled': settings.get('character_voices_enabled', False) is True,
                    'automatic_add_enabled': settings.get('automatic_add_enabled', False) is True,
                    'automatic_add_sound': settings.get('automatic_add_sound', True) is True,
                },
                'characters': [copy.deepcopy(row) for row in self._state['characters'].values()
                               if row['conversation_id'] == conversation_id],
            }

    def restore_story_snapshot(self, bundle: Mapping[str, Any], conversation_id: str) -> dict[str, str]:
        """Clone saved cards into a fresh scope in one storage transaction."""
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ValueError('A destination conversation is required.')
        cards = self.validate_story_snapshot(bundle)
        settings, rows = bundle['settings'], bundle['characters']
        discovery = settings['allow_new_characters']
        voices = settings['character_voices_enabled']
        limit = settings['max_characters']
        old_ids = [card.id for card in cards]
        mapping = {identity: 'cc_' + uuid.uuid4().hex for identity in old_ids}
        with self._lock:
            if (conversation_id in self._state['conversations']
                    or any(row['conversation_id'] == conversation_id
                           for row in self._state['characters'].values())):
                raise ValueError('Destination conversation already has characters or settings.')
            state = copy.deepcopy(self._state)
            state['conversations'][conversation_id] = {
                'allow_new_characters': discovery,
                'max_characters': limit,
                'character_voices_enabled': voices,
                'automatic_add_enabled': settings.get('automatic_add_enabled', False),
                'automatic_add_sound': settings.get('automatic_add_sound', True),
            }
            for card in cards:
                row = copy.deepcopy(next(item for item in rows if item['id'] == card.id))
                row['id'] = mapping[card.id]
                row['conversation_id'] = conversation_id
                row['revision'] = 1
                row['persona']['id'] = mapping[card.id]
                row['source_character_id'] = mapping.get(card.source_character_id,
                                                         card.source_character_id)
                row['jobs'] = {}
                if row.get('automation'):
                    row['automation'] = {'status': 'cancelled', 'added_event_id': '',
                        'error': 'Saved character restored. Use Remake to create new assets.'}
                state['characters'][row['id']] = row
            self._commit(state)
        return mapping

    @staticmethod
    def validate_story_snapshot(bundle: Mapping[str, Any]) -> list[ChatCharacterRecord]:
        """Check saved settings and cards without changing a live conversation."""
        if not isinstance(bundle, Mapping) or bundle.get('version') != 1:
            raise ValueError('Saved story cast is invalid.')
        settings, rows = bundle.get('settings'), bundle.get('characters')
        if not isinstance(settings, Mapping) or not isinstance(rows, list) or len(rows) > 20:
            raise ValueError('Saved story cast is invalid.')
        discovery = settings.get('allow_new_characters')
        voices = settings.get('character_voices_enabled')
        limit = settings.get('max_characters')
        if any(type(settings.get(k, default)) is not bool for k, default in
               [('automatic_add_enabled', False), ('automatic_add_sound', True)]):
            raise ValueError('Saved automatic character settings are invalid.')
        if (type(discovery) is not bool or type(voices) is not bool or type(limit) is not int
                or not 1 <= limit <= 20 or len(rows) > limit):
            raise ValueError('Saved story cast settings are invalid.')
        cards = [ChatCharacterRecord.from_dict(row) for row in rows]
        old_ids = [card.id for card in cards]
        if len(set(old_ids)) != len(old_ids) or any(not card.id for card in cards):
            raise ValueError('Saved story has duplicate character IDs.')
        return cards

    def remove_story_snapshot(self, conversation_id: str) -> None:
        """Remove a newly staged story scope after a failed chat import."""
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ValueError('A destination conversation is required.')
        with self._lock:
            state = copy.deepcopy(self._state)
            state['conversations'].pop(conversation_id, None)
            state['characters'] = {identity: row for identity, row in state['characters'].items()
                                   if row['conversation_id'] != conversation_id}
            self._commit(state)

    def get(self, character_id: str) -> ChatCharacterRecord:
        with self._lock:
            if character_id not in self._state['characters']:
                raise KeyError('Character not found.')
            return ChatCharacterRecord.from_dict(copy.deepcopy(self._state['characters'][character_id]))

    def set_discovery(self, conversation_id: str, enabled: bool,
                      expected_revision: int, *, max_characters: int | None = None,
                      character_voices_enabled: bool | None = None,
                      automatic_add_enabled: bool | None = None,
                      automatic_add_sound: bool | None = None) -> ChatCharacterSnapshot:
        conversation_id = _text(conversation_id, 160)
        if not conversation_id or type(enabled) is not bool:
            raise ValueError('A conversation and boolean discovery setting are required.')
        if character_voices_enabled is not None and type(character_voices_enabled) is not bool:
            raise ValueError('Character voices setting must be boolean.')
        if any(v is not None and type(v) is not bool for v in (automatic_add_enabled, automatic_add_sound)):
            raise ValueError('Automatic character settings must be boolean.')
        if max_characters is not None and (type(max_characters) is not int or not 1 <= max_characters <= 20):
            raise ValueError('Maximum characters must be a whole number from 1 to 20.')
        with self._lock:
            if expected_revision != self._state['revision']:
                raise CharacterRevisionConflict('Character settings changed. Refresh and try again.')
            state = copy.deepcopy(self._state)
            settings = state['conversations'].setdefault(conversation_id, {})
            was_auto = self.automatic_enabled(conversation_id)
            settings['allow_new_characters'] = enabled
            if character_voices_enabled is not None:
                settings['character_voices_enabled'] = character_voices_enabled
            if max_characters is not None:
                settings['max_characters'] = max_characters
            if automatic_add_enabled is not None:
                settings['automatic_add_enabled'] = automatic_add_enabled
            if automatic_add_sound is not None:
                settings['automatic_add_sound'] = automatic_add_sound
            if was_auto and not all(settings.get(k, False) for k in
                    ('allow_new_characters', 'character_voices_enabled', 'automatic_add_enabled')):
                settings['automatic_epoch'] = settings.get('automatic_epoch', 0) + 1
                for row in state['characters'].values():
                    if row['conversation_id'] == conversation_id and row.get('automation', {}).get('status') in {'queued', 'running'}:
                        row['automation'].update(status='cancelled', error='Automatic setup turned off. Existing assets kept.')
            self._commit(state)
            return self.snapshot(conversation_id)

    def candidates(self, conversation_id: str) -> list[dict]:
        with self._lock:
            seen = set(self._state.get('discarded_names', {}).get(conversation_id, []))
            rows = []
            for candidate in self._state.get('candidates', {}).get(conversation_id, []):
                try:
                    _speaker_name(candidate['name'])
                except ValueError:
                    continue
                key = _key(candidate['name'])
                if key in seen or self._find(conversation_id, candidate['name']):
                    continue
                seen.add(key)
                rows.append(copy.deepcopy(candidate))
            return rows

    def propose_candidates(self, conversation_id: str, names: Mapping[str, str]) -> None:
        with self._lock:
            snapshot=self.snapshot(conversation_id)
            if not snapshot.character_voices_enabled or not snapshot.allow_new_characters:
                return
            rows=self.candidates(conversation_id)
            for name, excerpt in list(names.items())[:20]:
                try: name=_speaker_name(name)
                except ValueError: continue
                if _key(name) in {'waiter','guard','stranger','receptionist','soldier','innkeeper'}:
                    continue
                if (self._find(conversation_id,name)
                        or _key(name) in self._state.get('discarded_names', {}).get(conversation_id, [])
                        or any(_key(c['name'])==_key(name) for c in rows)):
                    continue
                if len(rows)+len(snapshot.characters)>=snapshot.max_characters:
                    break
                rows.append({'id':'cc_'+uuid.uuid4().hex,'name':name,'excerpt':str(excerpt)[:500]})
            if rows!=self.candidates(conversation_id):
                state=copy.deepcopy(self._state)
                state.setdefault('candidates',{})[conversation_id]=rows
                self._commit(state)

    def accept_candidate(self, conversation_id: str, identity: str, expected_revision: int):
        with self._lock:
            receipt=self._state.get('candidate_receipts',{}).get(conversation_id+'/' + identity)
            if receipt:
                return self.get(receipt)
            if expected_revision!=self._state['revision']:
                raise CharacterRevisionConflict('Character settings changed. Refresh and try again.')
            rows=self.candidates(conversation_id)
            candidate=next((c for c in rows if c['id']==identity),None)
            if candidate is None: raise KeyError('Candidate not found.')
            card=self.ensure_speaker(conversation_id,candidate['name'],'candidate')
            if card is None: raise ValueError('Enable discovery and check the character limit first.')
            state=copy.deepcopy(self._state)
            state.setdefault('candidates',{})[conversation_id]=[c for c in rows if c['id']!=identity]
            state.setdefault('candidate_receipts',{})[conversation_id+'/' + identity]=card.id
            self._commit(state)
            return card

    def remove(self, character_id: str, expected_revision: int, operation_id: str) -> dict:
        operation_id = _text(operation_id, 120)
        if not operation_id:
            raise ValueError('An operation identity is required.')
        with self._lock:
            receipts = self._state.get('removals', {})
            if operation_id in receipts:
                if receipts[operation_id] != character_id:
                    raise ValueError('Operation identity already used.')
                return {'removed': True, 'id': character_id}
            current = self.get(character_id)
            if current.revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before removing.')
            state = copy.deepcopy(self._state)
            del state['characters'][character_id]
            state['candidate_receipts'] = {k: v for k, v in state.get('candidate_receipts', {}).items()
                                           if v != character_id}
            state.setdefault('removals', {})[operation_id] = character_id
            self._commit(state)
            return {'removed': True, 'id': character_id}

    def discard(self, conversation_id: str, identity: str,
                expected_revision: int, operation_id: str) -> dict:
        """Reject a discovery durably, without deleting generated media or other casts."""
        conversation_id = _text(conversation_id, 160)
        operation_id = _text(operation_id, 120)
        if not conversation_id or not operation_id:
            raise ValueError('An active conversation and operation identity are required.')
        with self._lock:
            receipt = self._state.get('discards', {}).get(operation_id)
            if receipt:
                if receipt['id'] != identity or receipt['conversation_id'] != conversation_id:
                    raise ValueError('Operation identity already used.')
                return copy.deepcopy(receipt)
            card = self._state['characters'].get(identity)
            candidate = next((c for c in self._state.get('candidates', {}).get(conversation_id, [])
                              if c['id'] == identity), None)
            if card:
                if card['conversation_id'] != conversation_id:
                    raise ValueError('The active conversation changed. Refresh the library.')
                revision = card['revision']
                names = [card['persona']['display_name'], *card.get('aliases', [])]
            elif candidate:
                revision = self._state['revision']
                names = [candidate['name']]
            else:
                raise KeyError('Character not found.')
            if revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before discarding.')
            state = copy.deepcopy(self._state)
            rejected = set(state.setdefault('discarded_names', {}).get(conversation_id, []))
            rejected.update(_key(name) for name in names)
            state['discarded_names'][conversation_id] = sorted(rejected)
            state.setdefault('candidates', {})[conversation_id] = [
                c for c in state.get('candidates', {}).get(conversation_id, [])
                if _key(c['name']) not in rejected]
            if card:
                if card.get('automation'):
                    state['characters'][identity]['conversation_id'] = ''
                    state['characters'][identity]['revision'] += 1
                    state['characters'][identity]['automation'].update(status='cancelled', added_event_id='')
                else:
                    del state['characters'][identity]
                state['candidate_receipts'] = {k: v for k, v in state.get('candidate_receipts', {}).items()
                                               if v != identity}
            result = {'discarded': True, 'id': identity, 'conversation_id': conversation_id}
            state.setdefault('discards', {})[operation_id] = result
            self._commit(state)
            return copy.deepcopy(result)

    def remove_from_chat(self, character_id: str, conversation_id: str,
                         expected_revision: int, operation_id: str) -> dict:
        """Leave the active cast while retaining a reusable library card."""
        conversation_id = _text(conversation_id, 160)
        operation_id = _text(operation_id, 120)
        if not conversation_id or not operation_id:
            raise ValueError('An active conversation and operation identity are required.')
        with self._lock:
            receipt = self._state.get('chat_removals', {}).get(operation_id)
            if receipt:
                if receipt['id'] != character_id or receipt['conversation_id'] != conversation_id:
                    raise ValueError('Operation identity already used for a different request.')
                return copy.deepcopy(receipt)
            selected = self.get(character_id)
            if selected.revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before removing.')
            target = (self._state['characters'][character_id]
                      if selected.conversation_id == conversation_id else
                      next((row for row in self._state['characters'].values()
                            if row['conversation_id'] == conversation_id
                            and row.get('source_character_id') == character_id), None))
            if target is None:
                raise ValueError('This character is not in the active conversation.')
            state = copy.deepcopy(self._state)
            target_id = target['id']
            source_id = target.get('source_character_id', '')
            if source_id and source_id in state['characters'] and source_id != target_id:
                del state['characters'][target_id]
            else:
                # Original discoveries have no other saved card. A blank scope keeps
                # their voice, portrait, and edits in All conversations only.
                row = state['characters'][target_id]
                row['conversation_id'] = ''
                row['source_character_id'] = ''
                row['revision'] += 1
            state['chat_additions'] = {
                key: value for key, value in state.get('chat_additions', {}).items()
                if value.get('destination') != target_id}
            result = {'removed': True, 'id': character_id,
                      'conversation_id': conversation_id, 'removed_id': target_id}
            state.setdefault('chat_removals', {})[operation_id] = result
            self._commit(state)
            return copy.deepcopy(result)

    def add_to_chat(self, character_id: str, conversation_id: str,
                    expected_revision: int, operation_id: str) -> ChatCharacterRecord:
        """Copy a saved card into the active chat without enabling discovery."""
        conversation_id = _text(conversation_id, 160)
        operation_id = _text(operation_id, 120)
        if not conversation_id or not operation_id:
            raise ValueError('An active conversation and operation identity are required.')
        with self._lock:
            receipt = self._state.get('chat_additions', {}).get(operation_id)
            if receipt:
                if receipt['source'] != character_id or receipt['conversation'] != conversation_id:
                    raise ValueError('Operation identity already used for a different request.')
                return self.get(receipt['destination'])
            source = self.get(character_id)
            if source.revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before adding.')
            existing = self._find(conversation_id, source.name)
            if existing is not None and existing['id'] != character_id and existing.get('source_character_id') != character_id:
                raise ValueError('A different character with this name is already in this conversation.')
            for label in (source.name, *source.aliases):
                match = self._find(conversation_id, label)
                if match is not None and (existing is None or match['id'] != existing['id']):
                    raise ValueError('A character with this name or alias is already in this conversation.')
            if existing is None:
                limit = self._state['conversations'].get(conversation_id, {}).get('max_characters', 6)
                count = sum(row['conversation_id'] == conversation_id
                            for row in self._state['characters'].values())
                if count >= limit:
                    raise ValueError('This conversation has reached its character limit.')
            state = copy.deepcopy(self._state)
            if existing is None:
                identity = self._copy_card_to_chat(state, character_id, conversation_id)
            else:
                identity = existing['id']
            state['conversations'].setdefault(conversation_id, {})['character_voices_enabled'] = True
            state.setdefault('chat_additions', {})[operation_id] = {
                'source': character_id, 'conversation': conversation_id, 'destination': identity}
            self._commit(state)
            return self.get(identity)

    @staticmethod
    def _copy_card_to_chat(state: dict[str, Any], source_id: str, conversation_id: str) -> str:
        identity = 'cc_' + uuid.uuid4().hex
        row = copy.deepcopy(state['characters'][source_id])
        row.update(id=identity, conversation_id=conversation_id, revision=1,
                   source_message_id='', source_character_id=source_id, created_at=time.time(),
                   copied_persona_id='', notice_dismissed=False, jobs={})
        row['persona']['id'] = identity
        state['characters'][identity] = row
        return identity

    def assign_existing_candidate(self, source_id: str, conversation_id: str,
                                  candidate_id: str, expected_revision: int,
                                  operation_id: str) -> ChatCharacterRecord:
        """Resolve a discovered speaker with a saved card in one store commit."""
        conversation_id = _text(conversation_id, 160)
        operation_id = _text(operation_id, 120)
        if not conversation_id or not operation_id:
            raise ValueError('An active conversation and operation identity are required.')
        with self._lock:
            receipt = self._state.get('candidate_assignments', {}).get(operation_id)
            if receipt:
                if (receipt['source'] != source_id or receipt['conversation'] != conversation_id
                        or receipt['candidate'] != candidate_id):
                    raise ValueError('Operation identity already used for a different request.')
                return self.get(receipt['destination'])
            source = self.get(source_id)
            if source.revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before assigning.')
            # A picker may stay open while automatic/manual acceptance turns
            # the exact candidate into a local card. Resolve its durable receipt.
            receipt_key = conversation_id + '/' + candidate_id
            placeholder_id = self._state.get('candidate_receipts', {}).get(receipt_key)
            placeholder = self._state['characters'].get(placeholder_id)
            if placeholder is not None and placeholder.get('conversation_id') != conversation_id:
                placeholder = None
            candidate = next((row for row in self._state.get('candidates', {}).get(conversation_id, [])
                              if row['id'] == candidate_id), None)
            if candidate is None and placeholder is not None:
                candidate = {'id': candidate_id, 'name': ChatCharacterRecord.from_dict(placeholder).name}
            if candidate is None:
                raise KeyError('Candidate not found.')
            _speaker_name(source.name)
            _speaker_name(candidate['name'])
            matches = [row for row in self._state['characters'].values()
                       if row.get('conversation_id') == conversation_id
                       and (row['id'] == source_id or row.get('source_character_id') == source_id)]
            if len(matches) > 1:
                raise ValueError('More than one story copy exists. Refresh the library before assigning.')
            target = matches[0] if matches else None
            exempt = {row['id'] for row in (target, placeholder) if row is not None}
            labels = {_key(label) for label in (source.name, *source.aliases, candidate['name'])}
            for row in self._state['characters'].values():
                if row.get('conversation_id') != conversation_id or row['id'] in exempt:
                    continue
                other = ChatCharacterRecord.from_dict(row)
                if labels.intersection({_key(label) for label in (other.name, *other.aliases)}):
                    raise ValueError('A character with this name or alias is already in this conversation.')
            state = copy.deepcopy(self._state)
            if placeholder is not None and (target is None or target['id'] != placeholder['id']):
                # Explicitly choosing a saved version displaces only the card
                # proven by this candidate receipt. Keep its profile and assets
                # in the library, rather than deleting or overwriting them.
                displaced = state['characters'][placeholder['id']]
                displaced['conversation_id'] = ''
                displaced['revision'] += 1
                if displaced.get('automation', {}).get('status') in {'queued', 'running'}:
                    displaced['automation'].update(status='cancelled', error='Saved character assigned instead.')
            settings = state['conversations'].get(conversation_id, {})
            count = sum(row['conversation_id'] == conversation_id for row in state['characters'].values())
            if target is None:
                if count >= settings.get('max_characters', 6):
                    raise ValueError('This conversation has reached its character limit.')
                identity = self._copy_card_to_chat(state, source_id, conversation_id)
                state['characters'][identity]['automation'] = {}
            else:
                identity = target['id']
            destination = state['characters'][identity]
            if _key(candidate['name']) not in {_key(source.name), *map(_key, destination.get('aliases', []))}:
                destination.setdefault('aliases', []).append(candidate['name'])
                if target is not None:
                    destination['revision'] += 1
            state.setdefault('candidates', {})[conversation_id] = [
                row for row in state.get('candidates', {}).get(conversation_id, []) if row['id'] != candidate_id]
            state.setdefault('candidate_receipts', {})[receipt_key] = identity
            state['conversations'].setdefault(conversation_id, {})['character_voices_enabled'] = True
            state.setdefault('candidate_assignments', {})[operation_id] = {
                'source': source_id, 'conversation': conversation_id,
                'candidate': candidate_id, 'destination': identity}
            self._commit(state)
            return self.get(identity)

    def _find(self, conversation_id: str, name: str) -> dict[str, Any] | None:
        key = _key(name)
        return next((row for row in self._state['characters'].values()
                     if row['conversation_id'] == conversation_id and key in
                     {_key(row['persona']['display_name']), *(_key(a) for a in row['aliases'])}), None)

    def ensure_speaker(self, conversation_id: str, speaker_name: str,
                       source_message_id: str) -> ChatCharacterRecord | None:
        conversation_id = _text(conversation_id, 160)
        if not conversation_id:
            return None
        try:
            name = _speaker_name(speaker_name)
        except ValueError:
            return None
        with self._lock:
            existing = self._find(conversation_id, name)
            if existing:
                return ChatCharacterRecord.from_dict(copy.deepcopy(existing))
            if _key(name) in self._state.get('discarded_names', {}).get(conversation_id, []):
                return None
            if not self._state['conversations'].get(conversation_id, {}).get('allow_new_characters', False):
                return None
            limit = self._state['conversations'].get(conversation_id, {}).get('max_characters', 6)
            if sum(row['conversation_id'] == conversation_id for row in self._state['characters'].values()) >= limit:
                return None
            identity = 'cc_' + uuid.uuid4().hex
            # Same PersonaConfig as roleplay, but no insertion/activation into its live session.
            persona = PersonaConfig(id=identity, display_name=name, behavior_mode='RPG character')
            row = dict(id=identity, conversation_id=conversation_id, revision=1,
                       persona=persona.to_dict(), aliases=[], source_message_id=_text(source_message_id, 160),
                       created_at=time.time())
            state = copy.deepcopy(self._state)
            state['characters'][identity] = row
            self._commit(state)
            return self.get(identity)

    def update(self, character_id: str, expected_revision: int,
               patch: ChatCharacterPatch) -> ChatCharacterRecord:
        allowed = {'name', 'role', 'description', 'system_prompt', 'aliases', 'voice_description',
                   'preview_text', 'portrait_prompt', 'notice_dismissed'}
        if not patch or set(patch) - allowed:
            raise ValueError('Unknown or empty character edit.')
        with self._lock:
            current = self.get(character_id)
            if current.revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before saving.')
            state = copy.deepcopy(self._state)
            row = state['characters'][character_id]
            for key, value in patch.items():
                if key == 'notice_dismissed':
                    if type(value) is not bool:
                        raise ValueError('Notice setting must be boolean.')
                    row[key] = value
                elif key == 'aliases':
                    if not isinstance(value, (list, tuple)) or len(value) > 20:
                        raise ValueError('Invalid character aliases.')
                    row[key] = list(dict.fromkeys(_speaker_name(a) for a in value))
                elif key == 'name':
                    row['persona']['display_name'] = _speaker_name(value)
                elif key in {'role', 'description', 'system_prompt'}:
                    row['persona'][key] = _text(value, 160 if key == 'role' else 5000)
                else:
                    row[key] = _text(value)
            for name in [row['persona']['display_name'], *row['aliases']]:
                existing = self._find(current.conversation_id, name)
                if existing and existing['id'] != character_id:
                    raise ValueError('That name already belongs to another character in this conversation.')
            row['revision'] += 1
            self._commit(state)
            return self.get(character_id)

    def enrich(self, character_id: str, expected_revision: int,
               proposal: ChatCharacterPatch) -> ChatCharacterRecord:
        with self._lock:
            current = self.get(character_id)
            if current.revision != expected_revision:
                return current
            fields = {'role', 'description', 'system_prompt', 'voice_description', 'preview_text', 'portrait_prompt'}
            public = current.public_dict()
            patch = {k: v for k, v in proposal.items() if k in fields and not public.get(k) and v}
            return self.update(character_id, expected_revision, patch) if patch else current

    def _apply_operation(self, character_id: str, expected_revision: int,
                         operation_id: str, kind: str, values: Mapping[str, object],
                         apply) -> ChatCharacterRecord:
        operation_id = _text(operation_id, 120)
        if not operation_id:
            raise ValueError('An operation identity is required.')
        fingerprint = hashlib.sha256(json.dumps([kind, character_id, values],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            previous = self._state.get('operations', {}).get(operation_id)
            if previous:
                if previous != fingerprint:
                    raise ValueError('Operation identity already used for a different request.')
                return self.get(character_id)
            current = self.get(character_id)
            if current.revision != expected_revision:
                raise CharacterRevisionConflict('Character changed. Refresh before saving.')
            state = copy.deepcopy(self._state)
            row = state['characters'][character_id]
            apply(row)
            row['revision'] += 1
            state.setdefault('operations', {})[operation_id] = fingerprint
            self._commit(state)
            return self.get(character_id)

    def assign_voice(self, character_id: str, expected_revision: int, voice_id: str,
                     operation_id: str, *, sample_path: str, language: str = '',
                     validate_sample: Callable[[], bool] | None = None) -> ChatCharacterRecord:
        """Paths come only from the host's validated saved-voice registry."""
        voice_id, language = _text(voice_id, 160), _text(language, 40)
        def apply(row):
            if voice_id and validate_sample is not None and not validate_sample():
                raise ValueError('The saved voice is unavailable. Refresh the voice library.')
            row['voice_id'] = voice_id
            row['persona']['voice'].update(enabled=bool(voice_id), sample_path=sample_path,
                                            language=language, backend='inherit')
        return self._apply_operation(character_id, expected_revision, operation_id,
            'voice', {'voice_id': voice_id, 'sample_path': sample_path, 'language': language}, apply)

    def remove_saved_voice(self, voice_id: str, expected_revision: int,
                           operation_id: str, remove_recording) -> dict:
        """Clear every chat-card assignment under the same lock as confirmation."""
        if not voice_id or not operation_id:
            raise ValueError('A voice and operation identity are required.')
        with self._lock:
            previous = self._state.get('voice_removals', {}).get(operation_id)
            if previous:
                if previous['voice_id'] != voice_id:
                    raise ValueError('Operation identity already used for a different request.')
                return copy.deepcopy(previous)
            if self._state['revision'] != expected_revision:
                raise CharacterRevisionConflict('Character assignments changed. Review removal again.')
            state = copy.deepcopy(self._state)
            affected = []
            for row in state['characters'].values():
                if row.get('voice_id') != voice_id:
                    continue
                affected.append(row['id'])
                row['voice_id'] = ''
                row['persona']['voice'].update(enabled=False, sample_path='', backend='inherit')
                row['revision'] += 1
            result = {'removed': True, 'voice_id': voice_id, 'character_ids': affected}
            state.setdefault('voice_removals', {})[operation_id] = result
            remove_recording(lambda: self._commit(state))
            return copy.deepcopy(result)

    def use_portrait(self, character_id: str, expected_revision: int, asset_id: str,
                     operation_id: str, *, asset_path: str) -> ChatCharacterRecord:
        def apply(row):
            row['portrait_asset_id'] = asset_id
            row['portrait_revision'] = row.get('portrait_revision', 0) + 1
            row['persona']['character_image_path'] = asset_path
        return self._apply_operation(character_id, expected_revision, operation_id,
            'portrait', {'asset_id': asset_id, 'asset_path': asset_path}, apply)

    def copy_to_persona(self, character_id: str, expected_revision: int, create_copy) -> ChatCharacterRecord:
        with self._lock:
            card = self.get(character_id)
            if card.copied_persona_id:
                return card
            intent = self._state.get('copy_intents', {}).get(character_id)
            if intent is None:
                if card.revision != expected_revision:
                    raise CharacterRevisionConflict('Character changed. Refresh before copying.')
                # A discovery card can be copied before enrichment has completed.
                # Make a standalone identity from the known facts even in that case.
                prompt_parts = [f'You are {card.name}.']
                if card.persona.role:
                    prompt_parts.append('Role:\n' + card.persona.role)
                if card.description:
                    prompt_parts.append('Character description:\n' + card.description)
                if card.persona.system_prompt:
                    prompt_parts.append('Character and interaction instructions:\n' + card.persona.system_prompt)
                prompt_parts.append(
                    'Interact with the user as this character. Keep your identity, personality, '
                    'motivations and manner of speaking consistent with the details above. '
                    'Respond to the current conversation and keep established events consistent. '
                    "Leave the user's dialogue, actions and decisions to the user. "
                    'Do not invent a shared history or present unknown character details as established facts.')
                prompt = '\n\n'.join(prompt_parts)
                intent = {'name': card.name, 'system_prompt': prompt,
                          # The complete prompt is editable without a separate type preset.
                          'persona_prompt_type': '',
                          'prompt_builder': {'candidate': prompt, 'prompt_type': 'custom',
                                             'description': card.description or card.persona.role},
                          'voice_path': card.persona.voice.sample_path,
                          'use_cloned_voice': bool(card.voice_id), 'avatar_path': card.persona.character_image_path,
                          'portrait_prompt': card.portrait_prompt, 'visual_identity_prompt': card.description,
                          'mood_reference_enabled': False}
                state = copy.deepcopy(self._state)
                state.setdefault('copy_intents', {})[character_id] = intent
                self._commit(state)
            # Capture survives failure after the destination wrote its atomic receipt.
            result = create_copy('chat-copy-' + character_id, copy.deepcopy(intent))
            state = copy.deepcopy(self._state)
            state['characters'][character_id]['copied_persona_id'] = str(result['id'])
            state['characters'][character_id]['revision'] += 1
            self._commit(state)
            return self.get(character_id)
