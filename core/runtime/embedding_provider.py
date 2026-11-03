"""Small provider-specific embedding transport, independent of chat activation."""
from collections.abc import Mapping
import math
from urllib.parse import urlsplit

PROVIDERS = {
    'lmstudio': {'label': 'LM Studio', 'base_url': 'http://127.0.0.1:1234/v1',
                 'model': 'text-embedding-bge-m3', 'context_length': 8192},
    'ollama': {'label': 'Ollama', 'base_url': 'http://127.0.0.1:11434',
               'model': 'embeddinggemma', 'context_length': 2048},
    'openai': {'label': 'OpenAI', 'base_url': 'https://api.openai.com/v1',
               'model': 'text-embedding-3-small', 'context_length': 8192},
}


def provider_id(value):
    value = str(value or 'lmstudio').strip().lower()
    if value not in PROVIDERS:
        raise ValueError('This provider does not support memory search. Choose LM Studio, Ollama or OpenAI.')
    return value


def baseline_model(provider, model):
    """Keep old LM Studio baselines intact; separate other providers' vectors."""
    provider = provider_id(provider)
    model = str(model or '').strip()
    if any(model.startswith(name + ':') for name in PROVIDERS if name != 'lmstudio'):
        return model
    return model if provider == 'lmstudio' else f'{provider}:{model}'


def server_url(value, provider):
    provider = provider_id(provider)
    value = str(value or PROVIDERS[provider]['base_url']).strip().rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Enter a valid HTTP or HTTPS server address without credentials or query parameters.')
    try:
        parsed.port
    except ValueError:
        raise ValueError('Enter a valid server port.') from None
    if provider == 'openai' and parsed.scheme != 'https':
        raise ValueError('OpenAI requires an HTTPS server address.')
    if provider == 'openai' and (parsed.hostname != 'api.openai.com' or parsed.port not in (None, 443) or parsed.path.rstrip('/') != '/v1'):
        raise ValueError('OpenAI memory search uses https://api.openai.com/v1. Choose a local provider for local search.')
    if provider == 'ollama':
        for suffix in ('/api/embed', '/api/embeddings', '/v1', '/api'):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
                break
    return value


def validate_vector(vector):
    if not isinstance(vector, (list, tuple)) or not vector:
        raise ValueError('The search model returned no embedding. Choose an embedding model and test again.')
    try:
        if any(isinstance(v, bool) for v in vector):
            raise ValueError()
        values = [float(v) for v in vector]
    except (TypeError, ValueError, OverflowError):
        raise ValueError('The search model returned an invalid embedding.') from None
    if not all(math.isfinite(v) for v in values) or not any(values):
        raise ValueError('The search model returned an invalid embedding.')
    return values


def existing_api_key(provider):
    from core.chat_providers import provider_api_key
    return provider_api_key(provider)


class EmbeddingProviderClient:
    def __init__(self, *, request_json, api_key_getter=None):
        self._request = request_json
        self._key = api_key_getter or existing_api_key

    def _headers(self, provider):
        key = str(self._key(provider) or '').strip()
        if provider == 'openai' and not key:
            raise ValueError('Add your OpenAI API key in Model and connection before testing memory search.')
        return {'Authorization': 'Bearer ' + key} if key else {}

    def list_models(self, provider, base_url):
        provider = provider_id(provider)
        url = server_url(base_url, provider)
        if provider == 'lmstudio':
            native = url[:-3] + '/api/v1' if url.endswith('/v1') and not url.endswith('/api/v1') else url
            if not native.endswith('/api/v1'):
                native += '/api/v1'
            data = self._request(native + '/models', timeout=8)
            rows = data.get('models', []) if isinstance(data, Mapping) else []
        elif provider == 'ollama':
            data = self._request(url + '/api/tags', timeout=8, headers=self._headers(provider))
            rows = data.get('models', []) if isinstance(data, Mapping) else []
        else:
            data = self._request(url + '/models', timeout=8, headers=self._headers(provider))
            rows = data.get('data', []) if isinstance(data, Mapping) else []
        found = set()
        for item in rows or []:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get('key') or item.get('id') or item.get('name') or item.get('model') or '')
            kind = str(item.get('type') or '').lower()
            capabilities = item.get('capabilities') or {}
            embedding = kind in {'embd', 'embedding', 'embeddings'} or (isinstance(capabilities, Mapping) and capabilities.get('embedding'))
            lower = name.lower()
            if name and (embedding or any(word in lower for word in ('embed', 'bge', 'e5', 'gte'))):
                if not any(word in lower for word in ('whisper', 'tts', 'rerank', 'grok-imagine')):
                    found.add(name)
        return sorted(found, key=str.lower)

    def embed(self, provider, base_url, model, text):
        provider = provider_id(provider)
        url = server_url(base_url, provider)
        if not str(model or '').strip():
            raise ValueError('Choose an embedding model first.')
        payload = {'model': str(model).strip(), 'input': [str(text)]}
        if provider == 'ollama':
            payload['truncate'] = False
            data = self._request(url + '/api/embed', payload=payload, headers=self._headers(provider), timeout=30)
            rows = data.get('embeddings', []) if isinstance(data, Mapping) else []
            vector = rows[0] if rows else []
        else:
            options = {} if provider == 'lmstudio' else {'headers': self._headers(provider)}
            data = self._request(url + '/embeddings', payload=payload, timeout=30, **options)
            rows = data.get('data', []) if isinstance(data, Mapping) else []
            vector = rows[0].get('embedding', []) if rows and isinstance(rows[0], Mapping) else []
        return validate_vector(vector)
