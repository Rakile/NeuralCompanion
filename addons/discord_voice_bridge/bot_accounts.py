"""Reusable Discord credentials stored in the existing addon-local bot records."""
import copy
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .settings import load_settings, redacted_settings, save_local_settings


_ACCOUNT_LOCK = threading.RLock()
_RUNNING_REASON = 'Stop this running Discord account before editing or removing it.'
_BOUND_REASON = 'Unassign this account from the saved Discord room before removing it.'
_LOCAL_CAST_REASON = 'This account is used by the Local room cast; preserve its participant before removing it.'
_METADATA_KEY = 'discord_account_identity'


def safe_avatar_url(value):
    """Accept only public Discord avatar CDN URLs, never arbitrary local/remote files."""
    text = str(value or '').strip()
    try:
        url = urlsplit(text)
        if (url.scheme == 'https' and url.hostname in {'cdn.discordapp.com', 'media.discordapp.net'}
                and not url.username and not url.password and url.port in (None, 443)
                and re.fullmatch(r'/(?:avatars/\d+/[A-Za-z0-9_]+|guilds/\d+/users/\d+/avatars/[A-Za-z0-9_]+|embed/avatars/\d+)\.(?:png|webp|jpg|gif)', url.path)):
            return text
    except ValueError:
        pass
    return ''


