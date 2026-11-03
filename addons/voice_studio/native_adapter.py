"""Typed native adapter; all feature controls and state remain addon-local."""
from __future__ import annotations

from PySide6 import QtCore
from ui.qml_bridge.native_registry import NativeSurfaceAdapter
from ui.qml_bridge.native_contracts import NativeSurface, NativeControl, NativeControlKind
from .native_controller import ACTION_NAMES


class VoiceStudioNativeAdapter(NativeSurfaceAdapter):
    def __init__(self, application):
        super().__init__('voice_studio_tab', 'nc.voice_studio')
        self.application = application
        self._revision = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _invoke(self, capability, payload=None):
        result = self.application.addons.invoke_addon_capability(self.addon_id, capability, payload or {})
        if not result.accepted or (capability == 'voice_studio.snapshot' and not isinstance(result.value, dict)):
            raise RuntimeError('Voice Studio is unavailable. Enable the addon first.')
        return result.value

    @QtCore.Slot()
    def _poll(self):
        # snapshot is in-memory only; blocking work belongs to the registry runner.
        try:
            if self._invoke('voice_studio.snapshot').get('busy'):
                self.changed.emit()
        except RuntimeError:
            pass

    def snapshot(self):
        try:
            state = self._invoke('voice_studio.snapshot')
        except RuntimeError as error:
            state = {'status': str(error), 'closed': True, 'busy': False}
        controls = [NativeControl('voice_studio_state', 'Voice Studio state', NativeControlKind.DISPLAY,
                                  section='Create Voices', value=state, metadata={'presentationHidden': True})]
        for action in ACTION_NAMES:
            section = ('Voice Library' if action in {'refresh', 'play_original', 'test', 'play_test', 'export_test', 'refine_test', 'save_voice_details', 'remove_voice', 'restore_voice'}
                       else 'Settings' if action in {'check_cloud', 'check_local', 'save_settings', 'cleanup', 'discard_cloud'}
                       else 'Create Voices')
            controls.append(NativeControl('vs_' + action, action.replace('_', ' ').title(), NativeControlKind.ACTION,
                section=section, enabled=not state.get('closed', False), metadata={'execution': 'ui'} if action in {'stop', 'pause'} else {}))
        return NativeSurface(self.surface_id, 'Voice Studio', self.addon_id,
                             ('Create Voices', 'Voice Library', 'Settings'), tuple(controls), revision=self._revision)

    def set_value(self, control_id, value):
        self._invoke('voice_studio.set', {'key': control_id.removeprefix('vs_'), 'value': value})
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id):
        self.trigger_with_payload(control_id, {})

    def trigger_with_payload(self, control_id, payload):
        self._invoke('voice_studio.action', {'action': control_id.removeprefix('vs_'), 'payload': payload or {}})
        self._revision += 1
        self.changed.emit()


def build_voice_studio_adapter(application):
    return VoiceStudioNativeAdapter(application)
