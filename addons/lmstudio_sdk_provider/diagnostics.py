"""Allowlisted SDK metadata only; never serialize prompts or tool payloads."""
from __future__ import annotations

from collections.abc import Mapping
import json
import math


# SDK prediction names also identify the corresponding wire field suffixes,
# except for maxTokens, whose wire name is maxPredictedTokens.
SETTINGS = {
    'temperature': 'temperature', 'top_p': 'topPSampling',
    'top_k': 'topKSampling', 'repeat_penalty': 'repeatPenalty',
    'min_p': 'minPSampling', 'max_tokens': 'maxTokens',
    'thinking': 'reasoning.enableThinking',
}
STATS = {
    'input_tokens': 'prompt_tokens_count', 'output_tokens': 'predicted_tokens_count',
    'total_tokens': 'total_tokens_count', 'tokens_per_second': 'tokens_per_second',
    'first_token_seconds': 'time_to_first_token_sec', 'gpu_layers': 'num_gpu_layers',
}
STOP_REASONS = {'eosFound', 'stopStringFound', 'toolCalls', 'maxPredictedTokensReached',
                'contextLengthReached', 'userStopped', 'failed'}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _settings(values):
    if not isinstance(values, Mapping):
        return {}
    return {key: value for key, value in values.items() if key in SETTINGS and
            ((key == 'thinking' and type(value) is bool) or
             (key != 'thinking' and (_number(value) or (key == 'max_tokens' and value is False))))}


def _display(values):
    return {key: 'unlimited' if key == 'max_tokens' and value is False else value
            for key, value in _settings(values).items()}


def sent_settings(stream):
    """Read the actual request after the SDK/no-cap wire correction."""
    names = {'llm.prediction.' + ('maxPredictedTokens' if sdk == 'maxTokens' else sdk): key
             for key, sdk in SETTINGS.items()}
    values = {}
    for layer in stream._endpoint.creation_params.get('predictionConfigStack', {}).get('layers', []):
        for item in layer.get('config', {}).get('fields', []):
            key = names.get(item.get('key'))
            if key is None:
                continue
            value = item.get('value')
            if isinstance(value, Mapping):
                if value.get('checked') is False:
                    value = False if key == 'max_tokens' else None
                elif value.get('checked') is True:
                    value = value.get('value')
            values[key] = value
    return _settings(values)


def result_event(request_id, sent, result, elapsed, *, thinking_reported=None):
    config = result.prediction_config
    config = config.to_dict() if callable(getattr(config, 'to_dict', None)) else config
    reported = _settings({key: config.get(sdk) for key, sdk in SETTINGS.items()})
    if type(thinking_reported) is bool:
        reported['thinking'] = thinking_reported
    stats = {key: value for key, attr in STATS.items()
             if _number(value := getattr(result.stats, attr, None))}
    reason = getattr(result.stats, 'stop_reason', None)
    if reason in STOP_REASONS:
        stats['stop_reason'] = reason
    stats['prediction_elapsed_seconds'] = elapsed
    return dict(phase='result', id=request_id, sent=_settings(sent), reported=reported,
                matches=[key for key in sent if key in reported and sent[key] == reported[key]],
                differences={key: dict(sent=sent[key], reported=reported[key])
                             for key in sent if key in reported and sent[key] != reported[key]},
                not_reported=[key for key in sent if key not in reported], stats=stats)


def format_event(event):
    """Validate again in the parent before writing anything to NC's console."""
    if not isinstance(event, Mapping):
        return []
    # JSON quoting keeps any embedded newline out of the log's structure.
    def dump(value):
        return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    identifier = event.get('id')
    prefix = '[LM Studio SDK][' + (identifier if isinstance(identifier, str) and identifier.isalnum() else 'request') + '] '
    if event.get('phase') == 'request':
        meta = {key: event[key] for key in ('sdk_version', 'model', 'instance')
                if isinstance(event.get(key), str)}
        meta.update({key: event[key] for key in ('context_requested', 'context_allocated')
                     if _number(event.get(key))})
        return [prefix + 'Request: ' + dump(meta),
                prefix + 'Settings sent: ' + dump(_display(event.get('sent')))]
    if event.get('phase') == 'result':
        sent, reported = _settings(event.get('sent')), _settings(event.get('reported'))
        comparison = dict(matches=[key for key in sent if key in reported and sent[key] == reported[key]],
                          differences={key: dict(sent=_display(sent)[key], reported=_display(reported)[key])
                                       for key in sent if key in reported and sent[key] != reported[key]},
                          not_reported=[key for key in sent if key not in reported])
        supplied = event.get('stats')
        supplied = supplied if isinstance(supplied, Mapping) else {}
        stats = {key: supplied[key] for key in (*STATS, 'prediction_elapsed_seconds')
                 if _number(supplied.get(key))}
        if supplied.get('stop_reason') in STOP_REASONS:
            stats['stop_reason'] = supplied['stop_reason']
        return [prefix + 'LM Studio reported: ' + dump(_display(reported)),
                prefix + 'Settings comparison (not_reported means unverified): ' + dump(comparison),
                prefix + 'Usage: ' + dump(stats)]
    if event.get('phase') == 'failed':
        return [prefix + 'Request failed; no additional server-reported configuration available.']
    if event.get('phase') == 'unavailable':
        return [prefix + 'SDK diagnostic metadata unavailable; prediction behavior unchanged.']
    return []


def report(callback, event):
    """Diagnostics must never turn a working prediction into a failed reply."""
    if callback is not None:
        try:
            callback(event)
        except Exception:
            pass


def log_event(event):
    for line in format_event(event):
        print(line)
