"""Pure persisted participant identities and admission/account reservations.

Callers serialize read/transition/save under their operation lock. A failed
admission still owns its account until cleanup explicitly settles it as left.
"""
import copy
import re
import uuid


_PHASES = {'joining', 'ready', 'leaving', 'left', 'failed'}
_ROLES = {'moderator', 'participant'}
_BINDING_FIELDS = ('participant_id', 'persona_id', 'bot_id', 'role')


def _identity(value, name, *, account=False):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f'Invalid room {name} identity.')
    if account and not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,95}', value):
        raise ValueError('Invalid prepared account identifier.')
    return value


def _binding_identities(bindings):
    if not isinstance(bindings, list):
        raise ValueError('The saved room participant mapping is invalid.')
    result, participants, personas, accounts = [], set(), set(), set()
    for member in bindings:
        if not isinstance(member, dict):
            raise ValueError('The saved room participant mapping is invalid.')
        participant = _identity(member.get('participant_id'), 'participant')
        persona = _identity(member.get('persona_id'), 'persona')
        account = _identity(member.get('bot_id'), 'account', account=True)
        if not isinstance(member.get('role'), str) or member['role'] not in _ROLES:
            raise ValueError('Invalid room participant role.')
        if participant in participants or persona in personas or account in accounts:
            raise ValueError('Room participant, persona and account identities must be unique.')
        participants.add(participant); personas.add(persona); accounts.add(account)
        result.append(tuple(member[key] for key in _BINDING_FIELDS))
    return sorted(result)


def validate_roster(roster):
    """Reject corrupt persisted identities without repairing or dropping them."""
    if (not isinstance(roster, dict) or type(roster.get('version')) is not int
            or roster['version'] != 1 or type(roster.get('revision')) is not int
            or roster['revision'] < 0 or not isinstance(roster.get('members'), list)):
        raise ValueError('The saved room roster version or format is invalid.')
    participants, personas, accounts, admissions = set(), set(), set(), set()
    histories, present_personas, replacements = set(), set(), set()
    destination_accounts, self_moves = set(), set()
    for member in roster['members']:
        if not isinstance(member, dict):
            raise ValueError('The saved room participant identity is invalid.')
        participant = _identity(member.get('participant_id'), 'participant')
        persona = _identity(member.get('persona_id'), 'persona')
        account = _identity(member.get('bot_id'), 'account', account=True)
        admission = _identity(member.get('admission_id'), 'admission')
        if participant in participants or persona in personas:
            raise ValueError('Room participant and persona identities must be unique.')
        participants.add(participant); personas.add(persona)
        phase = member.get('phase')
        if (not isinstance(phase, str) or phase not in _PHASES
                or not isinstance(member.get('role'), str) or member['role'] not in _ROLES):
            raise ValueError('Invalid room membership phase or role.')
        if phase != 'left':
            if account in accounts:
                raise ValueError('A prepared account is reserved by more than one participant.')
            accounts.add(account)
            present_personas.add(persona)
        history = member.get('history_key')
        if (not isinstance(history, str) or (not history and member.get('legacy_history') is not True)
                or ('legacy_history' in member and not isinstance(member['legacy_history'], bool))):
            raise ValueError('Invalid room participant history identity.')
        if history:
            if history in histories:
                raise ValueError('Different personas cannot share a room history identity.')
            histories.add(history)
        for field in ('drain_turn_id', 'replacement_persona_id', 'error'):
            if not isinstance(member.get(field), str):
                raise ValueError('Invalid room admission transition data.')
        replacement = member['replacement_persona_id']
        destination = member.get('replacement_bot_id', '')
        if not isinstance(destination, str):
            raise ValueError('Invalid replacement account identity.')
        if destination:
            _identity(destination, 'replacement account', account=True)
            if not replacement or (phase != 'left' and phase not in {'leaving', 'failed'}):
                raise ValueError('A replacement account requires a recorded departure.')
            if member['role'] == 'moderator' and destination != account:
                raise ValueError('The moderator must retain its account.')
            if phase != 'left' and destination != account:
                if destination in destination_accounts:
                    raise ValueError('A replacement account is already reserved.')
                destination_accounts.add(destination)
                if replacement == persona:
                    self_moves.add(persona)
        if replacement and phase != 'left':
            _identity(replacement, 'replacement persona')
            if replacement in replacements:
                raise ValueError('A replacement persona is already reserved.')
            replacements.add(replacement)
        records = member.get('admissions')
        if not isinstance(records, list) or not records:
            raise ValueError('Missing room admission records.')
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError('Invalid room admission record.')
            record_id = _identity(record.get('admission_id'), 'admission')
            _identity(record.get('bot_id'), 'account', account=True)
            if (record_id in admissions or not isinstance(record.get('phase'), str)
                    or record['phase'] not in _PHASES
                    or (index < len(records) - 1 and record['phase'] != 'left')):
                raise ValueError('Invalid or duplicate room admission identity.')
            admissions.add(record_id)
        current = records[-1]
        if current['admission_id'] != admission or current['bot_id'] != account or current['phase'] != phase:
            raise ValueError('The current room admission identity does not match its record.')
    if destination_accounts & accounts:
        raise ValueError('A replacement account is already assigned or reserved.')
    if (replacements & present_personas) - self_moves:
        raise ValueError('A replacement persona is already admitted.')


