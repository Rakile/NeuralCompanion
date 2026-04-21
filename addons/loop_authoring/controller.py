from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import threading
import time
from pathlib import Path

import loop_authoring
from PySide6 import QtCore, QtGui, QtWidgets
from qt_shared_widgets import ContextTokenStepper, NoWheelComboBox


class LoopAuthoringController(QtCore.QObject):

    def __init__(self, context=None):
        super().__init__()
        super().__setattr__("context", context)
        self.set_context(context)
        self._initialize_host_state()

    def set_context(self, context):
        super().__setattr__("context", context)
        super().__setattr__("dialogs", context.get_service("qt.dialogs") if context is not None else None)
        super().__setattr__("shell", context.get_service("qt.shell") if context is not None else None)
        super().__setattr__("musetalk_ui", context.get_service("qt.musetalk_ui") if context is not None else None)
        super().__setattr__("capabilities", context.get_service("addons.capabilities") if context is not None else None)
        super().__setattr__("shell_preview", bool(context.get_service("qt.loop_authoring_shell_preview") if context is not None else False))


    def _initialize_host_state(self):
        self._loop_author_output_id_manual_override = False
        self._loop_author_output_id_updating = False
        self._loop_author_prompt_manual_override = False
        self._loop_author_negative_prompt_manual_override = False
        self._loop_author_prompt_updating = False
        self._loop_author_generation_thread = None
        self._loop_author_generation_lock = threading.Lock()
        self._pending_loop_author_generation_result = None
        self._loop_author_wan2gp_root = loop_authoring.detect_wan2gp_root()
        self.loop_author_tab_widget = None

    def _is_shell_preview(self):
        return bool(getattr(self, "shell_preview", False))

    def _disable_shell_runtime_controls(self):
        if not self._is_shell_preview():
            return
        disabled_names = (
            "btn_loop_author_source_image",
            "btn_loop_author_reference_video",
            "btn_loop_author_wan2gp_root",
            "btn_loop_author_conda_env_refresh",
            "btn_loop_author_conda_command",
            "btn_loop_author_wan2gp_python",
            "btn_loop_author_save_draft",
            "btn_loop_author_generate",
            "btn_loop_author_open_draft",
            "btn_loop_author_open_wan2gp_outputs",
            "btn_loop_author_import_latest",
            "btn_loop_author_use_video",
        )
        for widget_name in disabled_names:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(False)
                widget.setToolTip("Disabled in the main.ui shell preview; the live app owns file, subprocess, and MuseTalk handoff actions.")
        for widget_name in (
            "loop_author_source_image_edit",
            "loop_author_reference_video_edit",
            "loop_author_wan2gp_root_edit",
            "loop_author_conda_command_edit",
            "loop_author_wan2gp_python_edit",
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None and hasattr(widget, "setReadOnly"):
                widget.setReadOnly(True)
                widget.setToolTip("Read-only in the main.ui shell preview.")
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText(
                "Loop Authoring shell preview only. Wan2GP launch, file dialogs, folder writes, and MuseTalk handoff are disabled."
            )

    def _detect_default_conda_command(self):
        env_candidates = [
            os.environ.get("CONDA_EXE", ""),
            os.environ.get("MAMBA_EXE", ""),
        ]
        path_candidates = [
            r"E:\miniconda3\condabin\conda.bat",
            r"E:\miniconda3\Scripts\conda.exe",
            r"C:\ProgramData\miniconda3\condabin\conda.bat",
            r"C:\ProgramData\miniconda3\Scripts\conda.exe",
            r"C:\ProgramData\Anaconda3\condabin\conda.bat",
            r"C:\ProgramData\Anaconda3\Scripts\conda.exe",
            str(Path.home() / "miniconda3" / "condabin" / "conda.bat"),
            str(Path.home() / "miniconda3" / "Scripts" / "conda.exe"),
            str(Path.home() / "anaconda3" / "condabin" / "conda.bat"),
            str(Path.home() / "anaconda3" / "Scripts" / "conda.exe"),
        ]
        for raw in env_candidates + path_candidates:
            candidate = str(raw or "").strip()
            if candidate and Path(candidate).exists():
                return candidate
        if shutil.which("conda"):
            return "conda"
        return "conda"


    def _warn(self, title, message):
        if self.dialogs is not None:
            self.dialogs.warning(title, message)
        else:
            QtWidgets.QMessageBox.warning(None, str(title), str(message))

    def _info(self, title, message):
        if self.dialogs is not None:
            self.dialogs.information(title, message)
        else:
            QtWidgets.QMessageBox.information(None, str(title), str(message))

    def build_tab(self):
        existing = self.loop_author_tab_widget
        if existing is not None:
            return existing

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("loop_authoring_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        loop_box = QtWidgets.QGroupBox("Loop Authoring (Experimental)")
        self.loop_box = loop_box
        loop_layout = QtWidgets.QVBoxLayout(loop_box)

        loop_intro = QtWidgets.QLabel(
            "Create a reusable local draft package for MuseTalk emotion loops. "
            "This is an authoring helper, not a realtime runtime feature. "
            "Use presets to generate known-good prompts and settings for tools like Wan2GP."
        )
        loop_intro.setWordWrap(True)
        loop_intro.setStyleSheet("color: #9fb3c8;")
        loop_layout.addWidget(loop_intro)

        backend_row = QtWidgets.QHBoxLayout()
        backend_column = QtWidgets.QVBoxLayout()
        backend_column.addWidget(QtWidgets.QLabel("Backend"))
        self.loop_author_backend_combo = NoWheelComboBox()
        self.loop_author_backend_combo.setObjectName("loop_author_backend_combo")
        self.loop_author_backend_combo.addItems(["Wan2GP", "Wan2.2 Official", "LTX-Video"])
        self.loop_author_backend_combo.currentTextChanged.connect(self._refresh_loop_authoring_recommendation)
        backend_column.addWidget(self.loop_author_backend_combo)
        backend_row.addLayout(backend_column, 1)

        preset_column = QtWidgets.QVBoxLayout()
        preset_column.addWidget(QtWidgets.QLabel("Preset"))
        self.loop_author_preset_combo = NoWheelComboBox()
        self.loop_author_preset_combo.setObjectName("loop_author_preset_combo")
        for preset in loop_authoring.list_presets():
            self.loop_author_preset_combo.addItem(preset.label, preset.key)
        self.loop_author_preset_combo.currentIndexChanged.connect(self._on_loop_author_preset_changed)
        preset_column.addWidget(self.loop_author_preset_combo)
        backend_row.addLayout(preset_column, 1)

        wan_profile_column = QtWidgets.QVBoxLayout()
        wan_profile_column.addWidget(QtWidgets.QLabel("Wan2GP Profile"))
        self.loop_author_wan2gp_profile_combo = NoWheelComboBox()
        self.loop_author_wan2gp_profile_combo.setObjectName("loop_author_wan2gp_profile_combo")
        for profile_key, profile_label in loop_authoring.WAN2GP_PROFILES:
            self.loop_author_wan2gp_profile_combo.addItem(profile_label, profile_key)
        self.loop_author_wan2gp_profile_combo.currentIndexChanged.connect(self._refresh_loop_authoring_recommendation)
        wan_profile_column.addWidget(self.loop_author_wan2gp_profile_combo)
        backend_row.addLayout(wan_profile_column, 1)

        wan_memory_column = QtWidgets.QVBoxLayout()
        wan_memory_column.addWidget(QtWidgets.QLabel("Wan2GP Memory"))
        self.loop_author_wan2gp_memory_combo = NoWheelComboBox()
        self.loop_author_wan2gp_memory_combo.setObjectName("loop_author_wan2gp_memory_combo")
        for memory_key, memory_label in loop_authoring.WAN2GP_MEMORY_PROFILES:
            self.loop_author_wan2gp_memory_combo.addItem(memory_label, memory_key)
        self.loop_author_wan2gp_memory_combo.currentIndexChanged.connect(self._refresh_loop_authoring_recommendation)
        wan_memory_column.addWidget(self.loop_author_wan2gp_memory_combo)
        backend_row.addLayout(wan_memory_column, 1)

        loop_layout.addLayout(backend_row)

        image_row = QtWidgets.QHBoxLayout()
        self.loop_author_source_image_edit = QtWidgets.QLineEdit()
        self.loop_author_source_image_edit.setObjectName("loop_author_source_image_edit")
        self.loop_author_source_image_edit.setPlaceholderText("Source still image for the avatar identity")
        self.loop_author_source_image_edit.textChanged.connect(self._update_loop_authoring_destination_hint)
        image_row.addWidget(self.loop_author_source_image_edit, 1)
        self.btn_loop_author_source_image = QtWidgets.QPushButton("Image")
        self.btn_loop_author_source_image.setObjectName("btn_loop_author_source_image")
        self.btn_loop_author_source_image.clicked.connect(self.browse_loop_authoring_source_image)
        image_row.addWidget(self.btn_loop_author_source_image)
        loop_layout.addWidget(QtWidgets.QLabel("Source Image"))
        loop_layout.addLayout(image_row)

        reference_row = QtWidgets.QHBoxLayout()
        self.loop_author_reference_video_edit = QtWidgets.QLineEdit()
        self.loop_author_reference_video_edit.setObjectName("loop_author_reference_video_edit")
        self.loop_author_reference_video_edit.setPlaceholderText("Optional motion/style reference video")
        self.loop_author_reference_video_edit.textChanged.connect(self._update_loop_authoring_destination_hint)
        reference_row.addWidget(self.loop_author_reference_video_edit, 1)
        self.btn_loop_author_reference_video = QtWidgets.QPushButton("Reference")
        self.btn_loop_author_reference_video.setObjectName("btn_loop_author_reference_video")
        self.btn_loop_author_reference_video.clicked.connect(self.browse_loop_authoring_reference_video)
        reference_row.addWidget(self.btn_loop_author_reference_video)
        self.loop_author_start_from_video_checkbox = QtWidgets.QCheckBox("Start From This Video")
        self.loop_author_start_from_video_checkbox.setObjectName("loop_author_start_from_video_checkbox")
        self.loop_author_start_from_video_checkbox.toggled.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_start_from_video_checkbox.toggled.connect(self._update_loop_authoring_destination_hint)
        reference_row.addWidget(self.loop_author_start_from_video_checkbox)
        loop_layout.addWidget(QtWidgets.QLabel("Reference Video"))
        loop_layout.addLayout(reference_row)

        wan2gp_root_row = QtWidgets.QHBoxLayout()
        self.loop_author_wan2gp_root_edit = QtWidgets.QLineEdit()
        self.loop_author_wan2gp_root_edit.setObjectName("loop_author_wan2gp_root_edit")
        self.loop_author_wan2gp_root_edit.setPlaceholderText("Path to local Wan2GP installation")
        if self._loop_author_wan2gp_root is not None:
            self.loop_author_wan2gp_root_edit.setText(str(self._loop_author_wan2gp_root))
        self.loop_author_wan2gp_root_edit.textChanged.connect(self._on_loop_author_wan2gp_root_changed)
        wan2gp_root_row.addWidget(self.loop_author_wan2gp_root_edit, 1)
        self.btn_loop_author_wan2gp_root = QtWidgets.QPushButton("Wan2GP")
        self.btn_loop_author_wan2gp_root.setObjectName("btn_loop_author_wan2gp_root")
        self.btn_loop_author_wan2gp_root.clicked.connect(self.browse_loop_authoring_wan2gp_root)
        wan2gp_root_row.addWidget(self.btn_loop_author_wan2gp_root)
        loop_layout.addWidget(QtWidgets.QLabel("Wan2GP Root"))
        loop_layout.addLayout(wan2gp_root_row)

        runtime_mode_row = QtWidgets.QHBoxLayout()

        runtime_mode_column = QtWidgets.QVBoxLayout()
        runtime_mode_column.addWidget(QtWidgets.QLabel("Wan2GP Runtime"))
        self.loop_author_wan2gp_runtime_combo = NoWheelComboBox()
        self.loop_author_wan2gp_runtime_combo.setObjectName("loop_author_wan2gp_runtime_combo")
        self.loop_author_wan2gp_runtime_combo.addItem("Python Executable", "python")
        self.loop_author_wan2gp_runtime_combo.addItem("Conda Environment", "conda")
        self.loop_author_wan2gp_runtime_combo.currentIndexChanged.connect(self._refresh_loop_authoring_runtime_mode_ui)
        self.loop_author_wan2gp_runtime_combo.currentIndexChanged.connect(self._update_loop_authoring_destination_hint)
        runtime_mode_column.addWidget(self.loop_author_wan2gp_runtime_combo)
        runtime_mode_row.addLayout(runtime_mode_column, 1)

        conda_env_column = QtWidgets.QVBoxLayout()
        conda_env_column.addWidget(QtWidgets.QLabel("Conda Env"))
        conda_env_row = QtWidgets.QHBoxLayout()
        self.loop_author_conda_env_combo = NoWheelComboBox()
        self.loop_author_conda_env_combo.setObjectName("loop_author_conda_env_combo")
        self.loop_author_conda_env_combo.setEditable(True)
        self.loop_author_conda_env_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.loop_author_conda_env_combo.setMinimumContentsLength(18)
        line_edit = self.loop_author_conda_env_combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("wan2gp")
            line_edit.textChanged.connect(self._update_loop_authoring_destination_hint)
        self.loop_author_conda_env_combo.currentTextChanged.connect(self._update_loop_authoring_destination_hint)
        conda_env_row.addWidget(self.loop_author_conda_env_combo, 1)
        self.btn_loop_author_conda_env_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_loop_author_conda_env_refresh.setObjectName("btn_loop_author_conda_env_refresh")
        self.btn_loop_author_conda_env_refresh.clicked.connect(self.refresh_loop_authoring_conda_env_list)
        conda_env_row.addWidget(self.btn_loop_author_conda_env_refresh)
        conda_env_column.addLayout(conda_env_row)
        runtime_mode_row.addLayout(conda_env_column, 1)

        conda_command_column = QtWidgets.QVBoxLayout()
        conda_command_column.addWidget(QtWidgets.QLabel("Path to Conda"))
        conda_command_row = QtWidgets.QHBoxLayout()
        self.loop_author_conda_command_edit = QtWidgets.QLineEdit()
        self.loop_author_conda_command_edit.setObjectName("loop_author_conda_command_edit")
        self.loop_author_conda_command_edit.setPlaceholderText("Path to conda.bat / conda.exe")
        self.loop_author_conda_command_edit.setText(self._detect_default_conda_command())
        self.loop_author_conda_command_edit.textChanged.connect(self._update_loop_authoring_destination_hint)
        self.loop_author_conda_command_edit.textChanged.connect(lambda *_: self.refresh_loop_authoring_conda_env_list())
        conda_command_row.addWidget(self.loop_author_conda_command_edit, 1)
        self.btn_loop_author_conda_command = QtWidgets.QPushButton("Conda")
        self.btn_loop_author_conda_command.setObjectName("btn_loop_author_conda_command")
        self.btn_loop_author_conda_command.clicked.connect(self.browse_loop_authoring_conda_command)
        conda_command_row.addWidget(self.btn_loop_author_conda_command)
        conda_command_column.addLayout(conda_command_row)
        runtime_mode_row.addLayout(conda_command_column, 1)

        loop_layout.addLayout(runtime_mode_row)

        wan2gp_python_row = QtWidgets.QHBoxLayout()
        self.loop_author_wan2gp_python_edit = QtWidgets.QLineEdit()
        self.loop_author_wan2gp_python_edit.setObjectName("loop_author_wan2gp_python_edit")
        self.loop_author_wan2gp_python_edit.setPlaceholderText("Python executable for this Wan2GP install")
        default_wan2gp_python = loop_authoring.default_wan2gp_python(self._loop_author_wan2gp_root)
        if default_wan2gp_python is not None:
            self.loop_author_wan2gp_python_edit.setText(str(default_wan2gp_python))
        self.loop_author_wan2gp_python_edit.textChanged.connect(self._update_loop_authoring_destination_hint)
        wan2gp_python_row.addWidget(self.loop_author_wan2gp_python_edit, 1)
        self.btn_loop_author_wan2gp_python = QtWidgets.QPushButton("Python")
        self.btn_loop_author_wan2gp_python.setObjectName("btn_loop_author_wan2gp_python")
        self.btn_loop_author_wan2gp_python.clicked.connect(self.browse_loop_authoring_wan2gp_python)
        wan2gp_python_row.addWidget(self.btn_loop_author_wan2gp_python)
        loop_layout.addWidget(QtWidgets.QLabel("Wan2GP Python"))
        loop_layout.addLayout(wan2gp_python_row)

        wan2gp_tuning_row = QtWidgets.QHBoxLayout()
        self.loop_author_disable_profile_loras_checkbox = QtWidgets.QCheckBox("Disable profile LoRAs (safer)")
        self.loop_author_disable_profile_loras_checkbox.setObjectName("loop_author_disable_profile_loras_checkbox")
        self.loop_author_disable_profile_loras_checkbox.setChecked(True)
        wan2gp_tuning_row.addWidget(self.loop_author_disable_profile_loras_checkbox, 1)

        reserved_column = QtWidgets.QVBoxLayout()
        reserved_column.addWidget(QtWidgets.QLabel("Reserved RAM Max"))
        self.loop_author_wan2gp_reserved_mem_combo = NoWheelComboBox()
        self.loop_author_wan2gp_reserved_mem_combo.setObjectName("loop_author_wan2gp_reserved_mem_combo")
        for value, label in [
            ("auto", "Auto"),
            ("0.20", "0.20"),
            ("0.25", "0.25"),
            ("0.30", "0.30"),
            ("0.35", "0.35"),
            ("0.40", "0.40"),
        ]:
            self.loop_author_wan2gp_reserved_mem_combo.addItem(label, value)
        reserved_column.addWidget(self.loop_author_wan2gp_reserved_mem_combo)
        wan2gp_tuning_row.addLayout(reserved_column)
        loop_layout.addLayout(wan2gp_tuning_row)

        loop_options_row = QtWidgets.QHBoxLayout()
        self.loop_author_sequence_strategy_section = QtWidgets.QWidget()
        strategy_column = QtWidgets.QVBoxLayout(self.loop_author_sequence_strategy_section)
        strategy_column.setContentsMargins(0, 0, 0, 0)
        strategy_column.setSpacing(4)
        strategy_column.addWidget(QtWidgets.QLabel("Long Sequence"))
        self.loop_author_sequence_strategy_combo = NoWheelComboBox()
        self.loop_author_sequence_strategy_combo.setObjectName("loop_author_sequence_strategy_combo")
        self.loop_author_sequence_strategy_combo.addItem("Single Run (Sliding Window)", "single_run")
        self.loop_author_sequence_strategy_combo.addItem("Continue Video Segments", "continue_segments")
        self.loop_author_sequence_strategy_combo.currentIndexChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_sequence_strategy_combo.currentIndexChanged.connect(self._sync_loop_authoring_continuation_controls)
        strategy_column.addWidget(self.loop_author_sequence_strategy_combo)
        loop_options_row.addWidget(self.loop_author_sequence_strategy_section, 2)

        self.loop_author_continuation_source_section = QtWidgets.QWidget()
        continuation_column = QtWidgets.QVBoxLayout(self.loop_author_continuation_source_section)
        continuation_column.setContentsMargins(0, 0, 0, 0)
        continuation_column.setSpacing(4)
        continuation_column.addWidget(QtWidgets.QLabel("Continuation Source"))
        self.loop_author_continuation_source_combo = NoWheelComboBox()
        self.loop_author_continuation_source_combo.setObjectName("loop_author_continuation_source_combo")
        self.loop_author_continuation_source_combo.addItem("Last Rendered Video (Quality)", "full_prefix")
        self.loop_author_continuation_source_combo.addItem("Tail Context Only (Memory-Safe)", "tail_context")
        self.loop_author_continuation_source_combo.currentIndexChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_continuation_source_combo.currentIndexChanged.connect(self._sync_loop_authoring_continuation_controls)
        continuation_column.addWidget(self.loop_author_continuation_source_combo)
        loop_options_row.addWidget(self.loop_author_continuation_source_section, 2)

        self.loop_author_output_id_section = QtWidgets.QWidget()
        output_column = QtWidgets.QVBoxLayout(self.loop_author_output_id_section)
        output_column.setContentsMargins(0, 0, 0, 0)
        output_column.setSpacing(4)
        output_column.addWidget(QtWidgets.QLabel("Draft ID"))
        self.loop_author_output_id_edit = QtWidgets.QLineEdit()
        self.loop_author_output_id_edit.setObjectName("loop_author_output_id_edit")
        self.loop_author_output_id_edit.setPlaceholderText("happy_idle_loop")
        self.loop_author_output_id_edit.textChanged.connect(self._on_loop_author_output_id_changed)
        output_column.addWidget(self.loop_author_output_id_edit)
        loop_layout.addWidget(self.loop_author_output_id_section)

        self.loop_author_duration_section = QtWidgets.QWidget()
        duration_column = QtWidgets.QVBoxLayout(self.loop_author_duration_section)
        duration_column.setContentsMargins(0, 0, 0, 0)
        duration_column.setSpacing(4)
        duration_column.addWidget(QtWidgets.QLabel("Seconds"))
        self.loop_author_duration_spin = ContextTokenStepper()
        self.loop_author_duration_spin.setObjectName("loop_author_duration_spin")
        self.loop_author_duration_spin.setRange(4, 300)
        self.loop_author_duration_spin.setMinimumWidth(92)
        self.loop_author_duration_spin.setValue(8)
        self.loop_author_duration_spin.valueChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_duration_spin.valueChanged.connect(self._update_loop_authoring_destination_hint)
        duration_column.addWidget(self.loop_author_duration_spin)
        loop_options_row.addWidget(self.loop_author_duration_section)

        self.loop_author_segment_duration_section = QtWidgets.QWidget()
        segment_column = QtWidgets.QVBoxLayout(self.loop_author_segment_duration_section)
        segment_column.setContentsMargins(0, 0, 0, 0)
        segment_column.setSpacing(4)
        segment_column.addWidget(QtWidgets.QLabel("Segment Seconds"))
        self.loop_author_segment_duration_spin = ContextTokenStepper()
        self.loop_author_segment_duration_spin.setObjectName("loop_author_segment_duration_spin")
        self.loop_author_segment_duration_spin.setRange(4, 300)
        self.loop_author_segment_duration_spin.setMinimumWidth(92)
        self.loop_author_segment_duration_spin.setValue(8)
        self.loop_author_segment_duration_spin.valueChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_segment_duration_spin.valueChanged.connect(self._update_loop_authoring_destination_hint)
        segment_column.addWidget(self.loop_author_segment_duration_spin)
        loop_options_row.addWidget(self.loop_author_segment_duration_section)

        self.loop_author_window_size_section = QtWidgets.QWidget()
        window_size_column = QtWidgets.QVBoxLayout(self.loop_author_window_size_section)
        window_size_column.setContentsMargins(0, 0, 0, 0)
        window_size_column.setSpacing(4)
        window_size_column.addWidget(QtWidgets.QLabel("Window Size"))
        self.loop_author_window_size_spin = ContextTokenStepper()
        self.loop_author_window_size_spin.setObjectName("loop_author_window_size_spin")
        self.loop_author_window_size_spin.setRange(0, 512)
        self.loop_author_window_size_spin.setMinimumWidth(92)
        self.loop_author_window_size_spin.setValue(0)
        self.loop_author_window_size_spin.valueChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_window_size_spin.valueChanged.connect(self._update_loop_authoring_destination_hint)
        window_size_column.addWidget(self.loop_author_window_size_spin)
        loop_options_row.addWidget(self.loop_author_window_size_section)

        self.loop_author_window_overlap_section = QtWidgets.QWidget()
        window_overlap_column = QtWidgets.QVBoxLayout(self.loop_author_window_overlap_section)
        window_overlap_column.setContentsMargins(0, 0, 0, 0)
        window_overlap_column.setSpacing(4)
        window_overlap_column.addWidget(QtWidgets.QLabel("Window Overlap"))
        self.loop_author_window_overlap_spin = ContextTokenStepper()
        self.loop_author_window_overlap_spin.setObjectName("loop_author_window_overlap_spin")
        self.loop_author_window_overlap_spin.setRange(0, 64)
        self.loop_author_window_overlap_spin.setMinimumWidth(92)
        self.loop_author_window_overlap_spin.setValue(0)
        self.loop_author_window_overlap_spin.valueChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_window_overlap_spin.valueChanged.connect(self._update_loop_authoring_destination_hint)
        window_overlap_column.addWidget(self.loop_author_window_overlap_spin)
        loop_options_row.addWidget(self.loop_author_window_overlap_section)

        self.loop_author_fps_section = QtWidgets.QWidget()
        fps_column = QtWidgets.QVBoxLayout(self.loop_author_fps_section)
        fps_column.setContentsMargins(0, 0, 0, 0)
        fps_column.setSpacing(4)
        fps_column.addWidget(QtWidgets.QLabel("FPS"))
        self.loop_author_fps_spin = ContextTokenStepper()
        self.loop_author_fps_spin.setObjectName("loop_author_fps_spin")
        self.loop_author_fps_spin.setRange(8, 30)
        self.loop_author_fps_spin.setMinimumWidth(92)
        self.loop_author_fps_spin.setValue(16)
        fps_column.addWidget(self.loop_author_fps_spin)
        loop_options_row.addWidget(self.loop_author_fps_section)

        self.loop_author_motion_section = QtWidgets.QWidget()
        motion_column = QtWidgets.QVBoxLayout(self.loop_author_motion_section)
        motion_column.setContentsMargins(0, 0, 0, 0)
        motion_column.setSpacing(4)
        motion_column.addWidget(QtWidgets.QLabel("Motion"))
        self.loop_author_motion_combo = NoWheelComboBox()
        self.loop_author_motion_combo.setObjectName("loop_author_motion_combo")
        self.loop_author_motion_combo.addItems(["Gentle", "Medium", "Expressive"])
        self.loop_author_motion_combo.currentTextChanged.connect(self._refresh_loop_authoring_recommendation)
        motion_column.addWidget(self.loop_author_motion_combo)
        loop_options_row.addWidget(self.loop_author_motion_section)
        loop_row_control_height = 32
        for control in (
            self.loop_author_sequence_strategy_combo,
            self.loop_author_continuation_source_combo,
            self.loop_author_duration_spin,
            self.loop_author_segment_duration_spin,
            self.loop_author_window_size_spin,
            self.loop_author_window_overlap_spin,
            self.loop_author_fps_spin,
            self.loop_author_motion_combo,
        ):
            control.setFixedHeight(loop_row_control_height)
        self.loop_author_output_id_edit.setFixedHeight(loop_row_control_height)
        loop_options_row.addStretch(1)
        loop_layout.addLayout(loop_options_row)

        continuation_tuning_row = QtWidgets.QHBoxLayout()
        continuation_tuning_row.setSpacing(10)

        self.loop_author_tail_context_section = QtWidgets.QWidget()
        tail_context_column = QtWidgets.QVBoxLayout(self.loop_author_tail_context_section)
        tail_context_column.setContentsMargins(0, 0, 0, 0)
        tail_context_column.setSpacing(4)
        tail_context_column.addWidget(QtWidgets.QLabel("Tail Context (s)"))
        self.loop_author_tail_context_spin = ContextTokenStepper()
        self.loop_author_tail_context_spin.setObjectName("loop_author_tail_context_spin")
        self.loop_author_tail_context_spin.setRange(1, 60)
        self.loop_author_tail_context_spin.setMinimumWidth(92)
        self.loop_author_tail_context_spin.setValue(6)
        self.loop_author_tail_context_spin.valueChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_tail_context_spin.valueChanged.connect(self._update_loop_authoring_destination_hint)
        tail_context_column.addWidget(self.loop_author_tail_context_spin)
        continuation_tuning_row.addWidget(self.loop_author_tail_context_section)

        self.loop_author_anchor_refresh_section = QtWidgets.QWidget()
        anchor_refresh_column = QtWidgets.QVBoxLayout(self.loop_author_anchor_refresh_section)
        anchor_refresh_column.setContentsMargins(0, 0, 0, 0)
        anchor_refresh_column.setSpacing(4)
        anchor_refresh_column.addWidget(QtWidgets.QLabel("Re-anchor Every"))
        self.loop_author_anchor_refresh_spin = ContextTokenStepper()
        self.loop_author_anchor_refresh_spin.setObjectName("loop_author_anchor_refresh_spin")
        self.loop_author_anchor_refresh_spin.setRange(0, 20)
        self.loop_author_anchor_refresh_spin.setMinimumWidth(92)
        self.loop_author_anchor_refresh_spin.setValue(0)
        self.loop_author_anchor_refresh_spin.valueChanged.connect(self._refresh_loop_authoring_recommendation)
        self.loop_author_anchor_refresh_spin.valueChanged.connect(self._update_loop_authoring_destination_hint)
        anchor_refresh_column.addWidget(self.loop_author_anchor_refresh_spin)
        continuation_tuning_row.addWidget(self.loop_author_anchor_refresh_section)

        self.loop_author_continuation_hint_label = QtWidgets.QLabel(
            "Continuation-only controls. Tail Context and Re-anchor are used only for Tail Context mode."
        )
        self.loop_author_continuation_hint_label.setWordWrap(True)
        self.loop_author_continuation_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.loop_author_continuation_hint_label.setVisible(False)
        continuation_tuning_row.addWidget(self.loop_author_continuation_hint_label, 1)
        continuation_tuning_row.addStretch(1)
        loop_layout.addLayout(continuation_tuning_row)

        self.loop_author_recommendation_label = QtWidgets.QLabel("")
        self.loop_author_recommendation_label.setWordWrap(True)
        self.loop_author_recommendation_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        loop_layout.addWidget(self.loop_author_recommendation_label)

        loop_layout.addWidget(QtWidgets.QLabel("Prompt"))
        self.loop_author_prompt_edit = QtWidgets.QTextEdit()
        self.loop_author_prompt_edit.setObjectName("loop_author_prompt_edit")
        self.loop_author_prompt_edit.setMinimumHeight(96)
        self.loop_author_prompt_edit.textChanged.connect(self._on_loop_author_prompt_changed)
        loop_layout.addWidget(self.loop_author_prompt_edit)

        loop_layout.addWidget(QtWidgets.QLabel("Negative Prompt"))
        self.loop_author_negative_prompt_edit = QtWidgets.QTextEdit()
        self.loop_author_negative_prompt_edit.setObjectName("loop_author_negative_prompt_edit")
        self.loop_author_negative_prompt_edit.setMinimumHeight(68)
        self.loop_author_negative_prompt_edit.textChanged.connect(self._on_loop_author_negative_prompt_changed)
        loop_layout.addWidget(self.loop_author_negative_prompt_edit)

        self.loop_author_destination_label = QtWidgets.QLabel("")
        self.loop_author_destination_label.setWordWrap(True)
        self.loop_author_destination_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        loop_layout.addWidget(self.loop_author_destination_label)

        loop_controls = QtWidgets.QHBoxLayout()
        self.btn_loop_author_apply_template = QtWidgets.QPushButton("Apply Template")
        self.btn_loop_author_apply_template.setObjectName("btn_loop_author_apply_template")
        self.btn_loop_author_apply_template.clicked.connect(self.apply_loop_authoring_template)
        loop_controls.addWidget(self.btn_loop_author_apply_template)
        self.btn_loop_author_save_draft = QtWidgets.QPushButton("Save Draft Package")
        self.btn_loop_author_save_draft.setObjectName("btn_loop_author_save_draft")
        self.btn_loop_author_save_draft.clicked.connect(self.save_loop_authoring_draft)
        loop_controls.addWidget(self.btn_loop_author_save_draft)
        self.btn_loop_author_generate = QtWidgets.QPushButton("Generate in Wan2GP")
        self.btn_loop_author_generate.setObjectName("btn_loop_author_generate")
        self.btn_loop_author_generate.clicked.connect(self.generate_loop_in_wan2gp)
        loop_controls.addWidget(self.btn_loop_author_generate)
        self.btn_loop_author_open_draft = QtWidgets.QPushButton("Open Draft Folder")
        self.btn_loop_author_open_draft.setObjectName("btn_loop_author_open_draft")
        self.btn_loop_author_open_draft.clicked.connect(self.open_loop_authoring_draft_folder)
        loop_controls.addWidget(self.btn_loop_author_open_draft)
        self.btn_loop_author_open_wan2gp_outputs = QtWidgets.QPushButton("Open Wan2GP Outputs")
        self.btn_loop_author_open_wan2gp_outputs.setObjectName("btn_loop_author_open_wan2gp_outputs")
        self.btn_loop_author_open_wan2gp_outputs.clicked.connect(self.open_loop_authoring_wan2gp_outputs)
        loop_controls.addWidget(self.btn_loop_author_open_wan2gp_outputs)
        self.btn_loop_author_import_latest = QtWidgets.QPushButton("Import Latest Wan2GP Video")
        self.btn_loop_author_import_latest.setObjectName("btn_loop_author_import_latest")
        self.btn_loop_author_import_latest.clicked.connect(self.import_latest_wan2gp_video)
        loop_controls.addWidget(self.btn_loop_author_import_latest)
        self.btn_loop_author_use_video = QtWidgets.QPushButton("Use Draft Video as MuseTalk Source")
        self.btn_loop_author_use_video.setObjectName("btn_loop_author_use_video")
        self.btn_loop_author_use_video.clicked.connect(self.use_loop_authoring_video_as_musetalk_source)
        loop_controls.addWidget(self.btn_loop_author_use_video)
        loop_controls.addStretch(1)
        loop_layout.addLayout(loop_controls)

        self.loop_author_status_label = QtWidgets.QLabel("Loop authoring draft helper idle.")
        self.loop_author_status_label.setStyleSheet("color: #9fb3c8;")
        loop_layout.addWidget(self.loop_author_status_label)
        content_layout.addWidget(loop_box)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        self.loop_author_tab_widget = scroll
        self._sync_loop_author_output_id_from_preset(force=True)
        self._refresh_loop_authoring_runtime_mode_ui()
        self._refresh_loop_authoring_recommendation()
        if not self.loop_author_prompt_edit.toPlainText().strip():
            self.apply_loop_authoring_template()
        self._disable_shell_runtime_controls()
        return scroll


    def _get_loop_authoring_preset_key(self):
        if not hasattr(self, "loop_author_preset_combo"):
            return "neutral_idle"
        key = self.loop_author_preset_combo.currentData()
        return str(key or "neutral_idle")

    def _get_loop_authoring_runtime_mode(self):
        if not hasattr(self, "loop_author_wan2gp_runtime_combo"):
            return "python"
        value = self.loop_author_wan2gp_runtime_combo.currentData()
        return str(value or "python")

    def _get_loop_authoring_conda_env(self):
        combo = getattr(self, "loop_author_conda_env_combo", None)
        if combo is None:
            return ""
        current_index = int(combo.currentIndex())
        if current_index >= 0:
            data = combo.itemData(current_index, QtCore.Qt.UserRole)
            if isinstance(data, dict):
                return str(data.get("value", "") or "").strip()
        return str(combo.currentText() or "").strip()

    def _get_loop_authoring_conda_env_mode(self):
        combo = getattr(self, "loop_author_conda_env_combo", None)
        if combo is None:
            return "name"
        current_index = int(combo.currentIndex())
        if current_index >= 0:
            data = combo.itemData(current_index, QtCore.Qt.UserRole)
            if isinstance(data, dict):
                return str(data.get("mode", "name") or "name")
        return "name"

    def _build_conda_invocation(self, conda_command, *args):
        command_text = str(conda_command or "").strip()
        if not command_text:
            raise RuntimeError("Set a valid conda command first.")
        lowered = command_text.lower()
        if lowered.endswith(".bat") or lowered.endswith(".cmd"):
            return ["cmd", "/c", command_text, *list(args)]
        return [command_text, *list(args)]

    def _set_loop_authoring_conda_env(self, env_name):
        combo = getattr(self, "loop_author_conda_env_combo", None)
        if combo is None:
            return
        wanted = str(env_name or "").strip()
        combo.blockSignals(True)
        try:
            matched_index = -1
            for index in range(combo.count()):
                item_text = str(combo.itemText(index) or "").strip()
                item_data = combo.itemData(index, QtCore.Qt.UserRole)
                item_value = str(item_data.get("value", "") or "").strip() if isinstance(item_data, dict) else ""
                if wanted and (wanted == item_text or wanted == item_value):
                    matched_index = index
                    break
            if matched_index >= 0:
                combo.setCurrentIndex(matched_index)
            else:
                combo.setEditText(wanted)
        finally:
            combo.blockSignals(False)

    def _collect_loop_authoring_conda_env_entries(self, payload):
        entries = []
        root_prefix = str(payload.get("root_prefix", "") or "").strip().rstrip("\\/")
        seen = set()
        for raw_path in list(payload.get("envs") or []):
            env_path_text = str(raw_path or "").strip()
            if not env_path_text:
                continue
            normalized_key = env_path_text.rstrip("\\/").lower()
            if normalized_key in seen:
                continue
            seen.add(normalized_key)
            env_path = Path(env_path_text)
            if normalized_key == root_prefix.lower():
                entries.append(("base", {"mode": "name", "value": "base"}))
                continue
            if env_path.parent.name.lower() == "envs":
                label = env_path.name.strip()
                value = label
                mode = "name"
            else:
                label = f"{env_path.name} ({env_path_text})"
                value = env_path_text
                mode = "prefix"
            if label:
                entries.append((label, {"mode": mode, "value": value}))
        return entries

    def refresh_loop_authoring_conda_env_list(self):
        if self._is_shell_preview():
            return
        combo = getattr(self, "loop_author_conda_env_combo", None)
        if combo is None:
            return
        current_text = self._get_loop_authoring_conda_env()
        current_mode = self._get_loop_authoring_conda_env_mode()
        conda_command = str(self.loop_author_conda_command_edit.text() or "").strip() if hasattr(self, "loop_author_conda_command_edit") else "conda"
        env_entries = []
        if conda_command and (Path(conda_command).exists() or shutil.which(conda_command)):
            try:
                commands_to_try = [
                    self._build_conda_invocation(conda_command, "env", "list", "--json"),
                    self._build_conda_invocation(conda_command, "info", "--envs", "--json"),
                    self._build_conda_invocation(conda_command, "env", "list"),
                ]
                for command in commands_to_try:
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=20,
                    )
                    if completed.returncode != 0:
                        continue
                    stdout = str(completed.stdout or "").strip()
                    if not stdout:
                        continue
                    if "--json" in command:
                        try:
                            payload = json.loads(stdout or "{}")
                        except Exception:
                            payload = {}
                        env_entries = self._collect_loop_authoring_conda_env_entries(payload)
                    else:
                        seen = set()
                        for raw_line in stdout.splitlines():
                            line = str(raw_line or "").strip()
                            if not line or line.startswith("#"):
                                continue
                            parts = line.replace("*", " ").split()
                            if len(parts) >= 2:
                                name = parts[0].strip()
                                path_text = parts[-1].strip()
                                if name.endswith(":") or "\\" in name or "/" in name:
                                    name = ""
                                if name == "base":
                                    entry = ("base", {"mode": "name", "value": "base"})
                                elif name:
                                    entry = (name, {"mode": "name", "value": name})
                                elif path_text:
                                    env_path = Path(path_text)
                                    entry = (f"{env_path.name} ({path_text})", {"mode": "prefix", "value": path_text})
                                else:
                                    entry = None
                                if entry is not None:
                                    key = (entry[0], entry[1]["mode"], entry[1]["value"])
                                    if key not in seen:
                                        env_entries.append(entry)
                                        seen.add(key)
                    if env_entries:
                        break
            except Exception:
                pass
        combo.blockSignals(True)
        try:
            combo.clear()
            matched_index = -1
            for index, (label, data) in enumerate(env_entries):
                combo.addItem(label, data)
                if current_text and current_mode == str(data.get("mode", "name") or "name") and current_text == str(data.get("value", "") or ""):
                    matched_index = index
                elif current_text and current_text == label:
                    matched_index = index
            if matched_index >= 0:
                combo.setCurrentIndex(matched_index)
            elif combo.count() > 0 and current_text.lower() not in {"", "wan2gp"}:
                combo.setEditText(current_text)
            elif combo.count() > 0:
                combo.setCurrentIndex(0)
            elif current_text:
                combo.setEditText(current_text)
        finally:
            combo.blockSignals(False)
        self._update_loop_authoring_destination_hint()

    def _refresh_loop_authoring_runtime_mode_ui(self, *_args):
        use_python = self._get_loop_authoring_runtime_mode() != "conda"
        for widget_name in ("loop_author_wan2gp_python_edit", "btn_loop_author_wan2gp_python"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(use_python)
        for widget_name in ("loop_author_conda_env_combo", "btn_loop_author_conda_env_refresh", "loop_author_conda_command_edit", "btn_loop_author_conda_command"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(not use_python)
        if not use_python:
            self.refresh_loop_authoring_conda_env_list()

    def _build_loop_authoring_wan2gp_command_prefix(self):
        if self._get_loop_authoring_runtime_mode() == "conda":
            conda_env = self._get_loop_authoring_conda_env()
            conda_env_mode = self._get_loop_authoring_conda_env_mode()
            conda_command = str(self.loop_author_conda_command_edit.text() or "").strip() if hasattr(self, "loop_author_conda_command_edit") else "conda"
            if not conda_env:
                raise RuntimeError("Set a Wan2GP conda environment first.")
            if not conda_command:
                raise RuntimeError("Set a valid conda command first.")
            if not (Path(conda_command).exists() or shutil.which(conda_command)):
                raise RuntimeError(f"Could not find conda command: {conda_command}")
            flag = "-p" if conda_env_mode == "prefix" else "-n"
            return self._build_conda_invocation(conda_command, "run", flag, conda_env, "python")
        python_path = str(self.loop_author_wan2gp_python_edit.text() or "").strip() if hasattr(self, "loop_author_wan2gp_python_edit") else ""
        if not python_path or not Path(python_path).exists():
            raise RuntimeError("Set a valid Wan2GP Python path first.")
        return [python_path]

    def _get_loop_authoring_source_image_name(self):
        if not hasattr(self, "loop_author_source_image_edit"):
            return ""
        path_text = str(self.loop_author_source_image_edit.text() or "").strip()
        return Path(path_text).name if path_text else ""

    def _get_loop_authoring_wan2gp_root(self):
        if not hasattr(self, "loop_author_wan2gp_root_edit"):
            return None
        text = str(self.loop_author_wan2gp_root_edit.text() or "").strip()
        if not text:
            return None
        return Path(text)

    def _get_loop_authoring_wan2gp_outputs_dir(self):
        return loop_authoring.wan2gp_outputs_dir(self._get_loop_authoring_wan2gp_root())

    def _get_loop_authoring_wan2gp_profile_key(self):
        if not hasattr(self, "loop_author_wan2gp_profile_combo"):
            return "i2v_2_2"
        return str(self.loop_author_wan2gp_profile_combo.currentData() or "i2v_2_2")

    def _get_loop_authoring_sequence_strategy(self):
        if not hasattr(self, "loop_author_sequence_strategy_combo"):
            return "single_run"
        return str(self.loop_author_sequence_strategy_combo.currentData() or "single_run")

    def _get_loop_authoring_continuation_source_mode(self):
        if not hasattr(self, "loop_author_continuation_source_combo"):
            return "full_prefix"
        return str(self.loop_author_continuation_source_combo.currentData() or "full_prefix")

    def _get_loop_authoring_single_run_window_size_override(self):
        if not hasattr(self, "loop_author_window_size_spin"):
            return None
        value = int(self.loop_author_window_size_spin.value())
        return None if value <= 0 else value

    def _get_loop_authoring_single_run_window_overlap_override(self):
        if not hasattr(self, "loop_author_window_overlap_spin"):
            return None
        value = int(self.loop_author_window_overlap_spin.value())
        return None if value <= 0 else value

    def _get_loop_authoring_start_from_reference_video(self):
        return bool(
            hasattr(self, "loop_author_start_from_video_checkbox")
            and self.loop_author_start_from_video_checkbox.isChecked()
        )

    def _update_loop_authoring_help_tooltips(self):
        strategy = self._get_loop_authoring_sequence_strategy()
        continuation_mode = self._get_loop_authoring_continuation_source_mode()
        segments_active = strategy == "continue_segments"
        tail_mode_active = segments_active and continuation_mode == "tail_context"

        sequence_tip = (
            "Single Run keeps one Wan2GP job alive and uses its internal sliding-window logic for long clips.\n\n"
            "Continue Video Segments runs shorter jobs and continues from earlier renders, which is easier to inspect "
            "and can be safer for very long sequences."
        )
        continuation_tip = (
            "Last Rendered Video (Quality): feeds the full previously rendered clip back into the next continuation. "
            "Best for visual consistency, but RAM grows faster.\n\n"
            "Tail Context Only (Memory-Safe): only feeds the last few seconds into the next continuation. "
            "Safer for long runs, but it can drift sooner."
        )
        segment_tip = (
            "Length of each continuation chunk when Long Sequence is set to Continue Video Segments. "
            "For example, 6 seconds means the app will keep extending the sequence in 6-second steps."
        )
        window_tip = (
            "Only used in Single Run mode. 0 keeps the Wan2GP profile default window size. "
            "Larger windows can improve continuity, but they usually cost more RAM."
        )
        overlap_tip = (
            "Only used in Single Run mode. 0 keeps the Wan2GP profile default overlap. "
            "Higher overlap can smooth transitions between windows, but it adds more repeated frames of work."
        )
        tail_tip = (
            "Only used in Tail Context Only mode. This is how many seconds from the end of the current render "
            "are passed into the next continuation job."
        )
        reanchor_tip = (
            "Only used in Tail Context Only mode. Every N segments, continuation hard-resets back to the source. "
            "Useful for experiments, but not seamless."
        )
        draft_tip = (
            "Name of the draft package folder under LoopAuthoring/drafts. "
            "Use something stable so it is easy to find and reuse later."
        )

        for widget in (
            getattr(self, "loop_author_sequence_strategy_section", None),
            getattr(self, "loop_author_sequence_strategy_combo", None),
        ):
            if widget is not None:
                widget.setToolTip(sequence_tip)
        for widget in (
            getattr(self, "loop_author_continuation_source_section", None),
            getattr(self, "loop_author_continuation_source_combo", None),
        ):
            if widget is not None:
                widget.setToolTip(continuation_tip)
        for widget in (
            getattr(self, "loop_author_segment_duration_section", None),
            getattr(self, "loop_author_segment_duration_spin", None),
        ):
            if widget is not None:
                widget.setToolTip(segment_tip)
        for widget in (
            getattr(self, "loop_author_window_size_section", None),
            getattr(self, "loop_author_window_size_spin", None),
        ):
            if widget is not None:
                widget.setToolTip(window_tip if strategy == "single_run" else "Single Run only. 0 keeps the Wan2GP profile default window size.")
        for widget in (
            getattr(self, "loop_author_window_overlap_section", None),
            getattr(self, "loop_author_window_overlap_spin", None),
        ):
            if widget is not None:
                widget.setToolTip(overlap_tip if strategy == "single_run" else "Single Run only. 0 keeps the Wan2GP profile default overlap.")
        for widget in (
            getattr(self, "loop_author_tail_context_section", None),
            getattr(self, "loop_author_tail_context_spin", None),
        ):
            if widget is not None:
                widget.setToolTip(tail_tip if tail_mode_active else "Only active in Tail Context Only mode.")
        for widget in (
            getattr(self, "loop_author_anchor_refresh_section", None),
            getattr(self, "loop_author_anchor_refresh_spin", None),
        ):
            if widget is not None:
                widget.setToolTip(reanchor_tip if tail_mode_active else "Only active in Tail Context Only mode.")
        for widget in (
            getattr(self, "loop_author_output_id_section", None),
            getattr(self, "loop_author_output_id_edit", None),
        ):
            if widget is not None:
                widget.setToolTip(draft_tip)

    def _sync_loop_authoring_continuation_controls(self):
        strategy = self._get_loop_authoring_sequence_strategy()
        continuation_mode = self._get_loop_authoring_continuation_source_mode()
        segments_active = strategy == "continue_segments"
        tail_mode_active = segments_active and continuation_mode == "tail_context"
        if hasattr(self, "loop_author_continuation_source_section"):
            self.loop_author_continuation_source_section.setVisible(segments_active)
        if hasattr(self, "loop_author_segment_duration_section"):
            self.loop_author_segment_duration_section.setVisible(segments_active)
        if hasattr(self, "loop_author_window_size_section"):
            self.loop_author_window_size_section.setVisible(strategy == "single_run")
        if hasattr(self, "loop_author_window_overlap_section"):
            self.loop_author_window_overlap_section.setVisible(strategy == "single_run")
        if hasattr(self, "loop_author_continuation_source_combo"):
            self.loop_author_continuation_source_combo.setEnabled(segments_active)
        if hasattr(self, "loop_author_window_size_spin"):
            self.loop_author_window_size_spin.setEnabled(strategy == "single_run")
        if hasattr(self, "loop_author_window_overlap_spin"):
            self.loop_author_window_overlap_spin.setEnabled(strategy == "single_run")
        if hasattr(self, "loop_author_tail_context_section"):
            self.loop_author_tail_context_section.setVisible(tail_mode_active)
        if hasattr(self, "loop_author_tail_context_spin"):
            self.loop_author_tail_context_spin.setEnabled(tail_mode_active)
        if hasattr(self, "loop_author_anchor_refresh_section"):
            self.loop_author_anchor_refresh_section.setVisible(tail_mode_active)
        if hasattr(self, "loop_author_anchor_refresh_spin"):
            self.loop_author_anchor_refresh_spin.setEnabled(tail_mode_active)
        if hasattr(self, "loop_author_continuation_hint_label"):
            self.loop_author_continuation_hint_label.setVisible(False)
        self._update_loop_authoring_help_tooltips()

    def _recommended_loop_authoring_wan2gp_memory_profile(self):
        total_vram = None
        if self.context is not None:
            try:
                total_vram = self.context.avatar.snapshot().get("detected_gpu_vram_gib")
            except Exception:
                total_vram = None
        profile_key = self._get_loop_authoring_wan2gp_profile_key()
        if total_vram is not None and total_vram >= 23.0 and profile_key in {"i2v_2_2", "ti2v_2_2", "vace_14B_2_2"}:
            return "3.5"
        return "4"

    def _get_loop_authoring_wan2gp_memory_profile(self):
        if not hasattr(self, "loop_author_wan2gp_memory_combo"):
            return self._recommended_loop_authoring_wan2gp_memory_profile()
        selected = str(self.loop_author_wan2gp_memory_combo.currentData() or "auto")
        if selected == "auto":
            return self._recommended_loop_authoring_wan2gp_memory_profile()
        return selected

    def _get_loop_authoring_wan2gp_reserved_mem_max(self):
        if not hasattr(self, "loop_author_wan2gp_reserved_mem_combo"):
            return None
        selected = str(self.loop_author_wan2gp_reserved_mem_combo.currentData() or "auto")
        if selected == "auto":
            return None
        return selected

    def _get_default_loop_authoring_output_id(self):
        return loop_authoring.sanitize_output_id(
            "",
            fallback=f"{self._get_loop_authoring_preset_key()}_loop",
        )

    def _compute_loop_authoring_output_id(self):
        raw_value = self.loop_author_output_id_edit.text() if hasattr(self, "loop_author_output_id_edit") else ""
        fallback = self._get_default_loop_authoring_output_id()
        return loop_authoring.sanitize_output_id(raw_value, fallback=fallback)

    def _compute_loop_authoring_draft_dir(self):
        return loop_authoring.default_draft_dir(self._compute_loop_authoring_output_id())

    def _set_loop_author_prompt_text(self, value):
        if not hasattr(self, "loop_author_prompt_edit"):
            return
        self._loop_author_prompt_updating = True
        try:
            self.loop_author_prompt_edit.setPlainText(str(value or ""))
        finally:
            self._loop_author_prompt_updating = False

    def _set_loop_author_negative_prompt_text(self, value):
        if not hasattr(self, "loop_author_negative_prompt_edit"):
            return
        self._loop_author_prompt_updating = True
        try:
            self.loop_author_negative_prompt_edit.setPlainText(str(value or ""))
        finally:
            self._loop_author_prompt_updating = False

    def _set_loop_author_output_id(self, value):
        if not hasattr(self, "loop_author_output_id_edit"):
            return
        self._loop_author_output_id_updating = True
        try:
            self.loop_author_output_id_edit.setText(str(value or ""))
        finally:
            self._loop_author_output_id_updating = False

    def _sync_loop_author_output_id_from_preset(self, force=False):
        if not hasattr(self, "loop_author_output_id_edit"):
            return
        if self._loop_author_output_id_manual_override and not force:
            return
        self._set_loop_author_output_id(self._get_default_loop_authoring_output_id())
        self._loop_author_output_id_manual_override = False

    def _on_loop_author_output_id_changed(self, _text):
        if self._loop_author_output_id_updating:
            self._update_loop_authoring_destination_hint()
            return
        clean_current = self._compute_loop_authoring_output_id()
        self._loop_author_output_id_manual_override = clean_current != self._get_default_loop_authoring_output_id()
        self._update_loop_authoring_destination_hint()

    def _on_loop_author_prompt_changed(self):
        if self._loop_author_prompt_updating:
            return
        if not hasattr(self, "loop_author_prompt_edit"):
            return
        expected_prompt = loop_authoring.build_prompt(
            self._get_loop_authoring_preset_key(),
            duration_seconds=int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else 8,
            motion_level=self.loop_author_motion_combo.currentText() if hasattr(self, "loop_author_motion_combo") else "Gentle",
            source_image_name=self._get_loop_authoring_source_image_name(),
        ).strip()
        current_prompt = self.loop_author_prompt_edit.toPlainText().strip()
        self._loop_author_prompt_manual_override = current_prompt != expected_prompt

    def _on_loop_author_negative_prompt_changed(self):
        if self._loop_author_prompt_updating:
            return
        if not hasattr(self, "loop_author_negative_prompt_edit"):
            return
        expected_negative = loop_authoring.build_negative_prompt(self._get_loop_authoring_preset_key()).strip()
        current_negative = self.loop_author_negative_prompt_edit.toPlainText().strip()
        self._loop_author_negative_prompt_manual_override = current_negative != expected_negative

    def _on_loop_author_preset_changed(self, _index):
        self._sync_loop_author_output_id_from_preset(force=False)
        self._set_loop_author_prompt_text(
            loop_authoring.build_prompt(
                self._get_loop_authoring_preset_key(),
                duration_seconds=int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else 8,
                motion_level=self.loop_author_motion_combo.currentText() if hasattr(self, "loop_author_motion_combo") else "Gentle",
                source_image_name=self._get_loop_authoring_source_image_name(),
            )
        )
        self._loop_author_prompt_manual_override = False
        self._set_loop_author_negative_prompt_text(
            loop_authoring.build_negative_prompt(self._get_loop_authoring_preset_key())
        )
        self._loop_author_negative_prompt_manual_override = False
        self._refresh_loop_authoring_recommendation()

    def _refresh_loop_authoring_recommendation(self):
        if not hasattr(self, "loop_author_recommendation_label"):
            return
        self._sync_loop_authoring_continuation_controls()
        preset = loop_authoring.get_preset(self._get_loop_authoring_preset_key())
        summary = f"Recommended: {preset.recommended_duration_seconds}s, {preset.recommended_motion} motion."
        strategy = self._get_loop_authoring_sequence_strategy()
        if strategy == "continue_segments":
            segment_seconds = int(self.loop_author_segment_duration_spin.value()) if hasattr(self, "loop_author_segment_duration_spin") else 8
            continuation_mode = self._get_loop_authoring_continuation_source_mode()
            starts_from_video = self._get_loop_authoring_start_from_reference_video()
            if continuation_mode == "full_prefix":
                if starts_from_video:
                    summary = f"{summary} Segments: {segment_seconds}s from selected start video."
                else:
                    summary = f"{summary} Segments: {segment_seconds}s, last rendered video."
            else:
                tail_context_seconds = int(self.loop_author_tail_context_spin.value()) if hasattr(self, "loop_author_tail_context_spin") else 6
                anchor_refresh_every = int(self.loop_author_anchor_refresh_spin.value()) if hasattr(self, "loop_author_anchor_refresh_spin") else 0
                if starts_from_video:
                    summary = f"{summary} Segments: {segment_seconds}s from selected start video, tail {tail_context_seconds}s."
                else:
                    summary = f"{summary} Segments: {segment_seconds}s, tail {tail_context_seconds}s."
                if anchor_refresh_every > 0:
                    summary = f"{summary} Re-anchor every {anchor_refresh_every}."
        else:
            summary = f"{summary} Single run."
            window_override = self._get_loop_authoring_single_run_window_size_override()
            overlap_override = self._get_loop_authoring_single_run_window_overlap_override()
            if window_override is None:
                summary = f"{summary} Window: Auto."
            else:
                summary = f"{summary} Window: {window_override} frames."
            if overlap_override is None:
                summary = f"{summary} Overlap: Auto."
            else:
                summary = f"{summary} Overlap: {overlap_override}."
        memory_profile = self._get_loop_authoring_wan2gp_memory_profile()
        selected_memory = (
            str(self.loop_author_wan2gp_memory_combo.currentData() or "auto")
            if hasattr(self, "loop_author_wan2gp_memory_combo")
            else "auto"
        )
        if selected_memory == "auto":
            summary = f"{summary} Memory: Auto -> {memory_profile}."
        else:
            summary = f"{summary} Memory: {memory_profile}."
        self.loop_author_recommendation_label.setText(summary)
        self._update_loop_authoring_destination_hint()

    def _update_loop_authoring_destination_hint(self):
        if not hasattr(self, "loop_author_destination_label"):
            return
        draft_dir = self._compute_loop_authoring_draft_dir()
        lines = [f"Draft Package: {draft_dir}", f"Draft ID: {self._compute_loop_authoring_output_id()}"]
        strategy = self._get_loop_authoring_sequence_strategy()
        if strategy == "continue_segments":
            segment_seconds = int(self.loop_author_segment_duration_spin.value()) if hasattr(self, "loop_author_segment_duration_spin") else 8
            lines.append(f"Long Sequence: Continue Video Segments ({segment_seconds}s)")
            continuation_mode = self._get_loop_authoring_continuation_source_mode()
            if self._get_loop_authoring_start_from_reference_video():
                lines.append("Initial Source: Selected Reference Video")
            else:
                lines.append("Initial Source: Source Image")
            if continuation_mode == "full_prefix":
                lines.append("Continuation Source: Last Rendered Video")
            else:
                tail_context_seconds = int(self.loop_author_tail_context_spin.value()) if hasattr(self, "loop_author_tail_context_spin") else 6
                anchor_refresh_every = int(self.loop_author_anchor_refresh_spin.value()) if hasattr(self, "loop_author_anchor_refresh_spin") else 0
                lines.append(f"Continuation Source: Tail Context ({tail_context_seconds}s)")
                if anchor_refresh_every > 0:
                    lines.append(f"Re-anchor Every: {anchor_refresh_every} segments")
        else:
            lines.append("Long Sequence: Single Run (Sliding Window)")
            window_override = self._get_loop_authoring_single_run_window_size_override()
            overlap_override = self._get_loop_authoring_single_run_window_overlap_override()
            if window_override is None:
                lines.append("Sliding Window Size: Profile Default")
            else:
                lines.append(f"Sliding Window Size: {window_override}")
            if overlap_override is None:
                lines.append("Sliding Window Overlap: Profile Default")
            else:
                lines.append(f"Sliding Window Overlap: {overlap_override}")
        if hasattr(self, "loop_author_source_image_edit"):
            source_text = str(self.loop_author_source_image_edit.text() or "").strip()
            if source_text:
                lines.append(f"Source Image: {source_text}")
        if hasattr(self, "loop_author_reference_video_edit"):
            reference_text = str(self.loop_author_reference_video_edit.text() or "").strip()
            if reference_text:
                lines.append(f"Reference Video: {reference_text}")
        wan2gp_root = self._get_loop_authoring_wan2gp_root()
        if wan2gp_root is not None:
            lines.append(f"Wan2GP Root: {wan2gp_root}")
        if self._get_loop_authoring_runtime_mode() == "conda":
            conda_env = self._get_loop_authoring_conda_env()
            conda_command = str(self.loop_author_conda_command_edit.text() or "").strip() if hasattr(self, "loop_author_conda_command_edit") else "conda"
            lines.append(f"Wan2GP Runtime: Conda ({conda_env or 'env not set'})")
            lines.append(f"Conda Command: {conda_command or 'conda'}")
        else:
            python_path = str(self.loop_author_wan2gp_python_edit.text() or "").strip() if hasattr(self, "loop_author_wan2gp_python_edit") else ""
            if python_path:
                lines.append(f"Wan2GP Python: {python_path}")
        if hasattr(self, "loop_author_wan2gp_memory_combo"):
            selected_memory_profile = str(self.loop_author_wan2gp_memory_combo.currentData() or "auto")
            effective_memory_profile = self._get_loop_authoring_wan2gp_memory_profile()
            if selected_memory_profile == "auto":
                lines.append(f"Wan2GP Memory Profile: Auto -> {effective_memory_profile}")
            else:
                lines.append(f"Wan2GP Memory Profile: {effective_memory_profile}")
        reserved_mem_max = self._get_loop_authoring_wan2gp_reserved_mem_max()
        if reserved_mem_max is not None:
            lines.append(f"Wan2GP Reserved RAM Max: {reserved_mem_max}")
        elif hasattr(self, "loop_author_wan2gp_reserved_mem_combo"):
            lines.append("Wan2GP Reserved RAM Max: Auto")
        wan2gp_outputs = self._get_loop_authoring_wan2gp_outputs_dir()
        if wan2gp_outputs is not None:
            lines.append(f"Wan2GP Outputs: {wan2gp_outputs}")
        self.loop_author_destination_label.setText("<br>".join(lines))

    def export_session_state(self):
        return {
            "loop_author_backend": self.loop_author_backend_combo.currentText() if hasattr(self, "loop_author_backend_combo") else "Wan2GP",
            "loop_author_sequence_strategy": self.loop_author_sequence_strategy_combo.currentData() if hasattr(self, "loop_author_sequence_strategy_combo") else "single_run",
            "loop_author_continuation_source_mode": self.loop_author_continuation_source_combo.currentData() if hasattr(self, "loop_author_continuation_source_combo") else "full_prefix",
            "loop_author_start_from_reference_video": bool(self.loop_author_start_from_video_checkbox.isChecked()) if hasattr(self, "loop_author_start_from_video_checkbox") else False,
            "loop_author_wan2gp_profile": self.loop_author_wan2gp_profile_combo.currentData() if hasattr(self, "loop_author_wan2gp_profile_combo") else "i2v_2_2",
            "loop_author_wan2gp_memory_profile": self.loop_author_wan2gp_memory_combo.currentData() if hasattr(self, "loop_author_wan2gp_memory_combo") else "auto",
            "loop_author_wan2gp_reserved_mem_max": self.loop_author_wan2gp_reserved_mem_combo.currentData() if hasattr(self, "loop_author_wan2gp_reserved_mem_combo") else "auto",
            "loop_author_disable_profile_loras": bool(self.loop_author_disable_profile_loras_checkbox.isChecked()) if hasattr(self, "loop_author_disable_profile_loras_checkbox") else True,
            "loop_author_preset": self.loop_author_preset_combo.currentData() if hasattr(self, "loop_author_preset_combo") else "neutral_idle",
            "loop_author_wan2gp_root": self.loop_author_wan2gp_root_edit.text() if hasattr(self, "loop_author_wan2gp_root_edit") else "",
            "loop_author_wan2gp_runtime": self.loop_author_wan2gp_runtime_combo.currentData() if hasattr(self, "loop_author_wan2gp_runtime_combo") else "python",
            "loop_author_wan2gp_python": self.loop_author_wan2gp_python_edit.text() if hasattr(self, "loop_author_wan2gp_python_edit") else "",
            "loop_author_conda_env": self._get_loop_authoring_conda_env(),
            "loop_author_conda_env_mode": self._get_loop_authoring_conda_env_mode(),
            "loop_author_conda_command": self.loop_author_conda_command_edit.text() if hasattr(self, "loop_author_conda_command_edit") else "conda",
            "loop_author_source_image": self.loop_author_source_image_edit.text() if hasattr(self, "loop_author_source_image_edit") else "",
            "loop_author_reference_video": self.loop_author_reference_video_edit.text() if hasattr(self, "loop_author_reference_video_edit") else "",
            "loop_author_output_id": self.loop_author_output_id_edit.text() if hasattr(self, "loop_author_output_id_edit") else "",
            "loop_author_duration": int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else 8,
            "loop_author_segment_duration": int(self.loop_author_segment_duration_spin.value()) if hasattr(self, "loop_author_segment_duration_spin") else 8,
            "loop_author_window_size": int(self.loop_author_window_size_spin.value()) if hasattr(self, "loop_author_window_size_spin") else 0,
            "loop_author_window_overlap": int(self.loop_author_window_overlap_spin.value()) if hasattr(self, "loop_author_window_overlap_spin") else 0,
            "loop_author_tail_context_seconds": int(self.loop_author_tail_context_spin.value()) if hasattr(self, "loop_author_tail_context_spin") else 6,
            "loop_author_anchor_refresh_every": int(self.loop_author_anchor_refresh_spin.value()) if hasattr(self, "loop_author_anchor_refresh_spin") else 0,
            "loop_author_fps": int(self.loop_author_fps_spin.value()) if hasattr(self, "loop_author_fps_spin") else 16,
            "loop_author_motion": self.loop_author_motion_combo.currentText() if hasattr(self, "loop_author_motion_combo") else "Gentle",
            "loop_author_prompt": self.loop_author_prompt_edit.toPlainText() if hasattr(self, "loop_author_prompt_edit") else "",
            "loop_author_negative_prompt": self.loop_author_negative_prompt_edit.toPlainText() if hasattr(self, "loop_author_negative_prompt_edit") else "",
        }

    def import_session_state(self, session):
        loop_author_backend = session.get("loop_author_backend")
        if loop_author_backend and hasattr(self, "loop_author_backend_combo"):
            index = self.loop_author_backend_combo.findText(str(loop_author_backend))
            if index >= 0:
                self.loop_author_backend_combo.setCurrentIndex(index)
        loop_author_sequence_strategy = session.get("loop_author_sequence_strategy")
        if loop_author_sequence_strategy and hasattr(self, "loop_author_sequence_strategy_combo"):
            for index in range(self.loop_author_sequence_strategy_combo.count()):
                if self.loop_author_sequence_strategy_combo.itemData(index) == loop_author_sequence_strategy:
                    self.loop_author_sequence_strategy_combo.setCurrentIndex(index)
                    break
        loop_author_continuation_source_mode = session.get("loop_author_continuation_source_mode")
        if loop_author_continuation_source_mode and hasattr(self, "loop_author_continuation_source_combo"):
            for index in range(self.loop_author_continuation_source_combo.count()):
                if self.loop_author_continuation_source_combo.itemData(index) == loop_author_continuation_source_mode:
                    self.loop_author_continuation_source_combo.setCurrentIndex(index)
                    break
        loop_author_start_from_reference_video = session.get("loop_author_start_from_reference_video")
        if loop_author_start_from_reference_video is not None and hasattr(self, "loop_author_start_from_video_checkbox"):
            self.loop_author_start_from_video_checkbox.setChecked(bool(loop_author_start_from_reference_video))
        loop_author_wan2gp_profile = session.get("loop_author_wan2gp_profile")
        if loop_author_wan2gp_profile and hasattr(self, "loop_author_wan2gp_profile_combo"):
            for index in range(self.loop_author_wan2gp_profile_combo.count()):
                if self.loop_author_wan2gp_profile_combo.itemData(index) == loop_author_wan2gp_profile:
                    self.loop_author_wan2gp_profile_combo.setCurrentIndex(index)
                    break
        loop_author_wan2gp_memory_profile = session.get("loop_author_wan2gp_memory_profile")
        if loop_author_wan2gp_memory_profile and hasattr(self, "loop_author_wan2gp_memory_combo"):
            for index in range(self.loop_author_wan2gp_memory_combo.count()):
                if self.loop_author_wan2gp_memory_combo.itemData(index) == loop_author_wan2gp_memory_profile:
                    self.loop_author_wan2gp_memory_combo.setCurrentIndex(index)
                    break
        loop_author_wan2gp_reserved_mem_max = session.get("loop_author_wan2gp_reserved_mem_max")
        if loop_author_wan2gp_reserved_mem_max and hasattr(self, "loop_author_wan2gp_reserved_mem_combo"):
            for index in range(self.loop_author_wan2gp_reserved_mem_combo.count()):
                if self.loop_author_wan2gp_reserved_mem_combo.itemData(index) == loop_author_wan2gp_reserved_mem_max:
                    self.loop_author_wan2gp_reserved_mem_combo.setCurrentIndex(index)
                    break
        loop_author_disable_profile_loras = session.get("loop_author_disable_profile_loras")
        if loop_author_disable_profile_loras is not None and hasattr(self, "loop_author_disable_profile_loras_checkbox"):
            self.loop_author_disable_profile_loras_checkbox.setChecked(bool(loop_author_disable_profile_loras))
        loop_author_preset = session.get("loop_author_preset")
        if loop_author_preset and hasattr(self, "loop_author_preset_combo"):
            for index in range(self.loop_author_preset_combo.count()):
                if self.loop_author_preset_combo.itemData(index) == loop_author_preset:
                    self.loop_author_preset_combo.setCurrentIndex(index)
                    break
        if hasattr(self, "loop_author_wan2gp_root_edit"):
            root_value = str(session.get("loop_author_wan2gp_root", "") or "")
            if not root_value and self._loop_author_wan2gp_root is not None:
                root_value = str(self._loop_author_wan2gp_root)
            self.loop_author_wan2gp_root_edit.setText(root_value)
        if hasattr(self, "loop_author_wan2gp_runtime_combo"):
            runtime_value = str(session.get("loop_author_wan2gp_runtime", "python") or "python")
            for index in range(self.loop_author_wan2gp_runtime_combo.count()):
                if self.loop_author_wan2gp_runtime_combo.itemData(index) == runtime_value:
                    self.loop_author_wan2gp_runtime_combo.setCurrentIndex(index)
                    break
        if hasattr(self, "loop_author_wan2gp_python_edit"):
            python_value = str(session.get("loop_author_wan2gp_python", "") or "")
            if not python_value:
                detected_python = loop_authoring.default_wan2gp_python(self._get_loop_authoring_wan2gp_root())
                if detected_python is not None:
                    python_value = str(detected_python)
            self.loop_author_wan2gp_python_edit.setText(python_value)
        if hasattr(self, "loop_author_conda_command_edit"):
            self.loop_author_conda_command_edit.setText(str(session.get("loop_author_conda_command", "conda") or "conda"))
        if hasattr(self, "loop_author_conda_env_combo"):
            self.refresh_loop_authoring_conda_env_list()
            self._set_loop_authoring_conda_env(str(session.get("loop_author_conda_env", "") or ""))
        if hasattr(self, "loop_author_source_image_edit"):
            self.loop_author_source_image_edit.setText(str(session.get("loop_author_source_image", "") or ""))
        if hasattr(self, "loop_author_reference_video_edit"):
            self.loop_author_reference_video_edit.setText(str(session.get("loop_author_reference_video", "") or ""))
        if hasattr(self, "loop_author_output_id_edit"):
            self.loop_author_output_id_edit.setText(str(session.get("loop_author_output_id", "") or ""))
            self._loop_author_output_id_manual_override = (
                self._compute_loop_authoring_output_id() != self._get_default_loop_authoring_output_id()
            )
        if hasattr(self, "loop_author_duration_spin"):
            self.loop_author_duration_spin.setValue(max(4, min(300, int(session.get("loop_author_duration", 8) or 8))))
        if hasattr(self, "loop_author_segment_duration_spin"):
            self.loop_author_segment_duration_spin.setValue(max(4, min(300, int(session.get("loop_author_segment_duration", 8) or 8))))
        if hasattr(self, "loop_author_window_size_spin"):
            self.loop_author_window_size_spin.setValue(max(0, min(512, int(session.get("loop_author_window_size", 0) or 0))))
        if hasattr(self, "loop_author_window_overlap_spin"):
            self.loop_author_window_overlap_spin.setValue(max(0, min(64, int(session.get("loop_author_window_overlap", 0) or 0))))
        if hasattr(self, "loop_author_tail_context_spin"):
            self.loop_author_tail_context_spin.setValue(max(1, min(60, int(session.get("loop_author_tail_context_seconds", 6) or 6))))
        if hasattr(self, "loop_author_anchor_refresh_spin"):
            self.loop_author_anchor_refresh_spin.setValue(max(0, min(20, int(session.get("loop_author_anchor_refresh_every", 0) or 0))))
        if hasattr(self, "loop_author_fps_spin"):
            self.loop_author_fps_spin.setValue(max(8, min(30, int(session.get("loop_author_fps", 16) or 16))))
        if hasattr(self, "loop_author_motion_combo"):
            motion_text = str(session.get("loop_author_motion", "") or "")
            index = self.loop_author_motion_combo.findText(motion_text)
            if index >= 0:
                self.loop_author_motion_combo.setCurrentIndex(index)
        if hasattr(self, "loop_author_prompt_edit"):
            self._set_loop_author_prompt_text(str(session.get("loop_author_prompt", "") or ""))
        if hasattr(self, "loop_author_negative_prompt_edit"):
            self._set_loop_author_negative_prompt_text(str(session.get("loop_author_negative_prompt", "") or ""))
        if hasattr(self, "loop_author_prompt_edit"):
            expected_prompt = loop_authoring.build_prompt(
                self._get_loop_authoring_preset_key(),
                duration_seconds=int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else 8,
                motion_level=self.loop_author_motion_combo.currentText() if hasattr(self, "loop_author_motion_combo") else "Gentle",
                source_image_name=self._get_loop_authoring_source_image_name(),
            ).strip()
            self._loop_author_prompt_manual_override = self.loop_author_prompt_edit.toPlainText().strip() not in {"", expected_prompt}
        if hasattr(self, "loop_author_negative_prompt_edit"):
            expected_negative = loop_authoring.build_negative_prompt(self._get_loop_authoring_preset_key()).strip()
            self._loop_author_negative_prompt_manual_override = self.loop_author_negative_prompt_edit.toPlainText().strip() not in {"", expected_negative}
        self._refresh_loop_authoring_runtime_mode_ui()
        self._refresh_loop_authoring_recommendation()
        if hasattr(self, "loop_author_prompt_edit") and not self.loop_author_prompt_edit.toPlainText().strip():
            self.apply_loop_authoring_template()

    def apply_loop_authoring_template(self):
        preset_key = self._get_loop_authoring_preset_key()
        preset = loop_authoring.get_preset(preset_key)
        if hasattr(self, "loop_author_output_id_edit") and not self._loop_author_output_id_manual_override:
            self._sync_loop_author_output_id_from_preset(force=True)
        if hasattr(self, "loop_author_duration_spin"):
            self.loop_author_duration_spin.setValue(preset.recommended_duration_seconds)
        if hasattr(self, "loop_author_segment_duration_spin"):
            self.loop_author_segment_duration_spin.setValue(min(max(4, preset.recommended_duration_seconds), 8))
        if hasattr(self, "loop_author_window_size_spin"):
            self.loop_author_window_size_spin.setValue(0)
        if hasattr(self, "loop_author_window_overlap_spin"):
            self.loop_author_window_overlap_spin.setValue(0)
        if hasattr(self, "loop_author_tail_context_spin"):
            self.loop_author_tail_context_spin.setValue(min(6, max(1, int(self.loop_author_segment_duration_spin.value()) if hasattr(self, "loop_author_segment_duration_spin") else 6)))
        if hasattr(self, "loop_author_anchor_refresh_spin"):
            self.loop_author_anchor_refresh_spin.setValue(0)
        if hasattr(self, "loop_author_motion_combo"):
            index = self.loop_author_motion_combo.findText(preset.recommended_motion)
            if index >= 0:
                self.loop_author_motion_combo.setCurrentIndex(index)
        if hasattr(self, "loop_author_prompt_edit"):
            self._set_loop_author_prompt_text(
                loop_authoring.build_prompt(
                    preset_key,
                    duration_seconds=int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else preset.recommended_duration_seconds,
                    motion_level=self.loop_author_motion_combo.currentText() if hasattr(self, "loop_author_motion_combo") else preset.recommended_motion,
                    source_image_name=self._get_loop_authoring_source_image_name(),
                )
            )
            self._loop_author_prompt_manual_override = False
        if hasattr(self, "loop_author_negative_prompt_edit"):
            self._set_loop_author_negative_prompt_text(loop_authoring.build_negative_prompt(preset_key))
            self._loop_author_negative_prompt_manual_override = False
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText(f"Applied template for '{preset.label}'.")
        self._refresh_loop_authoring_recommendation()

    def browse_loop_authoring_source_image(self):
        if self.dialogs is not None:
            path, _ = self.dialogs.open_file(
                "Select Loop Authoring Source Image",
                str(Path.cwd()),
                "Image Files (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select Loop Authoring Source Image",
                str(Path.cwd()),
                "Image Files (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
            )
        if path:
            self.loop_author_source_image_edit.setText(path)

    def browse_loop_authoring_reference_video(self):
        if self.dialogs is not None:
            path, _ = self.dialogs.open_file(
                "Select Optional Loop Authoring Reference Video",
                str(Path.cwd()),
                "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select Optional Loop Authoring Reference Video",
                str(Path.cwd()),
                "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)",
            )
        if path:
            self.loop_author_reference_video_edit.setText(path)

    def browse_loop_authoring_wan2gp_root(self):
        start_dir = str(self._get_loop_authoring_wan2gp_root() or Path.cwd())
        if self.dialogs is not None:
            path = self.dialogs.open_directory("Select Wan2GP Root", start_dir)
        else:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                None,
                "Select Wan2GP Root",
                start_dir,
            )
        if path:
            self.loop_author_wan2gp_root_edit.setText(path)

    def browse_loop_authoring_wan2gp_python(self):
        start_path = str(self._get_loop_authoring_wan2gp_root() or Path.cwd())
        if self.dialogs is not None:
            path, _ = self.dialogs.open_file(
                "Select Wan2GP Python",
                start_path,
                "Python Executable (python.exe);;All Files (*)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select Wan2GP Python",
                start_path,
                "Python Executable (python.exe);;All Files (*)",
            )
        if path:
            self.loop_author_wan2gp_python_edit.setText(path)

    def browse_loop_authoring_conda_command(self):
        start_path = str(Path(self.loop_author_conda_command_edit.text() or "").parent) if hasattr(self, "loop_author_conda_command_edit") and str(self.loop_author_conda_command_edit.text() or "").strip() else str(Path.cwd())
        if self.dialogs is not None:
            path, _ = self.dialogs.open_file(
                "Select Conda Command",
                start_path,
                "Conda Executable (conda.bat;conda.exe);;Batch Files (*.bat);;Executables (*.exe);;All Files (*)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select Conda Command",
                start_path,
                "Conda Executable (conda.bat;conda.exe);;Batch Files (*.bat);;Executables (*.exe);;All Files (*)",
            )
        if path and hasattr(self, "loop_author_conda_command_edit"):
            self.loop_author_conda_command_edit.setText(path)

    def _on_loop_author_wan2gp_root_changed(self, _text):
        root = self._get_loop_authoring_wan2gp_root()
        if hasattr(self, "loop_author_wan2gp_python_edit") and root is not None:
            current_python = str(self.loop_author_wan2gp_python_edit.text() or "").strip()
            detected_python = loop_authoring.default_wan2gp_python(root)
            if detected_python is not None and (not current_python or not Path(current_python).exists()):
                self.loop_author_wan2gp_python_edit.setText(str(detected_python))
        self._update_loop_authoring_destination_hint()

    def save_loop_authoring_draft(self):
        if not hasattr(self, "loop_author_source_image_edit"):
            return
        source_path = str(self.loop_author_source_image_edit.text() or "").strip()
        if not source_path:
            self._warn("Loop Authoring", "Choose a source image first.")
            return
        source_image = Path(source_path)
        if not source_image.exists():
            self._warn("Loop Authoring", f"Source image not found:\n{source_image}")
            return
        reference_text = str(self.loop_author_reference_video_edit.text() or "").strip() if hasattr(self, "loop_author_reference_video_edit") else ""
        if reference_text and not Path(reference_text).exists():
            self._warn("Loop Authoring", f"Reference video not found:\n{reference_text}")
            return

        preset_key = self._get_loop_authoring_preset_key()
        preset = loop_authoring.get_preset(preset_key)
        draft_dir = self._compute_loop_authoring_draft_dir()
        draft_dir.mkdir(parents=True, exist_ok=True)
        prompt_text = self.loop_author_prompt_edit.toPlainText().strip() if hasattr(self, "loop_author_prompt_edit") else ""
        negative_prompt_text = self.loop_author_negative_prompt_edit.toPlainText().strip() if hasattr(self, "loop_author_negative_prompt_edit") else ""
        if not prompt_text:
            prompt_text = loop_authoring.build_prompt(
                preset_key,
                duration_seconds=int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else preset.recommended_duration_seconds,
                motion_level=self.loop_author_motion_combo.currentText() if hasattr(self, "loop_author_motion_combo") else preset.recommended_motion,
                source_image_name=source_image.name,
            )
        if not negative_prompt_text:
            negative_prompt_text = loop_authoring.build_negative_prompt(preset_key)

        payload = {
            "draft_id": self._compute_loop_authoring_output_id(),
            "backend": self.loop_author_backend_combo.currentText() if hasattr(self, "loop_author_backend_combo") else "Wan2GP",
            "sequence_strategy": self._get_loop_authoring_sequence_strategy(),
            "wan2gp_root": str(self._get_loop_authoring_wan2gp_root() or ""),
            "wan2gp_runtime": self._get_loop_authoring_runtime_mode(),
            "wan2gp_python": self.loop_author_wan2gp_python_edit.text().strip() if hasattr(self, "loop_author_wan2gp_python_edit") else "",
            "wan2gp_conda_env": self._get_loop_authoring_conda_env(),
            "wan2gp_conda_command": self.loop_author_conda_command_edit.text().strip() if hasattr(self, "loop_author_conda_command_edit") else "conda",
            "preset_key": preset.key,
            "preset_label": preset.label,
            "emotion_tag": preset.emotion_tag,
            "duration_seconds": int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else preset.recommended_duration_seconds,
            "segment_duration_seconds": int(self.loop_author_segment_duration_spin.value()) if hasattr(self, "loop_author_segment_duration_spin") else min(8, preset.recommended_duration_seconds),
            "window_size_override": int(self.loop_author_window_size_spin.value()) if hasattr(self, "loop_author_window_size_spin") else 0,
            "window_overlap_override": int(self.loop_author_window_overlap_spin.value()) if hasattr(self, "loop_author_window_overlap_spin") else 0,
            "fps": int(self.loop_author_fps_spin.value()) if hasattr(self, "loop_author_fps_spin") else 16,
            "motion_level": self.loop_author_motion_combo.currentText() if hasattr(self, "loop_author_motion_combo") else preset.recommended_motion,
            "source_image": str(source_image),
            "reference_video": reference_text,
            "prompt": prompt_text,
            "negative_prompt": negative_prompt_text,
            "notes": preset.recommended_notes,
            "generated_at": round(time.time(), 3),
        }
        (draft_dir / "request.json").write_text(json.dumps(payload, indent=4), encoding="utf-8")
        (draft_dir / "prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
        (draft_dir / "negative_prompt.txt").write_text(negative_prompt_text + "\n", encoding="utf-8")
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText(f"Saved draft package '{payload['draft_id']}'.")
        print(f"[QtGUI] Loop authoring draft saved: {draft_dir}")
        self._update_loop_authoring_destination_hint()

    def _build_wan2gp_task_settings(
        self,
        *,
        seed_override=None,
        image_prompt_type_override=None,
        video_length_override=None,
        video_source_override=None,
        keep_frames_video_source_override=None,
        sliding_window_size_override=None,
        sliding_window_overlap_override=None,
        allow_missing_video_source=False,
    ):
        root = self._get_loop_authoring_wan2gp_root()
        profile_key = self._get_loop_authoring_wan2gp_profile_key()
        settings_path = loop_authoring.get_wan2gp_settings_path(root, profile_key)
        if settings_path is None or not Path(settings_path).exists():
            raise RuntimeError(f"Could not find Wan2GP settings for profile '{profile_key}'.")

        try:
            payload = json.loads(Path(settings_path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Could not read Wan2GP settings file '{settings_path}': {exc}") from exc

        prompt_text = self.loop_author_prompt_edit.toPlainText().strip() if hasattr(self, "loop_author_prompt_edit") else ""
        negative_prompt_text = self.loop_author_negative_prompt_edit.toPlainText().strip() if hasattr(self, "loop_author_negative_prompt_edit") else ""
        source_image = str(self.loop_author_source_image_edit.text() or "").strip() if hasattr(self, "loop_author_source_image_edit") else ""
        reference_video = str(self.loop_author_reference_video_edit.text() or "").strip() if hasattr(self, "loop_author_reference_video_edit") else ""
        image_prompt_type = str(image_prompt_type_override or payload.get("image_prompt_type") or "S")
        fps_value = int(self.loop_author_fps_spin.value()) if hasattr(self, "loop_author_fps_spin") else int(payload.get("force_fps") or 16)
        total_frames = int(video_length_override if video_length_override is not None else (int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else int(payload.get("video_length") or 125)) * fps_value)

        if image_prompt_type == "S":
            if not source_image:
                raise RuntimeError("Choose a source image first.")
            if not Path(source_image).exists():
                raise RuntimeError(f"Source image not found: {source_image}")
            payload["image_start"] = source_image
            payload["video_source"] = None
        else:
            video_source = str(video_source_override or reference_video or "").strip()
            if not video_source and not allow_missing_video_source:
                raise RuntimeError("No continuation video was available for this Wan2GP segment.")
            if video_source and video_source != "__TO_BE_FILLED_BY_PREVIOUS_OUTPUT__" and not Path(video_source).exists():
                raise RuntimeError(f"Continuation video not found: {video_source}")
            payload["image_start"] = None
            payload["video_source"] = video_source or None

        payload["prompt"] = prompt_text
        payload["negative_prompt"] = negative_prompt_text
        payload["image_prompt_type"] = image_prompt_type
        payload["video_length"] = max(1, int(total_frames))
        payload["force_fps"] = str(max(1, int(fps_value)))
        payload["seed"] = int(seed_override if seed_override is not None else payload.get("seed") or random.randint(1, 2_147_483_647))
        payload["model_type"] = str(payload.get("model_type") or profile_key)
        payload["keep_frames_video_source"] = (
            str(keep_frames_video_source_override)
            if keep_frames_video_source_override is not None
            else str(payload.get("keep_frames_video_source") or "")
        )
        if sliding_window_size_override is not None:
            payload["sliding_window_size"] = max(1, int(sliding_window_size_override))
        if sliding_window_overlap_override is not None:
            payload["sliding_window_overlap"] = max(1, int(sliding_window_overlap_override))

        if hasattr(self, "loop_author_disable_profile_loras_checkbox") and self.loop_author_disable_profile_loras_checkbox.isChecked():
            payload["activated_loras"] = []

        return payload

    def generate_loop_in_wan2gp(self):
        root = self._get_loop_authoring_wan2gp_root()
        if root is None or not (root / "wgp.py").exists():
            self._warn("Loop Authoring", "Set a valid Wan2GP root first.")
            return
        try:
            command_prefix = self._build_loop_authoring_wan2gp_command_prefix()
        except RuntimeError as exc:
            self._warn("Loop Authoring", str(exc))
            return
        if self._loop_author_generation_thread is not None and self._loop_author_generation_thread.is_alive():
            self._info("Loop Authoring", "A Wan2GP generation is already in progress.")
            return
        draft_dir = self._compute_loop_authoring_draft_dir()
        draft_dir.mkdir(parents=True, exist_ok=True)
        task_entries = []
        try:
            fps_value = int(self.loop_author_fps_spin.value()) if hasattr(self, "loop_author_fps_spin") else 16
            total_seconds = int(self.loop_author_duration_spin.value()) if hasattr(self, "loop_author_duration_spin") else 8
            total_frames = max(1, total_seconds * fps_value)
            strategy = self._get_loop_authoring_sequence_strategy()
            segment_seconds = int(self.loop_author_segment_duration_spin.value()) if hasattr(self, "loop_author_segment_duration_spin") else 8
            segment_frames = max(1, segment_seconds * fps_value)
            starts_from_reference_video = self._get_loop_authoring_start_from_reference_video()
            initial_reference_video = str(self.loop_author_reference_video_edit.text() or "").strip() if hasattr(self, "loop_author_reference_video_edit") else ""
            initial_reference_frames = 0

            def probe_initial_video_frames(video_path):
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(video_path),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if probe.returncode != 0:
                    raise RuntimeError((probe.stderr or probe.stdout or f"ffprobe failed for {video_path}").strip())
                try:
                    duration_seconds = max(0.0, float((probe.stdout or "").strip()))
                except Exception as exc:
                    raise RuntimeError(f"Could not parse duration for initial source video: {exc}") from exc
                return max(1, int(round(duration_seconds * fps_value)))

            if starts_from_reference_video:
                if not initial_reference_video:
                    raise RuntimeError("Choose a reference video first if you want to start from an existing video.")
                if not Path(initial_reference_video).exists():
                    raise RuntimeError(f"Initial source video not found: {initial_reference_video}")
                initial_reference_frames = probe_initial_video_frames(initial_reference_video)
                if initial_reference_frames >= total_frames:
                    raise RuntimeError(
                        f"The selected start video already covers about {initial_reference_frames / max(1, fps_value):.2f}s, "
                        f"which is at least the requested {total_seconds}s."
                    )
            if strategy == "continue_segments":
                seed_value = random.randint(1, 2_147_483_647)
                overlap_frames = 5
                try:
                    seed_payload = self._build_wan2gp_task_settings(seed_override=seed_value)
                    overlap_frames = max(1, int(seed_payload.get("sliding_window_overlap", 5) or 5))
                except Exception:
                    seed_payload = None
            remaining_total_frames = max(0, total_frames - initial_reference_frames)
            if strategy == "continue_segments" and remaining_total_frames > 0:
                plan_frames = []
                remaining_frames = remaining_total_frames
                while remaining_frames > 0:
                    chunk_frames = min(segment_frames, remaining_frames)
                    plan_frames.append(chunk_frames)
                    remaining_frames -= chunk_frames
                payload_plan = {
                    "mode": "continue_segments",
                    "seed": seed_value,
                    "fps": fps_value,
                    "segment_frames": plan_frames,
                    "sliding_window_size": segment_frames,
                    "overlap_frames": overlap_frames,
                    "continuation_source_mode": self._get_loop_authoring_continuation_source_mode(),
                    "initial_source_mode": "reference_video" if starts_from_reference_video else "source_image",
                    "initial_source_frames": initial_reference_frames,
                    "tail_context_seconds": int(self.loop_author_tail_context_spin.value()) if hasattr(self, "loop_author_tail_context_spin") else 6,
                    "anchor_refresh_every": int(self.loop_author_anchor_refresh_spin.value()) if hasattr(self, "loop_author_anchor_refresh_spin") else 0,
                }
                previous_video = initial_reference_video if starts_from_reference_video else None
                for index, frames_for_segment in enumerate(plan_frames, start=1):
                    if previous_video:
                        task_payload = self._build_wan2gp_task_settings(
                            video_source_override=previous_video,
                            image_prompt_type_override="V",
                            video_length_override=frames_for_segment,
                            seed_override=seed_value,
                            keep_frames_video_source_override=f"-{overlap_frames}",
                            sliding_window_size_override=frames_for_segment,
                            allow_missing_video_source=True,
                        )
                    else:
                        task_payload = self._build_wan2gp_task_settings(
                            image_prompt_type_override="S",
                            video_length_override=frames_for_segment,
                            seed_override=seed_value,
                            sliding_window_size_override=frames_for_segment,
                        )
                    task_entries.append({
                        "filename": f"wan2gp_task_part{index:02d}.json",
                        "label": f"segment_{index}",
                        "payload": task_payload,
                        "continue_mode": bool(previous_video),
                    })
                    previous_video = "__TO_BE_FILLED_BY_PREVIOUS_OUTPUT__"
                settings_json_path = draft_dir / "wan2gp_task_plan.json"
                settings_json_path.write_text(json.dumps(payload_plan, indent=4), encoding="utf-8")
            else:
                payload = self._build_wan2gp_task_settings(
                    sliding_window_size_override=self._get_loop_authoring_single_run_window_size_override(),
                    sliding_window_overlap_override=self._get_loop_authoring_single_run_window_overlap_override(),
                )
                task_entries.append({
                    "filename": "wan2gp_task.json",
                    "label": "single_run",
                    "payload": payload,
                    "continue_mode": False,
                })
                settings_json_path = draft_dir / "wan2gp_task.json"
                settings_json_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
        except Exception as exc:
            self._warn("Loop Authoring", str(exc))
            return
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText("Launching Wan2GP headless generation...")
        continuation_source_mode = self._get_loop_authoring_continuation_source_mode()
        tail_context_seconds = (
            int(self.loop_author_tail_context_spin.value()) if continuation_source_mode == "tail_context" and hasattr(self, "loop_author_tail_context_spin") else 0
        )
        anchor_refresh_every = (
            int(self.loop_author_anchor_refresh_spin.value()) if continuation_source_mode == "tail_context" and hasattr(self, "loop_author_anchor_refresh_spin") else 0
        )
        loop_author_source_image_path = ""
        try:
            loop_author_source_image_path = str(task_entries[0]["payload"].get("image_start") or "")
        except Exception:
            loop_author_source_image_path = str(self.loop_author_source_image_edit.text() or "").strip() if hasattr(self, "loop_author_source_image_edit") else ""

        def worker():
            result = {"ok": False, "error": "", "output_dir": str(draft_dir), "settings_json": str(settings_json_path)}
            try:
                base_command = list(command_prefix) + [
                    str((root / "wgp.py").resolve()),
                    "--process",
                ]
                reserved_mem_max = self._get_loop_authoring_wan2gp_reserved_mem_max()
                base_tail = [
                    "--output-dir",
                    str(draft_dir.resolve()),
                    "--profile",
                    str(self._get_loop_authoring_wan2gp_memory_profile()),
                ]
                if reserved_mem_max is not None:
                    base_tail.extend(["--perc-reserved-mem-max", str(reserved_mem_max)])
                env = os.environ.copy()
                alloc_conf = str(env.get("PYTORCH_CUDA_ALLOC_CONF", "") or "").strip()
                if "expandable_segments:True" not in alloc_conf:
                    env["PYTORCH_CUDA_ALLOC_CONF"] = (
                        f"{alloc_conf},expandable_segments:True" if alloc_conf else "expandable_segments:True"
                    )

                def find_newest_video(exclude_paths):
                    candidates = [
                        child.resolve()
                        for child in draft_dir.rglob("*")
                        if child.is_file() and child.suffix.lower() in loop_authoring.LOOP_AUTHORING_OUTPUT_EXTENSIONS
                    ]
                    new_candidates = [child for child in candidates if str(child) not in exclude_paths]
                    if new_candidates:
                        new_candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
                        return new_candidates[0]
                    if candidates:
                        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
                        return candidates[0]
                    return None

                def run_local_command(command, *, label):
                    completed = subprocess.run(
                        command,
                        cwd=str(draft_dir),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    return {
                        "label": label,
                        "command": " ".join(command),
                        "stdout": completed.stdout or "",
                        "stderr": completed.stderr or "",
                        "returncode": int(completed.returncode),
                    }

                def probe_duration_seconds(video_path):
                    probe = run_local_command(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=noprint_wrappers=1:nokey=1",
                            str(video_path),
                        ],
                        label="ffprobe_duration",
                    )
                    if probe["returncode"] != 0:
                        raise RuntimeError((probe["stderr"] or probe["stdout"] or f"ffprobe failed for {video_path}").strip())
                    try:
                        return max(0.0, float((probe["stdout"] or "").strip()))
                    except Exception as exc:
                        raise RuntimeError(f"Could not parse ffprobe duration for {video_path}: {exc}") from exc

                def probe_video_dimensions(video_path):
                    probe = run_local_command(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-select_streams",
                            "v:0",
                            "-show_entries",
                            "stream=width,height",
                            "-of",
                            "csv=p=0:s=x",
                            str(video_path),
                        ],
                        label="ffprobe_dimensions",
                    )
                    if probe["returncode"] != 0:
                        raise RuntimeError((probe["stderr"] or probe["stdout"] or f"ffprobe failed for {video_path}").strip())
                    raw = (probe["stdout"] or "").strip()
                    try:
                        width_text, height_text = raw.split("x", 1)
                        return max(1, int(width_text)), max(1, int(height_text))
                    except Exception as exc:
                        raise RuntimeError(f"Could not parse ffprobe dimensions for {video_path}: {raw!r}") from exc

                def build_tail_context_video(master_video_path, tail_seconds, segment_index):
                    master_path = Path(master_video_path)
                    tail_path = (draft_dir / f"_tail_context_part{segment_index:02d}.mp4").resolve()
                    ffmpeg_cmd = [
                        "ffmpeg",
                        "-y",
                        "-sseof",
                        f"-{max(0.05, float(tail_seconds)):.3f}",
                        "-i",
                        str(master_path),
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-qp",
                        "0",
                        "-pix_fmt",
                        "yuv420p",
                        str(tail_path),
                    ]
                    cut = run_local_command(ffmpeg_cmd, label=f"tail_context_part{segment_index:02d}")
                    if cut["returncode"] != 0 or not tail_path.exists():
                        raise RuntimeError((cut["stderr"] or cut["stdout"] or f"Could not create tail clip for {master_path}").strip())
                    return tail_path, cut

                def stitch_master_with_continuation(master_video_path, continued_video_path, tail_seconds, segment_index):
                    master_path = Path(master_video_path)
                    continued_path = Path(continued_video_path)
                    prefix_path = (draft_dir / f"_prefix_part{segment_index:02d}.mp4").resolve()
                    merged_path = (draft_dir / f"_master_part{segment_index:02d}.mp4").resolve()
                    prefix_seconds = max(0.0, probe_duration_seconds(master_path) - float(tail_seconds))
                    logs = []
                    target_width, target_height = probe_video_dimensions(continued_path)
                    if prefix_seconds > 0.05:
                        prefix_cmd = [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(master_path),
                            "-t",
                            f"{prefix_seconds:.3f}",
                            "-an",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "medium",
                            "-qp",
                            "0",
                            "-pix_fmt",
                            "yuv420p",
                            str(prefix_path),
                        ]
                        prefix_cut = run_local_command(prefix_cmd, label=f"prefix_part{segment_index:02d}")
                        logs.append(prefix_cut)
                        if prefix_cut["returncode"] != 0 or not prefix_path.exists():
                            raise RuntimeError((prefix_cut["stderr"] or prefix_cut["stdout"] or f"Could not create prefix clip for {master_path}").strip())
                        concat_filter = "concat=n=2:v=1:a=0[v]"
                        stitch_cmd = [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(prefix_path),
                            "-i",
                            str(continued_path),
                            "-filter_complex",
                            f"[0:v]scale={target_width}:{target_height},setsar=1[v0];[1:v]scale={target_width}:{target_height},setsar=1[v1];[v0][v1]{concat_filter}",
                            "-map",
                            "[v]",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "medium",
                            "-qp",
                            "0",
                            "-pix_fmt",
                            "yuv420p",
                            str(merged_path),
                        ]
                    else:
                        stitch_cmd = [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(continued_path),
                            "-an",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "medium",
                            "-qp",
                            "0",
                            "-pix_fmt",
                            "yuv420p",
                            str(merged_path),
                        ]
                    stitch = run_local_command(stitch_cmd, label=f"stitch_part{segment_index:02d}")
                    logs.append(stitch)
                    if stitch["returncode"] != 0 or not merged_path.exists():
                        raise RuntimeError((stitch["stderr"] or stitch["stdout"] or f"Could not stitch continuation for {continued_path}").strip())
                    return merged_path, logs

                def run_one_task(task_payload, task_filename, segment_label):
                    task_path = draft_dir / task_filename
                    task_path.write_text(json.dumps(task_payload, indent=4), encoding="utf-8")
                    existing_paths = {
                        str(child.resolve())
                        for child in draft_dir.rglob("*")
                        if child.is_file() and child.suffix.lower() in loop_authoring.LOOP_AUTHORING_OUTPUT_EXTENSIONS
                    }
                    command = list(base_command) + [str(task_path.resolve())] + list(base_tail)
                    completed = subprocess.run(
                        command,
                        cwd=str(root),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=env,
                    )
                    latest_video = find_newest_video(existing_paths)
                    return {
                        "command": " ".join(command),
                        "stdout": completed.stdout or "",
                        "stderr": completed.stderr or "",
                        "returncode": int(completed.returncode),
                        "video": str(latest_video) if latest_video is not None else "",
                        "segment": segment_label,
                        "task_path": str(task_path),
                    }

                stdout_parts = []
                stderr_parts = []
                command_lines = []
                segments_info = []
                if strategy == "continue_segments" and total_frames > 0:
                    accumulated_video = initial_reference_video if starts_from_reference_video else None
                    for index, entry in enumerate(task_entries, start=1):
                        task_payload = dict(entry["payload"])
                        refresh_from_source = bool(
                            anchor_refresh_every > 0
                            and index > 1
                            and ((index - 1) % anchor_refresh_every == 0)
                        )
                        if entry.get("continue_mode") and not refresh_from_source:
                            if not accumulated_video:
                                result["error"] = f"No previous video was available for {entry['label']}."
                                break
                            if continuation_source_mode == "tail_context":
                                tail_seconds = max(0.1, float(tail_context_seconds))
                                tail_video, tail_log = build_tail_context_video(accumulated_video, tail_seconds, index)
                                command_lines.append(tail_log["command"])
                                if tail_log["stdout"]:
                                    stdout_parts.append(f"===== {tail_log['label']} =====\n{tail_log['stdout']}")
                                if tail_log["stderr"]:
                                    stderr_parts.append(f"===== {tail_log['label']} =====\n{tail_log['stderr']}")
                                task_payload["video_source"] = str(tail_video)
                            else:
                                task_payload["video_source"] = str(accumulated_video)
                            task_payload["keep_frames_video_source"] = ""
                        elif refresh_from_source:
                            task_payload["image_prompt_type"] = "S"
                            task_payload["video_source"] = None
                            task_payload["keep_frames_video_source"] = ""
                            task_payload["image_start"] = loop_author_source_image_path
                        task_result = run_one_task(task_payload, entry["filename"], entry["label"])
                        command_lines.append(task_result["command"])
                        stdout_parts.append(f"===== {task_result['segment']} =====\n{task_result['stdout']}")
                        stderr_parts.append(f"===== {task_result['segment']} =====\n{task_result['stderr']}")
                        segments_info.append(task_result)
                        if task_result["returncode"] != 0:
                            result["error"] = (task_result["stderr"] or task_result["stdout"] or f"Wan2GP exited with code {task_result['returncode']}").strip()
                            break
                        if not task_result["video"]:
                            result["error"] = f"No output video was found for {task_result['segment']}."
                            break
                        if accumulated_video and entry.get("continue_mode"):
                            if continuation_source_mode == "tail_context":
                                stitch_tail_seconds = 0.0 if refresh_from_source else max(0.1, float(tail_context_seconds))
                                merged_video, stitch_logs = stitch_master_with_continuation(accumulated_video, task_result["video"], stitch_tail_seconds, index)
                                for one_log in stitch_logs:
                                    command_lines.append(one_log["command"])
                                    if one_log["stdout"]:
                                        stdout_parts.append(f"===== {one_log['label']} =====\n{one_log['stdout']}")
                                    if one_log["stderr"]:
                                        stderr_parts.append(f"===== {one_log['label']} =====\n{one_log['stderr']}")
                                accumulated_video = str(merged_video)
                                task_result["stitched_video"] = accumulated_video
                            else:
                                accumulated_video = task_result["video"]
                            task_result["refresh_from_source"] = refresh_from_source
                        else:
                            accumulated_video = task_result["video"]
                    else:
                        result["ok"] = True
                        result["final_video"] = accumulated_video or ""
                        result["segments"] = segments_info
                else:
                    entry = task_entries[0]
                    task_result = run_one_task(entry["payload"], entry["filename"], entry["label"])
                    command_lines.append(task_result["command"])
                    stdout_parts.append(task_result["stdout"])
                    stderr_parts.append(task_result["stderr"])
                    if task_result["returncode"] == 0:
                        result["ok"] = True
                        result["final_video"] = task_result["video"]
                    else:
                        result["error"] = (task_result["stderr"] or task_result["stdout"] or f"Wan2GP exited with code {task_result['returncode']}").strip()

                result["stdout"] = "\n\n".join(part for part in stdout_parts if part)
                result["stderr"] = "\n\n".join(part for part in stderr_parts if part)
                try:
                    (draft_dir / "wan2gp_stdout.log").write_text(result["stdout"], encoding="utf-8")
                    (draft_dir / "wan2gp_stderr.log").write_text(result["stderr"], encoding="utf-8")
                    (draft_dir / "wan2gp_command.txt").write_text("\n".join(command_lines), encoding="utf-8")
                except Exception:
                    pass
            except Exception as exc:
                result["error"] = str(exc)
                try:
                    (draft_dir / "wan2gp_stderr.log").write_text(str(exc), encoding="utf-8")
                except Exception:
                    pass
            with self._loop_author_generation_lock:
                self._pending_loop_author_generation_result = result
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_loop_author_generation_result", QtCore.Qt.QueuedConnection)

        self._loop_author_generation_thread = threading.Thread(target=worker, daemon=True)
        self._loop_author_generation_thread.start()

    def open_loop_authoring_draft_folder(self):
        draft_dir = self._compute_loop_authoring_draft_dir()
        draft_dir.mkdir(parents=True, exist_ok=True)
        opened = self.shell.open_local_path(draft_dir) if self.shell is not None else QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(draft_dir.resolve())))
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText(
                f"Opened draft folder '{draft_dir.name}'." if opened else f"Draft folder ready at: {draft_dir}"
            )

    def open_loop_authoring_wan2gp_outputs(self):
        outputs_dir = self._get_loop_authoring_wan2gp_outputs_dir()
        if outputs_dir is None:
            self._info(
                "Loop Authoring",
                "No Wan2GP outputs folder could be found yet.\n\nSet a valid Wan2GP root first.",
            )
            return
        opened = self.shell.open_local_path(outputs_dir) if self.shell is not None else QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(outputs_dir)))
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText(
                f"Opened Wan2GP outputs." if opened else f"Wan2GP outputs ready at: {outputs_dir}"
            )

    def import_latest_wan2gp_video(self):
        outputs_dir = self._get_loop_authoring_wan2gp_outputs_dir()
        latest_video = loop_authoring.find_latest_video_in_dir(outputs_dir)
        if latest_video is None:
            self._info(
                "Loop Authoring",
                "No Wan2GP output video was found.\n\nGenerate a loop in Wan2GP first, then import it here.",
            )
            return
        draft_dir = self._compute_loop_authoring_draft_dir()
        draft_dir.mkdir(parents=True, exist_ok=True)
        target_path = draft_dir / latest_video.name
        try:
            import shutil
            shutil.copy2(latest_video, target_path)
        except Exception as exc:
            self._warn(
                "Loop Authoring",
                f"Could not import the latest Wan2GP video:\n{exc}",
            )
            return
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText(f"Imported latest Wan2GP video: {latest_video.name}")
        print(f"[QtGUI] Imported latest Wan2GP video: {latest_video} -> {target_path}")

    def use_loop_authoring_video_as_musetalk_source(self):
        draft_dir = self._compute_loop_authoring_draft_dir()
        video_path = loop_authoring.find_generated_video(draft_dir)
        if video_path is None:
            self._info(
                "Loop Authoring",
                "No generated loop video was found in the current draft folder yet.\n\n"
                "After your local backend writes a video there, this button can hand it directly to MuseTalk preprocessing.",
            )
            return
        if self.capabilities is None:
            self._warn("Loop Authoring", "Addon capability service is unavailable, so the source field could not be updated.")
            return
        result = self.capabilities.invoke("avatar_preprocess.set_source_path", {"path": str(Path(video_path).resolve())})
        if not result:
            self._warn("Loop Authoring", "No addon accepted the source-path handoff request.")
            return
        if hasattr(self, "loop_author_status_label"):
            self.loop_author_status_label.setText(f"Using draft video '{video_path.name}' as MuseTalk source.")

    @QtCore.Slot()
    def _apply_pending_loop_author_generation_result(self):
        with self._loop_author_generation_lock:
            result = dict(self._pending_loop_author_generation_result or {})
            self._pending_loop_author_generation_result = None
        if result.get("ok"):
            latest_video = Path(result["final_video"]) if result.get("final_video") else loop_authoring.find_generated_video(Path(result.get("output_dir", "")))
            if hasattr(self, "loop_author_status_label"):
                if latest_video is not None:
                    if result.get("segments"):
                        self.loop_author_status_label.setText(f"Wan2GP segmented generation finished: {latest_video.name}")
                    else:
                        self.loop_author_status_label.setText(f"Wan2GP generation finished: {latest_video.name}")
                else:
                    self.loop_author_status_label.setText("Wan2GP generation finished.")
            print(f"[QtGUI] Wan2GP generation finished: {result.get('settings_json', '')}")
        else:
            error_text = str(result.get("error", "Wan2GP generation failed") or "Wan2GP generation failed")
            if hasattr(self, "loop_author_status_label"):
                self.loop_author_status_label.setText("Wan2GP generation failed.")
            print(f"[QtGUI] Wan2GP generation failed: {error_text}")
            self._warn("Loop Authoring", error_text[:4000])
