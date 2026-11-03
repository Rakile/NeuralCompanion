"""Isolated LM Studio SDK adapter. NC retains all tool execution ownership."""
from __future__ import annotations

import base64
from collections.abc import Mapping
from contextlib import nullcontext
from hashlib import sha256
import json
import time
from uuid import uuid4

from addons.lmstudio_sdk_provider import diagnostics, reasoning
from addons.lmstudio_sdk_provider.output_guard import ReservedTokenGuard, ReservedTokenLoopError

from core.conversation_tools import TOOL_OPTION, ToolCall, ToolRound, encode_tool_round, plain_json, strict_arguments
from core.native_tool_calls import CONTINUATION, build_payload
from core.lmstudio_runtime import model_key_matches


OWNED_PREFIX = 'nc-sdk-'


def _cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise ValueError('LM Studio SDK request cancelled.')


def _host(value):
    if not isinstance(value, str) or not value.strip() or '://' in value or '/' in value:
        raise ValueError('LM Studio SDK host must be host:port, without a URL scheme or path.')
    return value.strip()


def _catalog(client):
    result = []
    for model in client.llm.list_downloaded():
        key = model.model_key
        if not isinstance(key, str) or not key:
            raise ValueError('LM Studio SDK returned an invalid model key.')
        item = dict(id=key)
        for source, target in (('vision', 'supports_images'), ('trained_for_tool_use', 'supports_tools')):
            flag = getattr(model.info, source, None)
            if type(flag) is bool:
                item[target] = flag
        result.append(item)
    return result