def _record(member):
    return dict(admission_id=member['admission_id'], bot_id=member['bot_id'], phase=member['phase'])


def seed_roster(data: dict, bindings: list[dict]) -> dict:
    """Return a roster, preserving supplied legacy history keys verbatim.

An empty legacy key plus legacy_history marks a path the scoped compiler must
resolve. This helper has no room/settings scope and must not guess that path.
"""
    if not isinstance(data, dict):
        raise ValueError('A room checkpoint must be an object.')
    identities = _binding_identities(bindings)
    if 'roster' in data:
        validate_roster(data['roster'])
        roster = copy.deepcopy(data['roster'])
        current = [m for m in roster['members'] if m['phase'] != 'left']
        if _binding_identities(current) != identities:
            raise ValueError('The room mapping differs from its recorded membership identities.')
        return roster
    if 'bindings' in data and _binding_identities(data['bindings']) != identities:
        raise ValueError('The saved room participant mapping has changed without a recorded transition.')
    members = []
    saved = {b['participant_id']: b for b in data.get('bindings', [])}
    for binding in bindings:
        member = {key: binding[key] for key in _BINDING_FIELDS}
        legacy = saved.get(binding['participant_id'], {})
        history = legacy.get('history_key', binding.get('history_key', ''))
        member.update(history_key=history, legacy_history=True, phase='ready',
                      admission_id='admission_' + uuid.uuid4().hex,
                      drain_turn_id='', replacement_persona_id='', error='')
        member['admissions'] = [_record(member)]
        members.append(member)
    roster = dict(version=1, revision=0, members=members)
    validate_roster(roster)
    return roster


def begin_admission(roster: dict, persona_id: str, bot_id: str, *, role: str = 'participant') -> tuple[dict, dict]:
    validate_roster(roster)
    _identity(persona_id, 'persona'); _identity(bot_id, 'account', account=True)
    if not isinstance(role, str) or role not in _ROLES:
        raise ValueError('Invalid room participant role.')
    result = copy.deepcopy(roster)
    previous = next((m for m in result['members'] if m['persona_id'] == persona_id), None)
    if previous is not None and previous['phase'] != 'left':
        raise ValueError('This persona is already admitted or awaiting cleanup.')
    if any(m['replacement_persona_id'] == persona_id and m['phase'] != 'left' for m in result['members']):
        raise ValueError('This persona is reserved for a pending replacement.')
    if any(bot_id in {m['bot_id'], m.get('replacement_bot_id', '')} and m['phase'] != 'left' for m in result['members']):
        raise ValueError('This account is already assigned or reserved pending cleanup.')
    if role == 'moderator' and any(m['role'] == 'moderator' and m['phase'] != 'left' for m in result['members']):
        raise ValueError('The room already has a moderator.')
    member = previous
    if member is None:
        participant = 'member_' + uuid.uuid4().hex
        member = dict(participant_id=participant, persona_id=persona_id,
                      history_key=participant, admissions=[])
        result['members'].append(member)
    member.update(bot_id=bot_id, role=role, phase='joining', admission_id='admission_' + uuid.uuid4().hex,
                  drain_turn_id='', replacement_persona_id='', replacement_bot_id='', error='')
    member['admissions'].append(_record(member))
    result['revision'] += 1
    validate_roster(result)
    return result, copy.deepcopy(member)


