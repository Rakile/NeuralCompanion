from dataclasses import asdict

from core.addons import BaseAddon
from core.conversation_tools import ToolCall
from addons.chat_mcp_tools.bridge import ChatMcpBridge


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = ChatMcpBridge(context)

    def invoke_capability(self, capability, payload=None):
        payload = dict(payload or {})
        if capability == 'chat_mcp.snapshot':
            return self.controller.snapshot()
        if capability == 'chat_mcp.command':
            return {'accepted':self.controller.command(**payload)}
        if capability != 'chat_mcp.conversation':
            return None
        operation = payload.get('operation')
        if operation == 'offer':
            return self.controller.offer(persona_id=payload.get('persona_id',''),
                current_persona=payload.get('current_persona'), is_current=payload.get('is_current'),
                scope_server_id=payload.get('scope_server_id'),scope_tool_names=payload.get('scope_tool_names'))
        if operation == 'current':
            return self.controller.current(payload.get('ticket',''))
        if operation == 'execute':
            return asdict(self.controller.execute(payload.get('ticket',''),ToolCall(**payload['call'])))
        if operation == 'publish':
            return self.controller.publish(payload.get('ticket',''),payload.get('publish'))
        return None

    def begin_shutdown(self):
        if hasattr(self,'controller'): self.controller.begin_shutdown()

    def shutdown(self):
        if hasattr(self,'controller'): self.controller.close()
