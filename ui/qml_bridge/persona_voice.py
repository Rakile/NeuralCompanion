"""Persona access to the existing Voice Studio worker and audition pipeline."""
from __future__ import annotations

from typing import Any
import uuid

from PySide6 import QtCore

from ui.qml_bridge.native_registry import NativeSurfaceRegistry


class PersonaVoiceController(QtCore.QObject):
    changed = QtCore.Signal()
    SURFACE = 'voice_studio_tab'
    LIQUID_SURFACE = 'liquidai_tts_tab'
    ACTIONS = frozenset({'refresh', 'play_original', 'test', 'play_test', 'stop',
                         'save_voice_details', 'remove_voice', 'restore_voice'})

    def __init__(self, registry: NativeSurfaceRegistry, parent: QtCore.QObject | None = None, *, backend_getter=None):
        super().__init__(parent)
        self._registry = registry
        self._backend_getter = backend_getter
        self._liquid_pending = False
        self._liquid_error = ''
        self._pending = ''
        self._request_id = ''
        self._error = ''
        registry.surfaceChanged.connect(self._surface_changed)
        registry.actionCompleted.connect(self._completed)

    def _is_liquid(self):
        try:
            return callable(self._backend_getter) and str(self._backend_getter() or '').strip().lower() == 'liquidai'
        except (RuntimeError, TypeError, ValueError):
            return False

    def _liquid_state(self):
        result = dict(provider='liquidai', available=False, busy=self._liquid_pending,
            status='Enable LiquidAI in Addons to select its voices and speech language.',
            voice_options=[], language_options=[], provider_voice='', provider_language='')
        adapter = self._registry.adapter(self.LIQUID_SURFACE)
        if adapter is None:
            return result
        try:
            controls = {control.id: control for control in adapter.snapshot().controls}
            voice = controls['liquidai_tts_voice']
            language = controls['liquidai_tts_language']
            available = bool(dict(getattr(voice, 'metadata', {}) or {}).get('providerAvailable', True))
            result.update(available=available,
                voice_options=[dict(value=str(c.value), label=str(c.label)) for c in voice.choices],
                language_options=[dict(value=str(c.value), label=str(c.label)) for c in language.choices],
                provider_voice=str(voice.value or ''), provider_language=str(language.value or ''),
                busy=bool(self._liquid_pending or not voice.enabled or not language.enabled),
                status=self._liquid_error or ('Refreshing LiquidAI voices…' if self._liquid_pending else
                    'Choose a built-in or installed LiquidAI voice and its speech language.'))
            if not available:
                status = controls.get('liquidai_setup_status')
                result['status'] = str(getattr(status, 'value', '') or result['status'])
        except (RuntimeError, KeyError, TypeError, ValueError, AttributeError) as error:
            result['status'] = self._liquid_error or 'LiquidAI voice catalog is unavailable: ' + str(error)
        return result

    def validate_liquid_selection(self, voice, language):
        if not self._is_liquid():
            raise ValueError('Select LiquidAI as the speech provider before assigning its voices.')
        state = self._liquid_state()
        if not state['available']:
            raise ValueError(state['status'])
        if state['busy']:
            raise ValueError('Wait for the LiquidAI voice catalog to finish updating.')
        result = {}
        for key, value, choices in (('liquidai_tts_voice', voice, state['voice_options']),
                                   ('liquidai_tts_language', language, state['language_options'])):
            if not isinstance(value, str):
                raise ValueError('Choose a listed LiquidAI voice and speech language.')
            value = value.strip()
            if value:
                match = next((row['value'] for row in choices if row['value'].casefold() == value.casefold()), None)
                if match is None:
                    raise ValueError('The saved LiquidAI selection is unavailable. Refresh and choose a listed value.')
                value = match
            result[key] = value
        return result

    def _refresh_liquid(self):
        state = self._liquid_state()
        if not state['available'] or state['busy']:
            return
        self._liquid_error = ''
        self._liquid_pending = True
        try:
            if not self._registry.trigger_async(self.LIQUID_SURFACE, 'liquidai_refresh_voices', {}):
                self._liquid_pending = False
                self._liquid_error = 'LiquidAI voice refresh is already running.'
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self._liquid_pending = False
            self._liquid_error = str(error)
        self.changed.emit()

    @QtCore.Property('QVariantMap', notify=changed)
    def state(self) -> dict[str, Any]:
        if self._is_liquid():
            return self._liquid_state()
        adapter = self._registry.adapter(self.SURFACE)
        try:
            surface = adapter.snapshot() if adapter is not None else None
            state = next((dict(control.value) for control in surface.controls
                          if control.id == 'voice_studio_state'), {}) if surface else {}
        except (RuntimeError, KeyError, TypeError, ValueError):
            state = {}
        available = bool(state) and not state.get('closed', False)
        return {**state, 'available': available,
                'busy': bool(self._pending or state.get('busy')),
                'can_stop': self._pending in {'vs_test', 'vs_play_original', 'vs_play_test'},
                'status': self._error or state.get('status') or 'Enable Voice Studio to browse and preview recordings.'}

    @QtCore.Slot()
    def refreshState(self) -> None:
        """Read in-memory readiness only; a library scan is an explicit worker action."""
        self.changed.emit()

    @QtCore.Slot(str, 'QVariantMap')
    def act(self, action: str, payload: dict[str, Any]) -> None:
        if self._is_liquid():
            if action == 'refresh':
                self._refresh_liquid()
            return
        state = self.state
        if action not in self.ACTIONS or not state['available']:
            return
        if action != 'stop' and state['busy']:
            return
        if action == 'stop' and not state['can_stop']:
            return
        if action == 'test' and not state.get('audition_ready'):
            self._error = 'Load Chatterbox or Chatterbox Multilingual in Runtime → Text-to-speech before generating a test.'
            self.changed.emit()
            return
        self._error = ''
        # Mark pending before dispatch so a double click cannot queue another job.
        if action != 'stop':
            self._pending = 'vs_' + action
            self._request_id = uuid.uuid4().hex
        request = {**dict(payload), 'request_id': self._request_id}
        try:
            if not self._registry.trigger_async(self.SURFACE, 'vs_' + action, request):
                if action != 'stop':
                    self._pending = ''
                self._error = 'This action is already running.'
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            if action != 'stop':
                self._pending = ''
            self._error = str(error)
        self.changed.emit()

    @QtCore.Slot(str)
    def _surface_changed(self, surface: str) -> None:
        if surface in (self.SURFACE, self.LIQUID_SURFACE):
            self.changed.emit()

    @QtCore.Slot(str, str, bool, str)
    def _completed(self, surface: str, action: str, accepted: bool, error: str) -> None:
        if surface == self.LIQUID_SURFACE:
            if action == 'liquidai_refresh_voices':
                self._liquid_pending = False
                self._liquid_error = '' if accepted else str(error)
                self.changed.emit()
            return
        if surface != self.SURFACE:
            return
        if action == self._pending:
            self._pending = ''
            self._request_id = ''
        if not accepted:
            self._error = error
        self.changed.emit()
