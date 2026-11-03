"""Atomic Discord room checkpoints, isolated from Local room history."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from .room_membership import validate_roster


_FORBIDDEN = {'token', 'api_key', 'password', 'secret', 'pid', 'process', 'socket', 'runtime_token'}


def _check_safe(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN or str(key).lower().endswith(('_token', '_api_key', '_password')):
                raise ValueError('Room checkpoints cannot contain credentials or live process state.')
            _check_safe(item)
    elif isinstance(value, list):
        for item in value:
            _check_safe(item)


class DiscordRoomStore:
    def __init__(self, root, guild_id, channel_id, room_id):
        self.identity = dict(guild_id=str(guild_id), channel_id=str(channel_id), room_id=str(room_id))
        digest = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()
        self.path = Path(root) / (digest + '.json')
        self._lock = threading.RLock()

    def load(self):
        with self._lock:
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                return {}
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise ValueError('The saved Discord room is corrupt. Its existing file has been preserved.') from exc
            if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('identity') != self.identity or not isinstance(value.get('data'), dict):
                raise ValueError('The saved Discord room identity or format does not match this room.')
            _check_safe(value['data'])
            if 'roster' in value['data']:
                validate_roster(value['data']['roster'])
            return value['data']

    def save(self, value):
        if not isinstance(value, dict):
            raise ValueError('A room checkpoint must be an object.')
        _check_safe(value)
        if 'roster' in value:
            validate_roster(value['roster'])
        payload = json.dumps(dict(schema_version=1, identity=self.identity, data=value), ensure_ascii=False, indent=2)
        temporary = None
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                        prefix=self.path.stem + '.', suffix='.tmp', delete=False) as stream:
                    temporary = stream.name
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary and Path(temporary).exists():
                    Path(temporary).unlink()
