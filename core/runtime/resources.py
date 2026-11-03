"""Optional, category-free resident-resource inspection and exact cleanup.

Sources implement resources_snapshot() and unload_resource(instance_id).
Snapshots never prepare models. A missing measurement is None, not zero.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import nullcontext
from copy import deepcopy
import math
import threading
import time
from typing import Protocol
from urllib.parse import quote


class ResourceSource(Protocol):
    def resources_snapshot(self) -> Iterable[Mapping[str, object]]: ...
    def unload_resource(self, instance_id: str) -> object: ...


def _bytes(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if math.isfinite(value) and value >= 0 else None


class ResourceService:
    """Serialize inspection/cleanup, recheck use, and retain unconfirmed failures."""

    def __init__(self, *, sources: Callable, memory_reader: Callable | None = None,
                 process_reader: Callable | None = None,
                 blockers: Callable = lambda: (), admission: Callable | None = None):
        self._sources = sources
        if memory_reader is None:
            from .resource_memory import read_memory
            memory_reader = read_memory
        self._memory = memory_reader
        if process_reader is None:
            from .resource_process_memory import read_resource_process_memory
            process_reader = read_resource_process_memory
        self._process_memory = process_reader
        self._blockers = blockers
        self._admission = admission or (lambda _item: nullcontext())
        self._lock = threading.RLock()
        self._cache = {}
        self._failures = {}
        self._message = ''

    def _collect(self):
        errors, rows, targets = [], {}, {}
        try:
            blockers = tuple(str(x) for x in self._blockers() if str(x))
        except Exception:
            blockers = ('Runtime activity unavailable',)
        try:
            sources = dict(self._sources())
        except Exception as exc:
            sources = {}
            errors.append('Resource discovery: ' + str(exc))
            for key, old in self._cache.items():
                rows[key] = {**old, 'canUnload': False, 'status': 'unavailable',
                             'statusLabel': 'Inspection unavailable',
                             'unloadReason': 'Resource discovery failed.'}
        for source_id, source in sources.items():
            prefix = quote(str(source_id), safe='') + '/'
            try:
                values = tuple(source.resources_snapshot())
                for value in values:
                    raw = dict(value)
                    instance_id = str(raw.get('id') or '').strip()
                    if not instance_id:
                        raise ValueError('Resident resource has no exact instance id.')
                    key = prefix + quote(instance_id, safe='')
                    users = list(dict.fromkeys(str(x) for x in raw.get('users', ()) if str(x)))
                    users = list(dict.fromkeys(users + list(blockers)))
                    error = str(self._failures.get(key) or raw.get('error') or '')
                    status = str(raw.get('status') or ('in_use' if users else 'idle'))
                    if error:
                        status = 'cleanup_failed'
                    if users and not error:
                        status = 'in_use'
                    capability = bool(raw.get('canUnload', False) and callable(getattr(source, 'unload_resource', None)))
                    allowed = capability and not users and status in ('idle', 'cleanup_failed')
                    reason = ('Used by ' + ', '.join(users)) if users else str(raw.get('unloadReason') or '')
                    if not capability and not reason:
                        reason = 'This backend does not expose safe model unloading.'
                    item = {
                        'id': key, 'name': str(raw.get('name') or instance_id),
                        'model': str(raw.get('model') or ''), 'owner': str(raw.get('owner') or source_id),
                        'device': str(raw.get('device') or 'Unavailable'),
                        'ramBytes': _bytes(raw.get('ramBytes')), 'vramBytes': _bytes(raw.get('vramBytes')),
                        'processId': raw.get('processId'),
                        'processIncludeChildren': raw.get('processIncludeChildren') is True,
                        'processEndpoint': str(raw.get('processEndpoint') or ''),
                        'processBackend': str(raw.get('processBackend') or ''),
                        'processLabel': str(raw.get('processLabel') or ''),
                        'memoryNote': str(raw.get('memoryNote') or 'Per-model memory unavailable; process memory may be shared.'),
                        'users': users, 'status': status, 'error': error,
                        'statusLabel': {'idle': 'Loaded · idle', 'in_use': 'In use',
                                        'loading': 'Loading', 'unloading': 'Unloading',
                                        'cleanup_failed': 'Cleanup failed'}.get(status, 'Inspection unavailable'),
                        'canUnload': allowed, 'unloadReason': reason,
                    }
                    rows[key] = item
                    targets[key] = (source, instance_id)
            except Exception as exc:
                errors.append(str(source_id) + ': ' + str(exc))
                # A partially invalid snapshot cannot authorize any unloads.
                for key in tuple(rows):
                    if key.startswith(prefix):
                        rows[key] = {**rows[key], 'canUnload': False, 'status': 'unavailable',
                                     'statusLabel': 'Inspection unavailable',
                                     'unloadReason': 'The backend could not confirm residency.'}
                        targets.pop(key, None)
                # Never turn a failed probe into an apparently empty inventory.
                for key, old in self._cache.items():
                    if key.startswith(prefix):
                        rows[key] = {**old, 'canUnload': False, 'status': 'unavailable',
                                     'statusLabel': 'Inspection unavailable',
                                     'unloadReason': 'The backend could not confirm residency.'}
                        targets.pop(key, None)
        self._cache = rows
        return rows, targets, errors

    def snapshot(self):
        with self._lock:
            rows, _, errors = self._collect()
            try:
                memory = dict(self._memory())
            except Exception as exc:
                memory = {'ram': {}, 'gpus': []}
                errors.append('Memory readings: ' + str(exc))
            resources = deepcopy(list(rows.values()))
            try:
                process_memory = self._process_memory(resources)
                for item in resources:
                    item.update(process_memory.get(item['id'], {}))
            except Exception:
                pass  # Optional telemetry must not change residency or unload status.
            return {'resources': resources, 'memory': memory,
                    'errors': errors, 'message': self._message, 'updatedAt': time.time()}

    def unload(self, resource_id: str):
        with self._lock:
            rows, targets, _ = self._collect()
            item = rows.get(str(resource_id))
            if item is None or not item['canUnload'] or resource_id not in targets:
                return {'ok': False, 'message': (item or {}).get('unloadReason') or 'Resource is no longer available for unloading.'}
            try:
                attempted = False
                with self._admission(item):
                    # Startup and backend ownership may have changed since the UI snapshot.
                    current, targets, _ = self._collect()
                    fresh = current.get(resource_id)
                    if not fresh or not fresh['canUnload'] or resource_id not in targets:
                        return {'ok': False, 'message': 'Resource became busy or was replaced.'}
                    source, instance_id = targets[resource_id]
                    attempted = True
                    result = source.unload_resource(instance_id)
                    if result is False or getattr(result, 'accepted', True) is False or isinstance(result, Mapping) and result.get('ok') is False:
                        raise RuntimeError(str(getattr(getattr(result, 'failure', None), 'message', '') or 'Backend did not confirm cleanup.'))
                    remaining = tuple(source.resources_snapshot())
                    if any(str(r.get('id') or '') == instance_id for r in remaining):
                        raise RuntimeError('The resource is still resident after cleanup.')
                    cache_warning = ''
                    try:
                        from .resource_memory import release_unused_memory
                        release_unused_memory()
                    except Exception as exc:
                        cache_warning = ' Cache cleanup: ' + str(exc)
                self._failures.pop(resource_id, None)
                self._message = item['name'] + ' unloaded.' + cache_warning
                return {'ok': True, 'message': self._message}
            except Exception as exc:
                if attempted:
                    self._failures[resource_id] = str(exc)
                self._message = item['name'] + ': ' + str(exc)
                return {'ok': False, 'message': self._message}

    def free_unused(self):
        with self._lock:
            rows, _, _ = self._collect()
            ids = [key for key, item in rows.items() if item['canUnload']]
            results = [self.unload(key) for key in ids]
            count = sum(bool(r['ok']) for r in results)
            errors = [r['message'] for r in results if not r['ok']]
            self._message = f'{count} resource(s) unloaded.' + (' ' + '; '.join(errors) if errors else '')
            return {'ok': not errors, 'message': self._message}


class RegisteredResourceSources:
    """Adapt existing service registrations; older services need no new methods."""
    def __init__(self, registry):
        self._registry = registry

    def __call__(self):
        sources = {}
        registry = self._registry() if callable(self._registry) else self._registry
        for entry in registry.list_entries():
            service = entry.get('service')
            if callable(getattr(service, 'resources_snapshot', None)):
                key = str(entry['owner_addon_id']) + ':' + str(entry['name']) + ':' + str(id(service))
                sources[key] = service
        return sources
