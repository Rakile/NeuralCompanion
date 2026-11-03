"""Room membership references; never modifies the source Persona or Discord bots."""
import copy
import hashlib
import re
from pathlib import Path

ROLES = ('enthusiast', 'skeptic', 'pragmatist', 'moderator', 'participant')


def persona_bot(record):
    identity = str(record.get('id') or '').strip()
    name = str(record.get('name') or '').strip()
    prompt = str(record.get('system_prompt') or '').strip()
    if not identity or not name or not prompt:
        raise ValueError('Choose a saved persona with a name and prompt.')
    voice = str(record.get('voice_path') or '').strip() if record.get('use_cloned_voice', True) else ''
    if voice and (not Path(voice).is_file() or Path(voice).suffix.lower() != '.wav'):
        raise ValueError('The persona voice reference is missing or is not a WAV file. Assign a usable voice in Persona first.')
    from core.persona_overrides import normalize_persona_overrides
    overrides = normalize_persona_overrides(record.get('overrides'))
    technical = str(record.get('emotional_instructions') or '').strip()
    return {
        'id': 'local_persona_' + hashlib.sha256(identity.encode()).hexdigest()[:16],
        'name': name, 'enabled': True, 'local_room_role': 'participant',
        'local_room_persona_id': identity,
        'local_room_avatar_path': str(record.get('avatar_path') or ''),
        'chat': {'use_global_model': True},
        'persona_overrides': overrides,
        'persona': {'system_prompt': '\n\n'.join(part for part in (prompt, technical) if part),
                    'replace_nc_system_prompt': True, 'voice_clone_wav': voice},
        'response_filter': {'enabled': False, 'bot_names': name},
    }


def room_cast(settings):
    section = settings.get('local_room') or {}
    entries = section.get('cast') if isinstance(section, dict) else None
    bots = [copy.deepcopy(bot) for bot in settings.get('bots', []) if isinstance(bot, dict)]
    if not isinstance(entries, list):
        return [bot for bot in bots if bot.get('local_room_role') in ROLES and bot.get('enabled', True)]
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('The saved Local room cast is invalid.')
        source = entry.get('source_bot_id')
        if source:
            bot = next((copy.deepcopy(item) for item in bots if item.get('id') == source), None)
            if bot is None:
                raise ValueError('A saved Local room participant is missing from Bots: ' + str(source))
            bot['local_room_role'] = entry.get('local_room_role', 'participant')
        elif entry.get('local_room_persona_id'):
            from .linked_personas import visible_member
            bot = visible_member(entry)
        else:
            bot = copy.deepcopy(entry)
        result.append(bot)
    validate_cast(result, allow_moderator_only=section.get('membership_version') == 1)
    return result


def validate_cast(bots, *, allow_moderator_only=False):
    ids = [str(bot.get('id') or '') for bot in bots]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', key) for key in ids):
        raise ValueError('Local room participant identities must be unique.')
    if any(bot.get('local_room_role') not in ROLES for bot in bots):
        raise ValueError('Choose a valid Local room participant role.')
    if sum(bot.get('local_room_role') == 'moderator' for bot in bots) != 1:
        raise ValueError('Keep exactly one moderator in the Local room.')
    if len(bots) < 2 and not allow_moderator_only:
        raise ValueError('Keep a moderator and at least one other persona in the Local room.')


def persisted_cast(bots):
    result = []
    for bot in bots:
        if bot.get('local_room_persona_id'):
            result.append({key: copy.deepcopy(bot[key]) for key in (
                'id', 'local_room_persona_id', 'local_room_role') if key in bot})
        else:
            result.append(dict(id=bot['id'], source_bot_id=bot['id'],
                               local_room_role=bot['local_room_role']))
    return result