def _context_matches(actual, requested):
    # Same normalization as core.runtime.providers._lmstudio_main_chat_profile_matches:
    # LM Studio can round a requested context up to the next 256-token boundary.
    return requested == 0 or actual in (requested, ((requested + 255) // 256) * 256)


def _prepare_model(client, key, context, cancelled):
    if not isinstance(key, str) or not key:
        raise ValueError('Select an LM Studio SDK model first.')
    if type(context) is not int or context < 0:
        raise ValueError('LM Studio SDK context length must be a nonnegative integer.')
    legacy_identifier = OWNED_PREFIX + sha256(key.encode('utf-8')).hexdigest()[:24]
    named, legacy, matching_alias = None, None, None
    for model in client.llm.list_loaded():
        _cancelled(cancelled)
        info = model.get_info()
        if model.identifier in (key, legacy_identifier):
            if not model_key_matches(key,info.model_key):
                raise ValueError('LM Studio SDK model identifier belongs to a different model.')
            if model.identifier == key:
                named = (model, info)
            else:
                legacy = (model, info)
        elif model_key_matches(key,info.model_key) and _context_matches(info.context_length, context):
            matching_alias = model
    _cancelled(cancelled)
    # Reuse a matching loaded instance; renaming an alias does not justify reload.
    for candidate in (named,legacy):
        if candidate is not None and _context_matches(candidate[1].context_length,context):
            return candidate[0]
    if matching_alias is not None:
        return matching_alias
    if legacy is not None:
        client.llm.unload(legacy[0].identifier)
    if named is not None:
        model, info = named
        # Match the original provider: a requested context change replaces the
        # selected real-named instance, without unloading other model instances.
        client.llm.unload(model.identifier)
    load_context = context or (legacy[1].context_length if legacy is not None else 0)
    options = dict(config=dict(contextLength=load_context)) if load_context else {}
    model = client.llm.load_new_instance(key, instance_identifier=key, **options)
    _cancelled(cancelled)
    info = model.get_info()
    if not model_key_matches(key,info.model_key) or not _context_matches(info.context_length, context):
        raise ValueError('LM Studio SDK loaded model does not match the requested model/context.')
    return model


def _model_lifecycle(request, cancelled):
    # Reuse the original provider's inspection/loading primitives. SDK 1.5's
    # typed loader cannot express the original parallel-prediction setting.
    from dataclasses import asdict
    from core import lmstudio_runtime
    operation = request.get('lifecycle_operation')
    endpoint = 'http://' + _host(request.get('host'))
    key, context = request.get('model'), request.get('context_length',0)
    if operation not in {'inspect','load','unload_one','unload'} or type(context) is not int or context < 0:
        raise ValueError('Invalid SDK model-management request.')
    _cancelled(cancelled)
    if operation == 'inspect':
        result = [asdict(item) for item in lmstudio_runtime.list_loaded_model_instances(
            base_url=endpoint,prefer_native_api=True)]
    elif operation == 'load':
        if not isinstance(key,str) or not key:
            raise ValueError('Select an LM Studio SDK model first.')
        result = lmstudio_runtime.load_model(key,base_url=endpoint,
            load_config=lmstudio_runtime.main_chat_load_config(context or None),
            parallel_predictions=lmstudio_runtime.DEFAULT_PARALLEL_PREDICTIONS,
            preserve_existing_models=True,ttl_seconds=None)
    elif operation == 'unload_one':
        identifier = request.get('identifier')
        if not isinstance(identifier,str) or not identifier.strip():
            raise ValueError('An exact model identifier is required.')
        result = lmstudio_runtime.unload_model(identifier,base_url=endpoint)
    else:
        result = lmstudio_runtime.unload_models(base_url=endpoint)
    _cancelled(cancelled)
    return result


def _identity(host, model):
    info = model.get_info()
    reference = getattr(info, 'instance_reference', None)
    if not isinstance(reference, str) or not reference:
        raise ValueError('LM Studio SDK cannot identify this loaded model instance.')
    return json.dumps([host, info.model_key, model.identifier, reference, info.context_length],
                      separators=(',', ':'), ensure_ascii=False)


def _image(client, value):
    if not isinstance(value, dict):
        raise ValueError('LM Studio SDK image_url must contain a data URL.')
    url = value.get('url')
    if not isinstance(url, str) or not url.startswith('data:image/') or ';base64,' not in url:
        raise ValueError('LM Studio SDK images require a base64 image data URL.')
    header, encoded = url.split(';base64,', 1)
    data = base64.b64decode(encoded, validate=True)
    extension = header.split('/', 1)[1]
    return client.prepare_image(data, name='nc-image.' + extension)


def _history(client, messages, *, plain_text=False):
    from lmstudio import Chat, ChatHistoryData

    if not isinstance(messages, list):
        raise ValueError('LM Studio SDK requires prepared message history.')
    result = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError('Invalid LM Studio SDK message.')
        role = message.get('role')
        if role == 'developer':
            role = 'system'
        if role not in {'user', 'system', 'assistant', 'tool'}:
            raise ValueError('Unsupported LM Studio SDK message role.')
        content = message.get('content')
        if plain_text and (not isinstance(content, str) or message.get('tool_calls') or role == 'tool'):
            raise ValueError('Exact SDK prompt counting supports plain text messages only.')
        parts = []
        if isinstance(content, str):
            parts.append(dict(type='text', text=content))
        elif isinstance(content, list) and role == 'user':
            for part in content:
                if not isinstance(part, dict):
                    raise ValueError('Invalid LM Studio SDK message content.')
                if part.get('type') == 'text' and isinstance(part.get('text'), str):
                    parts.append(dict(type='text', text=part['text']))
                elif part.get('type') == 'image_url':
                    parts.append(_image(client, part.get('image_url')))
                else:
                    raise ValueError('Unsupported LM Studio SDK message content.')
        elif content is not None:
            raise ValueError('Unsupported LM Studio SDK message content.')
        if role == 'tool':
            identity = message.get('tool_call_id')
            if not isinstance(identity, str) or not identity or not isinstance(content, str):
                raise ValueError('Invalid LM Studio SDK tool result identity/content.')
            parts = [dict(type='toolCallResult', toolCallId=identity, content=content)]
        if message.get('reasoning_content'):
            raise ValueError('LM Studio SDK cannot preserve this reasoning continuation.')
        calls = message.get('tool_calls') or []
        if calls and (role != 'assistant' or not isinstance(calls, list)):
            raise ValueError('Invalid LM Studio SDK tool call history.')
        seen = set()
        if calls and not parts:
            parts.append(dict(type='text', text=''))
        for item in calls:
            if not isinstance(item, dict) or item.get('type') != 'function' or not isinstance(item.get('function'), dict):
                raise ValueError('Invalid LM Studio SDK tool call history.')
            identity, function = item.get('id'), item['function']
            name = function.get('name')
            if not isinstance(identity, str) or not identity or identity in seen or not isinstance(name, str) or not name:
                raise ValueError('Invalid LM Studio SDK tool call identity.')
            seen.add(identity)
            parts.append(dict(type='toolCallRequest', toolCallRequest=dict(type='function',
                id=identity, name=name, arguments=strict_arguments(function.get('arguments')))))
        result.append(dict(role=role, content=parts))
    # Match the original provider's template compatibility: one leading system
    # message, including context NC appended later in the prepared history.
    systems = [message for message in result if message['role'] == 'system']
    if systems:
        text = '\n\n'.join(part['text'] for message in systems for part in message['content'])
        result = [dict(role='system', content=[dict(type='text', text=text)]),
                  *(message for message in result if message['role'] != 'system')]
    # The typed path preserves consecutive user/assistant messages, empty turns
    # and native tool parts; the convenience dict parser would merge some turns.
    return Chat.from_history(ChatHistoryData.from_dict(dict(messages=result)))


def _response_format(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('Invalid LM Studio SDK structured response format.')
    kind = value.get('type')
    if kind == 'text':
        return None
    if kind == 'json_object':
        return dict(type='json', jsonSchema=dict(type='object'))
    if kind == 'json_schema':
        schema = value.get('json_schema', {}).get('schema')
        if not isinstance(schema, dict):
            raise ValueError('LM Studio SDK JSON response format requires a schema.')
        return dict(type='json', jsonSchema=schema)
    raise ValueError('Unsupported LM Studio SDK structured response format.')


def _config(params, additional):
    from lmstudio import LlmPredictionConfig

    unsupported = {'reasoning', 'reasoning_effort', 'thinking', 'enable_thinking',
                   'seed', 'frequency_penalty', 'presence_penalty'}
    supplied = unsupported.intersection(params) | unsupported.intersection(additional)
    if supplied:
        raise ValueError('Unsupported LM Studio SDK generation settings: ' + ', '.join(sorted(supplied)))
    values = {}
    for source, target in (('temperature', 'temperature'), ('max_tokens', 'maxTokens'),
                           ('top_p', 'topPSampling'), ('stop', 'stopStrings')):
        if params.get(source) is not None:
            value = params[source]
            if source == 'max_tokens' and value == -1:
                value = False  # NC's no-cap sentinel maps to the SDK's disabled limit.
            if source == 'stop' and isinstance(value, str):
                value = [value]
            values[target] = value
    for source, target in (('top_k', 'topKSampling'), ('repeat_penalty', 'repeatPenalty'),
                           ('min_p', 'minPSampling')):
        if additional.get(source) is not None:
            values[target] = additional[source]
    config = LlmPredictionConfig.from_dict(values)
    tools = params.get('tools')
    if tools:
        raw = dict(type='none') if params.get('tool_choice') == 'none' else dict(type='toolArray', tools=tools)
        # SDK 1.5's dict parser strips root JSON-schema keywords. Its public
        # config struct serializes assigned JSON unchanged. config.raw is not
        # mapped by 1.5's KV serializer, so it cannot carry tool schemas.
        config.raw_tools = plain_json(raw)
        if config.to_dict().get('rawTools') != raw:
            raise ValueError('LM Studio SDK cannot preserve native tool schemas.')
    return config


def _disable_output_limit_on_wire(stream, config):
    if config.to_dict().get('maxTokens') is not False:
        return
    endpoint = getattr(stream, '_endpoint', None)
    wire = getattr(endpoint, 'creation_params', None)
    layers = wire.get('predictionConfigStack', {}).get('layers', []) if isinstance(wire, dict) else []
    found = []
    for layer in layers:
        for field in layer.get('config', {}).get('fields', []):
            if field.get('key') == 'llm.prediction.maxPredictedTokens':
                found.append(field)
    if len(found) != 1:
        raise ValueError('Unsupported SDK unlimited-output serialization: expected one output-limit field.')
    field = found[0]
    value = field.get('value')
    if isinstance(value, dict) and value.get('checked') is True and value.get('value') is False:
        # SDK 1.5 CheckboxField incorrectly encodes False as checked=True/value=False.
        # Fix this request only, before start(): unchecked still needs the schema's
        # minimum numeric value. This placeholder is inactive, not a one-token cap.
        field['value'] = dict(checked=False, value=1)
    elif not (isinstance(value, dict) and value.get('checked') is False
              and type(value.get('value')) in (int,float) and value['value'] >= 1):
        raise ValueError('Unsupported SDK unlimited-output serialization; refusing an enabled or invalid limit.')


def _frame(kind, value):
    return json.dumps(dict(version=1, type=kind, value=value), ensure_ascii=False, allow_nan=False)


def _generate(client, model, request, cancelled, diagnostic=None):
    from lmstudio.json_api import PredictionFragmentEvent, PredictionToolCallEvent, PredictionToolCallAbortedEvent
    from lmstudio.sync_api import PredictionStream

    params = plain_json(request.get('params') or {})
    additional = plain_json(request.get('additional_params') or {})
    enabled = request.get('thinking_enabled')
    if enabled is not None and (type(enabled) is not bool or not reasoning.supports_toggle(
            request.get('reasoning_metadata'), request.get('model'))):
        raise ValueError('LM Studio SDK thinking override requires verified on/off model support.')
    native = TOOL_OPTION in additional
    if native:
        params = build_payload(params, additional[TOOL_OPTION], 'chat_completions')
    history = _history(client, params.get('messages'))
    config = _config(params, additional)
    stream = model.respond_stream(history, config=config,
                                  response_format=_response_format(params.get('response_format')))
    if not isinstance(stream, PredictionStream) or not callable(getattr(stream, '_iter_events', None)):
        message = 'Unsupported LM Studio SDK prediction stream; native event bridge requires the checked sync SDK API.'
        close = getattr(stream, 'close', None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                raise ValueError(message + ' Stream cleanup failed: ' + str(exc)) from exc
        raise ValueError(message)
    text, calls = [], []
    output_guard = ReservedTokenGuard()
    emit = request['_emit']
    try:
        _disable_output_limit_on_wire(stream, config)
        thinking = reasoning.ThinkingAdapter(stream, enabled) if enabled is not None else None
    except Exception:
        stream.close()
        raise
    request_id = request.get('_diagnostic_id') or uuid4().hex
    sent = {}
    if diagnostic is not None:
        try:
            from importlib.metadata import version
            info = model.get_info()
            sent = diagnostics.sent_settings(stream)
            diagnostics.report(diagnostic, dict(phase='request', id=request_id,
                sdk_version=version('lmstudio'), model=info.model_key, instance=model.identifier,
                context_requested=request.get('context_length', 0), context_allocated=info.context_length,
                sent=sent))
        except Exception:
            diagnostics.report(diagnostic, dict(phase='unavailable', id=request_id))
    started = time.monotonic()
    with (thinking or nullcontext()), stream:
        for event in stream._iter_events():
            if cancelled is not None and cancelled():
                stream.cancel()
                raise ValueError('LM Studio SDK request cancelled.')
            if isinstance(event, PredictionFragmentEvent):
                fragment = event.arg
                if fragment.reasoning_type != 'none':
                    continue
                try:
                    content = output_guard.feed(fragment.content)
                except ReservedTokenLoopError:
                    stream.cancel()
                    raise
                text.append(content)
                if request.get('stream') and content:
                    emit(_frame('text', content) if native else content)
            elif isinstance(event, PredictionToolCallEvent):
                value = event.arg
                if not native:
                    raise ValueError('LM Studio SDK returned an unrequested tool call.')
                if not params.get('tools') or params.get('tool_choice') == 'none':
                    raise ValueError('LM Studio SDK returned a tool call while tools were disabled for the final answer.')
                if (value.type != 'function' or not isinstance(value.id, str) or not value.id or
                        value.id in {item.call_id for item in calls} or not isinstance(value.name, str) or not value.name):
                    raise ValueError('Invalid LM Studio SDK tool call identity.')
                if not isinstance(value.arguments, Mapping):
                    raise ValueError('LM Studio SDK tool arguments must be an object.')
                arguments = json.dumps(plain_json(value.arguments), ensure_ascii=False, allow_nan=False)
                calls.append(ToolCall(value.id, value.name, arguments))
            elif isinstance(event, PredictionToolCallAbortedEvent):
                raise ValueError('LM Studio SDK tool call generation failed.')
        _cancelled(cancelled)
        tail = output_guard.finish()
        if tail:
            text.append(tail)
            if request.get('stream'):
                emit(_frame('text', tail) if native else tail)
        result = stream.result()
        if diagnostic is not None:
            try:
                event = diagnostics.result_event(request_id, sent, result, time.monotonic() - started,
                                                  thinking_reported=thinking.reported if thinking else None)
            except Exception:
                event = dict(phase='unavailable', id=request_id)
            diagnostics.report(diagnostic, event)
        if thinking is not None:
            thinking.verify()
        reason = result.stats.stop_reason
        answer = ''.join(text)
        if not native and reason in {'maxPredictedTokensReached', 'contextLengthReached'}:
            if not answer.strip():
                raise ValueError('LM Studio SDK stopped with no visible answer: ' + str(reason))
        elif reason not in {'eosFound', 'stopStringFound', 'toolCalls'}:
            raise ValueError('Incomplete LM Studio SDK generation: ' + str(reason))
        if reason == 'toolCalls' and not calls:
            raise ValueError('LM Studio SDK reported toolCalls without complete native calls.')
    if not native:
        return answer
    continuation = ()
    if calls:
        # Match the SDK's own assistant-history content, including reasoning
        # delimiters. Only this private continuation carries the raw text;
        # displayed/spoken text and deltas use the filtered answer above.
        continuation = (dict(type=CONTINUATION, protocol='chat_completions', payload=dict(content=result.content,
            tool_calls=[dict(id=item.call_id, type='function', function=dict(name=item.name, arguments=item.arguments))
                        for item in calls])),)
    encoded = encode_tool_round(ToolRound(answer, tuple(calls), continuation))
    if request.get('stream'):
        emit(_frame('round', encoded))
    return encoded


def handle_request(request, emit, *, sdk=None, cancelled=None, diagnostic=None, reasoning_reader=None):
    """Handle one JSON request using a dedicated SDK client lifetime."""
    if not isinstance(request, dict):
        raise ValueError('LM Studio SDK request must be an object.')
    host = _host(request.get('host'))
    action = request.get('action')
    if action not in {'models', 'check', 'generate', 'capabilities', 'count', 'cleanup', 'lifecycle'}:
        raise ValueError('Unknown LM Studio SDK action: ' + str(action))
    _cancelled(cancelled)
    if action == 'lifecycle':
        return _model_lifecycle(request,cancelled)
    if action == 'models':
        try:
            rows = (reasoning_reader or reasoning.fetch_catalog)(host)
            if not isinstance(rows, Mapping) or any(not isinstance(key, str) or not isinstance(row, Mapping)
                                                    for key, row in rows.items()):
                raise ValueError('Invalid native model catalog.')
            return sorted([dict(row, id=key) for key, row in rows.items()], key=lambda row: row['id'].lower())
        except Exception:
            # Older servers may lack native metadata. Keep their SDK catalog usable.
            _cancelled(cancelled)
    if sdk is None:
        import lmstudio as sdk
        sdk.set_sync_api_timeout(None)
    with sdk.Client(host) as client:
        if action == 'models':
            return _catalog(client)
        if action == 'check':
            return dict(connected=True, models=len(client.llm.list_downloaded()))
        if action == 'cleanup':
            unloaded = []
            for model in client.llm.list_loaded():
                if model.identifier.startswith(OWNED_PREFIX):
                    client.llm.unload(model.identifier)
                    unloaded.append(model.identifier)
            return dict(unloaded=unloaded)
        model = _prepare_model(client, request.get('model'), request.get('context_length', 0), cancelled)
        if action == 'generate':
            return _generate(client, model, dict(request, _emit=emit), cancelled, diagnostic)
        identity = _identity(host, model)
        if action == 'capabilities':
            return dict(context_limit=model.get_info().context_length, instance_identity=identity)
        expected = request.get('expected_instance')
        if expected is not None and identity != expected:
            raise ValueError('LM Studio SDK model instance changed before exact prompt counting.')
        history = _history(client, (request.get('params') or {}).get('messages'), plain_text=True)
        prompt = model.apply_prompt_template(history)
        count = model.count_tokens(prompt)
        if _identity(host, model) != identity:
            raise ValueError('LM Studio SDK model instance changed during exact prompt counting.')
        _cancelled(cancelled)
        if type(count) is not int or count < 0:
            raise ValueError('LM Studio SDK returned an invalid token count.')
        return dict(count=count, instance_identity=identity)
