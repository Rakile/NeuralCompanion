"""Bounded, connection-owned state differences. Never a playback receipt cache."""
from __future__ import annotations

from collections import OrderedDict
import json
import math
import re
import threading
import time
import uuid

VERSION = 1
MAX_FULL = 64 * 1024 * 1024
MAX_PATCH = 16 * 1024 * 1024
MAX_REVISION = 2**53 - 1
_UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
_FORBIDDEN = {'__proto__', 'prototype', 'constructor'}


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
                      allow_nan=False).encode('utf-8')


def _validate(value, depth=0):
    if depth > 64:
        raise ValueError('State nesting limit')
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN:
                raise ValueError('Invalid state key')
            _validate(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate(item, depth + 1)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise ValueError('Invalid state value')
    elif type(value) is float and not math.isfinite(value):
        raise ValueError('Nonfinite state value')


def _changes(old, new, path, sets, removes):
    if len(sets) + len(removes) > 4096 or len(path) > 32 or any(len(k) > 512 for k in path):
        raise OverflowError
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() - new.keys()):
            removes.append(path + [key])
        for key in sorted(new):
            if key not in old:
                sets.append({'path': path + [key], 'value': new[key]})
            else:
                _changes(old[key], new[key], path + [key], sets, removes)
    elif encoded(old) != encoded(new):
        sets.append({'path': path, 'value': new})


def request_cursor(query: dict[str, list[str]]) -> dict:
    """Only network boundaries use this; authentication must already have run."""
    if query.get('sync') != ['1']:
        raise ValueError('Update NC Desktop and NC Remote together (state protocol 1 required).')
    for key in ('context', 'epoch', 'revision'):
        if len(query.get(key, [])) > 1:
            raise ValueError('Invalid state cursor')
    result = {key: query.get(key, [''])[0] for key in ('context', 'epoch')}
    raw = query.get('revision', ['0'])[0]
    if not re.fullmatch(r'0|[1-9][0-9]{0,15}', raw):
        raise ValueError('Invalid state revision')
    result['revision'] = int(raw)
    _validate_cursor(**result)
    return result


def _validate_cursor(context='', epoch='', revision=0):
    if (not isinstance(context, str) or not isinstance(epoch, str)
            or (context and not _UUID.fullmatch(context)) or (epoch and not _UUID.fullmatch(epoch))
            or type(revision) is not int or not 0 <= revision <= MAX_REVISION
            or bool(context) != bool(epoch) or (not context and revision != 0)):
        raise ValueError('Invalid state cursor')


class StateSyncStore:
    def __init__(self, max_contexts=16, max_bytes=67108864, ttl=120, clock=time.monotonic):
        self._max_contexts, self._max_bytes, self._ttl = max_contexts, max_bytes, ttl
        self._clock = clock
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def _drop(self, key):
        entry = self._entries.pop(key)
        self._bytes -= len(entry['bytes'])

    def clear(self, owner: str | None = None) -> None:
        with self._lock:
            for key, entry in list(self._entries.items()):
                if owner is None or entry['owner'] == owner:
                    self._drop(key)

    def respond(self, owner: str, state: dict, *, context='', epoch='', revision=0) -> dict:
        _validate_cursor(context, epoch, revision)
        if not isinstance(owner, str) or not owner or not isinstance(state, dict):
            raise ValueError('Invalid snapshot')
        _validate(state)
        raw = encoded(state)
        if len(raw) > MAX_FULL - 1024:
            raise ValueError('State size limit')
        with self._lock:
            now = self._clock()
            for key, entry in list(self._entries.items()):
                if now - entry['used'] >= self._ttl:
                    self._drop(key)
            previous = self._entries.get(context)
            if previous and previous['owner'] != owner:
                raise ValueError('Invalid state context')
            matches = (previous is not None and epoch == previous['epoch']
                       and revision == previous['revision'])
            # A mismatched/lost response gets a fresh epoch. No old patch can
            # subsequently attach to this newly established baseline.
            if not matches:
                if previous:
                    self._drop(context)
                context, epoch, revision = str(uuid.uuid4()), str(uuid.uuid4()), 1
            elif raw != previous['bytes']:
                revision += 1
                if revision > MAX_REVISION:
                    self._drop(context)
                    previous = None
                    context, epoch, revision = str(uuid.uuid4()), str(uuid.uuid4()), 1
                    matches = False
            header = dict(version=VERSION, context=context, epoch=epoch, revision=revision)
            envelope = dict(header, kind='full', state=json.loads(raw))
            if matches:
                if raw == previous['bytes']:
                    envelope = dict(header, kind='unchanged')
                else:
                    sets, removes = [], []
                    try:
                        _changes(json.loads(previous['bytes']), envelope['state'], [], sets, removes)
                        paths = [op['path'] for op in sets] + removes
                        if (len(paths) > 4096 or any(not p or len(p) > 32 or any(len(k) > 512 for k in p) for p in paths)):
                            raise OverflowError
                        patch = dict(header, kind='patch', base_revision=previous['revision'], set=sets, remove=removes)
                        if len(encoded(patch)) < min(MAX_PATCH, len(encoded(envelope))):
                            envelope = patch
                    except OverflowError:
                        pass  # Full snapshot preserves values that exceed patch limits.
            if context in self._entries:
                self._drop(context)
            if len(raw) <= self._max_bytes and self._max_contexts > 0:
                self._entries[context] = dict(owner=owner, epoch=epoch, revision=revision, bytes=raw, used=now)
                self._bytes += len(raw)
                while len(self._entries) > self._max_contexts or self._bytes > self._max_bytes:
                    self._drop(next(iter(self._entries)))
            return {'ok': True, 'state_sync': envelope}
