"""Disabled-addon backend widget placeholders.

These helpers keep legacy backend/session code safe when an addon-owned runtime
surface is disabled. They create inert widgets only when the addon manager did
not provide the real addon-owned controls.
"""

from PySide6 import QtWidgets

from ui.widgets.basic import ContextTokenStepper, NoWheelComboBox


def _combo(object_name, labels=(), current_label=""):
    combo = NoWheelComboBox()
    combo.setObjectName(str(object_name or ""))
    combo.addItems(list(labels or []))
    if current_label:
        combo.setCurrentText(str(current_label))
    combo.setEnabled(False)
    return combo


def _spin(object_name, value=0, minimum=0, maximum=1000):
    spin = ContextTokenStepper()
    spin.setObjectName(str(object_name or ""))
    spin.setRange(int(minimum), int(maximum))
    spin.setValue(max(int(minimum), min(int(maximum), int(value or 0))))
    spin.setEnabled(False)
    spin.setMinimumWidth(112)
    spin.setMaximumWidth(132)
    return spin


def _checkbox(object_name, label, checked=False):
    checkbox = QtWidgets.QCheckBox(str(label or ""))
    checkbox.setObjectName(str(object_name or ""))
    checkbox.setChecked(bool(checked))
    checkbox.setEnabled(False)
    return checkbox


def _line_edit(object_name, value=""):
    edit = QtWidgets.QLineEdit()
    edit.setObjectName(str(object_name or ""))
    edit.setText(str(value or ""))
    edit.setEnabled(False)
    return edit


def _button(object_name, label):
    button = QtWidgets.QPushButton(str(label or ""))
    button.setObjectName(str(object_name or ""))
    button.setEnabled(False)
    return button


def ensure_musetalk_legacy_placeholders(backend, runtime_config=None):
    runtime = dict(runtime_config or {})
    vram_value = str(runtime.get("musetalk_vram_mode", "quality") or "quality").strip().lower()
    vram_label = {
        "quality": "Quality",
        "balanced": "Balanced",
        "low_vram": "Low VRAM",
        "very_low_vram": "Very Low VRAM",
    }.get(vram_value, "Quality")
    if not hasattr(backend, "musetalk_vram_combo"):
        backend.musetalk_vram_combo = _combo(
            "musetalk_vram_combo",
            ["Quality", "Balanced", "Low VRAM", "Very Low VRAM"],
            vram_label,
        )
    if not hasattr(backend, "musetalk_loop_fade_spin"):
        backend.musetalk_loop_fade_spin = _spin(
            "musetalk_loop_fade_spin",
            runtime.get("musetalk_loop_fade_ms", 150),
            0,
            1000,
        )
    if not hasattr(backend, "musetalk_use_frame_cache_checkbox"):
        backend.musetalk_use_frame_cache_checkbox = _checkbox(
            "musetalk_use_frame_cache_checkbox",
            "Use .npy startup cache",
            runtime.get("musetalk_use_frame_cache", True),
        )
    if not hasattr(backend, "musetalk_avatar_pack_combo"):
        backend.musetalk_avatar_pack_combo = _combo(
            "musetalk_avatar_pack_combo",
            ["MuseTalk addon disabled"],
            "MuseTalk addon disabled",
        )
    if not hasattr(backend, "btn_musetalk_avatar_pack_refresh"):
        backend.btn_musetalk_avatar_pack_refresh = _button("btn_musetalk_avatar_pack_refresh", "Refresh")
    if not hasattr(backend, "musetalk_avatar_pack_row_widget"):
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(backend.musetalk_avatar_pack_combo, 1)
        row.addWidget(backend.btn_musetalk_avatar_pack_refresh, 0)
        row_widget = QtWidgets.QWidget()
        row_widget.setLayout(row)
        backend.musetalk_avatar_pack_row_widget = row_widget


