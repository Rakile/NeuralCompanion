"""Local-room-only conversation metadata and heard-history storage."""
import copy
from functools import lru_cache
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import uuid

INSTANCE_ROOT = Path(__file__).resolve().parent / 'runtime_instances'
LOCK = threading.RLock()


def _directory():
    directory = INSTANCE_ROOT/'local_room'
    if directory.is_symlink() or directory.resolve() != INSTANCE_ROOT.resolve()/'local_room':
        raise ValueError('Local room storage points to another directory; operation stopped.')
    return directory


def _identity(value):
    value = str(value or '').strip().lower()
    if not re.fullmatch(r'[a-z0-9_-]+', value):
        raise ValueError('Invalid Local room participant identity.')
    return value


def history_path(identity):
    path = _directory() / (_identity(identity) + '.history.json')
    if path.is_symlink():
        raise ValueError('Local room history points to another file; operation stopped.')
    return path


def load():
    path = _directory()/'conversation.json'
    if path.is_symlink():
        raise ValueError('Local room metadata points to another file; operation stopped.')
    if not path.exists():
        return dict(version=1, id='', topic='', messages=[], members={}, anonymous=False)
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or not isinstance(data.get('id'), str)
            or not isinstance(data.get('topic'), str) or not isinstance(data.get('members'), dict)
            or not isinstance(data.get('messages'), list)):
        raise ValueError('Local room conversation data is invalid. It has not been overwritten.')
    if not isinstance(data.get('anonymous', False), bool):
        raise ValueError('The saved Local room Anonymous setting is invalid. It has not been overwritten.')
    data.setdefault('anonymous', False)
    if any(not isinstance(entry, dict) or not str(entry.get('id', '')).isdigit()
           or not isinstance(entry.get('name'), str) or not isinstance(entry.get('text'), str)
           for entry in data['messages']):
        raise ValueError('The saved Local room transcript is invalid. It has not been overwritten.')
    return data


