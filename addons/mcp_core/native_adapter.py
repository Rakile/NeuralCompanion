"""Native QML projection. Management enqueues work; polling reads sanitized memory."""
from __future__ import annotations

from PySide6 import QtCore

from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, NativeSurface
from ui.qml_bridge.native_registry import NativeSurfaceAdapter
from .contracts import copy_value


class McpCoreNativeAdapter(NativeSurfaceAdapter):
    stateChanged = QtCore.Signal()
    viewStateChanged = QtCore.Signal()

    def __init__(self, application, parent=None):
        super().__init__('mcp_core_tab', 'nc.mcp_core', parent)
        self.application = application
        self._state = {}
        self._view_state = {}
        self._addon_names = {}
        registry = getattr(application.addons,'registry_snapshot',None)
        if callable(registry):
            response = registry()
            for category in (response.value or ()) if response.accepted else ():
                for addon in category.get('addons',[]):
                    self._addon_names[addon['id']] = addon.get('name') or addon['id']
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def _invoke(self, capability, payload=None):
        response = self.application.addons.invoke_addon_capability(self.addon_id, capability, payload or {})
        if not response.accepted or not isinstance(response.value, dict):
            raise RuntimeError('MCP Core is unavailable. Enable the addon first.')
        return response.value

    @QtCore.Property('QVariantMap', notify=stateChanged)
    def state(self):
        return copy_value(self._state)

    @QtCore.Property('QVariantMap', notify=viewStateChanged)
    def viewState(self):
        return copy_value(self._view_state)

    @QtCore.Slot('QVariantMap')
    def rememberViewState(self, values):
        # UI context lasts for this controller only. Never retain forms/secrets,
        # persist selections, or change connection/permission state here.
        view = {'server_id':str(values.get('server_id') or ''),
                'addon_id':str(values.get('addon_id') or ''),
                'expanded_groups':dict(values.get('expanded_groups') or {}),
                'show_all_tools':bool(values.get('show_all_tools',False))}
        if view != self._view_state:
            self._view_state = copy_value(view)
            self.viewStateChanged.emit()

    @QtCore.Slot()
    def refresh(self):
        try:
            state = dict(self._invoke('runtime.mcp_core.snapshot'), available=True)
            state['addon_names'] = dict(self._addon_names)
        except (RuntimeError, AttributeError):
            state = {'available': False, 'closed': True, 'master': False,
                     'servers': {}, 'addons': {}, 'catalogs': {}, 'grants': {}, 'connections': {},
                     'management_status': 'MCP Core is unavailable. Enable the addon first.'}
        if state != self._state:
            self._state = state
            self.stateChanged.emit()
            self.changed.emit()

    @QtCore.Slot(bool)
    def setActive(self, active):
        if active:
            self.refresh()
            self._timer.start()
        else:
            self._timer.stop()

    @QtCore.Slot('QVariantMap', result=bool)
    def manage(self, payload):
        if not self._state.get('available'):
            return False
        try:
            response = self._invoke('runtime.mcp_core.manage', dict(payload))
        except RuntimeError:
            return False
        self.refresh()
        return bool(response.get('ok'))

    def snapshot(self):
        self.refresh()
        return NativeSurface(self.surface_id, 'MCP Core', self.addon_id, ('MCP Core',), (
            NativeControl('mcp_core_state', 'MCP Core state', NativeControlKind.DISPLAY,
                          section='MCP Core', value=self.state, metadata={'presentationHidden': True}),))

    def set_value(self, control_id, value):
        if control_id != 'master':
            raise KeyError(control_id)
        self.manage({'action': 'master', 'enabled': bool(value)})
