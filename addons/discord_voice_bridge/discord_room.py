"""Own a Discord-backed room without taking ownership of the user's Discord client."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
from .settings import load_settings, save_local_settings
from .linked_personas import records
from .room_config import validate_discord_room, discord_room_has_model_history
from .discord_room_store import DiscordRoomStore
from .room_anonymous import apply_anonymous
from .bot_accounts import account_rows
from .room_membership import (seed_roster, begin_admission, request_departure,
                              settle_admission, account_options, validate_roster)


_CONTINUATION_FIELDS = ('pending_route', 'pending_human_route', 'floor_target_bot_id',
    'floor_speaker_user_id', 'floor_speaker_name', 'muted_bot_ids', 'only_bot_ids',
    'muted_speaker_user_ids', 'allow_current_interruption', 'room_directives',
    'current_human_route', 'current_speaker_user_id', 'current_speaker_name')


class DiscordRoomController:
    def __init__(self, addon, *, settings_loader=load_settings, settings_saver=save_local_settings,
                 persona_provider=records, root=None, ready_timeout=60.0):
        self._addon = addon
        self._load, self._save, self._personas = settings_loader, settings_saver, persona_provider
        self._root = Path(root) if root is not None else Path(__file__).parent / 'runtime_instances/rooms'
        # Budget for Gateway login (30s handshake) before Node's 20s voice join,
        # plus process/channel setup. Readiness still releases the hold immediately.
        self._ready_timeout = ready_timeout
        self._lock = threading.RLock()
        self._operation = threading.RLock()
        self._phase, self._error = 'idle', ''
        self._settings = None
        self._owned = set()
        self._store = None
        self._store_loaded = False
        self._history_error = ''
        self._checkpoint_error = ''
        self._data = {}
        self._stop_thread = None
        self._stop_request = None
        self._continuing = False
        self._membership_epoch = 0
        self._membership_threads = {}
        self._candidate_bots = []
        self._membership_persistence_error = ''

    @property
    def session_settings(self):
        with self._lock:
            return copy.deepcopy(self._settings)

    def _people(self):
        value = self._personas()
        return list(value.values()) if isinstance(value, dict) else list(value)

    def bindings(self, settings=None):
        settings = settings if settings is not None else self._load()
        saved = (settings.get('room_session') or {}).get('bindings')
        if isinstance(saved, list):
            return copy.deepcopy(saved)
        result = []
        for bot in settings.get('bots', []):
            if bot.get('local_room_role') or not bot.get('local_room_persona_id'):
                continue
            result.append(dict(participant_id='member_' + str(bot['id']),
                persona_id=bot['local_room_persona_id'], bot_id=bot['id'],
                role='moderator' if str(bot.get('name', '')).casefold() == 'moderator' else 'participant'))
        return result

    def _ensure_store(self, settings):
        section = settings.get('room_session') or {}
        scope = settings.get('_room_identity')
        if not scope:
            bots = {b.get('id'): b for b in settings.get('bots', [])}
            first = next((bots.get(b.get('bot_id')) for b in self.bindings(settings) if bots.get(b.get('bot_id'))), {})
            connection = first.get('discord') or {}
            inherited = settings.get('discord') or {}
            scope = dict(guild_id=str(connection.get('guild_id') or inherited.get('guild_id') or section.get('guild_id') or '').strip(),
                channel_id=str(connection.get('voice_channel_id') or inherited.get('voice_channel_id') or section.get('channel_id') or '').strip(),
                room_id=str(section.get('room_id') or 'default'))
        candidate = DiscordRoomStore(self._root, **scope)
        if self._store is None or candidate.path != self._store.path:
            if self._owned:
                raise RuntimeError('Stop the active Discord room before changing its conversation scope.')
            # Invalidate the old view before reading another scope, even if that read fails.
            self._store, self._data, self._store_loaded = candidate, {}, False
            self._continuing = False
        if not self._store_loaded:
            data = self._store.load()
            if not isinstance(data.get('anonymous', False), bool):
                raise ValueError('The saved Discord room Anonymous setting is invalid. Its file was preserved.')
            data.setdefault('anonymous', False)
            self._data = data
            self._store_loaded = True
        return self._store

    def _has_history(self, settings):
        if self._data.get('messages') or self._data.get('continuation'):
            return True
        folder = self._store.path.with_suffix('.events')
        if any(path.stat().st_size for path in folder.glob('*.jsonl')):
            return True
        saved_bindings = self._data.get('bindings') or []
        if not isinstance(saved_bindings, list) or any(not isinstance(member, dict) for member in saved_bindings):
            raise ValueError('The saved Discord participant mapping is invalid. Its file was preserved.')
        bindings = self.bindings(settings) + saved_bindings
        if self._data.get('roster'):
            bindings = self._roster_bindings(self._data['roster'])
        return discord_room_has_model_history(settings, bindings, self._store.identity, roster=self._data.get('roster'))

    def _ensure_bindings(self, bindings):
        saved = self._data.get('bindings')
        if 'bindings' in self._data:
            fields = ('participant_id', 'persona_id', 'bot_id', 'role')
            def identity(value):
                return sorted(tuple(str(member.get(key) or '') for key in fields) for member in value)
            if (not isinstance(saved, list) or any(not isinstance(member, dict) for member in saved)
                    or identity(saved) != identity(bindings)):
                raise ValueError('The saved room participant mapping has changed. Restore the saved persona-to-bot mapping '
                                 'or start a new conversation before starting this room.')
            return
        data = copy.deepcopy(self._data)
        data['bindings'] = copy.deepcopy(bindings)
        self._store.save(data)
        self._data = data

    @staticmethod
    def _roster_bindings(roster):
        fields = ('participant_id', 'persona_id', 'bot_id', 'role')
        return [{key: member[key] for key in fields} for member in roster['members'] if member['phase'] != 'left']

    def _membership_path(self):
        return self._store.path.with_suffix('.membership.json')

    def _write_membership(self, roster):
        validate_roster(roster)
        path = self._membership_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                    prefix=path.stem + '.', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                json.dump(roster, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()

    def _ensure_roster(self, settings):
        self._ensure_store(settings)
        pending = self._data.get('membership_settings_pending')
        if pending:
            current = self.bindings(settings)
            if not any(self._same_bindings(current, expected) for expected in
                       (pending['previous_bindings'], self._data['bindings'])):
                raise ValueError('The saved room mapping changed outside its recorded pending transition.')
            self._persist_roster(self._data['roster'], settings)
            settings.setdefault('room_session', {})['bindings'] = copy.deepcopy(self._data['bindings'])
        bindings = self.bindings(settings)
        self._ensure_bindings(bindings)
        roster = seed_roster(self._data, bindings)
        # Resolve original legacy history storage IDs before an account can move.
        self._compile_membership(settings, roster)
        if roster != self._data.get('roster'):
            self._persist_roster(roster, settings, save_settings=False)
        return roster

    @staticmethod
    def _same_bindings(first, second):
        fields = ('participant_id', 'persona_id', 'bot_id', 'role')
        def identities(value):
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError('The saved room mapping is invalid.')
            return sorted(tuple(str(item.get(key) or '') for key in fields) for item in value)
        return identities(first) == identities(second)

    def _compile_membership(self, settings, roster):
        bindings = self._roster_bindings(roster)
        session = validate_discord_room(settings, self._people(), bindings,
                                       allow_moderator_only=True, roster=roster)
        session.setdefault('room_session', {})['bindings'] = bindings
        session.update(_room_membership_path=str(self._membership_path()),
            _room_roster_revision=roster['revision'], _room_transcript_dir=str(self._store.path.with_suffix('.events')),
            _room_store_root=str(self._root), _room_anonymous=self._data.get('anonymous', False),
            _room_moderator_id=next(m['bot_id'] for m in bindings if m['role'] == 'moderator'))
        members = {m['bot_id']: m for m in roster['members'] if m['phase'] != 'left'}
        for bot in session['bots']:
            member = members[bot['id']]
            bot.update(_room_membership_path=session['_room_membership_path'],
                _room_participant_id=member['participant_id'], _room_admission_id=member['admission_id'],
                _room_history_key=member['history_key'], _room_roster_revision=roster['revision'],
                _room_join_existing=True)
        return session

    def _persist_roster(self, roster, settings=None, *, save_settings=True):
        """Caller holds operation/state locks; publish no process before all writes succeed."""
        for member in roster['members']:
            if member['phase'] == 'joining':
                for flag in ('retry_departure', 'departure_drained', 'retry_retained_identity'):
                    member.pop(flag, None)
        settings = copy.deepcopy(settings if settings is not None else self._load())
        data = copy.deepcopy(self._data)
        data.update(roster=copy.deepcopy(roster), bindings=self._roster_bindings(roster))
        section = copy.deepcopy(settings.get('room_session') or {})
        section['bindings'] = copy.deepcopy(data['bindings'])
        if save_settings and not self._same_bindings(self.bindings(settings), data['bindings']):
            data.setdefault('membership_settings_pending', dict(previous_bindings=self.bindings(settings)))
        # Keep a failed reservation visible and recoverable even when the disk is
        # unavailable. No worker is launched until checkpoint, gate and settings agree.
        self._data = data
        if self._settings is not None:
            self._settings['room_session'] = copy.deepcopy(section)
        self._store.save(data)
        self._write_membership(roster)
        if save_settings and data.get('membership_settings_pending'):
            self._save({'room_session': section})
            data = copy.deepcopy(data)
            data.pop('membership_settings_pending', None)
            self._store.save(data)
            self._data = data
        if self._membership_persistence_error:
            if self._error == self._membership_persistence_error:
                self._error = ''
            if self._checkpoint_error == self._membership_persistence_error:
                self._checkpoint_error = ''
            self._membership_persistence_error = ''

    def _member(self, participant_id):
        member = next((m for m in self._data['roster']['members'] if m['participant_id'] == participant_id), None)
        if member is None:
            raise ValueError('The room participant is unavailable.')
        return member

    def _instance(self, bot_id):
        return next((item for item in getattr(self._addon, '_bridge_instances', [])
                     if item.instance_id == bot_id), None)

    def _stop_member_instance(self, bot_id, instance=None):
        if instance is not None and self._instance(bot_id) is not instance:
            return
        stop = getattr(self._addon, 'stop_owned_discord_instance', None)
        if stop is not None:
            stop(bot_id, room_identity=dict(self._store.identity))
        else:
            # Old controller fixtures/older addons have no compiled ownership seam.
            existing = self._instance(bot_id)
            if getattr(existing, 'settings', {}).get('_room_admission_id'):
                raise RuntimeError('Room-owned instance cleanup is unavailable.')
            self._addon.stop_bridge_instance(bot_id)

    def _notify_membership(self):
        with self._lock:
            roster = copy.deepcopy(self._data.get('roster') or {})
            bindings = self._roster_bindings(roster)
            people = {str(p.get('id')): p for p in self._people()}
            cached = {item['id']: item for item in self._candidate_bots}
            candidates = [{**copy.deepcopy(cached.get(m['bot_id']) or {'id': m['bot_id']}),
                           'name': (people.get(m['persona_id']) or {}).get('name') or m['persona_id']}
                          for m in bindings]
            payload = dict(revision=roster['revision'], candidate_bots=candidates)
        for identity in list(self._owned):
            self._addon.send_instance_command(identity, 'room_membership_changed', payload)

    def _capture_candidates(self, instance):
        candidates = (getattr(instance, 'settings', {}).get('room_router') or {}).get('candidate_bots')
        if isinstance(candidates, list):
            with self._lock:
                self._candidate_bots = copy.deepcopy(candidates)

    def _job_current(self, participant_id, admission_id, epoch):
        if self._phase != 'running' or not self._admission_current(participant_id, admission_id, epoch):
            return False
        member = self._member(participant_id)
        return member['phase'] in {'joining', 'leaving'}

    def _admission_current(self, participant_id, admission_id, epoch):
        if self._membership_epoch != epoch or self._stop_request is not None:
            return False
        member = self._member(participant_id)
        return member['admission_id'] == admission_id and member['phase'] != 'left'

    def _launch_job(self, member, target, *args):
        participant = member['participant_id']
        old = self._membership_threads.get(participant)
        if old is not None and old.is_alive():
            raise ValueError('This participant already has an operation awaiting cleanup.')
        token = (member['admission_id'], self._membership_epoch)
        member = copy.deepcopy(member)
        member['_required_revision'] = self._data['roster']['revision']
        thread = threading.Thread(target=target, args=(member, *token, *args),
            name='Discord room member ' + participant, daemon=True)
        self._membership_threads[participant] = thread
        thread.start()

    def _choose_account(self, settings, roster, bot_id=''):
        options = account_options(settings, roster)
        available = [item['bot_id'] for item in options if item['available'] and item['bot_id'] not in self._owned]
        if bot_id and bot_id not in available:
            raise ValueError('This prepared account is unavailable or reserved pending cleanup.')
        if not bot_id and not available:
            raise ValueError('No prepared Discord account is available. Add an account in Discord setup.')
        return bot_id or available[0]

    def add_persona(self, record, bot_id=''):
        with self._operation, self._lock:
            if self._stop_request is not None or self._phase == 'starting':
                raise RuntimeError('Wait for the room operation to finish.')
            settings = self._load()
            roster = self._ensure_roster(settings)
            persona_id = str(record.get('id') or '')
            if not any(str(p.get('id')) == persona_id for p in self._people()):
                raise ValueError('The saved Persona is unavailable.')
            previous = next((m for m in roster['members'] if m['persona_id'] == persona_id), None)
            if previous:
                pending = self._membership_threads.get(previous['participant_id'])
                if pending is not None and pending.is_alive():
                    raise ValueError('Wait for this participant cleanup to finish.')
            account = self._choose_account(settings, roster, str(bot_id or ''))
            roster, member = begin_admission(roster, persona_id, account)
            session = self._compile_membership(settings, roster)
            if self._phase != 'running':
                roster = settle_admission(roster, member['participant_id'], member['admission_id'], 'ready')
            try:
                self._persist_roster(roster, settings)
            except Exception as exc:
                self._fail_member(member, 'Participant admission could not be saved: ' + str(exc))
                return self.snapshot()
            state = self.snapshot()
            if self._phase == 'running':
                self._launch_job(member, self._join_member, session)
            return state

    def request_remove(self, participant_id):
        return self._request_departure(participant_id)

    def set_moderator(self, participant_id):
        """Persist an intentional stopped role change through the roster ledger."""
        with self._operation, self._lock:
            if (self._phase not in {'idle', 'error'} or self._owned
                    or self._stop_request is not None
                    or any(job.is_alive() for job in self._membership_threads.values())):
                raise RuntimeError('Stop the room and wait for participant cleanup before changing its moderator.')
            settings = self._load()
            roster = copy.deepcopy(self._ensure_roster(settings))
            selected = next((m for m in roster['members']
                if m['participant_id'] == participant_id and m['phase'] != 'left'), None)
            if selected is None:
                raise ValueError('Choose a participant in this Discord room.')
            if any(m['phase'] in {'joining', 'leaving'} for m in roster['members']):
                raise RuntimeError('Wait for participant cleanup before changing the moderator.')
            for member in roster['members']:
                if member['phase'] != 'left':
                    member['role'] = 'moderator' if member is selected else 'participant'
            roster['revision'] += 1
            validate_roster(roster)
            self._compile_membership(settings, roster)
            self._persist_roster(roster, settings)
            return self.snapshot()

    def replace_persona(self, participant_id, record, bot_id=''):
        return self._request_departure(participant_id, record=record, bot_id=bot_id)

    def _request_departure(self, participant_id, *, record=None, bot_id=''):
        with self._operation, self._lock:
            if self._stop_request is not None or self._phase == 'starting':
                raise RuntimeError('Wait for the room operation to finish.')
            settings = self._load()
            roster = self._ensure_roster(settings)
            member = copy.deepcopy(self._member(participant_id))
            pending = self._membership_threads.get(participant_id)
            if pending is not None and pending.is_alive():
                raise ValueError('Wait for this participant operation to finish.')
            if member['phase'] in {'joining', 'leaving'}:
                raise ValueError('Wait for this participant operation to finish.')
            persona_id = str((record or {}).get('id') or '')
            if record is not None and not any(str(p.get('id')) == persona_id for p in self._people()):
                raise ValueError('The saved replacement Persona is unavailable.')
            if bot_id and bot_id != member['bot_id']:
                if member['role'] == 'moderator':
                    raise ValueError('The moderator must retain its current account.')
                self._choose_account(settings, roster, str(bot_id))
            roster = request_departure(roster, participant_id, replacement_persona_id=persona_id,
                                       replacement_bot_id=str(bot_id or ''))
            leaving = next(m for m in roster['members'] if m['participant_id'] == participant_id)
            mod = self._moderator() if self._owned else {}
            leaving['drain_turn_id'] = str(mod.get('current_bot_turn_id') or '') if mod.get('current_bot_id') == member['bot_id'] else ''
            try:
                self._persist_roster(roster, settings)
            except Exception as exc:
                self._fail_member(leaving, 'Departure could not be saved: ' + str(exc), retry_departure=True)
                return self.snapshot()
            if self._phase != 'running' or member['bot_id'] not in self._owned:
                self._finish_departure(leaving, persona_id, running=False)
                return self.snapshot()
            state = self.snapshot()
            self._launch_job(leaving, self._depart_member, persona_id)
            return state

    def retry_join(self, participant_id):
        with self._operation, self._lock:
            settings = self._load()
            roster = self._ensure_roster(settings)
            member = copy.deepcopy(self._member(participant_id))
            thread = self._membership_threads.get(participant_id)
            if thread is not None and thread.is_alive():
                raise ValueError('Wait for this participant cleanup to finish.')
            if member['phase'] != 'failed':
                raise ValueError('Only a failed participant can retry joining.')
            if member.get('retry_departure'):
                roster = request_departure(roster, participant_id,
                    replacement_persona_id=member['replacement_persona_id'],
                    replacement_bot_id=member.get('replacement_bot_id', ''))
                leaving = next(m for m in roster['members'] if m['participant_id'] == participant_id)
                leaving.pop('retry_departure', None)
                try:
                    self._persist_roster(roster, settings)
                except Exception as exc:
                    self._fail_member(leaving, 'Departure retry could not be saved: ' + str(exc), retry_departure=True)
                    return self.snapshot()
                state = self.snapshot()
                if self._phase == 'running':
                    self._launch_job(leaving, self._depart_member, leaving['replacement_persona_id'])
                else:
                    self._finish_departure(leaving, leaving['replacement_persona_id'], running=False)
                return state
            if member['bot_id'] in self._owned or self._instance(member['bot_id']) is not None:
                if member.get('retry_retained_identity'):
                    state = self.snapshot()
                    self._launch_job(member, self._retry_retained_identity)
                    return state
                if member['role'] == 'moderator':
                    raise ValueError('Stop the room before retrying this moderator connection.')
                state = self.snapshot()
                self._launch_job(member, self._retry_member)
                return state
            roster = settle_admission(roster, participant_id, member['admission_id'], 'left')
            roster, member = begin_admission(roster, member['persona_id'], member['bot_id'], role=member['role'])
            session = self._compile_membership(settings, roster)
            if self._phase != 'running':
                roster = settle_admission(roster, participant_id, member['admission_id'], 'ready')
            self._persist_roster(roster, settings)
            state = self.snapshot()
            if self._phase == 'running':
                self._launch_job(member, self._join_member, session)
            return state

    def _retry_retained_identity(self, member, admission_id, epoch):
        joined = None
        try:
            instance = self._instance(member['bot_id'])
            server = getattr(instance, 'runtime_server', None)
            if server is None:
                raise RuntimeError('The retained persona runtime is unavailable.')
            with self._operation, self._lock:
                if not self._admission_current(member['participant_id'], admission_id, epoch):
                    return
                roster = settle_admission(self._data['roster'], member['participant_id'], admission_id, 'left')
                roster, joined = begin_admission(roster, member['persona_id'], member['bot_id'], role=member['role'])
                session = self._compile_membership(self._load(), roster)
                self._persist_roster(roster)
            expected = str(instance.settings.get('_room_admission_id') or '')
            prepared = self._addon.prepare_owned_discord_instance(session, member['bot_id'],
                room_identity=dict(self._store.identity), expected_admission_id=expected)
            server.rebind_room_member(prepared.settings, expected_admission_id=expected)
            instance.settings = prepared.settings
            self._capture_candidates(prepared)
            self._addon.send_instance_command(member['bot_id'], 'room_apply_identity', {'settings_path': str(prepared.settings_path)})
            if not self._wait_member(joined, joined['admission_id'], epoch):
                return
            with self._operation, self._lock:
                if self._job_current(joined['participant_id'], joined['admission_id'], epoch):
                    self._persist_roster(settle_admission(self._data['roster'], joined['participant_id'], joined['admission_id'], 'ready'))
            self._notify_membership()
        except Exception as exc:
            with self._operation, self._lock:
                current = joined or member
                if self._admission_current(current['participant_id'], current['admission_id'], epoch):
                    self._fail_member(current, 'Persona restoration retry failed: ' + str(exc), retry_identity=True)

    def _retry_member(self, member, admission_id, epoch):
        try:
            instance = self._instance(member['bot_id'])
            if instance is not None:
                self._stop_member_instance(member['bot_id'], instance)
            with self._operation, self._lock:
                self._owned.discard(member['bot_id'])
                if not self._admission_current(member['participant_id'], admission_id, epoch):
                    return
                roster = settle_admission(self._data['roster'], member['participant_id'], admission_id, 'left')
                roster, joined = begin_admission(roster, member['persona_id'], member['bot_id'], role=member['role'])
                session = self._compile_membership(self._load(), roster)
                if self._phase != 'running':
                    roster = settle_admission(roster, joined['participant_id'], joined['admission_id'], 'ready')
                self._persist_roster(roster)
                joined['_required_revision'] = roster['revision']
            if self._phase == 'running':
                self._join_member(joined, joined['admission_id'], epoch, session)
        except Exception as exc:
            with self._operation, self._lock:
                if self._admission_current(member['participant_id'], admission_id, epoch):
                    self._fail_member(member, 'Participant cleanup could not finish: ' + str(exc))

    def _member_ack(self, member, *, drained=False, strict=True):
        row = next((r for r in self._rows() if r['id'] == member['bot_id']), {})
        status = (row.get('node_status') or {}).get('room_member')
        if not status:
            instance = self._instance(member['bot_id'])
            compiled = getattr(instance, 'settings', {}).get('_room_admission_id')
            return not strict and not compiled and self._connected(row)
        exact = (status.get('participant_id') == member['participant_id']
                 and status.get('admission_id') == member['admission_id']
                 and type(status.get('revision')) is int
                 and status['revision'] >= member.get('_required_revision', 0))
        if drained:
            return exact and status.get('drained') is True and status.get('drain_turn_id') == member['drain_turn_id']
        return exact and self._connected(row) and status.get('ready') is True

    def _wait_member(self, member, admission_id, epoch, *, drained=False):
        deadline = time.monotonic() + self._ready_timeout
        while True:
            with self._lock:
                if not self._job_current(member['participant_id'], admission_id, epoch):
                    return False
                own_ack = (drained and member.get('departure_drained')) or self._member_ack(member, drained=drained)
                peers_settled = True
                if drained:
                    rows = {row['id']: row for row in self._rows()}
                    for peer in member.get('_history_settlement_peers', []):
                        status = ((rows.get(peer['bot_id']) or {}).get('node_status') or {}).get('room_member') or {}
                        exact_peer = (status.get('participant_id') == peer['participant_id']
                            and status.get('admission_id') == peer['admission_id']
                            and type(status.get('revision')) is int
                            and status['revision'] >= member.get('_required_revision', 0))
                        receipts = status.get('history_settlements') or []
                        acknowledged = exact_peer and any(isinstance(receipt, dict)
                            and receipt.get('participant_id') == member['participant_id']
                            and receipt.get('admission_id') == admission_id
                            and receipt.get('drain_turn_id') == member['drain_turn_id']
                            and type(receipt.get('revision')) is int
                            and receipt['revision'] >= member.get('_required_revision', 0)
                            and receipt.get('settled') is True for receipt in receipts)
                        if not acknowledged:
                            peers_settled = False
                            break
                if own_ack and peers_settled:
                    return True
                if drained and member.get('drain_turn_id'):
                    row = next((r for r in self._rows() if r['id'] == member['bot_id']), {})
                    moderator = self._moderator()
                    if (self._connected(row) and moderator.get('current_bot_id') == member['bot_id']
                            and moderator.get('current_bot_turn_id') == member['drain_turn_id']):
                        # A legitimate current reply may exceed the startup budget.
                        deadline = time.monotonic() + self._ready_timeout
            if time.monotonic() >= deadline:
                raise RuntimeError('The participant did not acknowledge ' + ('its exact reply drain.' if drained else 'voice and persona readiness.'))
            time.sleep(.02)

    def _join_member(self, member, admission_id, epoch, session):
        instance = None
        try:
            self._notify_membership()
            instance = self._addon.prepare_owned_discord_instance(session, member['bot_id'], room_identity=dict(self._store.identity))
            self._capture_candidates(instance)
            with self._lock:
                if not self._job_current(member['participant_id'], admission_id, epoch):
                    return
            self._addon.start_owned_discord_instance(instance, room_identity=dict(self._store.identity))
            with self._lock:
                if self._job_current(member['participant_id'], admission_id, epoch):
                    self._owned.add(member['bot_id'])
            if not self._wait_member(member, admission_id, epoch):
                self._stop_member_instance(member['bot_id'], instance)
                return
            with self._operation, self._lock:
                current = self._job_current(member['participant_id'], admission_id, epoch)
                if current:
                    roster = settle_admission(self._data['roster'], member['participant_id'], admission_id, 'ready')
                    self._persist_roster(roster)
            if not current:
                self._stop_member_instance(member['bot_id'], instance)
                return
            self._notify_membership()
        except Exception as exc:
            error = str(exc)
            try:
                if instance is not None:
                    self._stop_member_instance(member['bot_id'], instance)
            except Exception as cleanup:
                error += '; account cleanup failed: ' + str(cleanup)
            with self._operation, self._lock:
                if self._instance(member['bot_id']) is None:
                    self._owned.discard(member['bot_id'])
                elif self._instance(member['bot_id']) is instance:
                    self._owned.add(member['bot_id'])
                if self._admission_current(member['participant_id'], admission_id, epoch):
                    self._fail_member(member, error)

    def _fail_member(self, member, error, *, retry_departure=False, retry_identity=False):
        roster = settle_admission(self._data['roster'], member['participant_id'], member['admission_id'], 'failed', error=error)
        failed = next(m for m in roster['members'] if m['participant_id'] == member['participant_id'])
        if retry_departure:
            failed['retry_departure'] = True
            if member.get('departure_drained'):
                failed['departure_drained'] = True
        if retry_identity:
            failed['retry_retained_identity'] = True
        try:
            self._persist_roster(roster)
        except Exception as exc:
            # A failed checkpoint must not prevent a writable authoritative gate
            # from fencing this admission. If the gate itself remains unwritable,
            # interrupt only this owned connection rather than leave it routable.
            try:
                self._write_membership(roster)
            except Exception as gate:
                error += '; connection interrupted because membership gate could not be saved: ' + str(gate)
                try:
                    instance = self._instance(member['bot_id'])
                    if instance is not None:
                        self._stop_member_instance(member['bot_id'], instance)
                    self._owned.discard(member['bot_id'])
                    failed['departure_drained'] = True
                except Exception as cleanup:
                    error += '; affected connection cleanup failed: ' + str(cleanup)
                failed['error'] = error
                self._data['roster'] = roster
                try:
                    self._store.save(self._data)
                except Exception:
                    pass
            self._membership_persistence_error = 'Participant state could not be saved: ' + str(exc)
            self._checkpoint_error = self._membership_persistence_error
            self._error = self._checkpoint_error

    def _depart_member(self, member, admission_id, epoch, replacement):
        try:
            self._notify_membership()
            with self._lock:
                member['_history_settlement_peers'] = [
                    {key: peer[key] for key in ('bot_id', 'participant_id', 'admission_id')}
                    for peer in self._data['roster']['members']
                    if peer['bot_id'] in self._owned and peer['bot_id'] != member['bot_id'] and peer['phase'] != 'left']
            payload = {key: member[key] for key in ('participant_id', 'admission_id', 'drain_turn_id')}
            for identity in list(self._owned):
                self._addon.send_instance_command(identity, 'room_request_departure', payload)
            if not self._wait_member(member, admission_id, epoch, drained=True):
                return
            with self._operation, self._lock:
                if not self._job_current(member['participant_id'], admission_id, epoch):
                    return
                self._collect()
                member['departure_drained'] = True
            if replacement:
                if (member.get('replacement_bot_id') and member['replacement_bot_id'] != member['bot_id']) or self._instance(member['bot_id']) is None:
                    self._move_member(member, admission_id, epoch, replacement)
                    return
                self._replace_member(member, admission_id, epoch, replacement)
                return
            if self._instance(member['bot_id']) is not None:
                self._stop_member_instance(member['bot_id'])
            with self._operation, self._lock:
                if self._job_current(member['participant_id'], admission_id, epoch):
                    self._owned.discard(member['bot_id'])
                    self._finish_departure(member, '', running=True)
            self._notify_membership()
        except Exception as exc:
            with self._operation, self._lock:
                if self._job_current(member['participant_id'], admission_id, epoch):
                    self._fail_member(member, str(exc))

    def _finish_departure(self, member, replacement, *, running):
        previous = copy.deepcopy(self._data)
        roster = settle_admission(self._data['roster'], member['participant_id'], member['admission_id'], 'left')
        if replacement:
            roster, joined = begin_admission(roster, replacement, member.get('replacement_bot_id') or member['bot_id'], role=member['role'])
            if not running:
                roster = settle_admission(roster, joined['participant_id'], joined['admission_id'], 'ready')
        try:
            self._persist_roster(roster)
            return True
        except Exception as exc:
            # No new runtime has been exposed yet. Restore the captured source
            # intent under a newer revision and retain both account reservations.
            previous['roster']['revision'] = roster['revision'] + 1
            self._data = previous
            self._fail_member(member, 'Departure completion could not be saved: ' + str(exc), retry_departure=True)
            return False

    def _move_member(self, member, admission_id, epoch, replacement):
        if self._instance(member['bot_id']) is not None:
            self._stop_member_instance(member['bot_id'])
        with self._operation, self._lock:
            self._owned.discard(member['bot_id'])
            if not self._job_current(member['participant_id'], admission_id, epoch):
                return
            if not self._finish_departure(member, replacement, running=True):
                return
            joined = copy.deepcopy(next(m for m in self._data['roster']['members'] if m['persona_id'] == replacement))
            joined['_required_revision'] = self._data['roster']['revision']
            session = self._compile_membership(self._load(), self._data['roster'])
            self._persist_roster(self._data['roster'])
            self._membership_threads[joined['participant_id']] = threading.current_thread()
        self._join_member(joined, joined['admission_id'], epoch, session)

    def _replace_member(self, member, admission_id, epoch, replacement):
        """Retain the connection; rollback uses a fresh admission and original history."""
        instance = self._instance(member['bot_id'])
        server = getattr(instance, 'runtime_server', None)
        if server is None or not hasattr(server, 'rebind_room_member'):
            raise RuntimeError('Live persona identity replacement is unavailable for this runtime.')
        joined = None
        try:
            with self._operation, self._lock:
                if not self._job_current(member['participant_id'], admission_id, epoch):
                    return
                if not self._finish_departure(member, replacement, running=True):
                    return
                joined = copy.deepcopy(next(m for m in self._data['roster']['members'] if m['persona_id'] == replacement))
                session = self._compile_membership(self._load(), self._data['roster'])
                self._persist_roster(self._data['roster'])
            prepared = self._addon.prepare_owned_discord_instance(session, member['bot_id'],
                room_identity=dict(self._store.identity), expected_admission_id=admission_id)
            self._capture_candidates(prepared)
            server.rebind_room_member(prepared.settings, expected_admission_id=admission_id)
            instance.settings = prepared.settings
            self._addon.send_instance_command(member['bot_id'], 'room_apply_identity', {'settings_path': str(prepared.settings_path)})
            if not self._wait_member(joined, joined['admission_id'], epoch):
                return
            with self._operation, self._lock:
                if self._job_current(joined['participant_id'], joined['admission_id'], epoch):
                    status = (next(r for r in self._rows() if r['id'] == member['bot_id']).get('node_status') or {}).get('room_member') or {}
                    if status.get('nickname_error'):
                        raise RuntimeError('The replacement nickname was not applied: ' + str(status['nickname_error']))
                    self._persist_roster(settle_admission(self._data['roster'], joined['participant_id'], joined['admission_id'], 'ready'))
            self._notify_membership()
        except Exception as exc:
            if joined is None:
                raise
            restored = None
            try:
                with self._operation, self._lock:
                    if not self._admission_current(joined['participant_id'], joined['admission_id'], epoch):
                        return
                    roster = request_departure(self._data['roster'], joined['participant_id'], replacement_persona_id=member['persona_id'])
                    roster = settle_admission(roster, joined['participant_id'], joined['admission_id'], 'left')
                    roster, restored = begin_admission(roster, member['persona_id'], member['bot_id'], role=member['role'])
                    self._persist_roster(roster)
                    session = self._compile_membership(self._load(), self._data['roster'])
                current_admission = str(getattr(server, 'settings', instance.settings).get('_room_admission_id') or '')
                if current_admission not in {admission_id, joined['admission_id']}:
                    raise RuntimeError('The retained runtime identity changed during rollback.')
                prepared = self._addon.prepare_owned_discord_instance(session, member['bot_id'],
                    room_identity=dict(self._store.identity), expected_admission_id=str(instance.settings.get('_room_admission_id') or ''))
                self._capture_candidates(prepared)
                server.rebind_room_member(prepared.settings, expected_admission_id=current_admission)
                instance.settings = prepared.settings
                self._addon.send_instance_command(member['bot_id'], 'room_apply_identity', {'settings_path': str(prepared.settings_path)})
                if self._wait_member(restored, restored['admission_id'], epoch):
                    with self._operation, self._lock:
                        self._persist_roster(settle_admission(self._data['roster'], restored['participant_id'], restored['admission_id'], 'ready',
                            error='Replacement failed; previous persona restored: ' + str(exc)))
            except Exception as rollback:
                with self._operation, self._lock:
                    captured = restored or joined
                    if self._admission_current(captured['participant_id'], captured['admission_id'], epoch):
                        self._fail_member(captured, 'Replacement failed: ' + str(exc) + '; restoring the previous persona failed: ' + str(rollback),
                                          retry_identity=True)
            self._notify_membership()

    @staticmethod
    def _connected(row):
        return bool(row.get('runtime_connected') and row.get('endpoint_running', True)
                    and (row.get('node_status') or {}).get('voice_connected'))

    def _connection_problem(self, rows):
        connected = {row['id'] for row in rows if self._connected(row)}
        expected = self._owned
        if self._data.get('roster'):
            expected = {m['bot_id'] for m in self._data['roster']['members'] if m['phase'] == 'ready'} & self._owned
        if expected - connected:
            return 'A Discord room bot is disconnected or its runtime endpoint is unavailable. Stop and reconnect the room.'
        return ''

    def _startup_problem(self, rows):
        by_id = {row['id']: row for row in rows}
        problems = []
        for identity in sorted(self._owned):
            row = by_id.get(identity)
            if row is None:
                problems.append(identity + ': bot process was not started')
                continue
            reasons = []
            if not row.get('runtime_connected'):
                reasons.append('bot process is not running')
            if not row.get('endpoint_running', True):
                reason = 'runtime endpoint is not running'
                if row.get('endpoint_error'):
                    reason += ' (' + str(row['endpoint_error']) + ')'
                reasons.append(reason)
            node = row.get('node_status') or {}
            if not node:
                reasons.append('no Discord status has been reported')
            elif not node.get('voice_connected'):
                reason = 'Discord voice is not connected'
                if node.get('last_error'):
                    reason += ' (' + str(node['last_error']) + ')'
                reasons.append(reason)
            if reasons:
                problems.append(identity + ': ' + '; '.join(reasons))
        return 'The Discord bots or runtime endpoints did not connect and become ready. ' + ' | '.join(problems)

    def _present_directive(self, moderator):
        queue = self._filtered_continuation({'room_directives': moderator.get('room_directives') or []})['room_directives']
        relevant = [entry for entry in queue if entry.get('kind') in {'guide', 'say'}]
        pending = [entry for entry in relevant if entry.get('status', 'queued') in {'queued', 'preparing', 'delivering'}]
        failed = [entry for entry in relevant if entry.get('status') == 'failed']
        entry = pending[0] if pending else (failed[-1] if failed else None)
        if entry is None:
            return {}
        return {key: copy.deepcopy(entry[key]) for key in ('id', 'kind', 'text', 'moderator_id') if key in entry} | {
            'status': entry.get('status', 'queued'), 'detail': str(entry.get('detail') or entry.get('error') or '')}

    def _rows(self):
        return [row for row in self._addon.status_snapshot().get('instances', []) if row.get('id') in self._owned]

    def _moderator(self, rows=None):
        states = [(row.get('node_status') or {}).get('moderator_state') or {} for row in (self._rows() if rows is None else rows)]
        return copy.deepcopy(max(states, key=lambda state: str(state.get('updated_at') or ''), default={}))

    def _command(self, action, payload=None, target=None):
        bindings = self.bindings(self._settings or self._load())
        leader = next((b['bot_id'] for b in bindings if b.get('role') == 'moderator'), '')
        identity = target or leader
        if identity not in self._owned:
            raise RuntimeError('The room bot is unavailable. Stop and reconnect the room.')
        return self._addon.send_instance_command(identity, action, dict(payload or {}))

    def _collect(self):
        if self._settings is None:
            return
        folder = Path(self._settings['_room_transcript_dir'])
        # Commit cursors and message changes together only after the atomic save succeeds.
        data = copy.deepcopy(self._data)
        cursors = data.setdefault('cursors', {})
        messages = data.setdefault('messages', [])
        indexed = {m['id']: m for m in messages}
        seen = set(data.get('seen_events') or [])
        completed = set(data.get('completed_directives') or [])
        changed = False
        for bot_id in sorted(self._owned):
            path = folder / (bot_id + '.jsonl')
            if not path.exists():
                continue
            with path.open('rb') as stream:
                cursor = int(cursors.get(bot_id, 0))
                if cursor > path.stat().st_size:
                    raise RuntimeError('The Discord transcript changed unexpectedly; its saved history was preserved.')
                stream.seek(cursor)
                while True:
                    line = stream.readline()
                    if not line.endswith(b'\n'):
                        break
                    event = json.loads(line)
                    event_id = str(event['event_id'])
                    if event_id not in seen:
                        if event.get('kind') == 'directive_complete':
                            completed.add(str(event['directive_id']))
                        else:
                            message_id = str(event['message_id'])
                            message = indexed.get(message_id)
                            timestamp = str(event.get('timestamp') or '')
                            if message is None:
                                message = dict(id=message_id, name=str(event['name']), speaker_id=str(event['speaker_id']),
                                    timestamp=timestamp, parts={}, text='',
                                    role='user' if event.get('kind') == 'human' else 'assistant')
                                indexed[message_id] = message; messages.append(message)
                            elif timestamp and (not message.get('timestamp') or timestamp < message['timestamp']):
                                message['timestamp'] = timestamp
                            message['parts'][str(int(event.get('chunk_index', 0)))] = str(event['text'])
                            message['text'] = ' '.join(text for _,text in sorted(message['parts'].items(),key=lambda item:int(item[0])))
                        seen.add(event_id)
                    cursors[bot_id] = stream.tell(); changed = True
        if changed:
            data['seen_events'] = sorted(seen)
            data['completed_directives'] = sorted(completed)
            messages.sort(key=lambda message: (message.get('timestamp', ''), message['id']))
            self._store.save(data)
            self._data = data

    def _display_messages(self, messages, rows, moderator, member_map):
        # Status previews are deliberately excluded from _data, transcript saves and history().
        display = copy.deepcopy(messages)
        if self._phase != 'running':
            return display
        bot_id = str(moderator.get('current_bot_id') or '')
        turn_id = str(moderator.get('current_bot_turn_id') or '')
        row = next((row for row in rows if row['id'] == bot_id and self._connected(row)), None)
        if row is None or not turn_id:
            return display
        node = row.get('node_status') or {}
        preview = node.get('room_presentation')
        message_id = bot_id + ':' + turn_id
        if (not isinstance(preview, dict) or preview.get('id') != message_id
                or preview.get('turn_id') != turn_id or preview.get('speaker_id') != bot_id
                or node.get('active_turn_id') != turn_id
                or (not str(preview.get('text') or '').strip() and preview.get('display_pending') is not True)):
            return display
        if member_map:
            member = member_map.get(preview.get('participant_id')) or {}
            reported = node.get('room_member') or {}
            if (member.get('bot_id') != bot_id
                    or not preview.get('admission_id') or member.get('admission_id') != preview['admission_id']
                    or reported.get('participant_id') != member.get('participant_id')
                    or reported.get('admission_id') != member.get('admission_id')
                    or not (member.get('phase') == 'ready' or (member.get('phase') == 'leaving'
                        and member.get('drain_turn_id') == turn_id))):
                return display
        try:
            progress = min(1.0, max(0.0, float(preview.get('speech_progress') or 0)))
        except (TypeError, ValueError):
            progress = 0.0
        existing = next((message for message in display if message.get('id') == message_id), None)
        if existing is None:
            existing = dict(id=message_id, name=str(preview.get('name') or bot_id), speaker_id=bot_id,
                timestamp=str(preview.get('timestamp') or ''), role='assistant')
            display.append(existing)
        existing.update(text=str(preview.get('text') or ''), display_pending=preview.get('display_pending') is True,
            speech_active=bool(preview.get('speech_active')),
            speech_progress=progress, spoken_text=str(preview.get('spoken_text') or ''),
            spoken_prefix=str(preview.get('spoken_prefix') or ''))
        return display

    def _add_reply_settings(self, participants, people, prepared, settings):
        from core.persona_overrides import resolve_persona_reply_settings

        capability = getattr(getattr(getattr(self._addon, 'context', None), 'capabilities', None), 'runtime_config', None)
        snapshot = getattr(capability, 'snapshot', None)
        try:
            runtime_config = dict(snapshot() or {}) if callable(snapshot) else {}
        except Exception:
            runtime_config = {}
        base_chat = settings.get('chat') or {}
        session_bots = {bot['id']: bot for bot in (self._settings or {}).get('bots', [])}
        live_bots = {str(getattr(instance, 'instance_id', '')): getattr(instance, 'settings', {})
                     for instance in getattr(self._addon, '_bridge_instances', [])} if self._phase == 'running' else {}
        for participant in participants:
            if participant['role'] == 'human':
                continue
            bot = prepared.get(participant['id']) or {}
            raw_chat = bot.get('chat') or {}
            chat = {**base_chat, **raw_chat}
            # Managed Discord compilation uses the Runtime model unless the
            # assigned Persona overrides it; account shells carry no model policy.
            chat['use_global_model'] = True
            live = live_bots.get(participant['id']) or session_bots.get(participant['id']) or {}
            if isinstance(live.get('chat'), dict):
                chat = copy.deepcopy(live['chat'])
            person = people.get(participant.get('persona_id')) or {}
            summary = resolve_persona_reply_settings(runtime_config, chat, person.get('overrides'), local_room=True)
            inherited = resolve_persona_reply_settings(runtime_config, chat, {}, local_room=True)
            if 'context_entries' in raw_chat or chat.get('context_entries') != base_chat.get('context_entries'):
                inherited['context_source'] = 'participant'
                if summary['context_source'] != 'persona':
                    summary['context_source'] = 'participant'
            summary['inherited_defaults'] = inherited
            participant['reply_settings'] = summary

    def snapshot(self):
        with self._lock:
            account_settings = self._load()
            settings = self._settings or account_settings
            anonymous_available = False
            try:
                self._ensure_store(settings)
                anonymous_available = True
                self._collect()
                has_history = (self._has_history(settings) if self._phase in {'idle', 'error'} and not self._owned
                    else bool(self._data.get('messages') or self._data.get('continuation')))
                if self._error == self._history_error:
                    self._error = self._checkpoint_error
                self._history_error = ''
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                self._history_error = 'Discord room history is unavailable: ' + str(exc)
                self._error = self._history_error
                has_history = bool(self._data.get('messages') or self._data.get('continuation'))
            bindings = self.bindings(settings)
            roster = self._data.get('roster')
            if roster:
                bindings = self._roster_bindings(roster)
            member_map = {m['participant_id']: m for m in (roster or {}).get('members', [])}
            people = {p['id']:p for p in self._people()}
            prepared = {b['id']:b for b in account_settings.get('bots', []) if b.get('id')}
            rows = self._rows() if self._owned else []
            row_map = {row['id']: row for row in rows}
            moderator = self._moderator(rows) if rows else copy.deepcopy(self._data.get('continuation') or {})
            hold = moderator.get('room_hold') or {}
            current = str(moderator.get('current_bot_id') or (moderator.get('current_human_route') or {}).get('speaker_user_id') or '')
            next_id = str((moderator.get('pending_route') or {}).get('target_bot_id') or
                          (moderator.get('pending_human_route') or {}).get('speaker_user_id') or '')
            participants = []
            for member in bindings:
                bot_id = member.get('bot_id', '')
                person = people.get(member.get('persona_id')) or {}
                row = row_map.get(bot_id) or {}
                node = row.get('node_status') or {}
                connected = self._connected(row)
                membership = member_map.get(member['participant_id']) or {}
                membership_phase = membership.get('phase', 'ready')
                eligible = membership_phase == 'ready' and connected
                participants.append(dict(id=bot_id or member['participant_id'], participant_id=member['participant_id'],
                    admission_id=membership.get('admission_id', ''),
                    persona_id=member['persona_id'], bot_id=bot_id, name=person.get('name') or 'Persona unavailable',
                    bot_name=(prepared.get(bot_id) or {}).get('name') or bot_id, role=member.get('role','participant'),
                    connected=connected, speaking=connected and bool(node.get('speaking')),
                    desired=membership_phase not in {'leaving', 'left'}, present=connected, eligible=eligible, owned=bot_id in self._owned,
                    membership_phase=membership_phase, membership_error=membership.get('error', ''),
                    nickname=str((node.get('room_member') or {}).get('nickname') or ''),
                    nickname_error=str((node.get('room_member') or {}).get('nickname_error') or ''),
                    can_retry=membership_phase == 'failed' and not self._stop_request,
                    can_remove=member.get('role') != 'moderator' and membership_phase in {'ready', 'failed'} and not self._stop_request,
                    can_replace=membership_phase == 'ready' and not self._stop_request,
                    has_floor=bool(connected and current and current==bot_id), muted=bot_id in moderator.get('muted_bot_ids',[]),
                    avatar_path=person.get('avatar_path',''), history_count=len(self._data.get('messages') or [])))
            humans = {}
            for row in rows:
                if not self._connected(row):
                    continue
                for human in (row.get('node_status') or {}).get('participants', []):
                    if not human.get('is_bot'):
                        identity=str(human['id'])
                        humans[identity]=dict(id=identity,name=str(human.get('name') or identity),role='human',connected=True,
                            speaking=current==identity,has_floor=current==identity,
                            muted=identity in moderator.get('muted_speaker_user_ids',[]))
            participants.extend(humans.values())
            self._add_reply_settings(participants, people, prepared, settings)
            text_senders = [dict(id=p['id'], name=p['name']) for p in humans.values()]
            text_senders.append(dict(id='nc_operator', name='NC operator'))
            text_sender_id = str(self._data.get('text_sender_id') or '')
            if not text_sender_id and len(humans) == 1:
                text_sender_id = next(iter(humans))
                # Once shown, the default belongs to this person even if they leave.
                data = copy.deepcopy(self._data)
                data['text_sender_id'] = text_sender_id
                self._store.save(data)
                self._data = data
            text_sender = next((p for p in text_senders if p['id'] == text_sender_id), None)
            if not next_id:
                preparation = moderator.get('room_preparation') or {}
                target = str(preparation.get('target_bot_id') or '')
                eligible = any(person['id'] == target and person.get('bot_id')
                    and person.get('connected') and not person.get('muted') for person in participants)
                only = moderator.get('only_bot_ids') or []
                locked = str(moderator.get('floor_target_bot_id') or '')
                if (preparation.get('status') == 'preparing' and preparation.get('route_key')
                        and current and target != current and eligible
                        and preparation.get('source_bot_id') == moderator.get('current_bot_id')
                        and preparation.get('source_turn_id')
                        and preparation.get('source_turn_id') == moderator.get('current_bot_turn_id')
                        and not moderator.get('floor_speaker_user_id')
                        and (not locked or locked == target) and (not only or target in only)):
                    next_id = target
            for person in participants:
                person['is_next'] = bool(next_id and person['id'] == next_id)
            identity = dict(self._store.identity) if self._store else {}
            transport_error = self._connection_problem(rows)
            node_error = next((str((row.get('node_status') or {}).get('last_error') or '') for row in rows
                               if (row.get('node_status') or {}).get('last_error')), '')
            display_error = self._error or transport_error or node_error or str(moderator.get('last_error') or '')
            # The compiled session contains only its initial cast, not the reusable account pool.
            account_labels = {account['id']: account['label'] for account in account_rows(account_settings)}
            messages = [{k:v for k,v in m.items() if k!='parts'} for m in self._data.get('messages',[])]
            return dict(mode='discord',room_key='discord:' + (self._store.path.stem if self._store else ''),
                phase=self._phase, error=display_error, stopping=self._stop_request is not None,
                anonymous=self._data.get('anonymous', False),
                paused=hold.get('phase')=='paused', pausing=hold.get('phase')=='draining',
                joined=True,muted=False,input_mode='text_only',user_name='NC operator',
                text_senders=text_senders, text_sender_id=text_sender_id,
                text_sender_name=text_sender['name'] if text_sender else '',
                text_sender_available=text_sender is not None,
                participants=participants,bindings=bindings,current_id=current,next_id=next_id,moderator=moderator,
                messages=messages, display_messages=self._display_messages(messages, rows, moderator, member_map),
                prepared_bots=[dict(id=b['id'],name=account_labels.get(str(b['id'])) or b.get('name') or b['id'])
                    for b in account_settings.get('bots',[]) if b.get('id') and not b.get('local_room_role')],
                available_accounts=account_options(account_settings, roster) if roster else [],
                server_id=identity.get('guild_id',''),channel_id=identity.get('channel_id',''),
                capabilities=dict(local_microphone=False,edit_cast=self._phase in {'idle','error','running'} and not self._stop_request,
                    live_membership=True,
                    edit_anonymous=anonymous_available),
                conversation=dict(id='discord:' + (self._store.path.stem if self._store else ''),
                    topic=self._data.get('topic',''),saved=True,has_history=has_history,
                    continuing=self._continuing,member_count=len(bindings)),
                behavior=copy.deepcopy((settings.get('room_router') or {}).get('local_room_behavior') or {}),directive=self._present_directive(moderator))

    def start(self, saved_settings):
        with self._operation, self._lock:
            if self._phase=='running': return self.snapshot()
            if self._phase == 'starting' or any(t.is_alive() for t in self._membership_threads.values()):
                raise RuntimeError('Wait for pending participant cleanup before starting the room.')
            if getattr(self._addon,'_bridge_instances',[]):
                raise RuntimeError('Another bridge is already active. Stop it before starting this room.')
            try:
                bindings = self.bindings(saved_settings)
                self._ensure_store(saved_settings)
                roster = self._ensure_roster(saved_settings)
                session = self._compile_membership(saved_settings, roster)
                self._persist_roster(roster, saved_settings, save_settings=False)
                start_accounts = {m['bot_id'] for m in roster['members'] if m['phase'] == 'ready'}
                session['bots'] = [bot for bot in session['bots'] if bot['id'] in start_accounts]
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                self._error = str(exc)
                self._phase = 'error'
                raise
            self._settings=session; self._error=''; self._phase='starting'
            self._owned={b['id'] for b in session['bots']}
            session['_room_start_held']=True
            session['_room_anonymous']=self._data['anonymous']
            session['_room_moderator_id']=next(b['bot_id'] for b in self.bindings(session) if b['role']=='moderator')
            session['_room_transcript_dir']=str(self._store.path.with_suffix('.events'))
            session['_room_store_root']=str(self._root)
        try:
            # Process startup and readiness waits never hold the reservation locks.
            self._addon._start_instances_from_settings(session,force=True,sync_tiny_mvp_mic=False)
            register = getattr(self._addon, 'register_owned_discord_instance', None)
            if register is not None:
                for instance in getattr(self._addon, '_bridge_instances', []):
                    if instance.instance_id in self._owned:
                        register(instance, room_identity=dict(self._store.identity))
                        self._capture_candidates(instance)
            deadline=time.monotonic()+self._ready_timeout
            while True:
                with self._lock:
                    rows=self._rows()
                    ready={m['bot_id'] for m in roster['members'] if m['phase'] == 'ready' and self._member_ack(m, strict=False)}
                    if ready==self._owned: break
                    if time.monotonic()>=deadline: raise RuntimeError(self._startup_problem(rows))
                time.sleep(.02)
            with self._operation, self._lock:
                self._phase='running'
                state = self.snapshot()
                if self._history_error or self._checkpoint_error:
                    return state
                checkpoint=self._filtered_continuation(self._data.get('continuation') or {})
                self._continuing=bool(checkpoint or self._data.get('messages'))
                if checkpoint:
                    self._command('room_restore_checkpoint',dict(moderator=checkpoint))
                    problem = self._continuation_problem(checkpoint, state['participants'])
                    if problem:
                        self._error = problem
                        return self.snapshot()
                self._command('room_resume')
                next_bot = str((checkpoint.get('pending_route') or {}).get('target_bot_id') or '')
                if next_bot and not checkpoint.get('room_directives'):
                    self._command('moderator_call_on', {'reason': 'Continue the saved room handoff.', 'room_continuation': True}, target=next_bot)
                return self.snapshot()
        except Exception as exc:
            with self._operation, self._lock:
                self._error=str(exc); self._phase='error'
                self._teardown()
                raise

    def _filtered_continuation(self, value):
        result = copy.deepcopy(value)
        completed = set(self._data.get('completed_directives') or [])
        if 'room_directives' in result:
            result['room_directives'] = [item for item in result['room_directives'] if item.get('id') not in completed]
        return result

    @staticmethod
    def _continuation_problem(continuation, participants):
        bots = {str(p['id']) for p in participants if p.get('connected') and p.get('role') != 'human'}
        humans = {str(p['id']) for p in participants if p.get('connected') and p.get('role') == 'human'}
        bot_targets = [str((continuation.get('pending_route') or {}).get('target_bot_id') or ''),
                       str(continuation.get('floor_target_bot_id') or '')]
        human_targets = [str((continuation.get('current_human_route') or {}).get('speaker_user_id') or ''),
                         str((continuation.get('pending_human_route') or {}).get('speaker_user_id') or ''),
                         str(continuation.get('floor_speaker_user_id') or '')]
        for key in ('only_bot_ids', 'muted_bot_ids'):
            bot_targets.extend(str(item) for item in continuation.get(key) or [])
        human_targets.extend(str(item) for item in continuation.get('muted_speaker_user_ids') or [])
        if (any(target and target not in bots for target in bot_targets)
                or any(target and target not in humans for target in human_targets)):
            return ('A saved next speaker, speaker lock, or routing mute target is unavailable. '
                    'Choose a connected participant or clear the saved routing choice before Resume room.')
        return ''

    def _teardown(self):
        for identity in sorted(self._owned):
            self._stop_member_instance(identity)
        self._owned.clear(); self._settings=None

    def stop_after_turn(self):
        with self._operation, self._lock:
            if self._stop_request is not None or not self._owned: return self.snapshot()
            # Fence pending callbacks before the first hold command or teardown.
            self._membership_epoch += 1
            roster = copy.deepcopy(self._data.get('roster'))
            if roster:
                changed = False
                for member in roster['members']:
                    if member['phase'] == 'joining':
                        roster = settle_admission(roster, member['participant_id'], member['admission_id'], 'failed',
                                                  error='Room stopped before this participant finished joining. Retry to reconnect.')
                        changed = True
                if changed:
                    try:
                        self._persist_roster(roster)
                    except Exception as exc:
                        self._checkpoint_error = 'Pending participant cleanup could not be saved: ' + str(exc)
                        self._error = self._checkpoint_error
            current = self.snapshot()
            hold = current['moderator'].get('room_hold')
            # Node retains an existing hold unchanged until Resume, including its ID.
            self._stop_hold_request = str(hold.get('request_id') or '') if hold is not None else uuid.uuid4().hex
            self._command('room_pause_after_turn',dict(request_id=self._stop_hold_request))
            token=object(); self._stop_request=token
            self._stop_thread=threading.Thread(target=self._finish_stop,args=(token,),name='Discord room finish and stop',daemon=True)
            self._stop_thread.start()
            return self.snapshot()

    def _finish_stop(self, token):
        try:
            deadline=time.monotonic()+180
            while True:
                with self._operation, self._lock:
                    if self._stop_request is not token: return
                    state=self.snapshot()
                    if self._history_error:
                        raise RuntimeError(self._history_error)
                    rows = self._rows()
                    held = {row['id'] for row in rows
                            if self._connected(row)
                            and ((row.get('node_status') or {}).get('moderator_state') or {}).get('room_hold', {}).get('phase') == 'paused'
                            and ((row.get('node_status') or {}).get('moderator_state') or {}).get('room_hold', {}).get('request_id') == self._stop_hold_request}
                    if state['paused'] and held == self._owned:
                        # The common hold acknowledges all audio/history settlement.
                        # Complete recorded departures before saving a stopped cast.
                        for member in list((self._data.get('roster') or {}).get('members', [])):
                            if member['phase'] == 'leaving':
                                self._finish_departure(copy.deepcopy(member), member['replacement_persona_id'], running=False)
                        self._data['continuation']=self._filtered_continuation({k:state['moderator'][k] for k in _CONTINUATION_FIELDS if k in state['moderator']})
                        self._data['bindings']=self.bindings(self._settings)
                        self._store.save(self._data)
                        if self._error == self._checkpoint_error:
                            self._error = ''
                        self._checkpoint_error = ''
                        self._teardown(); self._phase='idle'; self._stop_request=None
                        return
                    if time.monotonic()>=deadline: raise RuntimeError('The current speaker has not finished. Use Stop speech and hold if necessary, then retry Stop room.')
                time.sleep(.05)
        except Exception as exc:
            with self._lock:
                self._checkpoint_error='The room could not finish stopping: '+str(exc)
                self._error=self._checkpoint_error; self._stop_request=None

    def control(self, action, participant_id='', text=''):
        with self._lock:
            if action == 'set_sender':
                state = self.snapshot()
                if not any(p['id'] == participant_id for p in state['text_senders']):
                    raise ValueError('Choose your connected Discord participant or NC operator as sender.')
                data = copy.deepcopy(self._data)
                data['text_sender_id'] = participant_id
                self._store.save(data)
                self._data = data
                return self.snapshot()
            if self._phase!='running' or not self._owned: raise RuntimeError('Start the Discord room first.')
            state = self.snapshot()
            human=any(p['id']==participant_id and p['role']=='human' for p in state['participants'])
            if action == 'resume':
                problem = (self._history_error or self._checkpoint_error or self._connection_problem(self._rows())
                           or self._continuation_problem(state['moderator'], state['participants']))
                if problem:
                    self._error = problem
                    raise RuntimeError(problem)
                self._error = ''
            if action in {'next','invite','only','mute','unmute'} and not any(
                    p['id'] == participant_id and p.get('connected') for p in state['participants']):
                raise ValueError('Choose an available connected participant in this Discord room.')
            if action == 'invite' and human:
                raise ValueError('Use Speak next for a Discord participant, then speak through Discord.')
            current_bot = state['current_id'] if state['current_id'] in self._owned else None
            if action == 'stop_speech':
                # Both commands share one inbox so the hold is installed before cancellation.
                self._command('room_pause_after_turn', dict(request_id=uuid.uuid4().hex), target=current_bot)
            payload={'speaker_user_id':participant_id} if human else {'target_bot_id':participant_id}
            commands=dict(pause='room_pause_after_turn',resume='room_resume',stop_speech='stop_playback',
                clear_next='moderator_clear_pending',clear_floor='moderator_clear_floor',
                next='moderator_route_next_human' if human else 'moderator_route_next',
                only='moderator_give_human_floor' if human else 'moderator_give_floor',
                mute='moderator_mute_human' if human else 'moderator_mute',
                unmute='moderator_unmute_human' if human else 'moderator_unmute',invite='moderator_call_on')
            if action in {'guide','announce'}:
                if not str(text).strip(): raise ValueError('Enter guidance or text to say first.')
                self._command('room_directive',dict(id=uuid.uuid4().hex,kind='guide' if action=='guide' else 'say',text=str(text).strip()))
            elif action in commands:
                if action=='pause': payload=dict(request_id=uuid.uuid4().hex)
                self._command(commands[action],payload,target=(participant_id if action=='invite' and not human
                    else current_bot if action=='stop_speech' else None))
            else: raise ValueError('This action is unavailable while a Discord room is active.')
            return self.snapshot()

    def send(self, text, sender_id=None):
        if not str(text).strip(): raise ValueError('Enter a room message first.')
        with self._lock:
            if self._phase!='running': raise RuntimeError('Start the Discord room first.')
            state = self.snapshot()
            if state['paused'] or state.get('stopping'):
                raise RuntimeError('Resume the Discord room before sending a message.')
            identity = state['text_sender_id'] if sender_id is None else str(sender_id)
            sender = next((p for p in state['text_senders'] if p['id'] == identity), None)
            if sender is None:
                raise ValueError('Choose your connected Discord participant or NC operator as sender.')
            # Also remember an explicit submission that preceded its selection update.
            if not self._data.get('text_sender_id'):
                data = copy.deepcopy(self._data)
                data['text_sender_id'] = identity
                self._store.save(data)
                self._data = data
            self._command('room_directive',dict(id=uuid.uuid4().hex,kind='input',text=str(text).strip(),
                sender_user_id=identity, sender_name=sender['name']))
            return self.snapshot()

    def set_topic(self, topic):
        with self._lock:
            self._ensure_store(self._settings or self._load())
            self._data['topic']=str(topic).strip(); self._store.save(self._data)
            return self.snapshot()

    def set_anonymous(self, anonymous):
        if not isinstance(anonymous, bool):
            raise ValueError('Anonymous must be enabled or disabled.')
        with self._operation, self._lock:
            settings = self._settings or self._load()
            self._ensure_store(settings)
            previous = self._data['anonymous']
            def persist(value):
                data = copy.deepcopy(self._data)
                data['anonymous'] = value
                self._store.save(data)
                self._data = data
            apply_anonymous(self._addon, self._settings, self._owned, anonymous, previous, persist)
            return self.snapshot()

    def history(self, participant_id):
        state=self.snapshot()
        return dict(participant_id=participant_id,entries=[dict(role=m.get('role','assistant'),content=m['name']+': '+m['text']) for m in state['messages']],count=len(state['messages']),context_entries=0)

    def new_conversation(self):
        with self._lock:
            if self._owned: raise RuntimeError('Stop the Discord room before starting a new conversation.')
            settings=self._load(); section=copy.deepcopy(settings.get('room_session') or {})
            self._ensure_store(settings)
            anonymous = self._data['anonymous']
            section['room_id']=uuid.uuid4().hex
            store = DiscordRoomStore(self._root, **{**self._store.identity, 'room_id': section['room_id']})
            data = dict(anonymous=anonymous)
            # Persist the fresh conversation before selecting it in user settings.
            store.save(data)
            self._save({'room_session':section})
            self._store, self._data, self._store_loaded = store, data, True
            self._settings = None
            self._error = self._history_error = self._checkpoint_error = ''
            self._continuing = False
            return self.snapshot()

    def set_muted(self, muted):
        raise RuntimeError('Use Discord to control your microphone.')

    def join(self):
        raise RuntimeError('Join the voice channel using Discord.')

    leave=join
