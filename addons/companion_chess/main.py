from core.addons import BaseAddon
from addons.companion_chess.controller import ChessController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller=ChessController(context)
        context.ui.register_manifest_tab(id='companion_chess_tab',factory=lambda context:None)

    def invoke_capability(self, capability, payload=None):
        if capability=='chess.snapshot': return self.controller.snapshot()
        if capability=='chess.command': return dict(accepted=self.controller.command(**dict(payload or {})))
        return None

    def begin_shutdown(self):
        if hasattr(self,'controller'): self.controller.begin_shutdown()

    def shutdown(self):
        if hasattr(self,'controller'): self.controller.close()