def _member(roster, participant_id):
    _identity(participant_id, 'participant')
    for member in roster['members']:
        if member['participant_id'] == participant_id:
            return member
    raise ValueError('The room participant identity is unavailable.')


def request_departure(roster: dict, participant_id: str, *, replacement_persona_id: str = '',
                      replacement_bot_id: str = '') -> dict:
    validate_roster(roster)
    result = copy.deepcopy(roster)
    member = _member(result, participant_id)
    if replacement_bot_id:
        _identity(replacement_bot_id, 'replacement account', account=True)
        if not replacement_persona_id:
            raise ValueError('A replacement account requires a replacement persona.')
        if member['role'] == 'moderator' and replacement_bot_id != member['bot_id']:
            raise ValueError('The moderator must retain its account.')
        if any(m['phase'] != 'left' and m is not member and replacement_bot_id in
               {m['bot_id'], m.get('replacement_bot_id', '')} for m in result['members']):
            raise ValueError('This replacement account is already assigned or reserved.')
    if replacement_persona_id:
        _identity(replacement_persona_id, 'replacement persona')
        if (replacement_persona_id == member['persona_id'] and
                (not replacement_bot_id or replacement_bot_id == member['bot_id'])) or any(
                m is not member and m['phase'] != 'left' and (m['persona_id'] == replacement_persona_id
                or m['replacement_persona_id'] == replacement_persona_id)
                for m in result['members']):
            raise ValueError('The replacement persona is already admitted.')
    if member['role'] == 'moderator' and not replacement_persona_id:
        raise ValueError('The moderator requires a replacement persona.')
    if member['phase'] == 'left':
        raise ValueError('This participant has already left.')
    if member['phase'] == 'leaving':
        if (member['replacement_persona_id'] != replacement_persona_id
                or member.get('replacement_bot_id', '') != replacement_bot_id):
            raise ValueError('A different departure is already recorded.')
        return result
    member.update(phase='leaving', replacement_persona_id=replacement_persona_id,
                  replacement_bot_id=replacement_bot_id)
    member['admissions'][-1] = _record(member)
    result['revision'] += 1
    validate_roster(result)
    return result


def settle_admission(roster: dict, participant_id: str, admission_id: str, phase: str, *, error: str = '') -> dict:
    validate_roster(roster)
    result = copy.deepcopy(roster)
    member = _member(result, participant_id)
    if admission_id != member['admission_id']:
        raise ValueError('A stale admission cannot settle this participant.')
    transitions = dict(joining={'ready', 'failed'}, ready={'failed'}, leaving={'left', 'failed'},
                       failed={'left'}, left=set())
    if (not isinstance(phase, str) or phase not in _PHASES
            or (phase != member['phase'] and phase not in transitions[member['phase']])):
        raise ValueError('Invalid room admission phase transition.')
    if not isinstance(error, str):
        raise ValueError('Invalid room admission error.')
    if member['phase'] == phase and member['error'] == error:
        return result
    member.update(phase=phase, error=error)
    member['admissions'][-1] = _record(member)
    result['revision'] += 1
    return result


def account_options(settings: dict, roster: dict) -> list[dict]:
    """Project prepared accounts in order; the first available is the auto offer.

Explicit selection remains a controller choice. No credentials, environment
variables, instance objects or other settings enter these option records.
"""
    validate_roster(roster)
    reserved = {m['bot_id']: m for m in roster['members'] if m['phase'] != 'left'}
    reserved.update({m['replacement_bot_id']: m for m in roster['members']
                     if m['phase'] != 'left' and m.get('replacement_bot_id')})
    options, seen = [], set()
    for bot in settings.get('bots', []):
        if not isinstance(bot, dict):
            raise ValueError('Invalid prepared account settings.')
        bot_id = _identity(bot.get('id'), 'account', account=True)
        if bot_id in seen:
            raise ValueError('Prepared account identities must be unique.')
        seen.add(bot_id)
        reason = ''
        if not bot.get('enabled', True):
            reason = 'This prepared account is disabled.'
        elif bot.get('local_room_role'):
            reason = 'This account belongs to the Local room.'
        elif bot_id in reserved:
            member = reserved[bot_id]
            reason = f"Reserved for {member['persona_id']} ({member['phase']})."
        options.append(dict(bot_id=bot_id, label=str(bot.get('account_label') or f'Bot {len(options) + 1}'),
                            available=not reason, unavailable_reason=reason))
    return options
