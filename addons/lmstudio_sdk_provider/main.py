"""Independent SDK-backed provider using NC's existing frozen chat contracts."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import json
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from core import chat_providers, lmstudio_runtime
from core.addons.base import BaseAddon
from core.conversation_tools import TOOL_OPTION, decode_tool_round
from addons.lmstudio_sdk_provider.process import SDKProcessRunner, cancelled, _yield_ui
from addons.lmstudio_sdk_provider import reasoning


PROVIDER_ID = 'lmstudio_sdk'
DEFAULT_BASE_URL = 'http://127.0.0.1:1234'
THINKING_OPTION = '_nc_sdk_thinking'


def sdk_host(value):
    value = str(value or DEFAULT_BASE_URL).strip()
    parsed = urlsplit(value if '://' in value else 'http://' + value)
    if (parsed.scheme != 'http' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path.rstrip('/') not in ('', '/v1') or any(c.isspace() for c in value)):
        raise ValueError('Use an SDK server host:port or http://host:port, without credentials, query or custom path.')
    host = parsed.hostname
    if ':' in host:
        host = '[' + host + ']'
    return f'{host}:{parsed.port or 1234}'


def context_length(value):
    number = int(value or 0)
    if number != 0 and lmstudio_runtime.configured_chat_context_length(number) is None:
        raise ValueError('SDK context length must be zero (current/NC default) or from 512 to 1048576 tokens.')
    return number


def generation_fields():
    fields = []
    for key, label, minimum, maximum, default in (
        ('temperature', 'Temperature', 0.0, 2.0, 0.7),
        ('top_p', 'Top P', 0.0, 1.0, 0.9),
        ('repeat_penalty', 'Repetition Penalty', 0.0, 3.0, 1.0),
        ('min_p', 'Min P', 0.0, 1.0, 0.0),
    ):
        fields.append(dict(id=key,label=label,kind='float',min=minimum,max=maximum,step=.01,
                           decimals=2,default=default,request_location='params' if key in ('temperature','top_p') else 'additional_params'))
    fields.append(dict(id='top_k',label='Top K',kind='int',min=-1,max=100000,step=1,default=40,request_location='additional_params'))
    fields.append(dict(id='max_tokens',label='Max Tokens (-1 = no cap)',kind='int',min=-1,max=131072,step=1,default=-1,request_location='params'))
    fields.append(dict(id='reasoning',label='Enable Thinking',kind='bool',default=False,
                       request_location='none',requires_model_support='reasoning_toggle',
                       description='Shown when LM Studio reports both off and on thinking support. Applies to new replies.'))
    return fields


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._chat_service = context.capabilities.providers
        self._runner = SDKProcessRunner()
        self._execution_lock = threading.RLock()
        self._reasoning_catalog = ('', {})
        if self._chat_service is None:
            context.logger.warning('LM Studio SDK provider requires the chat provider registry service.')
            return
        self._chat_service.register_provider(
            provider_id=PROVIDER_ID, label='LM Studio', order=100,
            description='Default LM Studio chat provider using the Python SDK.',
            client_factory=self._client, model_list_handler=self._list_models,
            completion_handler=self._complete_chat, stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection, api_key_getter=lambda: '',
            base_url_getter=self._base_url, frozen_execution_version=1,
            frozen_private_config_getter=self._frozen_config,
            frozen_public_config_fields=('base_url','context_length','provider_is_remote','reasoning_metadata'),
            frozen_prepare_handler=self._prepare, frozen_completion_handler=self._complete,
            frozen_stream_handler=self._stream, model_capabilities_handler=self._capabilities,
            frozen_model_lifecycle_handler=self._model_lifecycle,
            metadata={
                'legacy_generation_fallback':False,
                'auto_refresh_model_catalog_on_view':True,
                'native_tool_protocol_v1':'chat_completions', 'native_tool_streaming_v1':True,
                'supports_frozen_output_token_budget_override':True,
                'config_fields':[
                    dict(id='base_url',label='SDK server address',source='addon',default=DEFAULT_BASE_URL),
                    dict(id='context_length',label='Context Length (0 = current/NC default)',kind='int',
                         section='model_load',min=0,max=1048576,step=512,default=0,
                         description='Zero keeps a loaded model’s context, or uses the original NC load-profile default. Matching loaded models are reused; incompatible load configurations are reloaded.'),
                ],
                'generation_fields':generation_fields(),
                'hint':'Use the SDK server in LM Studio and select a model. The list refreshes automatically when opening these settings; Refresh also updates it manually. Requests use the Python SDK.',
            })
        context.logger.info('LM Studio SDK chat provider initialized.')

    def _setting(self, key):
        return self._chat_service.get_provider_setting(PROVIDER_ID, key)

    def _base_url(self):
        return str(self._setting('base_url') or DEFAULT_BASE_URL).strip()

    def _private_config(self):
        base_url = self._base_url()
        host = sdk_host(base_url)
        return dict(base_url=base_url, context_length=context_length(self._setting('context_length')),
                    provider_is_remote=urlsplit('http://' + host).hostname not in ('localhost','127.0.0.1','::1'))

    def _frozen_config(self):
        config = self._private_config()
        model = str(self._setting('model_name') or '').strip()
        host = sdk_host(config['base_url'])
        cached_host, catalog = self._reasoning_catalog
        if cached_host != host:
            catalog = {}
        row = catalog.get(model, {})
        config['reasoning_metadata'] = dict(model_key=model,
            supports_reasoning=row.get('supports_reasoning') is True,
            reasoning_options=list(row.get('reasoning_options') or []))
        return config

    @staticmethod
    def _prepare(binding, params, additional_params=None):
        generation = binding._generation_fields_copy()
        prepared, extras = dict(params or {}), dict(additional_params or {})
        prepared['model'] = str(binding.model_name or '').strip()
        if not prepared['model']:
            raise ValueError('Select a chat model under LM Studio before sending a message.')
        for key in ('temperature','top_p','max_tokens'):
            if key in generation:
                prepared[key] = generation[key]
        if 'max_tokens' in generation:
            prepared.pop('max_completion_tokens',None)
        for key in ('top_k','repeat_penalty','min_p'):
            if key in generation:
                extras[key] = generation[key]
        extras.pop(THINKING_OPTION, None)
        copy_config = getattr(binding, '_provider_config_copy', None)
        metadata = (copy_config() if callable(copy_config) else {}).get('reasoning_metadata', {})
        if reasoning.supports_toggle(metadata, prepared['model']):
            enabled = generation.get('reasoning', False)
            if type(enabled) is not bool:
                raise ValueError('LM Studio SDK Enable Thinking must be on or off.')
            extras[THINKING_OPTION] = enabled
        budget = extras.pop(chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE,None)
        if budget is not None:
            prepared.pop('max_completion_tokens',None)
            prepared['max_tokens'] = budget
        return prepared, extras

    @staticmethod
    def _request_config(request):
        binding = request.context._binding
        if binding is None:
            raise ValueError('SDK execution requires a captured provider binding.')
        config = binding._provider_config_copy()
        params = request.params_copy()
        extras = request.additional_params_copy()
        return dict(action='generate',host=sdk_host(config.get('base_url')),
                    context_length=context_length(config.get('context_length')),
                    model=params.get('model'),params=params,additional_params=extras,
                    thinking_enabled=extras.pop(THINKING_OPTION, None),
                    reasoning_metadata=config.get('reasoning_metadata', {}))

    def _complete(self, request, *, timeout=None, cancel_token=None):
        with self._serialized(timeout,cancel_token) as remaining:
            return self._runner.call(self._request_config(request),timeout=remaining,cancel_token=cancel_token)

    def _stream(self, request, *, timeout=None, cancel_token=None):
        config = self._request_config(request)
        def chunks():
            with self._serialized(timeout,cancel_token) as remaining:
                yield from self._runner.stream(config,timeout=remaining,cancel_token=cancel_token)
        return chunks()

    @contextmanager
    def _serialized(self, timeout, cancel_token):
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        while True:
            if cancelled(cancel_token):
                raise RuntimeError('LM Studio SDK request cancelled while waiting for the provider.')
            remaining = None if deadline is None else deadline-time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError('LM Studio SDK request deadline expired while waiting for the provider.')
            _yield_ui()
            if self._execution_lock.acquire(timeout=.05 if remaining is None else min(.05,remaining)):
                break
        try:
            yield None if deadline is None else max(0,deadline-time.monotonic())
        finally:
            self._execution_lock.release()

    def _model_lifecycle(self, binding, *, operation, reason='', cancel_token=None,
                         identifier=None, context_length_override=None):
        if operation not in {'inspect','load','unload_one','unload'}:
            raise ValueError('Unsupported SDK model-management operation.')
        config = binding._provider_config_copy()
        context = context_length(config.get('context_length'))
        if context_length_override is not None:
            context = context_length(context_length_override)
        request = dict(action='lifecycle',lifecycle_operation=operation,host=sdk_host(config.get('base_url')),
                       model=str(binding.model_name or '').strip(),context_length=context)
        if identifier is not None:
            request['identifier'] = identifier
        with self._serialized(None,cancel_token):
            result = self._runner.call(request,cancel_token=cancel_token)
            if cancelled(cancel_token):
                raise RuntimeError('LM Studio SDK model preparation cancelled.')
            return result

    def _operation(self, action, **values):
        config = self._private_config()
        return dict(action=action,host=sdk_host(config['base_url']),context_length=config['context_length'],
                    **({'catalog_base_url': config['base_url']} if action == 'models' else {}), **values)

    def _list_models(self, quiet=False):
        # Do not turn discovery failures into a misleading empty successful list.
        return self._refresh_catalog(self._operation('models'))

    def _refresh_catalog(self, operation):
        try:
            rows = self._runner.call(operation)
        except Exception:
            self._reasoning_catalog = ('', {})
            raise
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in rows):
            self._reasoning_catalog = ('', {})
            raise ValueError('LM Studio SDK returned an invalid model catalog.')
        rows = [dict(row, reasoning_base_url=operation['catalog_base_url']) for row in rows]
        self._reasoning_catalog = (operation['host'], {row['id']: dict(row) for row in rows})
        if rows and not any(row.get('reasoning_metadata_available') is True for row in rows):
            print('[LM Studio SDK] Thinking capability metadata unavailable; models retain their default thinking behavior.')
        return rows

    def _check_connection(self):
        try:
            self._runner.call(self._operation('check'))
            return True, 'Connected to the LM Studio Python SDK server.'
        except Exception as exc:
            return False, str(exc)

    def _capabilities(self, binding):
        config = binding._provider_config_copy()
        operation = dict(action='capabilities',host=sdk_host(config.get('base_url')),
                         context_length=context_length(config.get('context_length')),model=binding.model_name)
        with self._execution_lock:
            result = self._runner.call(operation)
        if not isinstance(result,dict) or type(result.get('context_limit')) is not int or result['context_limit'] <= 0:
            return None
        identity = result.get('instance_identity')
        if not isinstance(identity,str) or not identity:
            return None
        def count(messages):
            request = dict(operation,action='count',expected_instance=identity,params={'messages':list(messages)})
            with self._execution_lock:
                counted = self._runner.call(request)
            if counted.get('instance_identity') != identity or type(counted.get('count')) is not int or counted['count'] < 0:
                raise ValueError('SDK tokenizer or loaded model identity changed.')
            return counted['count']
        return dict(context_limit=result['context_limit'],token_counter=count,
                    capability_identity=binding.execution_identity,token_counter_identity=binding.execution_identity)

    def _legacy_operation(self, params, additional_params=None):
        values = dict(params or {})
        return self._operation('generate',model=values.get('model'),params=values,
                               additional_params=dict(additional_params or {}))

    def _complete_chat(self, params, additional_params=None):
        with self._execution_lock:
            return self._runner.call(self._legacy_operation(params,additional_params))

    def _stream_chat(self, params, additional_params=None):
        def chunks():
            with self._execution_lock:
                yield from self._runner.stream(self._legacy_operation(params,additional_params))
        return chunks()

    def _client(self):
        return _SDKClient(self)

    def shutdown(self):
        self._runner.close()
        unregister = getattr(self._chat_service,'unregister_provider',None)
        if callable(unregister):
            unregister(PROVIDER_ID)


class _SDKClient:
    """Legacy client-shaped compatibility through SDK handlers, never HTTP."""
    def __init__(self, addon):
        self.addon = addon
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[SimpleNamespace(**m) for m in addon._list_models()]))

    def create(self, **kwargs):
        params = dict(kwargs)
        streaming = params.pop('stream',False)
        extras = params.pop('extra_body',{}) or {}
        tools = params.pop('tools',None)
        if tools:
            extras[TOOL_OPTION] = dict(tools=[dict(type='function',**t['function']) for t in tools],
                                      input=[],final_only=params.pop('tool_choice','auto')=='none')
        if streaming:
            if tools:
                raise ValueError('Use the registered frozen SDK tool-stream handler for native tools.')
            return (SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text),finish_reason=None)])
                    for text in self.addon._stream_chat(params,extras))
        result = self.addon._complete_chat(params,extras)
        calls = None
        if tools:
            round_ = decode_tool_round(result)
            result = round_.text
            calls = [SimpleNamespace(id=c.call_id,type='function',function=SimpleNamespace(name=c.name,arguments=c.arguments)) for c in round_.calls]
        message = SimpleNamespace(role='assistant',content=result,tool_calls=calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=message,finish_reason='tool_calls' if calls else 'stop')])
