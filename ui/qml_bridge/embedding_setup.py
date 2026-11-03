"""Memory-search setup for provider pages; no chat activation or per-key I/O."""
from concurrent.futures import ThreadPoolExecutor
from PySide6 import QtCore
from core.runtime.embedding_provider import EmbeddingProviderClient, PROVIDERS, provider_id, server_url
from core.runtime.memory_embeddings import _request_json


class EmbeddingSetupController(QtCore.QObject):
    changed = QtCore.Signal()
    settingsSaved = QtCore.Signal()
    _finished = QtCore.Signal(object)

    def __init__(self, application, *, save_settings, client=None, parent=None):
        super().__init__(parent)
        self._application = application
        self._save = save_settings
        self._client = client or EmbeddingProviderClient(request_json=_request_json)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='memory-search-setup')
        self._epoch = 0
        self._closed = False
        self._drafts = {}
        self._state = {}
        self._finished.connect(self._complete)
        self.viewProvider('lmstudio')

    @QtCore.Property('QVariantMap', notify=changed)
    def state(self): return dict(self._state)

    def _config(self): return self._application.config.snapshot().values

    @QtCore.Slot(str)
    def viewProvider(self, provider):
        if self._closed: return
        viewed_provider = str(provider or 'lmstudio').lower()
        # Chat API choice does not create another embedding provider or index.
        provider = 'lmstudio' if viewed_provider == 'lmstudio_sdk' else viewed_provider
        self._epoch += 1
        values = self._config()
        active = str(values.get('long_term_memory_embedding_provider') or 'lmstudio')
        defaults = PROVIDERS.get(provider, {})
        draft = self._drafts.get(provider)
        if draft is None:
            draft = dict(model=defaults.get('model', ''), baseUrl=defaults.get('base_url', ''),
                         contextLength=defaults.get('context_length', 8192))
            if provider == active:
                draft.update(model=str(values.get('long_term_memory_embedding_model') or draft['model']),
                             baseUrl=str(values.get('long_term_memory_embedding_base_url') or draft['baseUrl']),
                             contextLength=int(values.get('long_term_memory_embedding_context_length') or draft['contextLength']))
            else:
                # Reuse a configured connection, without changing its chat model.
                from core.chat_providers import provider_base_url
                configured = provider_base_url(viewed_provider)
                if configured and viewed_provider == 'lmstudio_sdk':
                    configured = configured.strip().rstrip('/')
                    if '://' not in configured:
                        configured = 'http://' + configured
                    if not configured.endswith('/v1'):
                        configured += '/v1'
                if configured: draft['baseUrl'] = configured
            self._drafts[provider] = draft
        self._state = dict(provider=provider, supported=bool(defaults), **draft, models=[], busy=False,
                           feedback='', error='', selected=provider == active,
                           enabled=bool(values.get('long_term_memory_embedding_enabled')))
        self.refreshSelection()

    @QtCore.Slot()
    def refreshSelection(self):
        values = self._config()
        active = str(values.get('long_term_memory_embedding_provider') or 'lmstudio')
        draft = self._drafts.get(self._state.get('provider'), {})
        defaults = PROVIDERS.get(active, PROVIDERS['lmstudio'])
        self._state.update(selected=(self._state.get('provider') == active
            and draft.get('model') == values.get('long_term_memory_embedding_model', defaults['model'])
            and draft.get('baseUrl') == values.get('long_term_memory_embedding_base_url', defaults['base_url'])
            and draft.get('contextLength') == int(values.get('long_term_memory_embedding_context_length') or defaults['context_length'])
            and (active != 'openai' or bool(values.get('long_term_memory_embedding_cloud_consent')))),
            enabled=bool(values.get('long_term_memory_embedding_enabled')))
        self.changed.emit()

    @QtCore.Slot(str, 'QVariant')
    def setDraft(self, key, value):
        if self._closed or key not in {'model', 'baseUrl', 'contextLength'}: return
        try:
            value = max(512, min(262144, int(value))) if key == 'contextLength' else str(value or '').strip()
        except (ValueError, TypeError): return
        if self._state.get(key) == value: return
        self._epoch += 1
        self._drafts[self._state['provider']][key] = value
        self._state.update({key: value, 'feedback': '', 'error': '', 'busy': False})
        self.refreshSelection()

    @QtCore.Slot()
    def activate(self):
        if self._closed or self._state.get('busy'): return
        try:
            provider = provider_id(self._state['provider'])
            model = str(self._state['model']).strip()
            if not model: raise ValueError('Choose an embedding model first.')
            url = server_url(self._state['baseUrl'], provider)
            result = self._application.config.update_many({
                'long_term_memory_embedding_provider': provider,
                'long_term_memory_embedding_model': model,
                'long_term_memory_embedding_base_url': url,
                'long_term_memory_embedding_context_length': self._state['contextLength'],
                'long_term_memory_embedding_cloud_consent': provider == 'openai',
                'long_term_memory_embedding_enabled': True})
            if not result.accepted: raise ValueError('Memory search settings could not be saved.')
            self._drafts[provider]['baseUrl'] = url
            self._state['baseUrl'] = url
            self._save()
            self._state.update(feedback='Selected for memory search. Existing chats may need their search index rebuilt.', error='')
            self.refreshSelection()
            self.settingsSaved.emit()
        except Exception as error:
            self._state['error'] = str(error)
            self.changed.emit()

    @QtCore.Slot(bool)
    def setEnabled(self, enabled):
        if self._closed or self._state.get('busy'): return
        if enabled:
            self.activate()
            return
        try:
            result = self._application.config.update_many({'long_term_memory_embedding_enabled': False})
            if not result.accepted: raise ValueError('Memory search settings could not be saved.')
            self._save()
            self.refreshSelection()
            self.settingsSaved.emit()
        except Exception as error:
            self._state['error'] = str(error)
            self.changed.emit()

    def _work(self, action):
        if self._closed or self._state.get('busy') or not self._state.get('supported'): return
        self._epoch += 1
        epoch, state = self._epoch, dict(self._state)
        self._state.update(busy=True, feedback='', error='')
        self.changed.emit()
        def run():
            try:
                if action == 'models':
                    models = self._client.list_models(state['provider'], state['baseUrl'])
                    payload = {'models': models, 'feedback': f'{len(models)} embedding model(s) found.' if models else 'No embedding models found. See Setup instructions, or enter an installed model name.'}
                else:
                    self._client.embed(state['provider'], state['baseUrl'], state['model'], 'Memory search connection test.')
                    payload = {'feedback': 'Memory search model is ready.'}
            except Exception as error:
                payload = {'error': str(error)}
            if not self._closed: self._finished.emit((epoch, payload))
        self._executor.submit(run)

    @QtCore.Slot()
    def refreshModels(self): self._work('models')

    @QtCore.Slot()
    def testConnection(self): self._work('test')

    @QtCore.Slot(object)
    def _complete(self, event):
        epoch, payload = event
        if not self._closed and epoch == self._epoch:
            self._state.update(busy=False, **payload)
            self.changed.emit()

    def close(self):
        self._closed = True
        self._epoch += 1
        self._executor.shutdown(wait=False, cancel_futures=True)
