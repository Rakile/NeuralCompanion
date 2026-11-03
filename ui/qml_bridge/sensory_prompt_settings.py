"""Editable sensory prompt projection; no capture, inference or scheduling work."""
from collections.abc import Mapping
import json

from PySide6 import QtCore

from core.sensory import DEFAULT_SENSORY_PINGPONG_PROMPT, get_registry, resolve_pingpong_prompt
from core.runtime.sensory_context_templates import CONTEXT_TEMPLATE_FIELDS
from core.runtime.sensory_policy import SensoryPolicy, SensoryPromptInputs
from ui.qml_bridge.native_session import _plain


_SOURCE_FIELDS = (
    ('guidance', 'How NC reads this source', 'Source guidance appended to the shared review contract.'),
    ('instruction', 'How NC reads it', 'Source context instruction included in hidden review.'),
    ('description', 'What this source provides', 'The source description. Descriptive metadata does not change capture capabilities.'),
    ('snapshot_prompt', 'Snapshot text prefix', 'Override the source-provided capture framing. Tokens: __SOURCE__, __CAPTURED_AT__. An empty saved override removes the prefix.'),
    ('ping_payload', 'What gets reviewed', 'Editable JSON list describing the PING payload; this does not change the actual captured data.'),
    ('pong_influences', 'What review can do', 'Editable JSON list describing PONG outputs. Runtime action permissions still apply.'),
    ('tag_subscriptions', 'Matching tags', 'Editable JSON list of declared tag subscriptions.'),
)
_JSON_FIELDS = {'ping_payload', 'pong_influences', 'tag_subscriptions'}
_CONTEXT_DEFAULTS = {field['key']: field['default'] for field in CONTEXT_TEMPLATE_FIELDS}


