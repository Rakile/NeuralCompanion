from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons import BaseAddon

from addons.rag_context import indexer


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_rag_context_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load RAG Context controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RagContextController


class Addon(BaseAddon):
    TAB_ID = "rag_context_tab"

    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_manifest_designer_tab(
            id=self.TAB_ID,
            binder=self._bind_designer_tab,
        )
        context.logger.info("RAG Context addon initialized.")

    def _bind_designer_tab(self, widget, context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("RAG Context controller is unavailable.")
        return controller.bind_designer_tab(widget)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip().lower()
        if capability != "chat_context.collect":
            return None
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        return controller.collect_chat_context(dict(payload or {}))

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        if controller is None:
            return {}
        return {"rag_context": controller.export_state()}

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        payload = dict(session or {}).get("rag_context")
        if isinstance(payload, dict):
            controller.import_state(payload)
        return None
