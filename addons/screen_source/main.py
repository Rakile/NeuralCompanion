from __future__ import annotations

from core.addons import BaseAddon
from addons.screen_source.ui_contracts import (
    ScreenSourceCapabilities,
    ScreenSourceInitialization,
)
from addons.screen_source.native_service import (
    Addon as ScreenSourceImplementation,
)


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._implementation = ScreenSourceImplementation()
        self._implementation.initialize(
            ScreenSourceInitialization(
                logger=context.logger,
                ui=context.ui,
                manifest=context.manifest,
                app_root=context.app_root,
                capabilities=ScreenSourceCapabilities(
                    runtime_config=context.capabilities.runtime_config,
                    sensory_targets=context.capabilities.sensory_targets,
                    shell_session=context.capabilities.shell_session,
                ),
            )
        )

    def export_session_state(self): return self._implementation.export_session_state()
    def export_preset_state(self): return self._implementation.export_preset_state()
    def import_session_state(self, session): return self._implementation.import_session_state(session)
    def import_preset_state(self, preset): return self._implementation.import_preset_state(preset)

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        if name == "runtime.session.export":
            return self.export_session_state()
        if name == "runtime.session.import":
            self.import_session_state(dict(request.get("state") or {}))
            return {"accepted": True}
        if name == "runtime.screen.catalog":
            return self._implementation.capture_screen_catalog()
        if name == "runtime.screen.select_region":
            return self._implementation.select_capture_region(square=bool(request.get("square", False)))
        return None

    def shutdown(self):
        implementation = getattr(self, "_implementation", None)
        if implementation is not None:
            implementation.shutdown()
        self._implementation = None
