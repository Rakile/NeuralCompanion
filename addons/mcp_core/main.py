"""MCP Core lifecycle and finite native-management capabilities."""
from core.addons.base import BaseAddon
from addons.mcp_core.contracts import SERVICE_NAME
from addons.mcp_core.service import McpCoreService


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._service = McpCoreService(context)
        context.services.register_consumer_factory(SERVICE_NAME, self._service.port, {'version': 1})

    def invoke_capability(self, capability, payload=None):
        if capability == 'runtime.mcp_core.snapshot':
            return self._service.snapshot()
        if capability == 'runtime.mcp_core.manage':
            return self._service.manage(dict(payload or {}))
        return None

    def begin_shutdown(self):
        if hasattr(self, '_service'):
            self._service.begin_shutdown()

    def shutdown(self):
        if hasattr(self, '_service'):
            self._service.close()