class SensoryPromptSettingsController(QtCore.QObject):
    changed = QtCore.Signal()
    errorChanged = QtCore.Signal()
    sourceChanged = QtCore.Signal()
    previewChanged = QtCore.Signal()
    saved = QtCore.Signal()
    notificationRaised = QtCore.Signal(str, str, str)

    def __init__(self, application, *, persist, registry=None, parent=None):
        super().__init__(parent)
        self._application = application
        self._persist = persist
        self._registry = registry if registry is not None else get_registry()
        self._policy = SensoryPolicy(self._registry)
        self._source = 'off'
        self._values = {}
        self._error = ''
        self._preview = ''
        self.refresh()

    @QtCore.Property('QVariantList', constant=True)
    def generalFields(self):
        return [{'key': 'core', 'label': 'Shared ping/pong prompt', 'height': 320,
                 'description': 'Complete core JSON contract. __EMOTION_LIST__ is replaced with available avatar emotions at runtime.'}]

    @QtCore.Property('QVariantList', constant=True)
    def contextFields(self):
        return [{**field, 'key': 'context/' + field['key'], 'height': 160}
                for field in CONTEXT_TEMPLATE_FIELDS]

    @QtCore.Property('QVariantList', notify=sourceChanged)
    def sourceFields(self):
        if self._registry.get_provider(self._source) is None:
            return []
        return [{'key': f'source/{self._source}/{key}', 'label': label,
                 'description': description, 'height': 210 if key in _JSON_FIELDS else 160}
                for key, label, description in _SOURCE_FIELDS]

    @QtCore.Property(str, notify=sourceChanged)
    def sourceLabel(self):
        provider = self._registry.get_provider(self._source)
        return str(provider.label) if provider is not None else 'No source selected'

    @QtCore.Property('QVariantMap', notify=changed)
    def values(self):
        return dict(self._values)

    @QtCore.Property(str, notify=errorChanged)
    def error(self):
        return self._error

    @QtCore.Property(str, notify=previewChanged)
    def preview(self):
        return self._preview

    @QtCore.Property(str, constant=True)
    def previewNotice(self):
        return ('Configured text assembly, not a captured request. Uses enabled sources and marked sample payloads; '
                'live images, observations, conversation history and avatar emotions are supplied at runtime. '
                'No camera capture or model request is performed. Conditional framing is editable above.')

    @QtCore.Slot(str)
    def viewSource(self, source):
        source = str(source or 'off')
        if source == self._source:
            return
        self._source = source
        self.refresh()
        self.sourceChanged.emit()

    def _field_value(self, key, config):
        if key == 'core':
            return resolve_pingpong_prompt(config.get('sensory_pingpong_prompt'))
        if key.startswith('context/'):
            name = key.split('/', 1)[1]
            from core.runtime.sensory_context_templates import context_text
            return context_text(config, name)
        _, source, field = key.split('/', 2)
        effective = self._policy.effective_provider(source, config)
        metadata = effective.get('metadata', {})
        if field == 'guidance':
            return str(metadata.get('pingpong_prompt', ''))
        if field in {'instruction', 'description'}:
            return str(effective.get(field, ''))
        if field == 'snapshot_prompt':
            return str(metadata.get(field, ''))
        return json.dumps(_plain(metadata.get(field, [])), indent=2, ensure_ascii=False)

    @QtCore.Slot()
    def refresh(self):
        config = self._application.config.snapshot().values
        fields = self.generalFields + self.contextFields + self.sourceFields
        # Old delegates finish editing during sourceChanged teardown. Keep their
        # keyed values valid until then; a source switch must never blank a draft.
        keys = set(self._values) | {field['key'] for field in fields}
        values = {key: self._field_value(key, config) for key in keys}
        if values != self._values:
            self._values = values
            self.changed.emit()
        self.refreshPreview()

    def _failure(self, text):
        self._error = text
        self.errorChanged.emit()
        self.notificationRaised.emit('error', 'Sensory prompt was not saved', text)

    def _change(self, key, value=None, *, restore=False):
        config = _plain(self._application.config.snapshot().values)
        if key == 'core':
            return 'sensory_pingpong_prompt', DEFAULT_SENSORY_PINGPONG_PROMPT if restore else str(value)
        if key.startswith('context/'):
            name = key.split('/', 1)[1]
            if name not in _CONTEXT_DEFAULTS:
                raise ValueError('Unknown context template.')
            overrides = dict(config.get('sensory_context_templates', {}))
            if restore:
                overrides.pop(name, None)
            else:
                overrides[name] = str(value)
            return 'sensory_context_templates', overrides
        parts = key.split('/', 2)
        if len(parts) != 3 or parts[0] != 'source':
            raise ValueError('Unknown sensory prompt field.')
        _, source, field = parts
        if self._registry.get_provider(source) is None or field not in {row[0] for row in _SOURCE_FIELDS}:
            raise ValueError('The sensory source or field is unavailable.')
        if field == 'guidance':
            prompts = dict(config.get('sensory_pingpong_source_prompts', {}))
            if restore:
                prompts.pop(source, None)
                legacy = config.get('sensory_provider_metadata_overrides', {}).get(source, {}).get('metadata', {})
                if 'pingpong_prompt' in legacy:
                    # Canonical guidance takes precedence over legacy metadata.
                    # Restore the recommendation without rewriting other fields.
                    provider = self._registry.get_provider(source)
                    prompts[source] = str(provider.metadata.get('pingpong_prompt') or '')
            else:
                prompts[source] = str(value)
            return 'sensory_pingpong_source_prompts', prompts
        overrides = dict(config.get('sensory_provider_metadata_overrides', {}))
        provider = dict(overrides.get(source, {}))
        metadata = dict(provider.get('metadata', {}))
        target = provider if field in {'instruction', 'description'} else metadata
        if restore:
            target.pop(field, None)
        else:
            parsed = json.loads(str(value)) if field in _JSON_FIELDS else str(value)
            if field in _JSON_FIELDS and not isinstance(parsed, list):
                raise ValueError('This field requires a JSON list, for example [].')
            target[field] = parsed
        if metadata:
            provider['metadata'] = metadata
        else:
            provider.pop('metadata', None)
        if provider:
            overrides[source] = provider
        else:
            overrides.pop(source, None)
        return 'sensory_provider_metadata_overrides', overrides

    def _commit(self, key, value=None, *, restore=False):
        try:
            config_key, updated = self._change(key, value, restore=restore)
            current = self._application.config.get(config_key)
            if _plain(current) == updated:
                return
            result = self._application.config.update(config_key, updated)
            if not result.accepted:
                raise ValueError(str(getattr(result.failure, 'message', 'The settings update was rejected.')))
            if self._persist() is False:
                raise OSError('The runtime value changed, but session persistence is unavailable.')
        except (ValueError, TypeError, OSError) as error:
            self._failure(str(error))
            return
        self._error = ''
        self.errorChanged.emit()
        self.refresh()
        self.saved.emit()

    @QtCore.Slot(str, 'QVariant')
    def setField(self, key, value):
        # A focus-only visit must not manufacture overrides for displayed defaults.
        key = str(key)
        config = self._application.config.snapshot().values
        try:
            if str(value) == self._field_value(key, config):
                return
        except (ValueError, KeyError):
            self._failure('Unknown sensory prompt field.')
            return
        self._commit(key, value)

    @QtCore.Slot(str)
    def restoreField(self, key):
        self._commit(str(key), restore=True)

    @QtCore.Slot()
    def refreshPreview(self):
        config = self._application.config.snapshot()
        sources = self._policy.selected_sources(config)
        if not sources:
            preview = 'No sensory sources are enabled. The shared prompt and conditional templates remain editable above.'
        else:
            snapshots = []
            for source in sources:
                provider = self._policy.effective_provider(source, config)
                declared = str(provider.get('metadata', {}).get('snapshot_prompt') or '')
                snapshots.append({'source': source, 'captured_at': 0,
                                  'content_text': declared or f'[Live {source} capture payload is supplied at runtime.]'})
            messages = self._policy.build_messages(SensoryPromptInputs(
                snapshots=tuple(snapshots), config=config,
                available_emotions=('__EMOTION_LIST__',), allow_images=False))
            preview = '\n\n'.join(f'[{message.role}]\n{message.content}' for message in messages)
        if preview != self._preview:
            self._preview = preview
            self.previewChanged.emit()
