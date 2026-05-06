from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_audio_story_mode_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Audio Story Mode controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AudioStoryModeController


class Addon(BaseAddon):
    TAB_ID = "audio_story_mode_runtime"

    def initialize(self, context):
        super().initialize(context)
        self._shell_preview = bool(context.get_service("qt.audio_story_mode_shell_preview") if context is not None else False)
        self._controller_cls = None
        self.controller = None
        context.ui.register_manifest_designer_tab(
            id=self.TAB_ID,
            binder=self._bind_designer_tab,
        )
        context.logger.info("Audio Story Mode addon initialized.")

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

    def _build_runtime_widget(self, context):
        if getattr(self, "_shell_preview", False):
            return self._build_shell_preview_tab()
        controller = self._ensure_controller()
        if controller is None:
            raise RuntimeError("Audio Story Mode controller is unavailable.")
        return controller.build_runtime_widget()

    def _bind_designer_tab(self, widget, context):
        from PySide6 import QtWidgets

        if getattr(self, "_shell_preview", False):
            layout = widget.layout()
            if layout is None:
                layout = QtWidgets.QVBoxLayout(widget)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
            while layout.count():
                item = layout.takeAt(0)
                child = item.widget()
                if child is not None:
                    child.setParent(None)
            layout.addWidget(self._build_shell_preview_tab())
            return widget

        if not getattr(self, "_shell_preview", False):
            controller = self._ensure_controller()
            if controller is None:
                raise RuntimeError("Audio Story Mode controller is unavailable.")
            bound = controller.build_runtime_widget(widget)
            if bound is not None:
                return bound

        mount = widget.findChild(QtWidgets.QWidget, "addon_designer_mount")
        if mount is None:
            raise RuntimeError("Audio Story Mode Designer UI could not be bound.")
        layout = mount.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(mount)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        layout.addWidget(self._build_runtime_widget(context))
        return widget

    def _build_shell_preview_tab(self):
        from PySide6 import QtCore, QtWidgets

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("audio_story_mode_tab")
        scroll.setWidgetResizable(True)

        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        box = QtWidgets.QGroupBox("Audio Story Mode")
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.setContentsMargins(14, 12, 14, 12)
        box_layout.setSpacing(10)

        title = QtWidgets.QLabel("Shell preview only")
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
        box_layout.addWidget(title)

        intro = QtWidgets.QLabel(
            "The real Audio Story Mode tab is runtime-sensitive: it imports engine/shared state, "
            "creates a media player, and connects controls to transcription, TTS narration, visual generation, "
            "timeline sync, and Visual Reply publication.\n\n"
            "This Designer shell tab proves the addon mount boundary and tab replacement without importing the "
            "runtime controller or creating audio/model/image-generation objects."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        box_layout.addWidget(intro)

        workflow_box = QtWidgets.QGroupBox("Workflow Boundary")
        workflow_layout = QtWidgets.QVBoxLayout(workflow_box)
        workflow_layout.setContentsMargins(12, 10, 12, 10)
        workflow_layout.setSpacing(6)
        for step in (
            "Import audio file",
            "Transcribe through local Whisper",
            "Build transcript windows and story continuity",
            "Pre-generate Visual Reply images",
            "Play source audio or TTS narration",
            "Sync images to playback position",
        ):
            checkbox = QtWidgets.QCheckBox(step)
            checkbox.setEnabled(False)
            checkbox.setToolTip("Runtime action disabled in main.ui shell preview.")
            workflow_layout.addWidget(checkbox)
        box_layout.addWidget(workflow_box)

        controls_row = QtWidgets.QHBoxLayout()
        for label in ("Import Audio", "Transcribe Audio", "Play", "Pause", "Stop"):
            button = QtWidgets.QPushButton(label)
            button.setEnabled(False)
            button.setToolTip("Disabled in shell preview; the real addon owns this runtime action.")
            controls_row.addWidget(button)
        controls_row.addStretch(1)
        box_layout.addLayout(controls_row)

        progress = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setEnabled(False)
        progress.setToolTip("Playback timeline is disabled in shell preview.")
        box_layout.addWidget(progress)

        status = QtWidgets.QLabel("Ready for shell layout validation. Use the normal app path for real audio-story playback.")
        status.setObjectName("audio_story_mode_shell_status")
        status.setWordWrap(True)
        status.setStyleSheet("color: #8ea3b8;")
        box_layout.addWidget(status)

        layout.addWidget(box)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def export_session_state(self):
        controller = self._peek_controller()
        if controller is None:
            return {}
        return controller.export_session_state() or {}

    def import_session_state(self, session):
        controller = self._ensure_controller()
        if controller is None:
            return None
        return controller.import_session_state(session)

    def invoke_capability(self, capability, payload=None):
        controller = self._ensure_controller()
        if controller is None:
            return None
        capability_name = str(capability or "").strip().lower()
        if capability_name == "audio_story_mode.load_current_image":
            return controller.load_current_story_image(payload or {})
        if capability_name == "audio_story_mode.refresh_master_style_anchor":
            return controller.refresh_master_style_anchor(payload or {})
        return None

    def shutdown(self):
        controller = self.controller
        if controller is None:
            return None
        return controller.shutdown()
