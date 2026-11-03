"""Read linked Persona identities without importing the Qt UI or copying assets."""
import copy
import json
import hashlib
import re
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]


def member_reference(identity):
    identity = str(identity or '').strip()
    if not identity:
        raise ValueError('Choose a saved Persona.')
    return dict(id='local_persona_' + hashlib.sha256(identity.encode()).hexdigest()[:16],
                local_room_persona_id=identity, local_room_role='participant')


@lru_cache(maxsize=4)
def _read_records(path, modified, size):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    records = payload.get('personas', {})
    if not isinstance(records, dict):
        raise ValueError('The Persona library is invalid.')
    return {str(record.get('id')): record for record in records.values()
            if isinstance(record, dict) and record.get('id')}


def records():
    path = APP_ROOT / 'runtime/quick_personas.json'
    try:
        stat = path.stat()
        return _read_records(str(path), stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        return {}


def resolve_member(member):
    identity = str(member.get('local_room_persona_id') or '')
    if not identity:
        return copy.deepcopy(member)
    record = copy.deepcopy(records().get(identity))
    if record is None:
        raise ValueError(f'Persona {identity!r} is unavailable. Remove it from Local room or restore it in Persona.')
    for key in ('voice_path', 'avatar_path'):
        value = str(record.get(key) or '').strip()
        if value and not Path(value).is_absolute():
            record[key] = str(APP_ROOT / value)
    from .local_room_cast import persona_bot
    result = persona_bot(record)
    result['id'] = member.get('id') or result['id']
    result['local_room_role'] = member.get('local_room_role', 'participant')
    result['enabled'] = member.get('enabled', True)
    if isinstance(member.get('chat'), dict):
        result['chat'] = copy.deepcopy(member['chat'])
    if isinstance(member.get('nc_runtime'), dict):
        result['nc_runtime'] = copy.deepcopy(member['nc_runtime'])
    for key in ('_local_room_admission_id', '_local_room_conversation_id'):
        if key in member:
            result[key] = member[key]
    result['persona']['use_cloned_voice'] = bool(record.get('use_cloned_voice', True))
    return result


def visible_member(member):
    """A deleted or invalid Persona remains removable instead of hiding the room."""
    try:
        return resolve_member(member)
    except (ValueError, OSError) as error:
        if not member.get('local_room_persona_id'):
            raise
        return {key: copy.deepcopy(member[key]) for key in
                ('id', 'local_room_persona_id', 'local_room_role', 'enabled', 'nc_runtime',
                 '_local_room_admission_id', '_local_room_conversation_id') if key in member} | {
                    'name': 'Persona unavailable', 'local_room_error': str(error)}


def instance_settings(settings):
    """Generated worker settings keep links rather than another Persona snapshot."""
    result = copy.deepcopy(settings)
    result.pop('persona_overrides', None)
    if not result.get('_local_room_session'):
        return result
    from .local_room_cast import persisted_cast
    if isinstance(result.get('local_room'), dict) and isinstance(result['local_room'].get('cast'), list):
        result['local_room']['cast'] = persisted_cast(result['local_room']['cast'])
        linked_ids = {item.get('id') for item in result['local_room']['cast'] if item.get('local_room_persona_id')}
        for candidate in (result.get('room_router') or {}).get('candidate_bots', []):
            if candidate.get('id') in linked_ids:
                candidate.pop('persona_hint', None)
    if result.get('local_room_persona_id'):
        for key in ('persona', 'local_room_avatar_path', 'name'):
            result.pop(key, None)
        if isinstance(result.get('response_filter'), dict):
            result['response_filter'].pop('bot_names', None)
    return result


def cleanup_legacy_assets():
    """Remove only known unused copies while preserving their original files."""
    root = APP_ROOT / 'runtime/local_room_personas'
    if not root.is_dir() or root.is_symlink():
        return []
    originals = set()
    referenced = set()

    def inspect(value):
        if isinstance(value, dict):
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
        elif isinstance(value, str) and 'local_room_personas' in value.replace('\\', '/').lower().split('/'):
            path = Path(value)
            path = path if path.is_absolute() else APP_ROOT / path
            if path.resolve().is_relative_to(root.resolve()):
                referenced.add(str(path.resolve()).lower())

    try:
        for record in records().values():
            for key in ('voice_path', 'avatar_path'):
                value = str(record.get(key) or '')
                if not value:
                    continue
                path = Path(value)
                path = path if path.is_absolute() else APP_ROOT / path
                if path.is_file() and not path.resolve().is_relative_to(root.resolve()):
                    originals.add(hashlib.sha256(path.read_bytes()).hexdigest())
        addon = APP_ROOT/'addons/discord_voice_bridge'
        configs = [APP_ROOT/'runtime/quick_personas.json', addon/'settings.local.json',
                   *list((addon/'runtime_instances').glob('*.settings.json'))]
        for path in configs:
            if path.exists():
                inspect(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return []  # A failed reference audit cannot authorize deletion.
    removed = []
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'local_persona_[a-f0-9]{16}', folder.name):
            continue
        for path in folder.iterdir():
            if (path.is_symlink() or not path.is_file() or not re.fullmatch(r'[a-f0-9]{64}', path.stem)
                    or not path.resolve().is_relative_to(root.resolve())
                    or str(path.resolve()).lower() in referenced or path.stem not in originals):
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() == path.stem:
                path.unlink()
                removed.append(str(path))
        try:
            folder.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
    return removed
