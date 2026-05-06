from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_musetalk_preprocess_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load MuseTalk preprocess controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MuseTalkPreprocessController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._shell_preview = bool(context.get_service("qt.musetalk_preprocess_shell_preview") if context is not None else False)
        self._controller_cls = None
        self.controller = None
        context.ui.register_manifest_designer_tab(
            id="musetalk_preprocess_tab",
            binder=self._bind_designer_tab,
        )
        context.events.subscribe("ui.tab_focus_changed", self._on_ui_tab_focus_changed)
        context.events.subscribe("runtime.heavy_task_starting", self._on_runtime_heavy_task_starting)
        context.events.subscribe("app.resources_refreshed", self._on_app_resources_refreshed)
        context.logger.info("MuseTalk Preprocess addon initialized.")

    def _ensure_controller(self):
        if getattr(self, "_shell_preview", False):
            return None
        controller = getattr(self, "controller", None)
        if controller is not None:
            return controller
        controller_cls = getattr(self, "_controller_cls", None)
        if controller_cls is None:
            controller_cls = _load_controller_class()
            self._controller_cls = controller_cls
        controller = controller_cls(self.context)
        self.controller = controller
        return controller

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_tab(self, context):
        if getattr(self, "_shell_preview", False):
            return self._build_shell_preview_tab()
        controller = self._ensure_controller()
        if controller is None:
            raise RuntimeError("MuseTalk preprocess controller is unavailable.")
        return controller.build_tab()

    def _bind_designer_tab(self, widget, context):
        from PySide6 import QtWidgets

        mount = widget.findChild(QtWidgets.QWidget, "addon_designer_mount")
        if mount is None:
            raise RuntimeError("MuseTalk Preprocess Designer UI is missing addon_designer_mount.")
        layout = mount.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(mount)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        layout.addWidget(self._build_tab(context))
        return widget

    def _build_shell_preview_tab(self):
        from PySide6 import QtWidgets

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("musetalk_preprocess_tab")
        scroll.setWidgetResizable(True)

        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        box = QtWidgets.QGroupBox("MuseTalk Preprocess")
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.setContentsMargins(14, 12, 14, 12)
        box_layout.setSpacing(10)

        title = QtWidgets.QLabel("Shell preview only")
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
        box_layout.addWidget(title)

        text = QtWidgets.QLabel(
            "The real MuseTalk Preprocess tab is runtime-sensitive: it imports engine, OpenCV, "
            "and the MuseTalk bridge, and can start preprocessing/debug workers.\n\n"
            "This Designer shell tab confirms the addon mount point and ordering without loading "
            "MuseTalk runtime modules, starting bridge workers, scanning avatar folders, or mutating runtime state."
        )
        text.setWordWrap(True)
        text.setStyleSheet("color: #9fb3c8;")
        box_layout.addWidget(text)

        disabled_actions = [
            "Avatar pack and prepared variant scanning",
            "Source video/folder browsing",
            "MuseTalk preprocessing",
            "First-frame debug generation",
            "Mask editor bridge handoff",
            "Runtime avatar metadata writes",
        ]
        list_widget = QtWidgets.QListWidget()
        list_widget.setObjectName("musetalk_preprocess_shell_disabled_actions")
        list_widget.addItems(disabled_actions)
        list_widget.setToolTip("Actions intentionally disabled in main.ui shell preview.")
        box_layout.addWidget(list_widget)

        status = QtWidgets.QLabel("Ready for shell layout validation. Use the normal app path for real MuseTalk preprocessing.")
        status.setObjectName("musetalk_preprocess_shell_status")
        status.setWordWrap(True)
        status.setStyleSheet("color: #8ea3b8;")
        box_layout.addWidget(status)

        layout.addWidget(box)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _on_ui_tab_focus_changed(self, payload):
        controller = self._peek_controller()
        if controller is None:
            return
        current_path = [str(item or "").strip().lower() for item in list(payload.get("current_path", []) or []) if str(item or "").strip()]
        if current_path[:2] == ["musetalk", "preprocess"]:
            return
        controller._stop_cached_musetalk_tool_bridge()

    def _on_runtime_heavy_task_starting(self, payload):
        controller = self._peek_controller()
        if controller is None:
            return
        controller._stop_cached_musetalk_tool_bridge()

    def _on_app_resources_refreshed(self, payload):
        controller = self._peek_controller()
        if controller is None:
            return
        controller.refresh_musetalk_avatar_list()

    def invoke_capability(self, capability, payload=None):
        controller = self._ensure_controller()
        if controller is None:
            return None
        if str(capability or "").strip() == "avatar_preprocess.set_source_path":
            path = str((payload or {}).get("path") or "").strip()
            if not path or not hasattr(controller, "musetalk_source_edit"):
                return None
            resolved_path = str(Path(path).resolve())
            controller.musetalk_source_edit.setText(resolved_path)
            return {"handled": True}
        return None

    def export_session_state(self):
        controller = self._peek_controller()
        if controller is None:
            return {}
        return controller.export_session_state() or {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        controller = self._ensure_controller()
        if controller is None:
            return None
        return controller.import_session_state(session)

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        controller = self.controller
        if controller is None:
            return None
        controller._stop_cached_musetalk_tool_bridge()
        return None