def _write(path, data):
    if path.parent == INSTANCE_ROOT/'local_room':
        _directory()
        if path.is_symlink():
            raise ValueError('Local room data points to another file; operation stopped.')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def update(**changes):
    with LOCK:
        state = load()
        state.update(copy.deepcopy(changes))
        state['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        _write(INSTANCE_ROOT/'local_room/conversation.json', state)
        return state


def prepare(bots):
    with LOCK:
        state = load()
        if not state['id']:
            state['id'] = uuid.uuid4().hex
            # Older Local room instances used the bridge history directory.
            # Migrate only histories positively identified by their own settings.
            for settings_path in INSTANCE_ROOT.glob('*.settings.json'):
                if settings_path.is_symlink():
                    continue
                try:
                    settings = json.loads(settings_path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if not isinstance(settings, dict):
                    continue
                if not settings.get('_local_room_session'):
                    continue
                identity = _identity(settings.get('id') or settings_path.name.removesuffix('.settings.json'))
                state['members'][identity] = str(settings.get('name') or identity)
                channel = str((settings.get('discord') or {}).get('voice_channel_id') or '')
                storage_id = identity + ('__channel_' + channel if channel else '')
                if not re.fullmatch(r'[a-zA-Z0-9_.-]+', storage_id):
                    raise ValueError('Invalid legacy Local room history identity.')
                original = INSTANCE_ROOT/(storage_id + '.history.json')
                target = history_path(identity)
                if original.is_file() and not original.is_symlink() and not target.exists():
                    try:
                        content = json.loads(original.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        continue
                    if not isinstance(content, dict):
                        continue
                    if str(content.get('bot_id') or '').lower() == identity and isinstance(content.get('history'), list):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        assert original.resolve().is_relative_to(INSTANCE_ROOT.resolve())
                        assert target.resolve().is_relative_to(INSTANCE_ROOT.resolve())
                        # Legacy history has no scope stamp. Import a local copy,
                        # retaining the original for any non-local bridge user.
                        _write(target, {**content, 'conversation_id': state['id']})
        for bot in bots:
            identity = _identity(bot['id'])
            state['members'][identity] = str(bot.get('name') or identity)
        return update(**state)


def update_membership(bots):
    """Keep admission/lifecycle metadata separate from each persona's heard history."""
    with LOCK:
        prepare(bots)
        return update(membership={_identity(bot['id']): dict(
            admission_id=str(bot.get('_local_room_admission_id') or ''),
            phase=str(bot.get('_local_room_phase') or 'ready'),
            error=str(bot.get('_local_room_membership_error') or '')) for bot in bots})


def current(settings):
    identity = str(settings.get('_local_room_conversation_id') or '')
    return bool(identity and identity == load().get('id'))


def read_history(identity):
    with LOCK:
        path = history_path(identity)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('conversation_id') != load()['id']:
            return []
        if not isinstance(data.get('history'), list):
            raise ValueError('The saved participant history is invalid. Start a new conversation to clear it.')
        return [dict(entry) for entry in data.get('history', [])
                if isinstance(entry, dict) and entry.get('role') in {'user', 'assistant'}
                and isinstance(entry.get('content'), str)]


def messages():
    with LOCK:
        state = load()
        path = _directory()/'transcript.jsonl'
        if path.is_symlink():
            raise ValueError('Local room transcript points to another file; operation stopped.')
        if not path.exists():
            return copy.deepcopy(state['messages'])
        result = copy.deepcopy(state['messages'])
        utterance_rows = {}
        previous_utterance = ''
        previous_entry = {}
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # An append may still be finishing in the room process.
            if (isinstance(entry, dict) and entry.get('conversation_id') == state['id']
                    and not entry.get('display_only')
                    and isinstance(entry.get('name'), str) and isinstance(entry.get('text'), str)):
                utterance = str(entry.get('utterance_id') or '')
                if entry.get('replace_utterance') and utterance in utterance_rows:
                    result[utterance_rows[utterance]]['text'] = entry['text']
                    continue
                if utterance and utterance == previous_utterance and result and result[-1]['name'] == entry['name']:
                    result[-1]['text'] += ' ' + entry['text']
                elif (not utterance and previous_utterance and result
                      and entry.get('speaker_id') and entry.get('speaker_id') == previous_entry.get('speaker_id')
                      and entry.get('time') and entry.get('time') == previous_entry.get('time')
                      and result[-1]['name'] == entry['name']
                      and ' '.join(result[-1]['text'].split()) == ' '.join(entry['text'].split())):
                    # Older workers lost the utterance ID before publishing the
                    # completed speech, echoing its already recorded chunks.
                    # Collapse only that exact completion-time legacy pattern;
                    # retain distinct turns and leave the log itself untouched.
                    pass
                else:
                    result.append({'id': str(len(result)+1), 'name': entry['name'],
                                   'text': entry['text'], 'time': str(entry.get('time') or '')})
                if utterance: utterance_rows[utterance] = len(result)-1
                previous_utterance = utterance
                previous_entry = entry
        return result


@lru_cache(maxsize=1)
def _legacy_history_paths(root):
    """Classify old instance settings once; history itself remains live."""
    paths = []
    for settings_path in root.glob('*.settings.json'):
        if settings_path.is_symlink():
            continue
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
        if not isinstance(settings, dict) or not settings.get('_local_room_session'):
            continue
        identity = _identity(settings.get('id') or settings_path.name.removesuffix('.settings.json'))
        channel = str((settings.get('discord') or {}).get('voice_channel_id') or '')
        storage_id = identity + ('__channel_' + channel if channel else '')
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', storage_id):
            raise ValueError('Invalid legacy Local room history identity.')
        legacy = root/(storage_id + '.history.json')
        paths.append(legacy)
    return tuple(paths)


def has_history():
    """Include departed participants and legacy histories, not just the visible cast."""
    with LOCK:
        state = load()
        if messages() or state.get('continuation'):
            return True
        paths = list(_directory().glob('*.history.json'))
        if not state['id']:
            paths.extend(path for path in _legacy_history_paths(INSTANCE_ROOT) if path.exists())
        for path in paths:
            if path.is_symlink():
                raise ValueError('Local room history points to another file; operation stopped.')
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('history'), list):
                raise ValueError('The saved participant history is invalid. Start a new conversation to clear it.')
            if (not state['id'] or data.get('conversation_id') == state['id']) and data['history']:
                return True
        return False


def reset():
    with LOCK:
        directory = _directory()
        try:
            state = load()
        except ValueError:
            path = directory/'conversation.json'
            if path.is_symlink():
                raise
            if path.exists():
                path.replace(directory/('conversation.damaged-' + uuid.uuid4().hex + '.json'))
            state = dict(version=1, id='', topic='', messages=[], members={})
        paths = [directory/'transcript.jsonl', *directory.glob('*.history.json')]
        for path in paths:
            if path.is_symlink() or path.resolve().parent != directory.resolve():
                raise ValueError('Unsafe Local room data path; clearing stopped.')
        # Change the epoch before deleting so a finishing old request cannot
        # recreate history after the user has started a new conversation.
        state.update(id=uuid.uuid4().hex, topic='', messages=[], continuation={}, membership={})
        update(**state)
        for path in paths:
            path.unlink(missing_ok=True)
        return state
