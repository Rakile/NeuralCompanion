"""Validate room bindings without changing prepared Discord bot credentials."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from .local_room_cast import persona_bot


ROOM_HISTORY_ROOT = Path(__file__).resolve().parent / 'runtime_instances'


def discord_room_has_model_history(settings, bindings, scope, *, roster=None):
    """Check the same scoped/legacy files used by the Discord runtime."""
    prepared = {str(bot.get('id')): bot for bot in settings.get('bots', [])}
    if roster is not None:
        from .room_membership import seed_roster
        members = {row['participant_id']: row for row in seed_roster({'roster': roster}, bindings)['members']}
    else:
        members = {}
    for binding in bindings:
        bot_id = str(binding.get('bot_id') or '')
        if not bot_id:
            continue
        source = prepared.get(bot_id) or {}
        persona_id = str(binding.get('persona_id') or '')
        member = members.get(binding.get('participant_id')) or binding
        storage_id = member.get('history_key') or discord_history_storage_id(bot_id, scope, persona_id,
            source.get('local_room_persona_id') == persona_id, scope.get('channel_id'))
        # Match runtime_server._safe_history_segment without permitting path traversal.
        segment = re.sub(r'[^a-zA-Z0-9_.-]+', '_', storage_id.strip()).strip('._-').lower() or 'default'
        path = ROOM_HISTORY_ROOT / (segment + '.history.json')
        if path.is_symlink():
            raise ValueError('Discord room history points to another file; operation stopped.')
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        history = data.get('history') if isinstance(data, dict) else data
        if not isinstance(history, list):
            raise ValueError('The saved Discord participant history is invalid. Its file was preserved.')
        if history:
            return True
    return False


def discord_history_storage_id(bot_id, scope, persona_id, reuse_legacy, channel_id):
    """The pre-roster storage identity, shared by migration and runtime."""
    if scope is not None and (scope.get('room_id') != 'default' or not reuse_legacy):
        identity = {**scope, 'persona_id': str(persona_id or '')}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        return f'{bot_id}__room_{digest}'
    channel = str(channel_id or '').strip()
    return str(bot_id) + ('__channel_' + channel if channel else '')


def validate_discord_room(settings, personas, bindings, *, allow_moderator_only=False, roster=None):
    if len(bindings) < 2 and not allow_moderator_only:
        raise ValueError('Choose a moderator and at least one other persona.')
    if sum(member.get('role') == 'moderator' for member in bindings) != 1:
        raise ValueError('Choose exactly one moderator.')
    people = {str(p.get('id')): p for p in personas}
    prepared = {str(b.get('id')): b for b in settings.get('bots', []) if isinstance(b, dict)}
    seen_members, seen_bots, seen_personas, bots, scope = set(), set(), set(), [], None
    configured = settings.get('room_session') or {}
    for binding in bindings:
        member_id = str(binding.get('participant_id') or '').strip()
        bot_id = str(binding.get('bot_id') or '').strip()
        persona_id = str(binding.get('persona_id') or '').strip()
        if not member_id or member_id in seen_members:
            raise ValueError('Room participant identities must be unique.')
        if bot_id and (not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,95}',bot_id)):
            raise ValueError('Prepared bot identifiers must be stable lowercase IDs without path separators.')
        if not bot_id or bot_id in seen_bots:
            raise ValueError('Choose a unique prepared bot for each participant; this bot is already assigned.')
        if binding.get('role') not in {'moderator', 'participant'}:
            raise ValueError('Choose a moderator or participant role.')
        if persona_id not in people:
            raise ValueError('A selected Persona is unavailable. Choose another saved persona.')
        if persona_id in seen_personas:
            raise ValueError('Choose each Persona only once in this room.')
        source = prepared.get(bot_id)
        if source is None or not source.get('enabled', True):
            raise ValueError('A prepared Discord bot is missing or disabled. Check Bot accounts in the Discord tab.')
        connection = source.get('discord') or {}
        guild = str(connection.get('guild_id') or (settings.get('discord') or {}).get('guild_id') or '').strip()
        channel = str(connection.get('voice_channel_id') or (settings.get('discord') or {}).get('voice_channel_id') or '').strip()
        if not re.fullmatch(r'[0-9]+', guild) or not re.fullmatch(r'[0-9]+', channel):
            raise ValueError('Set a valid server ID and voice channel ID in Discord setup.')
        if scope is not None and scope != (guild, channel):
            raise ValueError('All room bots must use the same Discord server and voice channel.')
        if configured.get('guild_id') and str(configured['guild_id']) != guild:
            raise ValueError('A prepared bot uses a different Discord server.')
        if configured.get('channel_id') and str(configured['channel_id']) != channel:
            raise ValueError('A prepared bot uses a different Discord voice channel.')
        scope = guild, channel
        global_connection = settings.get('discord') or {}
        token = connection.get('token') or global_connection.get('token')
        env_name = connection.get('token_env_var') or global_connection.get('token_env_var')
        if not token and not (env_name and os.environ.get(str(env_name), '').strip()):
            raise ValueError('A prepared bot needs its token configured under Bot accounts in the Discord tab.')
        bot = copy.deepcopy(source)
        persona = persona_bot(people[persona_id])
        for key in ('name', 'persona', 'persona_overrides', 'local_room_avatar_path', 'local_room_persona_id', 'response_filter'):
            bot[key] = copy.deepcopy(persona[key])
        bot['id'], bot['enabled'] = bot_id, True
        bot.pop('local_room_role', None)
        bot.setdefault('chat', {})['use_global_model'] = True
        bot['_room_reuse_legacy_history'] = source.get('local_room_persona_id') == persona_id
        bot['_room_participant_id'] = member_id
        bot['_room_role'] = binding['role']
        # Managed room recovery is shared; legacy account overrides belong to standalone bridges.
        bot.setdefault('room_router', {})['dead_air_recovery'] = copy.deepcopy(
            (settings.get('room_router') or {}).get('dead_air_recovery') or {})
        # One captor serves the whole room; legacy account filters must not
        # change which humans are heard when capture ownership moves.
        bot.setdefault('discord', {}).update(guild_id=guild, voice_channel_id=channel,
            allowed_user_id=global_connection.get('allowed_user_id', ''),
            answer_mode=global_connection.get('answer_mode', 'allowed_user_only'))
        bots.append(bot)
        seen_members.add(member_id); seen_bots.add(bot_id)
        seen_personas.add(persona_id)
    result = copy.deepcopy(settings)
    result.update(bridge_mode='http', bots=bots, _discord_room_session=True,
                  _room_identity=dict(guild_id=scope[0], channel_id=scope[1], room_id=str(configured.get('room_id') or 'default')))
    if roster is not None:
        from .room_membership import seed_roster
        # Validate the mapping before mutating unresolved legacy keys. Callers
        # persist this ledger before admitting/reassigning an account.
        resolved = seed_roster({'roster': roster}, bindings)
        identity = result['_room_identity']
        for member in resolved['members']:
            if not member['history_key'] and member.get('legacy_history'):
                source = prepared.get(member['bot_id']) or {}
                member['history_key'] = discord_history_storage_id(member['bot_id'], identity,
                    member['persona_id'], source.get('local_room_persona_id') == member['persona_id'],
                    identity['channel_id'])
        segments = [re.sub(r'[^a-zA-Z0-9_.-]+', '_', member['history_key'].strip()).strip('._-').lower()
                    or 'default' for member in resolved['members']]
        if len(segments) != len(set(segments)):
            raise ValueError('Different personas cannot share a room history storage file.')
        members = {member['participant_id']: member for member in resolved['members']}
        for bot in bots:
            member = members[bot['_room_participant_id']]
            bot.update(_room_history_key=member['history_key'], _room_admission_id=member['admission_id'],
                       _room_roster_revision=resolved['revision'])
        roster.clear()
        roster.update(resolved)
    result.setdefault('tiny_mvp', {})['capture_mic'] = False
    result['start_on_nc_launch'] = result['auto_start_bridge'] = False
    result.setdefault('playback', {})['coordinate_bot_replies'] = True
    result.setdefault('room_router', {}).update(enabled=True, reply_floor_mode='wait', human_to_bot_routing=True,
        bot_to_bot_routing=True, route_bot_replies_from_text=True)
    return result