def ensure_visual_reply_legacy_placeholders(backend, runtime_config=None):
    runtime = dict(runtime_config or {})
    if not hasattr(backend, "visual_reply_mode_combo"):
        mode = "Off" if str(runtime.get("visual_reply_mode", "auto") or "auto").strip().lower() == "off" else "Auto"
        backend.visual_reply_mode_combo = _combo("visual_reply_mode_combo", ["Off", "Auto"], mode)
    if not hasattr(backend, "visual_reply_provider_combo"):
        provider = str(runtime.get("visual_reply_provider", "openai") or "openai").strip().lower()
        backend.visual_reply_provider_combo = _combo(
            "visual_reply_provider_combo",
            ["OpenAI", "xAI / Grok"],
            "xAI / Grok" if provider == "xai" else "OpenAI",
        )
    if not hasattr(backend, "visual_reply_size_combo"):
        size = str(runtime.get("visual_reply_size", "1024x1024") or "1024x1024").strip().lower()
        backend.visual_reply_size_combo = _combo(
            "visual_reply_size_combo",
            ["Auto", "1024x1024", "1024x1536", "1536x1024"],
            "Auto" if size == "auto" else size,
        )
    if not hasattr(backend, "visual_reply_model_edit"):
        backend.visual_reply_model_edit = _line_edit(
            "visual_reply_model_edit",
            runtime.get("visual_reply_model", "gpt-image-1"),
        )
    if not hasattr(backend, "visual_reply_auto_show_checkbox"):
        backend.visual_reply_auto_show_checkbox = _checkbox(
            "visual_reply_auto_show_checkbox",
            "Auto-show Visual Reply dock",
            runtime.get("visual_reply_auto_show_dock", True),
        )
    if not hasattr(backend, "visual_reply_hint"):
        backend.visual_reply_hint = QtWidgets.QLabel("Visual Reply addon is disabled.")
        backend.visual_reply_hint.setObjectName("visual_reply_hint")
        backend.visual_reply_hint.setWordWrap(True)
        backend.visual_reply_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")


def ensure_vam_legacy_placeholders(backend, runtime_config=None):
    runtime = dict(runtime_config or {})
    if not hasattr(backend, "vam_vmc_enabled_checkbox"):
        backend.vam_vmc_enabled_checkbox = _checkbox(
            "vam_vmc_enabled_checkbox",
            "Relay motion to VaM over VMC",
            runtime.get("vam_vmc_enabled", True),
        )
    if not hasattr(backend, "vam_bridge_enabled_checkbox"):
        backend.vam_bridge_enabled_checkbox = _checkbox(
            "vam_bridge_enabled_checkbox",
            "Enable VaM file bridge",
            runtime.get("vam_bridge_enabled", True),
        )
    if not hasattr(backend, "vam_play_audio_in_vam_checkbox"):
        backend.vam_play_audio_in_vam_checkbox = _checkbox(
            "vam_play_audio_in_vam_checkbox",
            "Play speech audio through VaM head audio",
            runtime.get("vam_play_audio_in_vam", True),
        )
    if not hasattr(backend, "vam_timeline_auto_resume_checkbox"):
        backend.vam_timeline_auto_resume_checkbox = _checkbox(
            "vam_timeline_auto_resume_checkbox",
            "Allow VaM Timeline auto-resume hooks",
            runtime.get("vam_timeline_auto_resume", True),
        )
    if not hasattr(backend, "vam_vmc_host_edit"):
        backend.vam_vmc_host_edit = _line_edit("vam_vmc_host_edit", runtime.get("vam_vmc_host", "127.0.0.1"))
    if not hasattr(backend, "vam_vmc_port_spin"):
        backend.vam_vmc_port_spin = _spin("vam_vmc_port_spin", runtime.get("vam_vmc_port", 39539), 1, 65535)
    if not hasattr(backend, "vam_root_edit"):
        backend.vam_root_edit = _line_edit("vam_root_edit", runtime.get("vam_root", ""))
    if not hasattr(backend, "vam_bridge_root_edit"):
        backend.vam_bridge_root_edit = _line_edit("vam_bridge_root_edit", runtime.get("vam_bridge_root", ""))
    if not hasattr(backend, "vam_target_atom_uid_edit"):
        backend.vam_target_atom_uid_edit = _line_edit(
            "vam_target_atom_uid_edit",
            runtime.get("vam_target_atom_uid", "Person"),
        )
    if not hasattr(backend, "vam_target_storable_id_edit"):
        backend.vam_target_storable_id_edit = _line_edit(
            "vam_target_storable_id_edit",
            runtime.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge"),
        )
