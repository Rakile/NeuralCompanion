"""Native-QML Document Memory addon entry point."""

from core.addons import BaseAddon

from addons.rag_context.native_controller import RagContextController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = RagContextController(context.storage, host=getattr(context.capabilities, "document_memory", None), tasks=context.tasks)
        context.logger.info("Document Memory native service initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if name.startswith("runtime.rag.") and name not in {"runtime.rag.status", "runtime.rag.packages.list", "runtime.rag.test_query"}:
            try:
                return self.controller.run_scoped(request, lambda: self._invoke_capability(capability, request))
            except (ValueError, KeyError, RuntimeError) as exc:
                return {"accepted": False, "error": str(exc), "status": str(exc)}
        return self._invoke_capability(capability, request)

    def _invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if name == "chat_context.collect":
            return self.controller.collect_chat_context(request)
        if name == "runtime.session.export":
            return self.export_session_state()
        if name == "runtime.session.import":
            self.import_session_state(dict(request.get("state") or {}))
            return {"accepted": True}
        if name == "runtime.rag.status":
            return self.controller.status_snapshot()
        if name.startswith("runtime.rag."):
            try:
                handled = True
                if name == "runtime.rag.packages.list":
                    return self.controller.status_snapshot()
                if name == "runtime.rag.packages.create":
                    self.controller.create_package(request.get("name", ""))
                elif name == "runtime.rag.packages.select":
                    self.controller.select_package(request.get("package_id", ""))
                elif name == "runtime.rag.packages.retry":
                    self.controller.retry_package_load()
                elif name == "runtime.rag.packages.cancel":
                    self.controller.cancel_package_load()
                elif name == "runtime.rag.sources.enable":
                    self.controller.set_source_enabled(request.get("source_id", ""), request.get("enabled", False))
                elif name == "runtime.rag.sources.refresh":
                    self.controller.refresh_sources(request.get("source_ids") or ())
                elif name == "runtime.rag.settings.update":
                    self.controller.update_settings(request.get("changes") or {}, package_id=request.get("package_id"), expected_revision=request.get("expected_revision"))
                elif name == "runtime.rag.index.pause":
                    self.controller.scheduler.set_paused(request.get("paused", True))
                elif name == "runtime.rag.index.rebuild":
                    return self.controller.build_index()
                elif name == "runtime.rag.models.refresh":
                    return self.controller.refresh_models()
                else:
                    handled = False
                if handled:
                    return {"accepted": True, **self.controller.status_snapshot()}
            except (ValueError, KeyError, RuntimeError) as exc:
                return {"accepted": False, "error": str(exc), "status": str(exc)}
        if name == "runtime.rag.add_files":
            self.controller.add_files(request.get("paths") or ())
            return self.controller.status_snapshot()
        if name == "runtime.rag.remove_files":
            self.controller.remove_files(request.get("paths") or ())
            return self.controller.status_snapshot()
        if name == "runtime.rag.clear_files":
            self.controller.clear_files()
            return self.controller.status_snapshot()
        if name == "runtime.rag.build_index":
            return self.controller.build_index()
        if name == "runtime.rag.test_query":
            return self.controller.test_query(request.get("query"))
        return None

    def export_session_state(self):
        return {"rag_context": self.controller.export_state()}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = dict(session or {}).get("rag_context")
        if isinstance(payload, dict):
            self.controller.import_state(payload)
        else:
            self.controller.import_state({"schema_version": 2,
                "package_id": self.controller.export_state().get("package_id", ""), "enabled": False})

    def import_preset_state(self, preset):
        self.import_session_state(preset)

    def shutdown(self):
        if self.controller is not None:
            self.controller.close()
        self.controller = None
