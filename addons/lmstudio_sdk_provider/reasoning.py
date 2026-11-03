"""Public model capabilities and a checked, request-local SDK thinking adapter."""
from __future__ import annotations

from collections.abc import Mapping
import json
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


THINKING_KEY = 'llm.prediction.reasoning.enableThinking'


def supports_toggle(metadata, model_key):
    return (isinstance(metadata, Mapping) and metadata.get('model_key') == model_key
            and metadata.get('supports_reasoning') is True
            and isinstance(metadata.get('reasoning_options'), (list, tuple))
            and {'off', 'on'}.issubset(value for value in metadata['reasoning_options'] if isinstance(value, str)))


def parse_catalog(payload):
    if not isinstance(payload, Mapping) or not isinstance(payload.get('models'), list):
        raise ValueError('LM Studio reasoning catalog is unavailable or malformed.')
    result = {}
    for model in payload['models']:
        if not isinstance(model, Mapping) or model.get('type') != 'llm':
            continue
        key = model.get('key')
        if not isinstance(key, str) or not key:
            continue
        capabilities = model.get('capabilities')
        value = capabilities.get('reasoning') if isinstance(capabilities, Mapping) else None
        value = value if isinstance(value, Mapping) else {}
        options = value.get('allowed_options')
        options = sorted({item.strip().lower() for item in options if isinstance(item, str)}) if isinstance(options, list) else []
        result[key] = dict(supports_reasoning=bool(value), reasoning_options=options,
                           supports_reasoning_toggle={'off', 'on'}.issubset(options),
                           reasoning_default=str(value.get('default') or '').strip().lower(),
                           reasoning_metadata_available=True,loaded=bool(model.get('loaded_instances')),
                           source='lmstudio_native')
        if isinstance(capabilities, Mapping):
            for source, target in (('vision','supports_images'),('trained_for_tool_use','supports_tools')):
                if type(capabilities.get(source)) is bool:
                    result[key][target] = capabilities[source]
    return result


def fetch_catalog(host):
    parsed = urlsplit('http://' + host)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in host)):
        raise ValueError('LM Studio reasoning metadata requires a plain SDK host:port.')
    parsed.port  # Validate the configured port before constructing a request.
    opener = build_opener(ProxyHandler({}))
    # Runs inside the isolated helper: the existing caller owns cancellation
    # and deadlines. This is metadata only, never a generation fallback.
    with opener.open(Request('http://' + host + '/api/v1/models', method='GET')) as response:
        return parse_catalog(json.load(response))


class ThinkingAdapter:
    """Add the missing boolean mapping; observe only its scalar acknowledgement."""
    def __init__(self, stream, enabled):
        from lmstudio.sync_api import PredictionStream
        if type(enabled) is not bool or not isinstance(stream, PredictionStream) or stream._is_started:
            raise ValueError('Unsupported SDK thinking request or already-started stream.')
        endpoint = stream._endpoint
        wire = getattr(endpoint, 'creation_params', None)
        layers = wire.get('predictionConfigStack', {}).get('layers') if isinstance(wire, dict) else None
        if not isinstance(layers, list):
            raise ValueError('Unsupported SDK thinking configuration stack.')
        overrides, existing = [], []
        for layer in layers:
            if not isinstance(layer, dict) or not isinstance(layer.get('config'), dict):
                raise ValueError('Unsupported SDK thinking configuration layer.')
            fields = layer['config'].get('fields')
            if not isinstance(fields, list) or any(not isinstance(field, dict) for field in fields):
                raise ValueError('Unsupported SDK thinking configuration fields.')
            if layer.get('layerName') == 'apiOverride':
                overrides.append(fields)
            existing.extend(field for field in fields if field.get('key') == THINKING_KEY)
        self.original = getattr(endpoint, 'iter_message_events', None)
        if len(overrides) != 1 or existing or not callable(self.original):
            raise ValueError('Unsupported SDK thinking mapping; refusing duplicate or ambiguous overrides.')
        self.stream, self.endpoint, self.enabled = stream, endpoint, enabled
        self.reported = None
        overrides[0].append(dict(key=THINKING_KEY, value=enabled))

    def __enter__(self):
        self.endpoint.iter_message_events = self._events
        return self

    def _events(self, contents):
        if isinstance(contents, Mapping) and contents.get('type') == 'success':
            config = contents.get('predictionConfig')
            fields = config.get('fields', []) if isinstance(config, Mapping) else []
            values = [item.get('value') for item in fields if isinstance(item, Mapping) and item.get('key') == THINKING_KEY]
            if len(values) == 1 and type(values[0]) is bool:
                self.reported = values[0]
        yield from self.original(contents)

    def verify(self):
        if self.reported is None:
            raise ValueError('LM Studio SDK thinking mode was not reported; the requested setting could not be verified.')
        if self.reported is not self.enabled:
            raise ValueError('LM Studio SDK thinking mode did not match the requested setting.')

    def __exit__(self, *args):
        self.endpoint.iter_message_events = self.original
