import importlib.util
from pathlib import Path

from core.addons.base import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_visual_reply_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Visual Reply controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.VisualReplyController


class Addon(BaseAddon):
    HOST_TAB_ID = "visuals_host"

    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        self.controller.install_panel()
        context.ui.register_manifest_designer_tab(
            id=self.HOST_TAB_ID,
            binder=self._bind_core_tab,
        )
        context.logger.info("Visual Reply addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _bind_core_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Visual Reply controller is unavailable.")
        return controller.bind_core_tab(widget)

    def _visual_reply_service(self):
        context = getattr(self, "context", None)
        if context is None:
            return None
        try:
            return context.get_service("qt.visual_reply")
        except Exception:
            return None

    def export_session_state(self):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "export_session_state"):
            return service.export_session_state() or {}
        return {}

    def export_preset_state(self):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "export_preset_state"):
            return service.export_preset_state() or {}
        return self.export_session_state()

    def import_session_state(self, session):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "import_session_state"):
            return service.import_session_state(session)
        return None

    def import_preset_state(self, preset):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "import_preset_state"):
            return service.import_preset_state(preset)
        return self.import_session_state(preset)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        payload = dict(payload or {})
        if capability == "runtime.engine_bridge":
            from addons.visual_reply.engine_bridge import create_engine_bridge

            return create_engine_bridge(
                payload.get("config_getter") or (lambda: payload.get("runtime_config") or {}),
                environ=payload.get("environ"),
                output_dir=payload.get("output_dir"),
            )
        if capability == "ui.panel_class":
            from addons.visual_reply.controller import AddonVisualReplyPanel

            return AddonVisualReplyPanel
        if capability == "runtime.apply_settings":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.apply_runtime_settings(backend, payload.get("settings") or {})
            return None
        if capability == "real_ui.sync_widget_names":
            return {
                "combo": [
                    "visual_reply_mode_combo",
                    "visual_reply_provider_combo",
                    "visual_reply_size_combo",
                    "visual_reply_comfyui_cleanup_combo",
                ],
                "line_edit": ["visual_reply_model_edit", "visual_reply_api_key_edit"],
                "checkbox": ["visual_reply_auto_show_checkbox"],
            }
        if capability == "runtime.status_snapshot":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_status_snapshot(backend, payload.get("runtime_config") or {})
            return None
        if capability == "runtime.generation":
            from addons.visual_reply import generation, runtime_config

            runtime = runtime_config.VisualReplyRuntime(lambda: payload.get("runtime_config") or {})
            return {
                "api_key": generation.api_key(runtime),
                "base_url": generation.base_url(runtime),
                "provider": generation.provider(runtime),
                "enabled": generation.enabled(runtime),
                "generation_available": generation.generation_available(runtime),
                "model": generation.model_name(runtime),
                "size": generation.image_size(runtime),
                "extra_body": generation.xai_extra_body(runtime),
                "response_format": "base64Data" if generation.provider(runtime) == "runware" else "b64_json",
            }
        if capability == "runtime.current_state":
            from addons.visual_reply import state

            return dict(getattr(state, "current_visual_reply_data", {}) or {})
        if capability == "runtime.set_state":
            from addons.visual_reply import state

            state.set_current_visual_reply_data(dict(payload.get("state") or {}))
            return True
        if capability == "runtime.output_base":
            import time
            import uuid

            from addons.visual_reply import generation

            prefix = str(payload.get("prefix") or "visual_reply").strip() or "visual_reply"
            index = int(payload.get("index", 0) or 0)
            return generation.output_dir() / f"{prefix}_{int(time.time())}_{index}_{uuid.uuid4().hex[:8]}"
        if capability == "runtime.client":
            from addons.visual_reply import generation, runtime_config

            runtime = runtime_config.VisualReplyRuntime(lambda: payload.get("runtime_config") or {})
            return generation.client(runtime)
        if capability == "runtime.apply_style_anchor":
            from addons.visual_reply import generation, runtime_config

            runtime = runtime_config.VisualReplyRuntime(lambda: payload.get("runtime_config") or {})
            return generation.apply_style_anchor(runtime, str(payload.get("prompt") or ""))
        if capability == "runtime.story_style_guide":
            from addons.visual_reply import generation, runtime_config

            runtime = runtime_config.VisualReplyRuntime(lambda: payload.get("runtime_config") or {})
            service = generation.VisualReplyGenerationService(runtime, output_dir=generation.output_dir())
            return service.story_style_guide_from_text(
                str(payload.get("text") or ""),
                continuity_strength=float(payload.get("continuity_strength", 0.8) or 0.8),
            )
        if capability == "runtime.story_prompt":
            from addons.visual_reply import generation, runtime_config

            runtime = runtime_config.VisualReplyRuntime(lambda: payload.get("runtime_config") or {})
            service = generation.VisualReplyGenerationService(runtime, output_dir=generation.output_dir())
            return service.story_prompt_from_text(
                str(payload.get("text") or ""),
                emotion=str(payload.get("emotion") or ""),
                story_style_guide=str(payload.get("story_style_guide") or ""),
            )
        if capability == "runtime.normalize_prompt":
            from addons.visual_reply import runtime_config

            return runtime_config.normalize_prompt_text(str(payload.get("prompt") or ""))
        if capability == "runtime.write_image_from_response":
            from addons.visual_reply import generation, runtime_config

            runtime = runtime_config.VisualReplyRuntime(lambda: payload.get("runtime_config") or {})
            service = generation.VisualReplyGenerationService(runtime, output_dir=generation.output_dir())
            return service.write_image_from_response(
                payload.get("response"),
                Path(payload.get("output_base_path")),
            )
        if capability == "legacy.build_utility_button":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_legacy_utility_button(backend)
            return None
        if capability == "legacy.build_settings_tab":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_legacy_settings_tab(backend)
            return None
        if capability == "legacy.build_runtime_widgets":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_legacy_runtime_widgets(backend, payload.get("runtime_config") or {})
            return None
        if capability == "real_ui.bind_runtime_controls":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.bind_runtime_controls(bridge)
            return None
        if capability == "real_ui.build_dock":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.build_dock(
                    bridge,
                    theme_provider=payload.get("theme_provider"),
                    runtime_config=payload.get("runtime_config") or {},
                    state_module=payload.get("state_module"),
                    storage_dir=payload.get("storage_dir"),
                )
            return None
        if capability == "real_ui.bind_show_button":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.bind_show_button(bridge)
            return None
        if capability == "real_ui.show_dock":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.show_dock(bridge)
            return None
        if capability == "real_ui.redirect_runtime_surface":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.redirect_runtime_surface(bridge)
            return None
        if capability.startswith("runtime.backend."):
            from addons.visual_reply.runtime import BackendVisualReplyRuntimeMixin

            backend = payload.get("backend")
            method_name = capability[len("runtime.backend.") :]
            method = getattr(BackendVisualReplyRuntimeMixin, method_name, None)
            if backend is not None and callable(method):
                return method(backend, *list(payload.get("args") or []), **dict(payload.get("kwargs") or {}))
            return None
        if capability == "shell.create_visual_reply_service":
            from addons.visual_reply.shell_service import _UiShellVisualReplyService

            return _UiShellVisualReplyService(payload.get("window"))
        if capability != "visual_reply.build_runtime_panel":
            return None
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.build_runtime_panel(capability_bridge=payload.get("capability_bridge"))
