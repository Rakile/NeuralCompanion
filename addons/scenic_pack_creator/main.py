"""Separate Scenic creator; the provider keeps runtime ownership."""
from core.addons import BaseAddon
from addons.scenic_pack_creator.controller import ScenicCreatorController

class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = ScenicCreatorController(context)

    def invoke_capability(self, capability, payload=None):
        if capability == 'scenic.creator.snapshot':
            return self.controller.snapshot()
        if capability == 'scenic.creator.command':
            data = dict(payload or {})
            return self.controller.command(str(data.get('action') or ''), data.get('payload'))
        return None

    def shutdown(self):
        if hasattr(self, 'controller'):
            self.controller.close()
