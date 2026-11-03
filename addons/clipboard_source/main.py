"""Native-QML Clipboard Source addon entry point."""

from core.addons import BaseAddon
from core.addons.focused_lifecycle import (
    ClipboardSourceCapabilities,
    ClipboardSourceInitialization,
)

from addons.clipboard_source.native_service import Addon as ClipboardSourceService


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._implementation = ClipboardSourceService()
        self._implementation.initialize(
            ClipboardSourceInitialization(
                logger=context.logger,
                ui=context.ui,
                manifest_root=context.manifest.root_dir,
                capabilities=ClipboardSourceCapabilities(
                    shell_session=context.capabilities.shell_session,
                    sensory_targets=context.capabilities.sensory_targets,
                    runtime_config=context.capabilities.runtime_config,
                    user_image_turns=context.capabilities.user_image_turns,
                    replay=context.capabilities.replay,
                ),
            )
        )

    def export_session_state(self):
        return self._implementation.export_session_state()

    def export_preset_state(self):
        return self._implementation.export_preset_state()

    def import_session_state(self, session):
        return self._implementation.import_session_state(session or {})

    def import_preset_state(self, preset):
        return self._implementation.import_preset_state(preset or {})

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        if name == "runtime.session.export":
            return dict(self.export_session_state() or {})
        if name == "runtime.session.import":
            self.import_session_state(dict(request.get("state") or {}))
            return {"accepted": True}
        return None

    def shutdown(self):
        implementation = getattr(self, "_implementation", None)
        self._implementation = None
        return implementation.shutdown() if implementation is not None else None
