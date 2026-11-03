"""Select a stopped room's transport while retaining the local microphone owner."""
import copy
from contextlib import contextmanager
import threading
import uuid

from .discord_room import DiscordRoomController
from .linked_personas import records
from .room_config import validate_discord_room
from .room_membership import account_options
from .settings import load_settings, save_local_settings


class RoomSessionController:
    def __init__(self, addon, local, discord=None, *, settings_loader=load_settings,
                 settings_saver=save_local_settings, persona_provider=records, **options):
        self._local = local
        self._load, self._save, self._personas = settings_loader, settings_saver, persona_provider
        self._discord = discord if discord is not None else DiscordRoomController(
            addon, settings_loader=settings_loader, settings_saver=settings_saver,
            persona_provider=persona_provider, **options)
        self._lock = threading.RLock()

    @contextmanager
    def resource_maintenance(self, *, blocking=False):
        # The facade serializes starts in both transports; retain the local guard
        # too because legacy bridge startup uses the local runtime endpoint lock.
        if not self._lock.acquire(blocking=blocking):
            raise RuntimeError('Room is starting or stopping; resources are busy.')
        try:
            with self._local.resource_maintenance():
                yield
        finally:
            self._lock.release()

    def _mode(self):
        return 'discord' if (self._load().get('room_session') or {}).get('mode') == 'discord' else 'local'

    def _selected(self):
        return self._discord if self._mode() == 'discord' else self._local

    def _require_stopped(self):
        for controller in (self._local, self._discord):
            phase = getattr(controller, '_phase', None)
            if phase is None:
                phase = controller.snapshot().get('phase', 'idle')
            if phase not in {'idle', 'error'} or getattr(controller, '_owned', False):
                raise RuntimeError('Stop the room before changing its transport.')

    def snapshot(self):
        with self._lock:
            mode = self._mode()
            result = copy.deepcopy(self._selected().snapshot())
            result['mode'] = mode
            if mode == 'local':
                result['room_key'] = 'local:' + str((result.get('conversation') or {}).get('id') or 'default')
                result.setdefault('bindings', [])
                result.setdefault('prepared_bots', [])
                result.setdefault('capabilities', {}).update(local_microphone=True, edit_cast=True)
            elif not self._discord._data.get('roster'):
                options = account_options(self._load(), dict(version=1, revision=0, members=[]))
                assigned = {b.get('bot_id') for b in result.get('bindings', [])}
                for option in options:
                    if option['bot_id'] in assigned:
                        option.update(available=False, unavailable_reason='Already assigned to a room participant.')
                result['available_accounts'] = options
            return result

    def configure(self, request):
        with self._lock:
            if 'anonymous' in request:
                if not isinstance(request['anonymous'], bool):
                    raise ValueError('Anonymous must be enabled or disabled.')
                self._selected().set_anonymous(request['anonymous'])
                return self.snapshot()
            settings = self._load()
            section = copy.deepcopy(settings.get('room_session') or {})
            if 'mode' in request:
                self._require_stopped()
                mode = str(request['mode'])
                if mode not in {'local', 'discord'}:
                    raise ValueError('Choose Local or Discord room mode.')
                section['mode'] = mode
            elif 'participant_id' in request and 'bot_id' in request:
                if self._mode() != 'discord':
                    raise ValueError('Choose Discord mode before assigning a prepared bot.')
                bindings = self._discord.bindings(settings)
                participant_id, bot_id = str(request['participant_id']), str(request['bot_id']).strip()
                member = self._member(bindings, participant_id)
                if not bot_id:
                    raise ValueError('Choose a prepared bot account; remove the participant to release its account.')
                if member.get('bot_id') == bot_id:
                    return self.snapshot()
                return self.replace_persona(member['participant_id'], dict(id=member['persona_id']), bot_id)
            else:
                raise ValueError('Choose a room mode or participant bot binding.')
            self._save({'room_session': section})
            return self.snapshot()

    @staticmethod
    def _member(bindings, participant_id):
        exact = [b for b in bindings if b.get('participant_id') == participant_id]
        matches = exact or [b for b in bindings if b.get('bot_id') and b['bot_id'] == participant_id]
        if len(matches) != 1:
            raise ValueError('Choose a participant in this Discord room.')
        return matches[0]

    def _save_bindings(self, bindings):
        section = copy.deepcopy(self._load().get('room_session') or {})
        section['bindings'] = bindings
        self._save({'room_session': section})
        return self.snapshot()

    def _saved_persona(self, record):
        identity = str(record.get('id') or '').strip()
        people = self._personas()
        people = list(people.values()) if isinstance(people, dict) else list(people)
        saved = next((p for p in people if str(p.get('id')) == identity), None)
        if saved is None:
            raise ValueError('Choose an available saved Persona.')
        return copy.deepcopy(saved)

    def add_persona(self, record, bot_id=''):
        with self._lock:
            saved = self._saved_persona(record)
            if self._mode() == 'discord' and not self._discord.bindings():
                self._require_stopped()
                settings = self._load()
                options = account_options(settings, dict(version=1, revision=0, members=[]))
                free = [a['bot_id'] for a in options if a['available']]
                if not free or (bot_id and bot_id not in free):
                    raise ValueError('No free prepared Discord account. Choose an available account in Discord setup.')
                binding = dict(participant_id='member_' + uuid.uuid4().hex, persona_id=saved['id'],
                    bot_id=bot_id or free[0], role='moderator')
                candidate = copy.deepcopy(settings)
                candidate.setdefault('room_session', {})['bindings'] = [binding]
                # Check the selected account's actual room scope before writing
                # the first binding. A recorded conversation is never remapped.
                self._discord._ensure_store(candidate)
                data = self._discord._data
                if data.get('roster') or 'bindings' in data or self._discord._has_history(candidate):
                    raise ValueError('Restore the saved room mapping or start a new conversation before adding participants.')
                return self._save_bindings([binding])
            self._selected().add_persona(saved, bot_id)
            return self.snapshot()

    def replace_persona(self, participant_id, record, bot_id=''):
        with self._lock:
            if self._mode() == 'discord':
                participant_id = self._member(self._discord.bindings(), participant_id)['participant_id']
            self._selected().replace_persona(participant_id, self._saved_persona(record), bot_id)
            return self.snapshot()

    def retry_join(self, participant_id):
        with self._lock:
            if self._mode() == 'discord':
                participant_id = self._member(self._discord.bindings(), participant_id)['participant_id']
            self._selected().retry_join(participant_id)
            return self.snapshot()

    def control(self, action, participant_id='', text=''):
        with self._lock:
            if action == 'remove':
                if self._mode() == 'discord':
                    participant_id = self._member(self._discord.bindings(), participant_id)['participant_id']
                self._selected().request_remove(participant_id)
                return self.snapshot()
            if self._mode() == 'discord' and action == 'moderator':
                self._require_stopped()
                bindings = self._discord.bindings()
                member = self._member(bindings, participant_id)
                self._discord.set_moderator(member['participant_id'])
                return self.snapshot()
            self._selected().control(action, participant_id, text)
            return self.snapshot()

    def _call(self, method, *args):
        with self._lock:
            getattr(self._selected(), method)(*args)
            return self.snapshot()

    def start(self, settings): return self._call('start', settings)
    def stop_after_turn(self): return self._call('stop_after_turn')
    def new_conversation(self):
        with self._lock:
            controller = self._selected()
            controller.new_conversation()
            # Local reset already starts its room; Discord reset selects a fresh
            # room ID first, so launch with the newly saved settings.
            if self._mode() == 'discord':
                controller.start(self._load())
            return self.snapshot()
    def set_topic(self, topic): return self._call('set_topic', topic)
    def send(self, text, sender_id=None):
        with self._lock:
            if self._mode() == 'discord':
                self._discord.send(text, sender_id)
            else:
                self._local.send(text)
            return self.snapshot()
    def join(self): return self._call('join')
    def leave(self): return self._call('leave')
    def set_muted(self, muted): return self._call('set_muted', muted)

    def history(self, participant_id):
        with self._lock:
            return self._selected().history(participant_id)

    def save_behavior(self, behavior):
        with self._lock:
            if self._mode() == 'discord':
                raise RuntimeError('Room behavior editing is available in Local mode.')
            return self._call('save_behavior', behavior)
