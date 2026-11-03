"""Atomic, immutable versions for locally named Main Chat stories."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ENTRY_ID = re.compile(r'[0-9a-f]{32}\Z')


class StoryLibraryStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self._index_path = self.root / 'index.json'
        if self._index_path.exists():
            index = json.loads(self._index_path.read_text(encoding='utf-8'))
            if not isinstance(index, dict) or index.get('version') != 1 or not isinstance(index.get('entries'), dict):
                raise ValueError('Story Library index is invalid.')
            for identity, row in index['entries'].items():
                if (not isinstance(identity, str) or not _ENTRY_ID.fullmatch(identity)
                        or not isinstance(row, dict) or row.get('entry_id') != identity
                        or set(row) != {'entry_id', 'name', 'saved_at', 'version',
                                            'current_beat', 'beat_count', 'character_names'}
                        or not isinstance(row.get('name'), str)
                        or not 1 <= len(row['name'].strip()) <= 120
                        or not isinstance(row.get('saved_at'), str)
                        or type(row.get('version')) is not int or row['version'] < 1
                        or (row.get('current_beat') is not None and
                            (type(row['current_beat']) is not int or row['current_beat'] < 0))
                        or type(row.get('beat_count')) is not int or row['beat_count'] < 0
                        or (row['beat_count'] == 0 and row['current_beat'] is not None)
                        or (row['beat_count'] > 0 and
                            (row['current_beat'] is None or row['current_beat'] >= row['beat_count']))
                        or not isinstance(row.get('character_names'), list)
                        or any(not isinstance(name, str) for name in row['character_names'])):
                    raise ValueError('Story Library index entry is invalid.')
            self._index = index
        else:
            self._index: dict[str, Any] = {'version': 1, 'entries': {}}

    @staticmethod
    def _name(value: str) -> str:
        if not isinstance(value, str) or '\x00' in value or not 1 <= len(value.strip()) <= 120:
            raise ValueError('Story name must contain 1–120 characters.')
        return value.strip()

    @staticmethod
    def _id(value: str) -> str:
        if not isinstance(value, str) or not _ENTRY_ID.fullmatch(value):
            raise ValueError('Story Library entry ID is invalid.')
        return value

    def _entry(self, entry_id: str) -> dict[str, Any]:
        entry = self._index['entries'].get(self._id(entry_id))
        if not isinstance(entry, dict):
            raise KeyError('Story Library entry not found.')
        return entry

    def _unique_name(self, name: str, except_id: str | None = None) -> None:
        if any(identity != except_id and row['name'].casefold() == name.casefold()
               for identity, row in self._index['entries'].items()):
            raise ValueError('A saved story already has this name.')

    def _publish_index(self, index: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ('.index-' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as output:
                json.dump(index, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._index_path)
            self._index = index
        finally:
            temporary.unlink(missing_ok=True)

    def list_entries(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(row) for row in sorted(self._index['entries'].values(),
                                               key=lambda row: row['saved_at'], reverse=True)]

    def read_version(self, entry_id: str) -> Path:
        with self._lock:
            row = self._entry(entry_id)
            folder = self.root / 'entries' / entry_id / f"v{row['version']:06d}"
            manifest_path = folder / 'manifest.json'
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if (not isinstance(manifest, dict) or manifest.get('entry_id') != entry_id
                        or manifest.get('version') != row['version']
                        or not isinstance(manifest.get('files'), dict)):
                    raise ValueError('Story Library version does not match its index.')
                for relative, digest in manifest['files'].items():
                    if not isinstance(relative, str) or not isinstance(digest, str):
                        raise ValueError('Story Library manifest is invalid.')
                    path = (folder / relative).resolve()
                    if (not path.is_relative_to(folder.resolve()) or not path.is_file()
                            or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                        raise ValueError('Saved story file is missing or corrupted.')
            except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                raise ValueError('Saved story version is unavailable or corrupted.') from exc
            return folder

    def write_version(self, entry_id: str | None, name: str,
                      capture: Callable[[Path], dict[str, object]]) -> dict[str, object]:
        name = self._name(name)
        with self._lock:
            if entry_id is None:
                self._unique_name(name)
                entry_id = uuid.uuid4().hex
                version = 1
            else:
                prior = self._entry(entry_id)
                self._unique_name(name, entry_id)
                version = int(prior['version']) + 1
            parent = self.root / 'entries' / entry_id
            parent.mkdir(parents=True, exist_ok=True)
            stage = parent / ('.staged-' + uuid.uuid4().hex)
            stage.mkdir()
            try:
                metadata = capture(stage)
                if not isinstance(metadata, dict):
                    raise ValueError('Story capture metadata is invalid.')
                beat = metadata.get('current_beat')
                total = metadata.get('beat_count')
                names = metadata.get('character_names')
                if (beat is not None and (type(beat) is not int or beat < 0)
                        or type(total) is not int or total < 0
                        or (total == 0 and beat is not None)
                        or (total > 0 and (beat is None or beat >= total))
                        or not isinstance(names, list) or any(not isinstance(item, str) for item in names)):
                    raise ValueError('Story capture metadata is invalid.')
                files: dict[str, str] = {}
                for path in stage.rglob('*'):
                    if path.is_symlink():
                        raise ValueError('Saved story cannot contain symbolic links.')
                    if path.is_file():
                        files[path.relative_to(stage).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
                if 'chat_context.json' not in files:
                    raise ValueError('Story capture has no chat context.')
                saved_at = datetime.now(timezone.utc).isoformat()
                manifest = {'schema_version': 1, 'entry_id': entry_id, 'version': version,
                            'name': name, 'saved_at': saved_at, 'files': files}
                (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
                final = parent / f'v{version:06d}'
                if final.exists():
                    raise ValueError('Story version already exists.')
                stage.rename(final)
                row = {'entry_id': entry_id, 'name': name, 'saved_at': saved_at,
                       'version': version, 'current_beat': beat, 'beat_count': total,
                       'character_names': list(names)}
                index = {'version': 1, 'entries': {**self._index['entries'], entry_id: row}}
                self._publish_index(index)
                return dict(row)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)

    def rename(self, entry_id: str, name: str) -> dict[str, object]:
        name = self._name(name)
        with self._lock:
            row = dict(self._entry(entry_id))
            self._unique_name(name, entry_id)
            row['name'] = name
            self._publish_index({'version': 1, 'entries': {**self._index['entries'], entry_id: row}})
            return row

    def delete(self, entry_id: str) -> None:
        with self._lock:
            self._entry(entry_id)
            rows = dict(self._index['entries'])
            del rows[entry_id]
            self._publish_index({'version': 1, 'entries': rows})
            try:
                shutil.rmtree(self.root / 'entries' / entry_id)
            except OSError:
                # An unlisted orphan is safer than a visible entry with missing files.
                pass
