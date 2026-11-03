"""Persona UI adapter: snapshots and command enqueueing only."""
from PySide6 import QtCore
from core import chat_providers
from core.native_tool_calls import provider_protocol


class ChatMcpNativeAdapter(QtCore.QObject):
    stateChanged=QtCore.Signal()

    def __init__(self,application,parent=None):
        super().__init__(parent)
        self.application=application
        self._state={}
        self._timer=QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._poll()

    def _invoke(self,capability,payload):
        response=self.application.addons.invoke_addon_capability('nc.chat_mcp_tools',capability,payload)
        return response.value if response.accepted else None

    @QtCore.Slot()
    def _poll(self):
        try: value=self._invoke('chat_mcp.snapshot',{}) or {}
        except (RuntimeError,AttributeError): value={}
        value=dict(value)
        try: provider=str(self.application.config.get('chat_provider',''))
        except (RuntimeError,AttributeError): provider=''
        registered=chat_providers.get_provider(provider)
        value.update(provider=provider,provider_supported=bool(registered and registered.normal_chat_available and provider_protocol(registered)))
        if value!=self._state:
            self._state=value; self.stateChanged.emit()

    @QtCore.Property('QVariantMap',notify=stateChanged)
    def state(self): return self._state

    @QtCore.Slot(str,'QVariantMap',result=bool)
    def command(self,action,fields):
        try:
            value=self._invoke('chat_mcp.command',dict(fields,action=action))
            return bool(value and value.get('accepted'))
        except (RuntimeError,AttributeError,ValueError): return False
