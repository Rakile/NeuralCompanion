"""Production resource adapters built from existing finite runtime owners."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import replace
import json
from urllib.parse import urlsplit, urlunsplit
import urllib.request

from .resources import ResourceService, RegisteredResourceSources
from .embedding_provider import PROVIDERS, server_url


def endpoint_key(url):
    value = str(url or '').strip().rstrip('/')
    parts = urlsplit(value)
    path = parts.path.rstrip('/')
    if path.endswith('/api/v1'):
        path = path[:-7]
    elif path.endswith('/v1'):
        path = path[:-3]
    host = (parts.hostname or '').lower()
    if host in ('localhost', '::1'):
        host = '127.0.0.1'
    port = parts.port
    authority = host + (':' + str(port) if port else '')
    return urlunsplit((parts.scheme.lower(), authority, path, '', ''))


class LMStudioResourceSource:
    def __init__(self, providers, selection, embeddings=None):
        self._providers, self._selection, self._embeddings = providers, selection, embeddings
        self._models = {}

    def resources_snapshot(self):
        rows = self._providers.resource_model_snapshot(self._selection)
        self._models = {str(r['id']): str(r.get('model') or '') for r in rows}
        return rows

    def unload_resource(self, identifier):
        model = self._models.get(str(identifier), '')
        result = self._providers.unload_resource_model(self._selection, str(identifier))
        if result and self._embeddings is not None:
            self._embeddings.clear_load_cache()
            port = self._embeddings.document_capability()
            port.forget_resource(self._selection.endpoint, model)
        return result


class OllamaResourceSource:
    def __init__(self, endpoint, providers, *, request=None):
        self._base = str(endpoint).rstrip('/')
        if self._base.endswith('/v1'):
            self._base = self._base[:-3]
        self._providers = providers
        self._request = request or self._http

    @staticmethod
    def _http(url, payload=None):
        request = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.load(response)

    def resources_snapshot(self):
        data = self._request(self._base + '/api/ps')
        if not isinstance(data, dict) or not isinstance(data.get('models'), list):
            raise RuntimeError('Ollama returned an invalid resident-model response.')
        return [{'id': str(r.get('name') or r.get('model')), 'name': str(r.get('name') or r.get('model')),
                 'model': str(r.get('model') or r.get('name')), 'owner': 'Ollama · ' + self._base,
                 'device': 'Managed by Ollama', 'vramBytes': r.get('size_vram'),
                 'processEndpoint': self._base, 'processBackend': 'ollama', 'processLabel': 'Ollama',
                 'canUnload': True, 'users': ['Model request'] if self._providers.active() else [],
                 'memoryNote': 'VRAM is reported by Ollama. Per-model RAM is unavailable.'}
                for r in data['models'] if r.get('name') or r.get('model')]

    def unload_resource(self, identifier):
        # ProviderService holds inference admission while the callback runs.
        def unload():
            resident = self._request(self._base + '/api/ps')
            if not any(str(r.get('name') or r.get('model')) == identifier for r in resident.get('models', ())):
                return False
            result = self._request(self._base + '/api/generate', {'model': identifier, 'keep_alive': 0})
            return isinstance(result, dict) and not result.get('error')
        return self._providers.resource_model_operation(unload)


def release_idle_speech_models(resources, entries):
    """Release resident speech services through the existing admission/recheck guard."""
    from urllib.parse import unquote
    source_ids = {
        str(entry['owner_addon_id']) + ':' + str(entry['name']) + ':' + str(id(entry['service']))
        for entry in entries
        if str((entry.get('metadata') or {}).get('kind') or '').lower()
        in {'tts', 'stt', 'tts_backend', 'stt_backend', 'text_to_speech', 'speech_to_text'}
        and entry.get('service') is not None
    }
    results = []
    for item in resources.snapshot()['resources']:
        source_id = unquote(str(item['id']).split('/', 1)[0])
        if source_id in source_ids and item.get('canUnload'):
            results.append(resources.unload(item['id']))
    errors = [str(result.get('message') or 'Speech model cleanup failed.')
              for result in results if not result.get('ok')]
    return {'ok': not errors, 'message': '; '.join(errors),
            'unloaded': sum(bool(result.get('ok')) for result in results)}


def build_resource_service(*, config, providers, registry, runtime_use, activity,
                           document_memory=None, embeddings=None):
    registered = RegisteredResourceSources(registry)
    document_embeddings = embeddings.document_capability() if embeddings is not None else None

    def sources():
        snapshot = config.snapshot()
        values = dict(snapshot.values)
        result = registered()
        capture = getattr(providers, 'capture_selection', None)
        if not callable(capture):
            return result
        selection = capture(snapshot, provider_id='lmstudio')
        endpoints = [selection.endpoint]
        embedding_provider = str(values.get('long_term_memory_embedding_provider') or 'lmstudio').strip().lower()
        embedding_endpoint = values.get('long_term_memory_embedding_base_url')
        if embedding_provider == 'lmstudio' and embedding_endpoint:
            endpoints.append(embedding_endpoint)
        if document_embeddings is not None:
            endpoints.extend(document_embeddings.resource_endpoints())
        seen = set()
        for endpoint in endpoints:
            if not endpoint or endpoint_key(endpoint) in seen:
                continue
            key = endpoint_key(endpoint); seen.add(key)
            result['lmstudio:' + key] = LMStudioResourceSource(providers, replace(selection, endpoint=str(endpoint)), embeddings)
        settings = values.get('chat_provider_settings') or {}
        ollama_endpoints = []
        if values.get('chat_provider') == 'ollama' or settings.get('ollama'):
            chosen = capture(snapshot, provider_id='ollama')
            if chosen.endpoint:
                ollama_endpoints.append(chosen.endpoint)
        if embedding_provider == 'ollama':
            ollama_endpoints.append(server_url(embedding_endpoint or PROVIDERS['ollama']['base_url'], 'ollama'))
        for endpoint in ollama_endpoints:
            key = 'ollama:' + endpoint_key(endpoint)
            if key not in result:
                result[key] = OllamaResourceSource(endpoint, providers)
        return result

    def blockers():
        users = []
        if runtime_use is not None and runtime_use.snapshot().owner == 'chat':
            users.append('Main chat')
        if providers.active():
            users.append('Model request')
        state = dict(document_memory.idle_snapshot() if document_memory is not None else activity())
        from .document_memory import idle_reason
        reason = idle_reason(state)
        if reason:
            users.append(reason)
        if embeddings is not None and embeddings.resource_busy():
            users.append('Memory search or indexing')
        for source in registered().values():
            reader = getattr(source, 'resource_users', None)
            if callable(reader):
                users.extend(reader())
        return tuple(dict.fromkeys(users))

    @contextmanager
    def admission(_item):
        with ExitStack() as stack:
            # Acquire addon startup/job guards before the global runtime gate,
            # matching their normal startup lock order.
            for source in registered().values():
                guard = getattr(source, 'resource_maintenance', None)
                if callable(guard):
                    stack.enter_context(guard())
            if runtime_use is not None:
                stack.enter_context(runtime_use.resource_maintenance())
            if embeddings is not None:
                stack.enter_context(embeddings.resource_maintenance())
            if blockers():
                raise RuntimeError('Resources became busy before cleanup.')
            yield
    return ResourceService(sources=sources, blockers=blockers, admission=admission)
