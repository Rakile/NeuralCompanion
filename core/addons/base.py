from __future__ import annotations


class BaseAddon:
    """Minimal addon base class for in-process addons."""

    def initialize(self, context):
        self.context = context

    def invoke_capability(self, capability, payload=None):
        return None

    def export_session_state(self):
        return {}

    def import_session_state(self, session):
        return None

    def export_preset_state(self):
        return {}

    def import_preset_state(self, preset):
        return None

    def shutdown(self):
        return None