def _credential_key(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest() if _real_token(token) else ''


def _verified_identity(bot, settings):
    metadata = bot.get(_METADATA_KEY)
    if (isinstance(metadata, dict) and metadata.get('secret')
            and metadata['secret'] == _credential_key(_effective_token(bot, settings))):
        return metadata
    return {}


class _NoDiscordRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # Authorization must never follow a redirect to a different endpoint.
        raise urllib.error.HTTPError(request.full_url, code, 'Unexpected Discord redirect', headers, response)


def _fetch_discord_identity(token):
    """Read bot identity only; no login, gateway connection, or profile mutation."""
    unavailable = dict(state='unavailable', message='Discord could not be reached. Try checking again.')
    if not _real_token(token):
        return dict(state='invalid', message='No bot token is configured.')
    try:
        request = urllib.request.Request('https://discord.com/api/v10/users/@me', headers={
            'Authorization': 'Bot ' + token, 'User-Agent': 'NeuralCompanion Discord account check',
            'Accept': 'application/json'})
        with urllib.request.build_opener(_NoDiscordRedirect()).open(request, timeout=5) as response:
            payload = json.loads(response.read(65537))
        if not isinstance(payload, dict):
            return unavailable
        identity = str(payload.get('id') or '')
        name = str(payload.get('global_name') or payload.get('username') or '').strip()[:100]
        if payload.get('bot') is not True:
            return dict(state='invalid', message='This token does not belong to a Discord bot.')
        if not re.fullmatch(r'\d{1,30}', identity) or not name:
            return unavailable
        avatar = str(payload.get('avatar') or '')
        avatar_url = (f'https://cdn.discordapp.com/avatars/{identity}/{avatar}.png?size=128'
                      if re.fullmatch(r'[A-Za-z0-9_]{1,128}', avatar)
                      else f'https://cdn.discordapp.com/embed/avatars/{(int(identity) >> 22) % 6}.png')
        return dict(state='valid', message='Bot token verified.', discord_id=identity,
                    discord_name=name, avatar_url=avatar_url)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return dict(state='invalid', message='Invalid bot token. Replace it and save again.')
        if error.code == 429:
            return dict(state='unavailable', message='Discord is rate limiting account checks. Try again later.')
        return unavailable
    except (OSError, ValueError, TypeError):
        return unavailable


def check_discord_accounts(account_ids=None):
    """Check a token snapshot outside locks, then discard results for replaced tokens."""
    selected = set(account_ids) if account_ids is not None else None
    with _ACCOUNT_LOCK:
        settings = load_settings()
        pending = [(str(bot['id']), _effective_token(bot, settings)) for bot in settings.get('bots', [])
                   if isinstance(bot, dict) and bot.get('id') and _is_account(bot)
                   and (selected is None or str(bot['id']) in selected)]
    results, discarded = [], 0
    for identity, token in pending:
        result = _fetch_discord_identity(token)
        with _ACCOUNT_LOCK:
            settings = load_settings()
            bots = copy.deepcopy(list(settings.get('bots') or []))
            matches = [bot for bot in bots if isinstance(bot, dict) and str(bot.get('id') or '') == identity]
            if len(matches) != 1 or _effective_token(matches[0], settings) != token:
                discarded += 1
                continue
            bot = matches[0]
            previous = _verified_identity(bot, settings)
            metadata = {key: previous[key] for key in ('discord_id', 'discord_name', 'avatar_url')
                        if key in previous} if result['state'] == 'unavailable' else {}
            metadata.update({key: result[key] for key in ('state', 'message', 'discord_id', 'discord_name', 'avatar_url') if key in result})
            # Existing secret redaction protects this correlation value in every settings projection.
            metadata.update(secret=_credential_key(token), checked_at=datetime.now(timezone.utc).isoformat())
            bot[_METADATA_KEY] = metadata
            save_local_settings({'bots': bots}, allow_secret_updates=True)
            results.append(dict(account_id=identity, state=result['state'], message=result['message']))
    return dict(ok=True, checked=len(results), discarded=discarded, results=results)


def _connection(bot):
    value = bot.get('discord')
    return value if isinstance(value, dict) else {}


def _token(value):
    return str(value or '').strip()


def _real_token(value):
    value = _token(value)
    return bool(value and value.casefold() != '<redacted>')


def _effective_token(bot, settings):
    connection, inherited = _connection(bot), settings.get('discord') or {}
    # Match launch precedence; environment values are compared only in memory.
    inline = _token(connection.get('token')) or _token(inherited.get('token'))
    if inline:
        return inline
    variable = _token(connection.get('token_env_var')) or _token(inherited.get('token_env_var')) or 'DISCORD_TOKEN'
    return _token(os.environ.get(variable))


def _is_account(bot):
    connection = _connection(bot)
    if bot.get('discord_account') is True or 'account_label' in bot or _real_token(connection.get('token')):
        return True
    return bool(not bot.get('local_room_role') and _token(connection.get('token_env_var')))


def _bindings(settings):
    saved = (settings.get('room_session') or {}).get('bindings')
    if isinstance(saved, list):
        return [item for item in saved if isinstance(item, dict)]
    # Match the existing Discord room's inferred bindings without changing them.
    return [dict(bot_id=bot.get('id'), persona_id=bot['local_room_persona_id'])
            for bot in settings.get('bots', []) if isinstance(bot, dict)
            and not bot.get('local_room_role') and bot.get('local_room_persona_id')]


def _local_cast_ids(settings, room):
    identities = {str(bot.get('id') or '') for bot in settings.get('bots', [])
                  if isinstance(bot, dict) and bot.get('local_room_role')}
    entries = (settings.get('local_room') or {}).get('cast') or []
    if room.get('mode') == 'local':
        entries = list(entries) + list(room.get('participants') or [])
    for entry in entries:
        if isinstance(entry, dict):
            for key in ('source_bot_id', 'id'):
                if entry.get(key):
                    identities.add(str(entry[key]))
    return identities


def _running_ids(instances):
    running = set()
    for instance in instances or []:
        if isinstance(instance, dict):
            identity = str(instance.get('id') or '')
            active = bool(instance.get('runtime_connected') or instance.get('endpoint_running'))
        else:
            identity = str(getattr(instance, 'instance_id', '') or '')
            process = getattr(instance, 'process', None)
            server = getattr(instance, 'runtime_server', None)
            active = bool((process is not None and process.poll() is None)
                          or (server is not None and server.running))
        if active:
            running.add(identity)
    return running


def account_rows(settings, room_snapshot=None, instances=None):
    """Project only safe account metadata; never copy credentials or environment names."""
    room = room_snapshot or {}
    bindings = _bindings(settings)
    current = [item for item in room.get('bindings', []) if isinstance(item, dict)]
    active = _running_ids(instances)
    local_cast = _local_cast_ids(settings, room)
    live_status = {str(item.get('id') or ''): item.get('node_status') or {}
                   for item in instances or [] if isinstance(item, dict) and item.get('runtime_connected')}
    connected = {str(item.get('id') or '') for item in instances or [] if isinstance(item, dict)
                 and item.get('runtime_connected') and (item.get('node_status') or {}).get('voice_connected')}
    if room.get('mode') == 'discord' and room.get('phase', 'idle') not in {'idle', 'error'}:
        active.update(str(item.get('bot_id') or '') for item in current)
    assignments = {str(item.get('bot_id') or ''): str(item.get('persona_id') or '')
                   for item in bindings + current if item.get('bot_id')}
    rows = []
    for bot in settings.get('bots', []):
        if not isinstance(bot, dict) or not bot.get('id') or not _is_account(bot):
            continue
        identity = str(bot['id'])
        connection = _connection(bot)
        running, assigned = identity in active, identity in assignments
        configured = bool(_real_token(connection.get('token')) or _token(connection.get('token_env_var')))
        local_member = identity in local_cast
        reason = _RUNNING_REASON if running else (_BOUND_REASON if assigned else
            (_LOCAL_CAST_REASON if local_member else ''))
        status = 'Connected' if identity in connected else ('Connecting' if running else
            ('Assigned · not connected' if assigned else ('Not connected' if configured else 'Token required')))
        metadata = _verified_identity(bot, settings)
        node = live_status.get(identity, {})
        rows.append(dict(id=identity, label=_token(bot.get('account_label')) or f'Bot {len(rows) + 1}',
            token_configured=configured, assigned_persona=assignments.get(identity, ''),
            avatar_url=safe_avatar_url(node.get('bot_avatar_url')) or safe_avatar_url(metadata.get('avatar_url')),
            discord_name=str(metadata.get('discord_name') or node.get('bot_tag') or ''),
            bot_nickname=str(node.get('bot_nickname') or ''),
            nickname_error=str(node.get('nickname_error') or ''),
            verification_state=str(metadata.get('state') or 'unchecked'),
            verification_message=str(metadata.get('message') or 'Not checked yet.'),
            status=status,
            can_edit=not running, can_remove=not running and not assigned and not local_member, blocked_reason=reason))
    return rows


def _runtime_port(section):
    try:
        if section.get('port') not in (None, ''):
            return int(section['port'])
        endpoint = section.get('http_endpoint') or section.get('endpoint')
        return urlsplit(str(endpoint)).port if endpoint else None
    except (TypeError, ValueError):
        return None


def _available_port(settings):
    occupied = {8768}
    global_port = _runtime_port(settings.get('nc_runtime') or {})
    if global_port:
        occupied.add(global_port)
    nonlocal_index = 0
    for index, bot in enumerate(settings.get('bots', [])):
        if not isinstance(bot, dict):
            continue
        section = bot.get('nc_runtime') or {}
        explicit = any(key in section for key in ('port', 'http_endpoint', 'endpoint'))
        if explicit:
            occupied.add(_runtime_port(section) or global_port or 8768)
        else:
            # Reserve both full local-cast and filtered standalone normalization.
            occupied.add(8768 + index)
            if not bot.get('local_room_role'):
                occupied.add(8768 + nonlocal_index)
        if not bot.get('local_room_role'):
            nonlocal_index += 1
    # Continue the configured range; users may have moved away from blocked low ports.
    highest = max(port for port in occupied if 1 <= port <= 65535)
    if highest < 65535:
        return highest + 1
    for port in range(8768, 65536):
        if port not in occupied:
            return port
    raise ValueError('No free Discord account runtime port is available.')


def perform_account_action(action, payload, room_snapshot=None, instances=None):
    """Validate and save account-only changes without connecting or stopping any runtime."""
    if action not in {'account_add', 'account_update', 'account_remove'}:
        raise ValueError('Unknown Discord account action.')
    with _ACCOUNT_LOCK:
        room_snapshot = room_snapshot() if callable(room_snapshot) else room_snapshot
        instances = instances() if callable(instances) else instances
        settings = load_settings()
        bots = copy.deepcopy(list(settings.get('bots') or []))
        identity = _token(payload.get('account_id'))
        token = _token(payload.get('token'))
        target = None
        if action != 'account_add':
            matches = [bot for bot in bots if isinstance(bot, dict) and str(bot.get('id') or '') == identity]
            if len(matches) != 1 or not _is_account(matches[0]):
                raise ValueError('Choose an available Discord account.')
            target = matches[0]
            row = next(row for row in account_rows(settings, room_snapshot, instances) if row['id'] == identity)
            if not row['can_edit'] or (action == 'account_remove' and not row['can_remove']):
                raise ValueError(row['blocked_reason'])
        if action == 'account_add' or token:
            if not _real_token(token):
                raise ValueError('A non-empty Discord bot token is required; redacted placeholders cannot be saved.')
            candidates = [_effective_token(bot, settings) for bot in bots
                          if isinstance(bot, dict) and bot is not target]
            candidates.append(_effective_token({}, settings))
            if any(_token(value) == token for value in candidates):
                raise ValueError('This Discord credential is already configured. Use its existing account.')
        if action == 'account_add':
            occupied = {str(bot.get('id') or '').casefold() for bot in bots if isinstance(bot, dict)}
            identity = 'discord_account_' + uuid.uuid4().hex
            while identity.casefold() in occupied:
                identity = 'discord_account_' + uuid.uuid4().hex
            labels = {row['label'].casefold() for row in account_rows(settings)}
            label_suffix = 1
            while f'bot {label_suffix}' in labels:
                label_suffix += 1
            label = _token(payload.get('label')) or f'Bot {label_suffix}'
            bots.append(dict(id=identity, name=label, discord_account=True, account_label=label,
                enabled=True, discord={'token': token}, nc_runtime={'port': _available_port(settings)}))
        elif action == 'account_update':
            if 'label' in payload:
                default = next(row['label'] for row in account_rows(settings) if row['id'] == identity)
                target['account_label'] = _token(payload.get('label')) or default
            if token:
                target.setdefault('discord', {})['token'] = token
        else:
            bots.remove(target)
        saved = save_local_settings({'bots': bots}, allow_secret_updates=True)
        return {'ok': True, 'account_id': identity, 'settings': redacted_settings(saved)}
