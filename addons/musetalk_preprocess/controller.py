from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core.musetalk_avatar_packs import discover_avatar_packs
from qt_shared_widgets import ContextTokenStepper, NoWheelComboBox


class _LazyModuleProxy:
    def __init__(self, module_name: str):
        self._module_name = str(module_name)
        self._module = None

    def _resolve(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def is_loaded(self) -> bool:
        return self._module is not None

    def __getattr__(self, item):
        return getattr(self._resolve(), str(item))


cv2 = _LazyModuleProxy("cv2")
engine = _LazyModuleProxy("engine")
musetalk_bridge = _LazyModuleProxy("musetalk_bridge")

MUSE_AVATAR_RESULTS_DIR = Path("MuseTalk") / "results" / "v15" / "avatars"
MUSE_AVATAR_PACKS_DIR = Path("MuseTalk") / "results" / "v15" / "avatar_packs"
MUSE_STANDALONE_TARGET_PACK_ID = "__standalone__"
MUSE_VRAM_MODE_LABELS = {
    "quality": "Quality",
    "balanced": "Balanced",
    "low": "Low VRAM",
    "very_low": "Very Low VRAM",
}


class MuseTalkPreprocessController(QtCore.QObject):

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


    def _initialize_host_state(self):
        self._musetalk_prepare_in_flight = False
        self._pending_musetalk_prepare_result = None
        self._musetalk_prepare_lock = threading.Lock()
        self._pending_musetalk_first_frame_result = None
        self._musetalk_first_frame_lock = threading.Lock()
        self._musetalk_tool_bridge = None
        self._musetalk_tool_bridge_mode = None
        self._musetalk_tool_bridge_lock = threading.Lock()
        self._last_musetalk_debug_preview = None
        self._musetalk_source_frame_count = None
        self._musetalk_source_frame_count_signature = ""
        self.musetalk_preprocess_tab_widget = None
        self._musetalk_pack_emotion_checkboxes = {}


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

    def _notify_settings_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def _runtime_config_value(self, key, default=None):
        if not engine.is_loaded():
            return default
        try:
            return engine.RUNTIME_CONFIG.get(str(key), default)
        except Exception:
            return default

    def _normalize_musetalk_enabled_pack_emotions(self, raw_value):
        mapping = {}
        if not isinstance(raw_value, dict):
            return mapping
        for raw_pack_id, raw_tags in raw_value.items():
            pack_id = str(raw_pack_id or "").strip()
            if not pack_id:
                continue
            if isinstance(raw_tags, (list, tuple, set)):
                iterable = list(raw_tags)
            else:
                iterable = str(raw_tags or "").split(",")
            tags = []
            for raw_tag in iterable:
                clean_tag = str(raw_tag or "").strip().strip("[]").strip().lower()
                if clean_tag and clean_tag not in tags:
                    tags.append(clean_tag)
            mapping[pack_id] = tags
        return mapping

    def _get_musetalk_enabled_pack_emotions(self):
        return self._normalize_musetalk_enabled_pack_emotions(self._runtime_config_value("musetalk_enabled_pack_emotions", {}))

    def _set_musetalk_enabled_pack_emotions(self, mapping, notify=True):
        normalized = self._normalize_musetalk_enabled_pack_emotions(mapping)
        engine.update_runtime_config("musetalk_enabled_pack_emotions", normalized)
        if notify:
            self._notify_settings_changed()

    def _discover_musetalk_pack_catalog(self):
        try:
            return discover_avatar_packs(
                default_avatar_id=str(self._runtime_config_value("musetalk_avatar_id", "default_avatar") or "default_avatar"),
                legacy_map=getattr(engine, "MUSE_EMOTION_AVATAR_MAP", {}) if engine.is_loaded() else {},
                legacy_transitions=getattr(engine, "MUSE_AVATAR_TRANSITIONS", {}) if engine.is_loaded() else {},
                avatars_dir=MUSE_AVATAR_RESULTS_DIR,
                packs_dir=MUSE_AVATAR_PACKS_DIR,
                include_legacy=False,
                include_standalone=False,
            )
        except Exception:
            return {}

    def _refresh_musetalk_pack_emotion_editor(self):
        layout = getattr(self, "musetalk_pack_emotions_layout", None)
        summary_label = getattr(self, "musetalk_pack_emotions_summary_label", None)
        if layout is None or summary_label is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()
        self._musetalk_pack_emotion_checkboxes = {}

        selected_pack_id = str(self._current_musetalk_target_pack_id() or MUSE_STANDALONE_TARGET_PACK_ID).strip() or MUSE_STANDALONE_TARGET_PACK_ID
        if selected_pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            summary_label.setText("Standalone avatars do not expose pack-level emotion toggles. The selected avatar itself remains usable as the base/default state.")
            note = QtWidgets.QLabel("No pack-scoped emotion variants available for Standalone Avatars.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #8ea3b8;")
            layout.addWidget(note)
            layout.addStretch(1)
            return

        pack_catalog = self._discover_musetalk_pack_catalog()
        pack = pack_catalog.get(selected_pack_id)
        if pack is None:
            summary_label.setText(f"Avatar pack '{selected_pack_id}' could not be loaded.")
            note = QtWidgets.QLabel("Refresh the Avatar Pack list or create/preprocess the pack first.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #8ea3b8;")
            layout.addWidget(note)
            layout.addStretch(1)
            return

        full_map = {
            str(tag or "").strip().lower(): str(avatar_id or "").strip()
            for tag, avatar_id in (pack.emotion_avatar_map() or {}).items()
            if str(tag or "").strip()
        }
        locked_tags = {
            tag
            for tag, avatar_id in full_map.items()
            if avatar_id == str(pack.default_avatar_id or "").strip() or tag in {"neutral", "default", "idle", "base"}
        }
        stored_map = self._get_musetalk_enabled_pack_emotions()
        selected_tags = set(stored_map.get(selected_pack_id, [])) if selected_pack_id in stored_map else set(full_map.keys())
        selected_tags |= locked_tags

        summary_label.setText(
            f"Pack '{pack.display_name or pack.pack_id}' uses '{pack.default_avatar_id}' as its locked base avatar. "
            f"Enabled optional emotion tags: {max(len(selected_tags - locked_tags), 0)} / {max(len(full_map) - len(locked_tags), 0)}."
        )

        base_checkbox = QtWidgets.QCheckBox(f"Base / Default ({pack.default_avatar_id})")
        base_checkbox.setChecked(True)
        base_checkbox.setEnabled(False)
        layout.addWidget(base_checkbox)

        if not full_map:
            note = QtWidgets.QLabel("This pack does not currently expose any emotion-tagged variants.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #8ea3b8;")
            layout.addWidget(note)
            layout.addStretch(1)
            return

        for tag in sorted(full_map.keys()):
            avatar_id = full_map[tag]
            checkbox = QtWidgets.QCheckBox(f"{tag} ({avatar_id})")
            checkbox.setChecked(tag in selected_tags)
            if tag in locked_tags:
                checkbox.setEnabled(False)
            else:
                checkbox.toggled.connect(lambda checked, pack_id=selected_pack_id, emotion_tag=tag: self._on_musetalk_pack_emotion_toggled(pack_id, emotion_tag, checked))
            self._musetalk_pack_emotion_checkboxes[(selected_pack_id, tag)] = checkbox
            layout.addWidget(checkbox)
        layout.addStretch(1)

    def _set_all_musetalk_pack_emotions(self, enabled):
        selected_pack_id = str(self._current_musetalk_target_pack_id() or MUSE_STANDALONE_TARGET_PACK_ID).strip() or MUSE_STANDALONE_TARGET_PACK_ID
        if selected_pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            return
        pack_catalog = self._discover_musetalk_pack_catalog()
        pack = pack_catalog.get(selected_pack_id)
        if pack is None:
            return
        full_map = {
            str(tag or "").strip().lower(): str(avatar_id or "").strip()
            for tag, avatar_id in (pack.emotion_avatar_map() or {}).items()
            if str(tag or "").strip()
        }
        locked_tags = {
            tag
            for tag, avatar_id in full_map.items()
            if avatar_id == str(pack.default_avatar_id or "").strip() or tag in {"neutral", "default", "idle", "base"}
        }
        mapping = self._get_musetalk_enabled_pack_emotions()
        optional_tags = sorted(tag for tag in full_map.keys() if tag not in locked_tags)
        if enabled:
            mapping.pop(selected_pack_id, None)
        else:
            mapping[selected_pack_id] = []
        self._set_musetalk_enabled_pack_emotions(mapping, notify=True)
        live_adapter = getattr(engine, "avatar_gui", None)
        if live_adapter is not None and hasattr(live_adapter, "_reload_avatar_pose_connections"):
            try:
                live_adapter._reload_avatar_pose_connections()
            except Exception:
                pass
        self._refresh_musetalk_pack_emotion_editor()

    def _on_musetalk_pack_emotion_toggled(self, pack_id, emotion_tag, checked):
        clean_pack_id = str(pack_id or "").strip()
        clean_tag = str(emotion_tag or "").strip().lower()
        if not clean_pack_id or not clean_tag:
            return
        pack_catalog = self._discover_musetalk_pack_catalog()
        pack = pack_catalog.get(clean_pack_id)
        if pack is None:
            return
        full_map = {
            str(tag or "").strip().lower(): str(avatar_id or "").strip()
            for tag, avatar_id in (pack.emotion_avatar_map() or {}).items()
            if str(tag or "").strip()
        }
        locked_tags = {
            tag
            for tag, avatar_id in full_map.items()
            if avatar_id == str(pack.default_avatar_id or "").strip() or tag in {"neutral", "default", "idle", "base"}
        }
        current = self._get_musetalk_enabled_pack_emotions()
        selected_tags = set(current.get(clean_pack_id, [])) if clean_pack_id in current else set(full_map.keys())
        selected_tags |= locked_tags
        if checked:
            selected_tags.add(clean_tag)
        else:
            selected_tags.discard(clean_tag)
        optional_tags = {tag for tag in full_map.keys() if tag not in locked_tags}
        normalized_optional_selection = sorted(tag for tag in selected_tags if tag in optional_tags)
        if set(normalized_optional_selection) == optional_tags:
            current.pop(clean_pack_id, None)
        else:
            current[clean_pack_id] = normalized_optional_selection
        self._set_musetalk_enabled_pack_emotions(current, notify=True)
        live_adapter = getattr(engine, "avatar_gui", None)
        if live_adapter is not None and hasattr(live_adapter, "_reload_avatar_pose_connections"):
            try:
                live_adapter._reload_avatar_pose_connections()
            except Exception:
                pass
        self._refresh_musetalk_pack_emotion_editor()

    def _current_musetalk_vram_mode_key(self):
        if self.context is not None:
            try:
                return str(self.context.avatar.snapshot().get("musetalk_vram_mode_key") or "quality")
            except Exception:
                pass
        return "quality"

    def _sanitize_avatar_id(self, value):
        text = str(value or "").strip()
        text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text or "default_avatar"

    def _current_musetalk_target_pack_id(self):
        combo = getattr(self, "musetalk_target_pack_combo", None)
        if combo is not None:
            selected = str(combo.currentData() or "").strip()
            if selected:
                return selected
        runtime_pack_id = str(self._runtime_config_value("musetalk_avatar_pack_id", "") or "").strip()
        if runtime_pack_id and (MUSE_AVATAR_PACKS_DIR / runtime_pack_id).is_dir():
            return runtime_pack_id
        return MUSE_STANDALONE_TARGET_PACK_ID

    def _musetalk_target_pack_root(self, pack_id=None):
        selected_pack_id = str(pack_id or self._current_musetalk_target_pack_id() or MUSE_STANDALONE_TARGET_PACK_ID).strip() or MUSE_STANDALONE_TARGET_PACK_ID
        if selected_pack_id == MUSE_STANDALONE_TARGET_PACK_ID:
            return MUSE_AVATAR_RESULTS_DIR
        return MUSE_AVATAR_PACKS_DIR / selected_pack_id

    def _musetalk_target_avatar_root(self, avatar_id, pack_id=None):
        clean_avatar_id = self._sanitize_avatar_id(avatar_id)
        return self._musetalk_target_pack_root(pack_id=pack_id) / clean_avatar_id

    def _musetalk_avatar_pose_path(self, avatar_id, pack_id=None):
        return self._musetalk_target_avatar_root(avatar_id, pack_id=pack_id) / "avatar_pose.json"

    def _musetalk_avatar_info_path(self, avatar_id, pack_id=None):
        return self._musetalk_target_avatar_root(avatar_id, pack_id=pack_id) / "avator_info.json"

    def build_tab(self):
        existing = self.musetalk_preprocess_tab_widget
        if existing is not None:
            return existing

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("musetalk_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        musetalk_box = QtWidgets.QGroupBox("MuseTalk Avatars")
        self.musetalk_box = musetalk_box
        musetalk_layout = QtWidgets.QVBoxLayout(musetalk_box)

        musetalk_intro = QtWidgets.QLabel(
            "Preprocess a source video or PNG frame folder into the canonical MuseTalk avatar structure. "
            "The app will create or update either flat avatars under MuseTalk/results/v15/avatars/<avatar_id> or pack variants under MuseTalk/results/v15/avatar_packs/<pack>/<avatar_id>."
        )
        musetalk_intro.setWordWrap(True)
        musetalk_intro.setStyleSheet("color: #9fb3c8;")
        musetalk_layout.addWidget(musetalk_intro)

        def build_musetalk_card(title, description=""):
            card = QtWidgets.QFrame()
            card.setObjectName("Panel")
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(8)
            title_label = QtWidgets.QLabel(title)
            title_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
            card_layout.addWidget(title_label)
            if description:
                description_label = QtWidgets.QLabel(description)
                description_label.setWordWrap(True)
                description_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                card_layout.addWidget(description_label)
            return card, card_layout

        source_card, source_card_layout = build_musetalk_card(
            "Source",
            "Pick the prepared avatar you want to inspect, or a source clip/folder you want to preprocess into a MuseTalk avatar.",
        )
        pack_row = QtWidgets.QHBoxLayout()
        self.musetalk_target_pack_combo = NoWheelComboBox()
        self.musetalk_target_pack_combo.setObjectName("musetalk_target_pack_combo")
        self.musetalk_target_pack_combo.currentTextChanged.connect(self._on_musetalk_target_pack_changed)
        pack_row.addWidget(self.musetalk_target_pack_combo, 1)
        self.btn_musetalk_target_pack_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_musetalk_target_pack_refresh.setObjectName("btn_musetalk_target_pack_refresh")
        self.btn_musetalk_target_pack_refresh.clicked.connect(self.refresh_musetalk_target_pack_list)
        pack_row.addWidget(self.btn_musetalk_target_pack_refresh)
        self.btn_musetalk_target_pack_new = QtWidgets.QPushButton("New Pack")
        self.btn_musetalk_target_pack_new.setObjectName("btn_musetalk_target_pack_new")
        self.btn_musetalk_target_pack_new.clicked.connect(self.create_musetalk_target_pack)
        pack_row.addWidget(self.btn_musetalk_target_pack_new)
        source_card_layout.addWidget(QtWidgets.QLabel("Avatar Pack"))
        source_card_layout.addLayout(pack_row)

        prepared_row = QtWidgets.QHBoxLayout()
        self.musetalk_avatar_combo = NoWheelComboBox()
        self.musetalk_avatar_combo.setObjectName("musetalk_avatar_combo")
        self.musetalk_avatar_combo.addItem("No Prepared Avatars")
        self.musetalk_avatar_combo.currentTextChanged.connect(self._sync_avatar_id_from_prepared_selection)
        prepared_row.addWidget(self.musetalk_avatar_combo, 1)
        self.btn_musetalk_avatar_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_musetalk_avatar_refresh.setObjectName("btn_musetalk_avatar_refresh")
        self.btn_musetalk_avatar_refresh.clicked.connect(self.refresh_musetalk_avatar_list)
        prepared_row.addWidget(self.btn_musetalk_avatar_refresh)
        self.btn_musetalk_clear_frame_cache = QtWidgets.QPushButton("Clear .npy Cache")
        self.btn_musetalk_clear_frame_cache.setObjectName("btn_musetalk_clear_frame_cache")
        self.btn_musetalk_clear_frame_cache.setToolTip("Delete the selected avatar's generated NumPy startup cache. PNG frames and normal preprocess files are kept.")
        self.btn_musetalk_clear_frame_cache.clicked.connect(self.clear_selected_musetalk_frame_cache)
        prepared_row.addWidget(self.btn_musetalk_clear_frame_cache)
        source_card_layout.addWidget(QtWidgets.QLabel("Prepared Variants"))
        source_card_layout.addLayout(prepared_row)

        source_row = QtWidgets.QHBoxLayout()
        self.musetalk_source_edit = QtWidgets.QLineEdit()
        self.musetalk_source_edit.setObjectName("musetalk_source_edit")
        self.musetalk_source_edit.setPlaceholderText("Source video (.mp4/.mov/...) or folder of PNG frames")
        self.musetalk_source_edit.textChanged.connect(self._update_musetalk_avatar_destination_hint)
        self.musetalk_source_edit.textChanged.connect(self._on_musetalk_source_changed)
        source_row.addWidget(self.musetalk_source_edit, 1)
        self.btn_musetalk_source_video = QtWidgets.QPushButton("Video")
        self.btn_musetalk_source_video.setObjectName("btn_musetalk_source_video")
        self.btn_musetalk_source_video.clicked.connect(self.browse_musetalk_source_video)
        self.btn_musetalk_source_folder = QtWidgets.QPushButton("Frames")
        self.btn_musetalk_source_folder.setObjectName("btn_musetalk_source_folder")
        self.btn_musetalk_source_folder.clicked.connect(self.browse_musetalk_source_folder)
        source_row.addWidget(self.btn_musetalk_source_video)
        source_row.addWidget(self.btn_musetalk_source_folder)
        source_card_layout.addWidget(QtWidgets.QLabel("Source"))
        source_card_layout.addLayout(source_row)

        source_options_row = QtWidgets.QHBoxLayout()
        avatar_id_column = QtWidgets.QVBoxLayout()
        self.musetalk_avatar_id_edit = QtWidgets.QLineEdit()
        self.musetalk_avatar_id_edit.setObjectName("musetalk_avatar_id_edit")
        self.musetalk_avatar_id_edit.setPlaceholderText("default_avatar")
        self.musetalk_avatar_id_edit.textChanged.connect(self._update_musetalk_avatar_destination_hint)
        avatar_id_column.addWidget(QtWidgets.QLabel("Avatar ID"))
        avatar_id_column.addWidget(self.musetalk_avatar_id_edit)
        source_options_row.addLayout(avatar_id_column, 1)
        self.musetalk_recreate_checkbox = QtWidgets.QCheckBox("Recreate existing folder")
        self.musetalk_recreate_checkbox.setObjectName("musetalk_recreate_checkbox")
        source_options_row.addWidget(self.musetalk_recreate_checkbox, 0, QtCore.Qt.AlignBottom)
        source_card_layout.addLayout(source_options_row)

        self.musetalk_avatar_destination_label = QtWidgets.QLabel("")
        self.musetalk_avatar_destination_label.setWordWrap(True)
        self.musetalk_avatar_destination_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        source_card_layout.addWidget(self.musetalk_avatar_destination_label)

        source_footer = QtWidgets.QVBoxLayout()
        source_footer.setSpacing(10)
        self.btn_musetalk_prepare_avatar = QtWidgets.QPushButton("Preprocess Avatar")
        self.btn_musetalk_prepare_avatar.setObjectName("btn_musetalk_prepare_avatar")
        self.btn_musetalk_prepare_avatar.clicked.connect(self.preprocess_musetalk_avatar)
        prepare_row = QtWidgets.QHBoxLayout()
        prepare_row.setContentsMargins(0, 0, 0, 0)
        prepare_row.addWidget(self.btn_musetalk_prepare_avatar, 0, QtCore.Qt.AlignLeft)
        self.musetalk_create_frame_cache_checkbox = QtWidgets.QCheckBox("Create .npy startup cache")
        self.musetalk_create_frame_cache_checkbox.setObjectName("musetalk_create_frame_cache_checkbox")
        self.musetalk_create_frame_cache_checkbox.setChecked(True)
        self.musetalk_create_frame_cache_checkbox.setToolTip(
            "Create a NumPy cache for prepared full-frame images. Uses more disk space, but makes later MuseTalk initialization much faster."
        )
        prepare_row.addWidget(self.musetalk_create_frame_cache_checkbox, 0, QtCore.Qt.AlignLeft)
        prepare_row.addStretch(1)
        source_footer.addLayout(prepare_row)

        tags_column = QtWidgets.QVBoxLayout()
        tags_column.setSpacing(6)
        tags_column.addWidget(QtWidgets.QLabel("Emotion Tags"))
        self.musetalk_emotion_tags_edit = QtWidgets.QLineEdit()
        self.musetalk_emotion_tags_edit.setObjectName("musetalk_emotion_tags_edit")
        self.musetalk_emotion_tags_edit.setPlaceholderText("angry, shy, surprised")
        tags_column.addWidget(self.musetalk_emotion_tags_edit)
        tags_actions = QtWidgets.QHBoxLayout()
        tags_actions.setContentsMargins(0, 0, 0, 0)
        self.btn_musetalk_avatar_save_metadata = QtWidgets.QPushButton("Save Tag Mapping")
        self.btn_musetalk_avatar_save_metadata.setObjectName("btn_musetalk_avatar_save_metadata")
        self.btn_musetalk_avatar_save_metadata.clicked.connect(self.save_musetalk_avatar_metadata)
        tags_actions.addWidget(self.btn_musetalk_avatar_save_metadata)
        tags_actions.addStretch(1)
        tags_column.addLayout(tags_actions)
        source_footer.addLayout(tags_column)
        source_card_layout.addLayout(source_footer)
        musetalk_layout.addWidget(source_card)

        emotion_card, emotion_card_layout = build_musetalk_card(
            "Enabled Emotions For Selected Pack",
            "Use the Avatar Pack dropdown above to choose which pack you are editing. Disabled emotion tags are ignored at runtime and MuseTalk keeps the current visual state. The default/base avatar always stays enabled.",
        )
        self.musetalk_pack_emotions_summary_label = QtWidgets.QLabel("")
        self.musetalk_pack_emotions_summary_label.setWordWrap(True)
        self.musetalk_pack_emotions_summary_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        emotion_card_layout.addWidget(self.musetalk_pack_emotions_summary_label)

        emotion_actions = QtWidgets.QHBoxLayout()
        self.btn_musetalk_pack_emotions_all = QtWidgets.QPushButton("Enable All")
        self.btn_musetalk_pack_emotions_all.clicked.connect(lambda: self._set_all_musetalk_pack_emotions(True))
        emotion_actions.addWidget(self.btn_musetalk_pack_emotions_all)
        self.btn_musetalk_pack_emotions_none = QtWidgets.QPushButton("Disable All Optional")
        self.btn_musetalk_pack_emotions_none.clicked.connect(lambda: self._set_all_musetalk_pack_emotions(False))
        emotion_actions.addWidget(self.btn_musetalk_pack_emotions_none)
        emotion_actions.addStretch(1)
        emotion_card_layout.addLayout(emotion_actions)

        self.musetalk_pack_emotions_scroll = QtWidgets.QScrollArea()
        self.musetalk_pack_emotions_scroll.setWidgetResizable(True)
        self.musetalk_pack_emotions_scroll.setMinimumHeight(120)
        self.musetalk_pack_emotions_scroll.setMaximumHeight(220)
        self.musetalk_pack_emotions_widget = QtWidgets.QWidget()
        self.musetalk_pack_emotions_layout = QtWidgets.QVBoxLayout(self.musetalk_pack_emotions_widget)
        self.musetalk_pack_emotions_layout.setContentsMargins(0, 0, 0, 0)
        self.musetalk_pack_emotions_layout.setSpacing(8)
        self.musetalk_pack_emotions_scroll.setWidget(self.musetalk_pack_emotions_widget)
        emotion_card_layout.addWidget(self.musetalk_pack_emotions_scroll)
        musetalk_layout.addWidget(emotion_card)

        mask_card, mask_card_layout = build_musetalk_card(
            "Mask Settings",
            "These controls define the crop and inpaint region that MuseTalk is allowed to touch.",
        )
        mask_row = QtWidgets.QHBoxLayout()

        bbox_column = QtWidgets.QVBoxLayout()
        self.musetalk_bbox_shift_spin = ContextTokenStepper()
        self.musetalk_bbox_shift_spin.setObjectName("musetalk_bbox_shift_spin")
        self.musetalk_bbox_shift_spin.setRange(-80, 80)
        self.musetalk_bbox_shift_spin.setMinimumWidth(92)
        self.musetalk_bbox_shift_spin.setValue(0)
        bbox_column.addWidget(QtWidgets.QLabel("BBox Shift"))
        bbox_column.addWidget(self.musetalk_bbox_shift_spin)
        mask_row.addLayout(bbox_column)

        parsing_column = QtWidgets.QVBoxLayout()
        self.musetalk_parsing_mode_combo = NoWheelComboBox()
        self.musetalk_parsing_mode_combo.setObjectName("musetalk_parsing_mode_combo")
        self.musetalk_parsing_mode_combo.addItem("Jaw", "jaw")
        self.musetalk_parsing_mode_combo.addItem("Raw", "raw")
        self.musetalk_parsing_mode_combo.setMinimumWidth(132)
        parsing_column.addWidget(QtWidgets.QLabel("Parsing Mode"))
        parsing_column.addWidget(self.musetalk_parsing_mode_combo)
        mask_row.addLayout(parsing_column)

        extra_margin_column = QtWidgets.QVBoxLayout()
        self.musetalk_extra_margin_spin = ContextTokenStepper()
        self.musetalk_extra_margin_spin.setObjectName("musetalk_extra_margin_spin")
        self.musetalk_extra_margin_spin.setRange(0, 80)
        self.musetalk_extra_margin_spin.setMinimumWidth(92)
        self.musetalk_extra_margin_spin.setValue(10)
        extra_margin_column.addWidget(QtWidgets.QLabel("Extra Margin"))
        extra_margin_column.addWidget(self.musetalk_extra_margin_spin)
        mask_row.addLayout(extra_margin_column)

        left_cheek_column = QtWidgets.QVBoxLayout()
        self.musetalk_left_cheek_width_spin = ContextTokenStepper()
        self.musetalk_left_cheek_width_spin.setObjectName("musetalk_left_cheek_width_spin")
        self.musetalk_left_cheek_width_spin.setRange(20, 160)
        self.musetalk_left_cheek_width_spin.setMinimumWidth(92)
        self.musetalk_left_cheek_width_spin.setValue(90)
        left_cheek_column.addWidget(QtWidgets.QLabel("Left Cheek"))
        left_cheek_column.addWidget(self.musetalk_left_cheek_width_spin)
        mask_row.addLayout(left_cheek_column)

        right_cheek_column = QtWidgets.QVBoxLayout()
        self.musetalk_right_cheek_width_spin = ContextTokenStepper()
        self.musetalk_right_cheek_width_spin.setObjectName("musetalk_right_cheek_width_spin")
        self.musetalk_right_cheek_width_spin.setRange(20, 160)
        self.musetalk_right_cheek_width_spin.setMinimumWidth(92)
        self.musetalk_right_cheek_width_spin.setValue(90)
        right_cheek_column.addWidget(QtWidgets.QLabel("Right Cheek"))
        right_cheek_column.addWidget(self.musetalk_right_cheek_width_spin)
        mask_row.addLayout(right_cheek_column)
        mask_control_height = 32
        for control in (
            self.musetalk_bbox_shift_spin,
            self.musetalk_parsing_mode_combo,
            self.musetalk_extra_margin_spin,
            self.musetalk_left_cheek_width_spin,
            self.musetalk_right_cheek_width_spin,
        ):
            control.setFixedHeight(mask_control_height)
        mask_row.addStretch(1)
        mask_card_layout.addLayout(mask_row)

        quick_debug_actions = QtWidgets.QHBoxLayout()
        quick_debug_actions.addWidget(QtWidgets.QLabel("Quick Debug"))
        self.btn_musetalk_debug_first_frame_quick = QtWidgets.QPushButton("Debug First Frame")
        self.btn_musetalk_debug_first_frame_quick.setObjectName("btn_musetalk_debug_first_frame_quick")
        self.btn_musetalk_debug_first_frame_quick.clicked.connect(self.debug_musetalk_first_frame)
        quick_debug_actions.addWidget(self.btn_musetalk_debug_first_frame_quick)
        self.btn_musetalk_debug_first_frame_modified_quick = QtWidgets.QPushButton("Debug Using Modified Mask")
        self.btn_musetalk_debug_first_frame_modified_quick.setObjectName("btn_musetalk_debug_first_frame_modified_quick")
        self.btn_musetalk_debug_first_frame_modified_quick.clicked.connect(self.debug_musetalk_first_frame_using_modified_mask)
        quick_debug_actions.addWidget(self.btn_musetalk_debug_first_frame_modified_quick)
        self.musetalk_debug_show_mask_overlay_quick_checkbox = QtWidgets.QCheckBox("Show Mask Overlay")
        self.musetalk_debug_show_mask_overlay_quick_checkbox.setObjectName("musetalk_debug_show_mask_overlay_quick_checkbox")
        self.musetalk_debug_show_mask_overlay_quick_checkbox.toggled.connect(self._on_musetalk_debug_overlay_checkbox_toggled)
        quick_debug_actions.addWidget(self.musetalk_debug_show_mask_overlay_quick_checkbox)
        quick_debug_actions.addStretch(1)
        mask_card_layout.addLayout(quick_debug_actions)
        musetalk_layout.addWidget(mask_card)

        mask_ranges_card, mask_ranges_card_layout = build_musetalk_card(
            "Mask Ranges (Experimental)",
            "Optional frame-specific overrides for moving head sections. Frames not covered here use the current Mask Settings above.",
        )
        mask_ranges_editor_row = QtWidgets.QHBoxLayout()

        range_start_column = QtWidgets.QVBoxLayout()
        self.musetalk_mask_range_start_spin = ContextTokenStepper()
        self.musetalk_mask_range_start_spin.setObjectName("musetalk_mask_range_start_spin")
        self.musetalk_mask_range_start_spin.setRange(0, 50000)
        self.musetalk_mask_range_start_spin.setMinimumWidth(92)
        self.musetalk_mask_range_start_spin.setValue(0)
        range_start_column.addWidget(QtWidgets.QLabel("Start Frame"))
        range_start_column.addWidget(self.musetalk_mask_range_start_spin)
        mask_ranges_editor_row.addLayout(range_start_column)

        range_end_column = QtWidgets.QVBoxLayout()
        self.musetalk_mask_range_end_spin = ContextTokenStepper()
        self.musetalk_mask_range_end_spin.setObjectName("musetalk_mask_range_end_spin")
        self.musetalk_mask_range_end_spin.setRange(0, 50000)
        self.musetalk_mask_range_end_spin.setMinimumWidth(92)
        self.musetalk_mask_range_end_spin.setValue(0)
        range_end_column.addWidget(QtWidgets.QLabel("End Frame"))
        range_end_column.addWidget(self.musetalk_mask_range_end_spin)
        mask_ranges_editor_row.addLayout(range_end_column)
        self.musetalk_mask_range_passthrough_checkbox = QtWidgets.QCheckBox("Passthrough / No Mask")
        self.musetalk_mask_range_passthrough_checkbox.setObjectName("musetalk_mask_range_passthrough_checkbox")
        mask_ranges_editor_row.addWidget(self.musetalk_mask_range_passthrough_checkbox, 0, QtCore.Qt.AlignBottom)
        mask_ranges_editor_row.addStretch(1)
        mask_ranges_card_layout.addLayout(mask_ranges_editor_row)

        mask_range_actions = QtWidgets.QHBoxLayout()
        self.btn_musetalk_mask_range_add = QtWidgets.QPushButton("Add Range From Current Settings")
        self.btn_musetalk_mask_range_add.setObjectName("btn_musetalk_mask_range_add")
        self.btn_musetalk_mask_range_add.clicked.connect(self.add_musetalk_mask_range)
        mask_range_actions.addWidget(self.btn_musetalk_mask_range_add)
        self.btn_musetalk_mask_range_update = QtWidgets.QPushButton("Update Selected")
        self.btn_musetalk_mask_range_update.setObjectName("btn_musetalk_mask_range_update")
        self.btn_musetalk_mask_range_update.clicked.connect(self.update_selected_musetalk_mask_range)
        mask_range_actions.addWidget(self.btn_musetalk_mask_range_update)
        self.btn_musetalk_mask_range_load = QtWidgets.QPushButton("Load Selected Into Mask Settings")
        self.btn_musetalk_mask_range_load.setObjectName("btn_musetalk_mask_range_load")
        self.btn_musetalk_mask_range_load.clicked.connect(self.load_selected_musetalk_mask_range)
        mask_range_actions.addWidget(self.btn_musetalk_mask_range_load)
        self.btn_musetalk_mask_range_remove = QtWidgets.QPushButton("Remove Selected")
        self.btn_musetalk_mask_range_remove.setObjectName("btn_musetalk_mask_range_remove")
        self.btn_musetalk_mask_range_remove.clicked.connect(self.remove_selected_musetalk_mask_range)
        mask_range_actions.addWidget(self.btn_musetalk_mask_range_remove)
        mask_range_actions.addStretch(1)
        mask_ranges_card_layout.addLayout(mask_range_actions)

        self.musetalk_mask_ranges_table = QtWidgets.QTableWidget(0, 8)
        self.musetalk_mask_ranges_table.setObjectName("musetalk_mask_ranges_table")
        self.musetalk_mask_ranges_table.setHorizontalHeaderLabels([
            "Start",
            "End",
            "BBox",
            "Apply",
            "Mode",
            "Margin",
            "Left",
            "Right",
        ])
        self.musetalk_mask_ranges_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.musetalk_mask_ranges_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.musetalk_mask_ranges_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.musetalk_mask_ranges_table.verticalHeader().setVisible(False)
        self.musetalk_mask_ranges_table.horizontalHeader().setStretchLastSection(False)
        self.musetalk_mask_ranges_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.musetalk_mask_ranges_table.setAlternatingRowColors(True)
        self.musetalk_mask_ranges_table.setStyleSheet(
            "QTableWidget { background-color: #10161f; alternate-background-color: #141c27; color: #e7edf5; gridline-color: #2a394b; border: 1px solid #2a394b; }"
            "QHeaderView::section { background-color: #182231; color: #dce6f2; border: 1px solid #2a394b; padding: 4px 6px; font-weight: 600; }"
            "QTableWidget::item { padding: 4px 6px; }"
            "QTableWidget::item:selected { background-color: #29476d; color: #ffffff; }"
            "QTableCornerButton::section { background-color: #182231; border: 1px solid #2a394b; }"
        )
        self.musetalk_mask_ranges_table.setMinimumHeight(150)
        mask_ranges_card_layout.addWidget(self.musetalk_mask_ranges_table)
        musetalk_layout.addWidget(mask_ranges_card)

        mask_override_card, mask_override_card_layout = build_musetalk_card(
            "Modified Mask Overrides (Experimental)",
            "Frame-specific manual mask replacements captured from the debug editor. These are applied after normal preprocess finishes.",
        )
        mask_override_actions = QtWidgets.QHBoxLayout()
        self.btn_musetalk_mask_override_add = QtWidgets.QPushButton("Add Current Modified Mask To List")
        self.btn_musetalk_mask_override_add.setObjectName("btn_musetalk_mask_override_add")
        self.btn_musetalk_mask_override_add.clicked.connect(self.add_current_musetalk_mask_override)
        mask_override_actions.addWidget(self.btn_musetalk_mask_override_add)
        self.btn_musetalk_mask_override_load = QtWidgets.QPushButton("Load Selected Frame")
        self.btn_musetalk_mask_override_load.setObjectName("btn_musetalk_mask_override_load")
        self.btn_musetalk_mask_override_load.clicked.connect(self.load_selected_musetalk_mask_override)
        mask_override_actions.addWidget(self.btn_musetalk_mask_override_load)
        self.btn_musetalk_mask_override_remove = QtWidgets.QPushButton("Remove Selected")
        self.btn_musetalk_mask_override_remove.setObjectName("btn_musetalk_mask_override_remove")
        self.btn_musetalk_mask_override_remove.clicked.connect(self.remove_selected_musetalk_mask_override)
        mask_override_actions.addWidget(self.btn_musetalk_mask_override_remove)
        mask_override_actions.addStretch(1)
        mask_override_card_layout.addLayout(mask_override_actions)

        self.musetalk_mask_overrides_table = QtWidgets.QTableWidget(0, 7)
        self.musetalk_mask_overrides_table.setObjectName("musetalk_mask_overrides_table")
        self.musetalk_mask_overrides_table.setHorizontalHeaderLabels([
            "Frame",
            "Range",
            "BBox",
            "Mode",
            "Margin",
            "Status",
            "File",
        ])
        self.musetalk_mask_overrides_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.musetalk_mask_overrides_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.musetalk_mask_overrides_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.musetalk_mask_overrides_table.verticalHeader().setVisible(False)
        self.musetalk_mask_overrides_table.horizontalHeader().setStretchLastSection(True)
        self.musetalk_mask_overrides_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.musetalk_mask_overrides_table.setAlternatingRowColors(True)
        self.musetalk_mask_overrides_table.setStyleSheet(
            "QTableWidget { background-color: #10161f; alternate-background-color: #141c27; color: #e7edf5; gridline-color: #2a394b; border: 1px solid #2a394b; }"
            "QHeaderView::section { background-color: #182231; color: #dce6f2; border: 1px solid #2a394b; padding: 4px 6px; font-weight: 600; }"
            "QTableWidget::item { padding: 4px 6px; }"
            "QTableWidget::item:selected { background-color: #29476d; color: #ffffff; }"
            "QTableCornerButton::section { background-color: #182231; border: 1px solid #2a394b; }"
        )
        self.musetalk_mask_overrides_table.setMinimumHeight(120)
        mask_override_card_layout.addWidget(self.musetalk_mask_overrides_table)
        musetalk_layout.addWidget(mask_override_card)

        debug_card, debug_card_layout = build_musetalk_card(
            "Debug & Testing",
            "Use the warmed debug worker to inspect the current mask settings before committing to a real preprocess.",
        )
        debug_frame_row = QtWidgets.QHBoxLayout()
        debug_frame_column = QtWidgets.QVBoxLayout()
        self.musetalk_debug_frame_index_spin = ContextTokenStepper()
        self.musetalk_debug_frame_index_spin.setObjectName("musetalk_debug_frame_index_spin")
        self.musetalk_debug_frame_index_spin.setRange(0, 5000)
        self.musetalk_debug_frame_index_spin.setMinimumWidth(110)
        self.musetalk_debug_frame_index_spin.setValue(0)
        debug_frame_column.addWidget(QtWidgets.QLabel("Debug Frame"))
        debug_frame_column.addWidget(self.musetalk_debug_frame_index_spin)
        debug_frame_row.addLayout(debug_frame_column)
        debug_frame_note = QtWidgets.QLabel("0 = first frame. For videos or PNG folders, choose a later frame for debug preview.")
        debug_frame_note.setWordWrap(True)
        debug_frame_note.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        debug_frame_row.addWidget(debug_frame_note, 1)
        self.musetalk_source_frame_info_label = QtWidgets.QLabel("Source frames: unknown until first debug/preprocess.")
        self.musetalk_source_frame_info_label.setWordWrap(True)
        self.musetalk_source_frame_info_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.musetalk_debug_show_mask_overlay_checkbox = QtWidgets.QCheckBox("Show Mask Overlay")
        self.musetalk_debug_show_mask_overlay_checkbox.setObjectName("musetalk_debug_show_mask_overlay_checkbox")
        self.musetalk_debug_show_mask_overlay_checkbox.toggled.connect(self._on_musetalk_debug_overlay_checkbox_toggled)
        debug_frame_row.addWidget(self.musetalk_debug_show_mask_overlay_checkbox, 0, QtCore.Qt.AlignBottom)
        debug_card_layout.addLayout(debug_frame_row)
        debug_card_layout.addWidget(self.musetalk_source_frame_info_label)

        debug_tools_row = QtWidgets.QHBoxLayout()
        brush_size_column = QtWidgets.QVBoxLayout()
        self.musetalk_debug_brush_size_spin = ContextTokenStepper()
        self.musetalk_debug_brush_size_spin.setObjectName("musetalk_debug_brush_size_spin")
        self.musetalk_debug_brush_size_spin.setRange(1, 160)
        self.musetalk_debug_brush_size_spin.setMinimumWidth(96)
        self.musetalk_debug_brush_size_spin.setValue(12)
        self.musetalk_debug_brush_size_spin.valueChanged.connect(self._on_musetalk_debug_brush_settings_changed)
        brush_size_column.addWidget(QtWidgets.QLabel("Brush Size"))
        brush_size_column.addWidget(self.musetalk_debug_brush_size_spin)
        debug_tools_row.addLayout(brush_size_column)

        brush_feather_column = QtWidgets.QVBoxLayout()
        self.musetalk_debug_brush_feather_spin = ContextTokenStepper()
        self.musetalk_debug_brush_feather_spin.setObjectName("musetalk_debug_brush_feather_spin")
        self.musetalk_debug_brush_feather_spin.setRange(0, 80)
        self.musetalk_debug_brush_feather_spin.setMinimumWidth(96)
        self.musetalk_debug_brush_feather_spin.setValue(6)
        self.musetalk_debug_brush_feather_spin.valueChanged.connect(self._on_musetalk_debug_brush_settings_changed)
        brush_feather_column.addWidget(QtWidgets.QLabel("Brush Feather"))
        brush_feather_column.addWidget(self.musetalk_debug_brush_feather_spin)
        debug_tools_row.addLayout(brush_feather_column)

        zoom_column = QtWidgets.QVBoxLayout()
        zoom_column.addWidget(QtWidgets.QLabel("Preview Zoom"))
        zoom_buttons_row = QtWidgets.QHBoxLayout()
        self.btn_musetalk_debug_zoom_out = QtWidgets.QPushButton("-")
        self.btn_musetalk_debug_zoom_out.setObjectName("btn_musetalk_debug_zoom_out")
        self.btn_musetalk_debug_zoom_out.setFixedWidth(34)
        self.btn_musetalk_debug_zoom_out.clicked.connect(lambda: self._zoom_musetalk_debug_preview(0.8))
        zoom_buttons_row.addWidget(self.btn_musetalk_debug_zoom_out)
        self.btn_musetalk_debug_zoom_reset = QtWidgets.QPushButton("Fit")
        self.btn_musetalk_debug_zoom_reset.setObjectName("btn_musetalk_debug_zoom_reset")
        self.btn_musetalk_debug_zoom_reset.clicked.connect(self._reset_musetalk_debug_preview_zoom)
        zoom_buttons_row.addWidget(self.btn_musetalk_debug_zoom_reset)
        self.btn_musetalk_debug_zoom_in = QtWidgets.QPushButton("+")
        self.btn_musetalk_debug_zoom_in.setObjectName("btn_musetalk_debug_zoom_in")
        self.btn_musetalk_debug_zoom_in.setFixedWidth(34)
        self.btn_musetalk_debug_zoom_in.clicked.connect(lambda: self._zoom_musetalk_debug_preview(1.25))
        zoom_buttons_row.addWidget(self.btn_musetalk_debug_zoom_in)
        zoom_column.addLayout(zoom_buttons_row)
        debug_tools_row.addLayout(zoom_column)
        debug_tools_row.addStretch(1)
        debug_card_layout.addLayout(debug_tools_row)

        test_audio_row = QtWidgets.QHBoxLayout()
        self.musetalk_test_audio_edit = QtWidgets.QLineEdit()
        self.musetalk_test_audio_edit.setObjectName("musetalk_test_audio_edit")
        self.musetalk_test_audio_edit.setPlaceholderText("Short WAV/MP3 for first-frame lip-sync test")
        test_audio_row.addWidget(self.musetalk_test_audio_edit, 1)
        self.btn_musetalk_test_audio = QtWidgets.QPushButton("Audio")
        self.btn_musetalk_test_audio.setObjectName("btn_musetalk_test_audio")
        self.btn_musetalk_test_audio.clicked.connect(self.browse_musetalk_test_audio)
        test_audio_row.addWidget(self.btn_musetalk_test_audio)
        debug_card_layout.addWidget(QtWidgets.QLabel("Audio First-Frame Test (Experimental)"))
        debug_card_layout.addLayout(test_audio_row)

        musetalk_debug_hint = QtWidgets.QLabel(
            "Debug First Frame writes only to MuseTalk/runtime/first_frame_debug and does not modify prepared avatar folders. "
            "Audio Frame Test uses a temporary scratch avatar and cleans it up afterward."
        )
        musetalk_debug_hint.setWordWrap(True)
        musetalk_debug_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        debug_card_layout.addWidget(musetalk_debug_hint)

        debug_actions = QtWidgets.QHBoxLayout()
        self.btn_musetalk_debug_first_frame = QtWidgets.QPushButton("Debug First Frame")
        self.btn_musetalk_debug_first_frame.setObjectName("btn_musetalk_debug_first_frame")
        self.btn_musetalk_debug_first_frame.clicked.connect(self.debug_musetalk_first_frame)
        debug_actions.addWidget(self.btn_musetalk_debug_first_frame)
        self.btn_musetalk_debug_first_frame_modified = QtWidgets.QPushButton("Debug Using Modified Mask")
        self.btn_musetalk_debug_first_frame_modified.setObjectName("btn_musetalk_debug_first_frame_modified")
        self.btn_musetalk_debug_first_frame_modified.clicked.connect(self.debug_musetalk_first_frame_using_modified_mask)
        debug_actions.addWidget(self.btn_musetalk_debug_first_frame_modified)
        self.btn_musetalk_first_frame_test = QtWidgets.QPushButton("Audio Frame Test")
        self.btn_musetalk_first_frame_test.setObjectName("btn_musetalk_first_frame_test")
        self.btn_musetalk_first_frame_test.clicked.connect(self.render_musetalk_first_frame_test)
        debug_actions.addWidget(self.btn_musetalk_first_frame_test)
        debug_actions.addStretch(1)
        debug_card_layout.addLayout(debug_actions)
        musetalk_layout.addWidget(debug_card)

        self.musetalk_avatar_status_label = QtWidgets.QLabel("MuseTalk avatar preprocessing idle.")
        self.musetalk_avatar_status_label.setStyleSheet("color: #9fb3c8;")
        musetalk_layout.addWidget(self.musetalk_avatar_status_label)
        content_layout.addWidget(musetalk_box)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        self.musetalk_preprocess_tab_widget = scroll
        self.refresh_musetalk_target_pack_list()
        self.refresh_musetalk_avatar_list()
        self._refresh_musetalk_pack_emotion_editor()
        self._update_musetalk_avatar_destination_hint()
        self._reset_musetalk_source_frame_info()
        return scroll


    def export_session_state(self):
        return {
            "musetalk_source_path": self.musetalk_source_edit.text() if hasattr(self, "musetalk_source_edit") else "",
            "musetalk_preprocess_target_pack_id": str(self.musetalk_target_pack_combo.currentData() or self._current_musetalk_target_pack_id()) if hasattr(self, "musetalk_target_pack_combo") else self._current_musetalk_target_pack_id(),
            "musetalk_avatar_id": self.musetalk_avatar_id_edit.text() if hasattr(self, "musetalk_avatar_id_edit") else "",
            "musetalk_bbox_shift": int(self.musetalk_bbox_shift_spin.value()) if hasattr(self, "musetalk_bbox_shift_spin") else 0,
            "musetalk_debug_frame_index": int(self.musetalk_debug_frame_index_spin.value()) if hasattr(self, "musetalk_debug_frame_index_spin") else 0,
            "musetalk_debug_show_mask_overlay": self._musetalk_debug_overlay_enabled(),
            "musetalk_debug_brush_size": int(self.musetalk_debug_brush_size_spin.value()) if hasattr(self, "musetalk_debug_brush_size_spin") else 12,
            "musetalk_debug_brush_feather": int(self.musetalk_debug_brush_feather_spin.value()) if hasattr(self, "musetalk_debug_brush_feather_spin") else 6,
            "musetalk_parsing_mode": self.musetalk_parsing_mode_combo.currentData() if hasattr(self, "musetalk_parsing_mode_combo") else "jaw",
            "musetalk_extra_margin": int(self.musetalk_extra_margin_spin.value()) if hasattr(self, "musetalk_extra_margin_spin") else 10,
            "musetalk_left_cheek_width": int(self.musetalk_left_cheek_width_spin.value()) if hasattr(self, "musetalk_left_cheek_width_spin") else 90,
            "musetalk_right_cheek_width": int(self.musetalk_right_cheek_width_spin.value()) if hasattr(self, "musetalk_right_cheek_width_spin") else 90,
            "musetalk_mask_ranges": self._get_musetalk_mask_ranges(),
            "musetalk_mask_overrides": self._get_musetalk_mask_overrides(),
            "musetalk_recreate": bool(self.musetalk_recreate_checkbox.isChecked()) if hasattr(self, "musetalk_recreate_checkbox") else False,
            "musetalk_create_frame_cache": bool(self.musetalk_create_frame_cache_checkbox.isChecked()) if hasattr(self, "musetalk_create_frame_cache_checkbox") else True,
            "musetalk_emotion_tags": self.musetalk_emotion_tags_edit.text() if hasattr(self, "musetalk_emotion_tags_edit") else "",
            "musetalk_enabled_pack_emotions": self._get_musetalk_enabled_pack_emotions(),
            "musetalk_test_audio": self.musetalk_test_audio_edit.text() if hasattr(self, "musetalk_test_audio_edit") else "",
        }

    def import_session_state(self, session):
        musetalk_source_path = session.get("musetalk_source_path")
        if musetalk_source_path is not None and hasattr(self, "musetalk_source_edit"):
            self.musetalk_source_edit.setText(str(musetalk_source_path))
        musetalk_avatar_pack_id = session.get("musetalk_preprocess_target_pack_id")
        if musetalk_avatar_pack_id is None:
            musetalk_avatar_pack_id = session.get("musetalk_avatar_pack_id")
        if hasattr(self, "musetalk_target_pack_combo"):
            self.refresh_musetalk_target_pack_list(selected_pack_id=musetalk_avatar_pack_id)
            self.refresh_musetalk_avatar_list()
        musetalk_avatar_id = session.get("musetalk_avatar_id")
        if musetalk_avatar_id is not None and hasattr(self, "musetalk_avatar_id_edit"):
            self.musetalk_avatar_id_edit.setText(str(musetalk_avatar_id))
        musetalk_bbox_shift = session.get("musetalk_bbox_shift")
        if musetalk_bbox_shift is not None and hasattr(self, "musetalk_bbox_shift_spin"):
            self.musetalk_bbox_shift_spin.setValue(int(musetalk_bbox_shift))
        musetalk_debug_frame_index = session.get("musetalk_debug_frame_index")
        if musetalk_debug_frame_index is not None and hasattr(self, "musetalk_debug_frame_index_spin"):
            self.musetalk_debug_frame_index_spin.setValue(int(musetalk_debug_frame_index))
        musetalk_debug_show_mask_overlay = session.get("musetalk_debug_show_mask_overlay")
        if musetalk_debug_show_mask_overlay is not None:
            self._set_musetalk_debug_overlay_checked(bool(musetalk_debug_show_mask_overlay))
        musetalk_debug_brush_size = session.get("musetalk_debug_brush_size")
        if musetalk_debug_brush_size is not None and hasattr(self, "musetalk_debug_brush_size_spin"):
            self.musetalk_debug_brush_size_spin.setValue(int(musetalk_debug_brush_size))
        musetalk_debug_brush_feather = session.get("musetalk_debug_brush_feather")
        if musetalk_debug_brush_feather is not None and hasattr(self, "musetalk_debug_brush_feather_spin"):
            self.musetalk_debug_brush_feather_spin.setValue(int(musetalk_debug_brush_feather))
        musetalk_parsing_mode = str(session.get("musetalk_parsing_mode", "") or "").strip().lower()
        if musetalk_parsing_mode and hasattr(self, "musetalk_parsing_mode_combo"):
            index = self.musetalk_parsing_mode_combo.findData(musetalk_parsing_mode)
            if index >= 0:
                self.musetalk_parsing_mode_combo.setCurrentIndex(index)
        musetalk_extra_margin = session.get("musetalk_extra_margin")
        if musetalk_extra_margin is not None and hasattr(self, "musetalk_extra_margin_spin"):
            self.musetalk_extra_margin_spin.setValue(int(musetalk_extra_margin))
        musetalk_left_cheek_width = session.get("musetalk_left_cheek_width")
        if musetalk_left_cheek_width is not None and hasattr(self, "musetalk_left_cheek_width_spin"):
            self.musetalk_left_cheek_width_spin.setValue(int(musetalk_left_cheek_width))
        musetalk_right_cheek_width = session.get("musetalk_right_cheek_width")
        if musetalk_right_cheek_width is not None and hasattr(self, "musetalk_right_cheek_width_spin"):
            self.musetalk_right_cheek_width_spin.setValue(int(musetalk_right_cheek_width))
        self._set_musetalk_mask_ranges(session.get("musetalk_mask_ranges") or [])
        self._set_musetalk_mask_overrides(session.get("musetalk_mask_overrides") or [])
        musetalk_recreate = session.get("musetalk_recreate")
        if musetalk_recreate is not None and hasattr(self, "musetalk_recreate_checkbox"):
            self.musetalk_recreate_checkbox.setChecked(bool(musetalk_recreate))
        musetalk_create_frame_cache = session.get("musetalk_create_frame_cache")
        if musetalk_create_frame_cache is not None and hasattr(self, "musetalk_create_frame_cache_checkbox"):
            self.musetalk_create_frame_cache_checkbox.setChecked(bool(musetalk_create_frame_cache))
        musetalk_emotion_tags = session.get("musetalk_emotion_tags")
        if musetalk_emotion_tags is not None and hasattr(self, "musetalk_emotion_tags_edit"):
            self.musetalk_emotion_tags_edit.setText(str(musetalk_emotion_tags))
        musetalk_enabled_pack_emotions = session.get("musetalk_enabled_pack_emotions")
        if musetalk_enabled_pack_emotions is not None:
            self._set_musetalk_enabled_pack_emotions(musetalk_enabled_pack_emotions, notify=False)
        musetalk_test_audio = session.get("musetalk_test_audio")
        if musetalk_test_audio is not None and hasattr(self, "musetalk_test_audio_edit"):
            self.musetalk_test_audio_edit.setText(str(musetalk_test_audio))
        self._update_musetalk_avatar_destination_hint()
        self._refresh_musetalk_pack_emotion_editor()

    def refresh_musetalk_target_pack_list(self, selected_pack_id=None):
        combo = getattr(self, "musetalk_target_pack_combo", None)
        if combo is None:
            return
        requested = str(selected_pack_id or combo.currentData() or self._current_musetalk_target_pack_id()).strip() or MUSE_STANDALONE_TARGET_PACK_ID
        pack_ids = []
        if MUSE_AVATAR_PACKS_DIR.exists():
            for child in sorted(MUSE_AVATAR_PACKS_DIR.iterdir()):
                if child.is_dir():
                    pack_ids.append(child.name)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Standalone Avatars", MUSE_STANDALONE_TARGET_PACK_ID)
        for pack_id in pack_ids:
            combo.addItem(pack_id, pack_id)
        target_index = 0
        for index in range(combo.count()):
            if str(combo.itemData(index) or "") == requested:
                target_index = index
                break
        combo.setCurrentIndex(target_index)
        combo.blockSignals(False)
        self._refresh_musetalk_pack_emotion_editor()

    def _on_musetalk_target_pack_changed(self, _choice):
        self.refresh_musetalk_avatar_list()
        self._update_musetalk_avatar_destination_hint()
        self._refresh_musetalk_pack_emotion_editor()

    def create_musetalk_target_pack(self):
        MUSE_AVATAR_PACKS_DIR.mkdir(parents=True, exist_ok=True)
        current_pack_id = self._current_musetalk_target_pack_id()
        suggested_name = ""
        if current_pack_id and current_pack_id != MUSE_STANDALONE_TARGET_PACK_ID:
            suggested_name = str(current_pack_id)
        name, accepted = QtWidgets.QInputDialog.getText(
            None,
            "Create Avatar Pack",
            "Avatar pack name:",
            text=suggested_name,
        )
        if not accepted:
            return
        pack_name = self._sanitize_avatar_id(name)
        if not pack_name:
            self._warn("MuseTalk Avatar", "Enter a valid avatar pack name.")
            return
        pack_dir = MUSE_AVATAR_PACKS_DIR / pack_name
        if pack_dir.exists() and not pack_dir.is_dir():
            self._warn("MuseTalk Avatar", f"A non-folder entry already exists at:\n{pack_dir}")
            return
        pack_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_musetalk_target_pack_list(selected_pack_id=pack_name)
        self.refresh_musetalk_avatar_list()
        self._update_musetalk_avatar_destination_hint()
        if hasattr(self, "musetalk_avatar_status_label"):
            self.musetalk_avatar_status_label.setText(f"Avatar pack '{pack_name}' is ready.")

    def refresh_musetalk_avatar_list(self):
        if not hasattr(self, "musetalk_avatar_combo"):
            return
        previous = str(self.musetalk_avatar_combo.currentText() or "").strip()
        avatar_names = []
        target_root = self._musetalk_target_pack_root()
        if target_root.exists():
            for child in sorted(target_root.iterdir()):
                if not child.is_dir():
                    continue
                if (child / "avator_info.json").exists() or (child / "full_imgs").exists():
                    avatar_names.append(child.name)
        self.musetalk_avatar_combo.blockSignals(True)
        self.musetalk_avatar_combo.clear()
        self.musetalk_avatar_combo.addItems(avatar_names or ["No Prepared Avatars"])
        if previous in avatar_names:
            self.musetalk_avatar_combo.setCurrentText(previous)
        elif avatar_names:
            self.musetalk_avatar_combo.setCurrentIndex(0)
        self.musetalk_avatar_combo.blockSignals(False)
        current_choice = str(self.musetalk_avatar_combo.currentText() or "").strip()
        if current_choice and current_choice != "No Prepared Avatars":
            self._sync_avatar_id_from_prepared_selection(current_choice)
        self._update_musetalk_avatar_destination_hint()

    def _sync_avatar_id_from_prepared_selection(self, choice):
        if not hasattr(self, "musetalk_avatar_id_edit"):
            return
        clean_choice = str(choice or "").strip()
        if not clean_choice or clean_choice == "No Prepared Avatars":
            return
        self.musetalk_avatar_id_edit.setText(clean_choice)
        metadata = self._read_musetalk_avatar_metadata(clean_choice)
        if hasattr(self, "musetalk_emotion_tags_edit"):
            tags = metadata.get("emotion_tags") or []
            self.musetalk_emotion_tags_edit.setText(", ".join(str(tag) for tag in tags if tag))
        if hasattr(self, "musetalk_bbox_shift_spin") and "bbox_shift" in metadata:
            try:
                self.musetalk_bbox_shift_spin.setValue(int(metadata.get("bbox_shift", 0) or 0))
            except Exception:
                pass
        self._apply_musetalk_mask_settings(metadata)
        self._set_musetalk_mask_ranges(metadata.get("mask_ranges") or [])
        self._set_musetalk_mask_overrides(metadata.get("mask_overrides") or [])
        self._update_musetalk_avatar_destination_hint()

    def clear_selected_musetalk_frame_cache(self):
        avatar_id = ""
        if hasattr(self, "musetalk_avatar_combo"):
            avatar_id = str(self.musetalk_avatar_combo.currentText() or "").strip()
        if not avatar_id or avatar_id == "No Prepared Avatars":
            avatar_id = self._sanitize_avatar_id(self.musetalk_avatar_id_edit.text()) if hasattr(self, "musetalk_avatar_id_edit") else ""
        if not avatar_id:
            self._warn("MuseTalk Cache", "Select a prepared avatar variant first.")
            return

        avatar_root = self._musetalk_target_avatar_root(avatar_id, pack_id=self._current_musetalk_target_pack_id())
        cache_paths = [
            avatar_root / "full_imgs_cache.npy",
            avatar_root / "full_imgs_cache.json",
        ]
        existing = [path for path in cache_paths if path.exists()]
        if not existing:
            if hasattr(self, "musetalk_avatar_status_label"):
                self.musetalk_avatar_status_label.setText(f"No .npy startup cache found for '{avatar_id}'.")
            return

        total_bytes = 0
        for path in existing:
            try:
                total_bytes += int(path.stat().st_size)
            except OSError:
                pass
        total_mib = total_bytes / (1024 ** 2)
        response = QtWidgets.QMessageBox.question(
            None,
            "Clear MuseTalk Cache",
            f"Delete the generated .npy startup cache for '{avatar_id}'?\n\n"
            f"This removes about {total_mib:.1f} MiB and keeps all PNG/preprocess backup files.\n"
            "The cache can be recreated during preprocessing or the next MuseTalk initialize.",
        )
        if response != QtWidgets.QMessageBox.Yes:
            return

        removed = 0
        errors = []
        for path in existing:
            try:
                path.unlink()
                removed += 1
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        if errors:
            self._warn("MuseTalk Cache", "Some cache files could not be deleted:\n\n" + "\n".join(errors))
            return
        if hasattr(self, "musetalk_avatar_status_label"):
            self.musetalk_avatar_status_label.setText(
                f"Cleared .npy startup cache for '{avatar_id}' ({removed} file(s), ~{total_mib:.1f} MiB)."
            )

    def _apply_musetalk_mask_settings(self, metadata):
        metadata = dict(metadata or {})
        parsing_mode = str(metadata.get("parsing_mode", "jaw") or "jaw").strip().lower() or "jaw"
        if hasattr(self, "musetalk_parsing_mode_combo"):
            index = self.musetalk_parsing_mode_combo.findData(parsing_mode)
            if index >= 0:
                self.musetalk_parsing_mode_combo.setCurrentIndex(index)
        for widget_name, key_name, default_value in (
            ("musetalk_extra_margin_spin", "extra_margin", 10),
            ("musetalk_left_cheek_width_spin", "left_cheek_width", 90),
            ("musetalk_right_cheek_width_spin", "right_cheek_width", 90),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.setValue(int(metadata.get(key_name, default_value) or default_value))
            except Exception:
                pass

    def _get_musetalk_mask_settings(self):
        parsing_mode = "jaw"
        if hasattr(self, "musetalk_parsing_mode_combo"):
            parsing_mode = str(self.musetalk_parsing_mode_combo.currentData() or "jaw").strip().lower() or "jaw"
        return {
            "parsing_mode": parsing_mode,
            "extra_margin": int(self.musetalk_extra_margin_spin.value()) if hasattr(self, "musetalk_extra_margin_spin") else 10,
            "left_cheek_width": int(self.musetalk_left_cheek_width_spin.value()) if hasattr(self, "musetalk_left_cheek_width_spin") else 90,
            "right_cheek_width": int(self.musetalk_right_cheek_width_spin.value()) if hasattr(self, "musetalk_right_cheek_width_spin") else 90,
        }

    def _get_current_musetalk_mask_profile(self):
        return {
            "bbox_shift": int(self.musetalk_bbox_shift_spin.value()) if hasattr(self, "musetalk_bbox_shift_spin") else 0,
            **self._get_musetalk_mask_settings(),
        }

    def _resolve_musetalk_mask_profile_for_frame(self, frame_index):
        frame_index = max(0, int(frame_index or 0))
        base_profile = {
            **self._get_current_musetalk_mask_profile(),
            "passthrough": False,
            "range_label": "Global",
        }
        for entry in self._get_musetalk_mask_ranges():
            if int(entry.get("start_frame", 0) or 0) <= frame_index <= int(entry.get("end_frame", 0) or 0):
                resolved = self._normalize_musetalk_mask_range(entry)
                resolved["range_label"] = f"{resolved['start_frame']}-{resolved['end_frame']}"
                return resolved
        return base_profile

    def _normalize_musetalk_mask_range(self, payload):
        payload = dict(payload or {})
        start_frame = max(0, int(payload.get("start_frame", 0) or 0))
        end_frame = max(start_frame, int(payload.get("end_frame", start_frame) or start_frame))
        parsing_mode = str(payload.get("parsing_mode", "jaw") or "jaw").strip().lower() or "jaw"
        if parsing_mode not in {"jaw", "raw"}:
            parsing_mode = "jaw"
        return {
            "start_frame": start_frame,
            "end_frame": end_frame,
            "bbox_shift": int(payload.get("bbox_shift", 0) or 0),
            "passthrough": bool(payload.get("passthrough", False)),
            "parsing_mode": parsing_mode,
            "extra_margin": int(payload.get("extra_margin", 10) or 10),
            "left_cheek_width": int(payload.get("left_cheek_width", 90) or 90),
            "right_cheek_width": int(payload.get("right_cheek_width", 90) or 90),
        }

    def _get_musetalk_mask_ranges(self):
        table = getattr(self, "musetalk_mask_ranges_table", None)
        if table is None:
            return []
        ranges = []
        for row in range(table.rowCount()):
            item_payload = table.item(row, 0).data(QtCore.Qt.UserRole) if table.item(row, 0) is not None else None
            if item_payload:
                ranges.append(self._normalize_musetalk_mask_range(item_payload))
        ranges.sort(key=lambda entry: (entry["start_frame"], entry["end_frame"]))
        return ranges

    def _set_musetalk_mask_ranges(self, ranges):
        table = getattr(self, "musetalk_mask_ranges_table", None)
        if table is None:
            return
        normalized = [self._normalize_musetalk_mask_range(item) for item in list(ranges or [])]
        normalized.sort(key=lambda entry: (entry["start_frame"], entry["end_frame"]))
        table.setRowCount(0)
        for entry in normalized:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                entry["start_frame"],
                entry["end_frame"],
                entry["bbox_shift"],
                "Passthrough" if entry.get("passthrough") else "Mask",
                entry["parsing_mode"],
                entry["extra_margin"],
                entry["left_cheek_width"],
                entry["right_cheek_width"],
            ]
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(QtCore.Qt.UserRole, dict(entry))
                table.setItem(row, col, item)
        if table.rowCount() > 0:
            table.selectRow(0)

    def _build_musetalk_mask_range_from_current_controls(self):
        return self._normalize_musetalk_mask_range({
            "start_frame": int(self.musetalk_mask_range_start_spin.value()) if hasattr(self, "musetalk_mask_range_start_spin") else 0,
            "end_frame": int(self.musetalk_mask_range_end_spin.value()) if hasattr(self, "musetalk_mask_range_end_spin") else 0,
            "passthrough": bool(self.musetalk_mask_range_passthrough_checkbox.isChecked()) if hasattr(self, "musetalk_mask_range_passthrough_checkbox") else False,
            **self._get_current_musetalk_mask_profile(),
        })

    def add_musetalk_mask_range(self):
        table = getattr(self, "musetalk_mask_ranges_table", None)
        if table is None:
            return
        entry = self._build_musetalk_mask_range_from_current_controls()
        ranges = self._get_musetalk_mask_ranges()
        ranges.append(entry)
        self._set_musetalk_mask_ranges(ranges)

    def _selected_musetalk_mask_range_row(self):
        table = getattr(self, "musetalk_mask_ranges_table", None)
        if table is None:
            return -1
        selection = table.selectionModel()
        if selection is None or not selection.hasSelection():
            return -1
        rows = selection.selectedRows()
        return int(rows[0].row()) if rows else -1

    def load_selected_musetalk_mask_range(self):
        table = getattr(self, "musetalk_mask_ranges_table", None)
        row = self._selected_musetalk_mask_range_row()
        if table is None or row < 0:
            return
        item = table.item(row, 0)
        payload = item.data(QtCore.Qt.UserRole) if item is not None else None
        if not payload:
            return
        entry = self._normalize_musetalk_mask_range(payload)
        if hasattr(self, "musetalk_mask_range_start_spin"):
            self.musetalk_mask_range_start_spin.setValue(entry["start_frame"])
        if hasattr(self, "musetalk_mask_range_end_spin"):
            self.musetalk_mask_range_end_spin.setValue(entry["end_frame"])
        if hasattr(self, "musetalk_mask_range_passthrough_checkbox"):
            self.musetalk_mask_range_passthrough_checkbox.setChecked(bool(entry.get("passthrough", False)))
        if hasattr(self, "musetalk_bbox_shift_spin"):
            self.musetalk_bbox_shift_spin.setValue(entry["bbox_shift"])
        if hasattr(self, "musetalk_parsing_mode_combo"):
            index = self.musetalk_parsing_mode_combo.findData(entry["parsing_mode"])
            if index >= 0:
                self.musetalk_parsing_mode_combo.setCurrentIndex(index)
        for widget_name, value_key in (
            ("musetalk_extra_margin_spin", "extra_margin"),
            ("musetalk_left_cheek_width_spin", "left_cheek_width"),
            ("musetalk_right_cheek_width_spin", "right_cheek_width"),
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setValue(int(entry[value_key]))

    def update_selected_musetalk_mask_range(self):
        table = getattr(self, "musetalk_mask_ranges_table", None)
        row = self._selected_musetalk_mask_range_row()
        if table is None or row < 0:
            return
        ranges = self._get_musetalk_mask_ranges()
        if row >= len(ranges):
            return
        ranges[row] = self._build_musetalk_mask_range_from_current_controls()
        self._set_musetalk_mask_ranges(ranges)
        if row < table.rowCount():
            table.selectRow(row)

    def remove_selected_musetalk_mask_range(self):
        table = getattr(self, "musetalk_mask_ranges_table", None)
        row = self._selected_musetalk_mask_range_row()
        if table is None or row < 0:
            return
        ranges = self._get_musetalk_mask_ranges()
        if row >= len(ranges):
            return
        del ranges[row]
        self._set_musetalk_mask_ranges(ranges)

    def _mask_override_staging_dir(self, avatar_id):
        clean_avatar_id = self._sanitize_avatar_id(avatar_id)
        pack_token = self._sanitize_avatar_id(self._current_musetalk_target_pack_id())
        return (Path("MuseTalk") / "runtime" / "mask_override_staging" / pack_token / clean_avatar_id).resolve()

    def _normalize_musetalk_mask_override(self, payload):
        payload = dict(payload or {})
        frame_index = max(0, int(payload.get("frame_index", 0) or 0))
        override_mask_path = str(payload.get("override_mask_path", "") or "").strip()
        bbox = [int(v) for v in list(payload.get("bbox", []) or [])[:4]]
        crop_box = [int(v) for v in list(payload.get("crop_box", []) or [])[:4]]
        range_label = str(payload.get("range_label", "Global") or "Global")
        return {
            "frame_index": frame_index,
            "override_mask_path": override_mask_path,
            "range_label": range_label,
            "bbox_shift": int(payload.get("bbox_shift", 0) or 0),
            "parsing_mode": str(payload.get("parsing_mode", "jaw") or "jaw"),
            "extra_margin": int(payload.get("extra_margin", 10) or 10),
            "left_cheek_width": int(payload.get("left_cheek_width", 90) or 90),
            "right_cheek_width": int(payload.get("right_cheek_width", 90) or 90),
            "bbox": bbox if len(bbox) == 4 else [],
            "crop_box": crop_box if len(crop_box) == 4 else [],
            "mask_width": int(payload.get("mask_width", max(0, (crop_box[2] - crop_box[0]) if len(crop_box) == 4 else 0)) or 0),
            "mask_height": int(payload.get("mask_height", max(0, (crop_box[3] - crop_box[1]) if len(crop_box) == 4 else 0)) or 0),
        }

    def _get_musetalk_mask_overrides(self):
        table = getattr(self, "musetalk_mask_overrides_table", None)
        if table is None:
            return []
        overrides = []
        for row in range(table.rowCount()):
            item_payload = table.item(row, 0).data(QtCore.Qt.UserRole) if table.item(row, 0) is not None else None
            if item_payload:
                overrides.append(self._normalize_musetalk_mask_override(item_payload))
        overrides.sort(key=lambda entry: entry["frame_index"])
        return overrides

    def _validate_musetalk_mask_overrides(self, overrides=None):
        normalized = [self._normalize_musetalk_mask_override(item) for item in list(overrides if overrides is not None else self._get_musetalk_mask_overrides())]
        validated = []
        missing = []
        for entry in normalized:
            override_mask_path = str(entry.get("override_mask_path", "") or "").strip()
            path_obj = Path(override_mask_path) if override_mask_path else None
            exists = bool(path_obj and path_obj.is_file())
            status = "OK" if exists else "Missing file"
            validated_entry = dict(entry)
            validated_entry["override_exists"] = exists
            validated_entry["status"] = status
            validated.append(validated_entry)
            if not exists:
                missing.append(validated_entry)
        return validated, missing

    def _set_musetalk_mask_overrides(self, overrides):
        table = getattr(self, "musetalk_mask_overrides_table", None)
        if table is None:
            return
        normalized, missing = self._validate_musetalk_mask_overrides(overrides)
        normalized.sort(key=lambda entry: entry["frame_index"])
        table.setRowCount(0)
        for entry in normalized:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                entry["frame_index"],
                entry["range_label"],
                entry["bbox_shift"],
                entry["parsing_mode"],
                entry["extra_margin"],
                entry.get("status", ""),
                Path(entry["override_mask_path"]).name if entry["override_mask_path"] else "",
            ]
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(QtCore.Qt.UserRole, dict(entry))
                if col == 5:
                    if entry.get("override_exists", False):
                        item.setForeground(QtGui.QBrush(QtGui.QColor("#7fd38d")))
                    else:
                        item.setForeground(QtGui.QBrush(QtGui.QColor("#ff9c7a")))
                if col == 6:
                    item.setToolTip(str(entry.get("override_mask_path", "") or ""))
                table.setItem(row, col, item)
        if table.rowCount() > 0:
            table.selectRow(0)
        if hasattr(self, "musetalk_avatar_status_label"):
            if missing:
                self.musetalk_avatar_status_label.setText(
                    f"Mask overrides loaded: {len(normalized)} total, {len(missing)} missing staged file(s)."
                )
            elif normalized:
                self.musetalk_avatar_status_label.setText(
                    f"Mask overrides loaded: {len(normalized)} total, all staged files present."
                )

    def _selected_musetalk_mask_override_row(self):
        table = getattr(self, "musetalk_mask_overrides_table", None)
        if table is None:
            return -1
        selection = table.selectionModel()
        if selection is None or not selection.hasSelection():
            return -1
        rows = selection.selectedRows()
        return int(rows[0].row()) if rows else -1

    def add_current_musetalk_mask_override(self):
        result = dict(self._last_musetalk_debug_preview or {})
        if not result or str(result.get("mode", "")) != "debug":
            self._warn("MuseTalk Avatar", "Run Debug First Frame first.")
            return
        modified_mask_path = self._current_modified_debug_mask_path()
        if not modified_mask_path or not os.path.isfile(modified_mask_path):
            self._warn("MuseTalk Avatar", "No modified debug mask exists yet. Turn on Show Mask Overlay and paint the mask first.")
            return
        avatar_id = self._sanitize_avatar_id(self.musetalk_avatar_id_edit.text())
        frame_index = int(result.get("actual_frame_index", 0) or 0)
        staging_dir = self._mask_override_staging_dir(avatar_id)
        staging_dir.mkdir(parents=True, exist_ok=True)
        staged_mask_path = staging_dir / f"{frame_index:08d}.png"
        shutil.copyfile(modified_mask_path, staged_mask_path)
        entry = self._normalize_musetalk_mask_override({
            "frame_index": frame_index,
            "override_mask_path": str(staged_mask_path),
            "range_label": str(result.get("range_label", "Global") or "Global"),
            "bbox_shift": int(result.get("bbox_shift", 0) or 0),
            "parsing_mode": str(result.get("parsing_mode", "jaw") or "jaw"),
            "extra_margin": int(result.get("extra_margin", 10) or 10),
            "left_cheek_width": int(result.get("left_cheek_width", 90) or 90),
            "right_cheek_width": int(result.get("right_cheek_width", 90) or 90),
            "bbox": list(result.get("bbox", []) or []),
            "crop_box": list(result.get("crop_box", []) or []),
        })
        overrides = self._get_musetalk_mask_overrides()
        overrides = [item for item in overrides if int(item.get("frame_index", -1)) != frame_index]
        overrides.append(entry)
        self._set_musetalk_mask_overrides(overrides)
        if hasattr(self, "musetalk_avatar_status_label"):
            self.musetalk_avatar_status_label.setText(f"Added modified mask override for frame {frame_index}.")

    def load_selected_musetalk_mask_override(self):
        table = getattr(self, "musetalk_mask_overrides_table", None)
        row = self._selected_musetalk_mask_override_row()
        if table is None or row < 0:
            return
        item = table.item(row, 0)
        payload = item.data(QtCore.Qt.UserRole) if item is not None else None
        if not payload:
            return
        entry = self._normalize_musetalk_mask_override(payload)
        if hasattr(self, "musetalk_debug_frame_index_spin"):
            self.musetalk_debug_frame_index_spin.setValue(entry["frame_index"])

    def remove_selected_musetalk_mask_override(self):
        table = getattr(self, "musetalk_mask_overrides_table", None)
        row = self._selected_musetalk_mask_override_row()
        if table is None or row < 0:
            return
        overrides = self._get_musetalk_mask_overrides()
        if row >= len(overrides):
            return
        entry = overrides[row]
        override_mask_path = str(entry.get("override_mask_path", "") or "")
        if override_mask_path and os.path.isfile(override_mask_path):
            try:
                os.remove(override_mask_path)
            except Exception:
                pass
        del overrides[row]
        self._set_musetalk_mask_overrides(overrides)

    def _parse_musetalk_emotion_tags(self, raw_text):
        tags = []
        for chunk in str(raw_text or "").split(","):
            clean = str(chunk or "").strip().strip("[]").strip().lower()
            if clean and clean not in tags:
                tags.append(clean)
        return tags

    def _read_musetalk_avatar_metadata(self, avatar_id):
        clean_avatar_id = self._sanitize_avatar_id(avatar_id)
        payload = {"avatar_id": clean_avatar_id, "emotion_tags": []}
        pose_path = self._musetalk_avatar_pose_path(clean_avatar_id)
        if pose_path.exists():
            try:
                stored = json.loads(pose_path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    payload.update(stored)
            except Exception:
                pass
        info_path = self._musetalk_avatar_info_path(clean_avatar_id)
        if info_path.exists():
            try:
                stored_info = json.loads(info_path.read_text(encoding="utf-8"))
                if isinstance(stored_info, dict):
                    if "video_path" in stored_info and "video_path" not in payload:
                        payload["video_path"] = stored_info.get("video_path", "")
                    for key_name, default_value in (
                        ("bbox_shift", 0),
                        ("extra_margin", 10),
                        ("parsing_mode", "jaw"),
                        ("left_cheek_width", 90),
                        ("right_cheek_width", 90),
                    ):
                        if key_name in stored_info and key_name not in payload:
                            payload[key_name] = stored_info.get(key_name, default_value)
                    if "mask_ranges" in stored_info and "mask_ranges" not in payload:
                        payload["mask_ranges"] = stored_info.get("mask_ranges") or []
                    if "mask_overrides" in stored_info and "mask_overrides" not in payload:
                        payload["mask_overrides"] = stored_info.get("mask_overrides") or []
            except Exception:
                pass
        return payload

    def _write_musetalk_avatar_metadata(self, avatar_id, avatar_path=None, emotion_tags_text=None):
        clean_avatar_id = self._sanitize_avatar_id(avatar_id)
        avatar_root = Path(avatar_path) if avatar_path else self._musetalk_target_avatar_root(clean_avatar_id)
        avatar_root.mkdir(parents=True, exist_ok=True)
        raw_emotion_tags_text = (
            self.musetalk_emotion_tags_edit.text() if hasattr(self, "musetalk_emotion_tags_edit") else ""
        ) if emotion_tags_text is None else str(emotion_tags_text or "")
        payload = {
            "avatar_id": clean_avatar_id,
            "emotion_tags": self._parse_musetalk_emotion_tags(raw_emotion_tags_text),
            "bbox_shift": int(self.musetalk_bbox_shift_spin.value()) if hasattr(self, "musetalk_bbox_shift_spin") else 0,
            **self._get_musetalk_mask_settings(),
            "mask_ranges": self._get_musetalk_mask_ranges(),
            "mask_overrides": self._get_musetalk_mask_overrides(),
            "updated_at": round(time.time(), 3),
        }
        pose_path = avatar_root / "avatar_pose.json"
        pose_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
        return pose_path

    def _musetalk_source_signature(self, source_path):
        path = str(source_path or "").strip()
        return str(Path(path).resolve()) if path else ""

    def _set_musetalk_source_frame_constraints(self, frame_count=None):
        frame_count = int(frame_count or 0) if frame_count is not None else 0
        debug_max = max(0, frame_count - 1) if frame_count > 0 else 5000
        range_max = max(debug_max, 50000 if frame_count <= 0 else debug_max)
        for widget_name, maximum in (("musetalk_debug_frame_index_spin", debug_max), ("musetalk_mask_range_start_spin", range_max), ("musetalk_mask_range_end_spin", range_max)):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            current = int(widget.value())
            widget.setRange(0, int(maximum))
            if current > int(maximum):
                widget.setValue(int(maximum))

    def _update_musetalk_source_frame_info_label(self):
        label = getattr(self, "musetalk_source_frame_info_label", None)
        if label is None:
            return
        frame_count = self._musetalk_source_frame_count
        if frame_count is None:
            label.setText("Source frames: unknown until first debug/preprocess.")
            return
        if frame_count <= 0:
            label.setText("Source frames: unavailable for current source.")
            return
        max_index = max(0, int(frame_count) - 1)
        cycle_count = int(frame_count) * 2
        label.setText(
            f"Source frames: {int(frame_count)} (valid debug/range indices 0-{max_index}; prepared ping-pong cycle: {cycle_count})."
        )

    def _reset_musetalk_source_frame_info(self):
        self._musetalk_source_frame_count = None
        self._musetalk_source_frame_count_signature = self._musetalk_source_signature(
            self.musetalk_source_edit.text() if hasattr(self, "musetalk_source_edit") else ""
        )
        self._set_musetalk_source_frame_constraints(None)
        self._update_musetalk_source_frame_info_label()

    def _count_musetalk_source_frames(self, source_path):
        source = Path(str(source_path or "").strip())
        if not source.exists():
            return None
        if source.is_dir():
            return len([
                name for name in os.listdir(source)
                if os.path.isfile(source / name) and Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
            ])
        ext = source.suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            return 1
        capture = cv2.VideoCapture(str(source))
        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if frame_count > 0:
                return frame_count
            counted = 0
            while True:
                ok, _ = capture.read()
                if not ok:
                    break
                counted += 1
            return counted
        finally:
            capture.release()

    def _ensure_musetalk_source_frame_info(self, source_path=None):
        current_source = self.musetalk_source_edit.text() if hasattr(self, "musetalk_source_edit") else ""
        source_text = str(source_path or current_source or "").strip()
        signature = self._musetalk_source_signature(source_text)
        if not source_text:
            self._reset_musetalk_source_frame_info()
            return None
        if signature == self._musetalk_source_frame_count_signature and self._musetalk_source_frame_count is not None:
            return self._musetalk_source_frame_count
        frame_count = self._count_musetalk_source_frames(source_text)
        self._musetalk_source_frame_count = int(frame_count) if frame_count is not None else None
        self._musetalk_source_frame_count_signature = signature
        self._set_musetalk_source_frame_constraints(self._musetalk_source_frame_count)
        self._update_musetalk_source_frame_info_label()
        return self._musetalk_source_frame_count

    def _on_musetalk_source_changed(self, *_args):
        self._reset_musetalk_source_frame_info()

    def _update_musetalk_avatar_destination_hint(self):
        if not hasattr(self, "musetalk_avatar_destination_label"):
            return
        avatar_id = self._sanitize_avatar_id(
            self.musetalk_avatar_id_edit.text() if hasattr(self, "musetalk_avatar_id_edit") else ""
        )
        pack_id = self._current_musetalk_target_pack_id()
        destination = self._musetalk_target_avatar_root(avatar_id, pack_id=pack_id)
        source_text = str(self.musetalk_source_edit.text() or "").strip() if hasattr(self, "musetalk_source_edit") else ""
        pack_label = "Standalone Avatars" if pack_id == MUSE_STANDALONE_TARGET_PACK_ID else f"Avatar Pack: {pack_id}"
        lines = [pack_label, f"Destination: {destination}"]
        if source_text:
            lines.append(f"Source: {source_text}")
        self.musetalk_avatar_destination_label.setText("<br>".join(lines))

    def _set_musetalk_prepare_busy(self, busy, message=None):
        self._musetalk_prepare_in_flight = bool(busy)
        for widget_name in (
            "btn_musetalk_prepare_avatar",
            "btn_musetalk_debug_first_frame",
            "btn_musetalk_debug_first_frame_modified",
            "btn_musetalk_debug_first_frame_quick",
            "btn_musetalk_debug_first_frame_modified_quick",
            "btn_musetalk_first_frame_test",
            "btn_musetalk_target_pack_refresh",
            "btn_musetalk_target_pack_new",
            "musetalk_target_pack_combo",
            "btn_musetalk_avatar_refresh",
            "btn_musetalk_clear_frame_cache",
            "btn_musetalk_source_video",
            "btn_musetalk_source_folder",
            "musetalk_source_edit",
            "musetalk_avatar_id_edit",
            "musetalk_bbox_shift_spin",
            "musetalk_parsing_mode_combo",
            "musetalk_extra_margin_spin",
            "musetalk_left_cheek_width_spin",
            "musetalk_right_cheek_width_spin",
            "musetalk_mask_range_start_spin",
            "musetalk_mask_range_end_spin",
            "musetalk_mask_range_passthrough_checkbox",
            "musetalk_mask_ranges_table",
            "btn_musetalk_mask_range_add",
            "btn_musetalk_mask_range_update",
            "btn_musetalk_mask_range_load",
            "btn_musetalk_mask_range_remove",
            "musetalk_mask_overrides_table",
            "btn_musetalk_mask_override_add",
            "btn_musetalk_mask_override_load",
            "btn_musetalk_mask_override_remove",
            "musetalk_debug_frame_index_spin",
            "musetalk_debug_show_mask_overlay_checkbox",
            "musetalk_recreate_checkbox",
            "musetalk_create_frame_cache_checkbox",
            "musetalk_avatar_combo",
            "musetalk_emotion_tags_edit",
            "musetalk_test_audio_edit",
            "btn_musetalk_test_audio",
            "btn_musetalk_avatar_save_metadata",
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(not busy)
        if hasattr(self, "musetalk_avatar_status_label") and message is not None:
            self.musetalk_avatar_status_label.setText(str(message))

    def browse_musetalk_source_video(self):
        if self.dialogs is not None:
            path, _ = self.dialogs.open_file(
                "Select MuseTalk Source Video",
                str(Path.cwd()),
                "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select MuseTalk Source Video",
                str(Path.cwd()),
                "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)",
            )
        if path:
            self.musetalk_source_edit.setText(path)
            self._ensure_musetalk_source_frame_info(path)

    def browse_musetalk_source_folder(self):
        if self.dialogs is not None:
            path = self.dialogs.open_directory("Select MuseTalk Source Frame Folder", str(Path.cwd()))
        else:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                None,
                "Select MuseTalk Source Frame Folder",
                str(Path.cwd()),
            )
        if path:
            self.musetalk_source_edit.setText(path)
            self._ensure_musetalk_source_frame_info(path)

    def browse_musetalk_test_audio(self):
        if self.dialogs is not None:
            path, _ = self.dialogs.open_file(
                "Select MuseTalk First-Frame Test Audio",
                str(Path.cwd()),
                "Audio Files (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select MuseTalk First-Frame Test Audio",
                str(Path.cwd()),
                "Audio Files (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)",
            )
        if path:
            self.musetalk_test_audio_edit.setText(path)

    def _get_cached_musetalk_tool_bridge(self, vram_mode):
        requested_mode = str(vram_mode or "quality").strip().lower() or "quality"
        with self._musetalk_tool_bridge_lock:
            bridge = self._musetalk_tool_bridge
            if bridge is not None and self._musetalk_tool_bridge_mode != requested_mode:
                try:
                    bridge.stop()
                except Exception:
                    pass
                self._musetalk_tool_bridge = None
                self._musetalk_tool_bridge_mode = None
                bridge = None
            if bridge is None:
                bridge = musetalk_bridge.MuseTalkBridge(root_dir="./MuseTalk", worker_options={"vram_mode": requested_mode})
                bridge.start()
                self._musetalk_tool_bridge = bridge
                self._musetalk_tool_bridge_mode = requested_mode
            return bridge

    def _stop_cached_musetalk_tool_bridge(self):
        with self._musetalk_tool_bridge_lock:
            bridge = self._musetalk_tool_bridge
            self._musetalk_tool_bridge = None
            self._musetalk_tool_bridge_mode = None
        if bridge is not None:
            try:
                bridge.stop()
            except Exception:
                pass

    def preprocess_musetalk_avatar(self):
        if self._musetalk_prepare_in_flight:
            return
        self._stop_cached_musetalk_tool_bridge()
        source_path = str(self.musetalk_source_edit.text() or "").strip()
        if not source_path:
            self._warn("MuseTalk Avatar", "Choose a source video or frame folder first.")
            return
        source = Path(source_path)
        if not source.exists():
            self._warn("MuseTalk Avatar", f"Source not found:\n{source}")
            return
        self._ensure_musetalk_source_frame_info(source_path)
        avatar_id = self._sanitize_avatar_id(self.musetalk_avatar_id_edit.text())
        target_pack_id = self._current_musetalk_target_pack_id()
        avatar_path_override = str(self._musetalk_target_avatar_root(avatar_id, pack_id=target_pack_id).resolve())
        if avatar_id != str(self.musetalk_avatar_id_edit.text() or "").strip():
            self.musetalk_avatar_id_edit.setText(avatar_id)
        bbox_shift = int(self.musetalk_bbox_shift_spin.value())
        mask_settings = self._get_musetalk_mask_settings()
        mask_ranges = self._get_musetalk_mask_ranges()
        mask_overrides, missing_overrides = self._validate_musetalk_mask_overrides()
        if missing_overrides:
            missing_frames = ", ".join(str(int(entry.get("frame_index", 0) or 0)) for entry in missing_overrides[:10])
            extra_suffix = "" if len(missing_overrides) <= 10 else f" and {len(missing_overrides) - 10} more"
            self._warn(
                "MuseTalk Avatar",
                "Preprocess cannot continue because some modified mask override files are missing.\n\n"
                f"Frames: {missing_frames}{extra_suffix}\n\n"
                "Re-add those modified masks or remove the stale override rows first.",
            )
            return
        recreate = bool(self.musetalk_recreate_checkbox.isChecked())
        create_frame_cache = bool(self.musetalk_create_frame_cache_checkbox.isChecked()) if hasattr(self, "musetalk_create_frame_cache_checkbox") else True
        vram_mode = self._current_musetalk_vram_mode_key()
        self._set_musetalk_prepare_busy(True, f"Preprocessing MuseTalk avatar '{avatar_id}'...")
        print(f"[QtGUI] MuseTalk avatar preprocessing started: pack={target_pack_id}, avatar_id={avatar_id}, source={source}")

        def worker():
            result = {
                "ok": False,
                "avatar_id": avatar_id,
                "source_path": str(source),
                "avatar_path": "",
                "error": "",
                "used_live_bridge": False,
            }
            bridge = None
            try:
                live_adapter = getattr(engine, "avatar_gui", None)
                if (
                    live_adapter is not None
                    and isinstance(live_adapter, getattr(engine, "MuseTalkAdapter"))
                    and getattr(live_adapter, "bridge", None) is not None
                ):
                    bridge = live_adapter.bridge
                    result["used_live_bridge"] = True
                else:
                    bridge = musetalk_bridge.MuseTalkBridge(root_dir="./MuseTalk", worker_options={"vram_mode": vram_mode})
                    bridge.start()
                response = bridge.request(
                    {
                        "action": "prepare_avatar",
                        "avatar_id": avatar_id,
                        "avatar_path_override": avatar_path_override,
                        "video_path": str(source),
                        "bbox_shift": bbox_shift,
                        "recreate": recreate,
                        "mask_ranges": mask_ranges,
                        "mask_overrides": mask_overrides,
                        "create_frame_cache": create_frame_cache,
                        **mask_settings,
                    },
                    timeout=1800,
                )
                avatar_path = str(response.get("avatar_path", "") or "")
                result["ok"] = bool(avatar_path)
                result["avatar_path"] = avatar_path
                if result["used_live_bridge"] and avatar_path and getattr(live_adapter, "avatar_pack_id", "") == target_pack_id:
                    try:
                        live_adapter.prepared_avatars[avatar_id] = avatar_path
                    except Exception:
                        pass
            except Exception as exc:
                result["error"] = str(exc)
            finally:
                if bridge is not None and not result["used_live_bridge"]:
                    try:
                        bridge.stop()
                    except Exception:
                        pass
                with self._musetalk_prepare_lock:
                    self._pending_musetalk_prepare_result = result
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_apply_pending_musetalk_prepare_result",
                    QtCore.Qt.QueuedConnection,
                )

        threading.Thread(target=worker, daemon=True).start()

    def render_musetalk_first_frame_test(self):
        if self._musetalk_prepare_in_flight:
            return
        audio_path = str(self.musetalk_test_audio_edit.text() or "").strip() if hasattr(self, "musetalk_test_audio_edit") else ""
        if not audio_path:
            self._warn("MuseTalk Avatar", "Choose a short test audio clip first.")
            return
        audio_file = Path(audio_path)
        if not audio_file.exists():
            self._warn("MuseTalk Avatar", f"Test audio not found:\n{audio_file}")
            return
        avatar_id = self._sanitize_avatar_id(self.musetalk_avatar_id_edit.text())
        if avatar_id != str(self.musetalk_avatar_id_edit.text() or "").strip():
            self.musetalk_avatar_id_edit.setText(avatar_id)
        metadata = self._read_musetalk_avatar_metadata(avatar_id)
        source_path = str(self.musetalk_source_edit.text() or "").strip() if hasattr(self, "musetalk_source_edit") else ""
        if not source_path:
            source_path = str(metadata.get("video_path", "") or "").strip()
        if not source_path:
            self._warn(
                "MuseTalk Avatar",
                "Choose a source video/frame folder or select a prepared avatar with stored metadata first.",
            )
            return
        source = Path(source_path)
        if not source.exists():
            self._warn("MuseTalk Avatar", f"Source not found:\n{source}")
            return
        self._ensure_musetalk_source_frame_info(source_path)
        bbox_shift = int(self.musetalk_bbox_shift_spin.value()) if hasattr(self, "musetalk_bbox_shift_spin") else int(metadata.get("bbox_shift", 0) or 0)
        mask_settings = self._get_musetalk_mask_settings()
        vram_mode = self._current_musetalk_vram_mode_key()
        self._set_musetalk_prepare_busy(True, f"Rendering scratch audio-frame test for '{avatar_id}'...")
        scratch_avatar_id = self._sanitize_avatar_id(f"__scratch_frame_test_{avatar_id}_{int(time.time())}")
        scratch_avatar_path = MUSE_AVATAR_RESULTS_DIR / scratch_avatar_id

        def worker():
            result = {
                "ok": False,
                "avatar_id": avatar_id,
                "frame_path": "",
                "frame_dir": "",
                "error": "",
                "used_live_bridge": False,
                "mode": "audio",
            }
            bridge = None
            try:
                bridge = self._get_cached_musetalk_tool_bridge(vram_mode)
                bridge.request(
                    {
                        "action": "prepare_avatar",
                        "avatar_id": scratch_avatar_id,
                        "video_path": str(source),
                        "bbox_shift": bbox_shift,
                        "recreate": True,
                        **mask_settings,
                    },
                    timeout=1800,
                )
                fps_value = 24
                try:
                    fps_value = int(getattr(getattr(engine, "avatar_gui", None), "fps", 24) or 24)
                except Exception:
                    fps_value = 24
                chunk_id = f"first_frame_test_{avatar_id}_{int(time.time())}"
                response = bridge.request(
                    {
                        "action": "render_audio",
                        "avatar_id": scratch_avatar_id,
                        "audio_path": str(audio_file),
                        "chunk_id": chunk_id,
                        "fps": fps_value,
                        "output_root": os.path.join("runtime", "first_frame_tests"),
                        "max_frames": 1,
                    },
                    timeout=600,
                )
                frame_dir = str(response.get("frame_dir", "") or "")
                frame_paths = []
                if frame_dir and os.path.isdir(frame_dir):
                    frame_paths = sorted(Path(frame_dir).glob("*.png"))
                if frame_paths:
                    result["ok"] = True
                    result["frame_dir"] = frame_dir
                    result["frame_path"] = str(frame_paths[0])
                else:
                    result["error"] = "MuseTalk first-frame test produced no PNG output."
            except Exception as exc:
                result["error"] = str(exc)
            finally:
                if scratch_avatar_path.exists():
                    try:
                        shutil.rmtree(scratch_avatar_path, ignore_errors=True)
                    except Exception:
                        pass
                with self._musetalk_first_frame_lock:
                    self._pending_musetalk_first_frame_result = result
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_apply_pending_musetalk_first_frame_result",
                    QtCore.Qt.QueuedConnection,
                )

        threading.Thread(target=worker, daemon=True).start()

    def _current_modified_debug_mask_path(self):
        result = dict(self._last_musetalk_debug_preview or {})
        explicit_path = str(result.get("modified_mask_path", "") or "")
        if explicit_path and os.path.isfile(explicit_path):
            return explicit_path
        debug_dir = str(result.get("debug_dir", "") or result.get("frame_dir", "") or "")
        if not debug_dir:
            return ""
        candidate = str(Path(debug_dir) / "debug_mask_modified.png")
        return candidate if os.path.isfile(candidate) else ""

    def debug_musetalk_first_frame(self, use_modified_mask=False):
        if self._musetalk_prepare_in_flight:
            return
        source_path = str(self.musetalk_source_edit.text() or "").strip() if hasattr(self, "musetalk_source_edit") else ""
        if not source_path:
            self._warn("MuseTalk Avatar", "Choose a source video or frame folder first.")
            return
        source = Path(source_path)
        if not source.exists():
            self._warn("MuseTalk Avatar", f"Source not found:\n{source}")
            return
        self._ensure_musetalk_source_frame_info(source_path)
        avatar_id = self._sanitize_avatar_id(self.musetalk_avatar_id_edit.text())
        if avatar_id != str(self.musetalk_avatar_id_edit.text() or "").strip():
            self.musetalk_avatar_id_edit.setText(avatar_id)
        resolved_profile = self._resolve_musetalk_mask_profile_for_frame(
            int(self.musetalk_debug_frame_index_spin.value()) if hasattr(self, "musetalk_debug_frame_index_spin") else 0
        )
        bbox_shift = int(resolved_profile.get("bbox_shift", 0) or 0)
        debug_frame_index = int(self.musetalk_debug_frame_index_spin.value()) if hasattr(self, "musetalk_debug_frame_index_spin") else 0
        mask_settings = {
            "parsing_mode": str(resolved_profile.get("parsing_mode", "jaw") or "jaw"),
            "extra_margin": int(resolved_profile.get("extra_margin", 10) or 10),
            "left_cheek_width": int(resolved_profile.get("left_cheek_width", 90) or 90),
            "right_cheek_width": int(resolved_profile.get("right_cheek_width", 90) or 90),
        }
        vram_mode = self._current_musetalk_vram_mode_key()
        modified_mask_path = ""
        if use_modified_mask:
            modified_mask_path = self._current_modified_debug_mask_path()
            if not modified_mask_path or not os.path.isfile(modified_mask_path):
                self._warn("MuseTalk Avatar", "No modified debug mask exists yet. Turn on Show Mask Overlay and paint the mask first.")
                return
        status_message = f"Debugging frame {debug_frame_index} for '{avatar_id}'..."
        if use_modified_mask:
            status_message = f"Debugging frame {debug_frame_index} for '{avatar_id}' using modified mask..."
        self._set_musetalk_prepare_busy(True, status_message)

        def worker():
            result = {
                "ok": False,
                "avatar_id": avatar_id,
                "frame_path": "",
                "frame_dir": "",
                "debug_dir": "",
                "input_frame_path": "",
                "error": "",
                "used_live_bridge": False,
                "mode": "debug",
                "range_label": str(resolved_profile.get("range_label", "Global") or "Global"),
            }
            bridge = None
            try:
                live_adapter = getattr(engine, "avatar_gui", None)
                if (
                    live_adapter is not None
                    and isinstance(live_adapter, getattr(engine, "MuseTalkAdapter"))
                    and getattr(live_adapter, "bridge", None) is not None
                ):
                    bridge = live_adapter.bridge
                    result["used_live_bridge"] = True
                else:
                    bridge = self._get_cached_musetalk_tool_bridge(vram_mode)
                payload = {
                    "action": "debug_first_frame",
                    "source_path": str(source),
                    "bbox_shift": bbox_shift,
                    "frame_index": debug_frame_index,
                    "output_root": os.path.join("runtime", "first_frame_debug"),
                    **mask_settings,
                }
                if modified_mask_path:
                    payload["modified_mask_path"] = modified_mask_path
                response = bridge.request(payload, timeout=1800)
                frame_path = str(response.get("frame_path", "") or "")
                frame_dir = str(response.get("debug_dir", "") or "")
                if frame_path and os.path.isfile(frame_path):
                    result["ok"] = True
                    result["frame_path"] = frame_path
                    result["frame_dir"] = frame_dir
                    result["debug_dir"] = frame_dir
                    result["input_frame_path"] = str(response.get("input_frame_path", "") or "")
                    result["mask_frame_path"] = str(response.get("mask_frame_path", "") or "")
                    result["mask_overlay_path"] = str(response.get("mask_overlay_path", "") or "")
                    result["bbox"] = list(response.get("bbox", []) or [])
                    result["crop_box"] = list(response.get("crop_box", []) or [])
                    result["used_modified_mask"] = bool(response.get("used_modified_mask", False))
                    result["modified_mask_path"] = str(response.get("modified_mask_path", "") or "")
                    result["bbox_shift"] = int(response.get("bbox_shift", bbox_shift) or bbox_shift)
                    result["parsing_mode"] = str(response.get("parsing_mode", mask_settings.get("parsing_mode", "jaw")) or mask_settings.get("parsing_mode", "jaw"))
                    result["extra_margin"] = int(response.get("extra_margin", mask_settings.get("extra_margin", 10)) or mask_settings.get("extra_margin", 10))
                    result["left_cheek_width"] = int(response.get("left_cheek_width", mask_settings.get("left_cheek_width", 90)) or mask_settings.get("left_cheek_width", 90))
                    result["right_cheek_width"] = int(response.get("right_cheek_width", mask_settings.get("right_cheek_width", 90)) or mask_settings.get("right_cheek_width", 90))
                    result["requested_frame_index"] = int(response.get("requested_frame_index", debug_frame_index) or 0)
                    result["actual_frame_index"] = int(response.get("actual_frame_index", debug_frame_index) or 0)
                else:
                    result["error"] = "MuseTalk debug first-frame test produced no PNG output."
            except Exception as exc:
                result["error"] = str(exc)
            finally:
                with self._musetalk_first_frame_lock:
                    self._pending_musetalk_first_frame_result = result
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_apply_pending_musetalk_first_frame_result",
                    QtCore.Qt.QueuedConnection,
                )

        threading.Thread(target=worker, daemon=True).start()

    def debug_musetalk_first_frame_using_modified_mask(self):
        self.debug_musetalk_first_frame(use_modified_mask=True)

    def _on_musetalk_debug_brush_settings_changed(self, *_args):
        if self.musetalk_ui is None:
            return
        radius = int(self.musetalk_debug_brush_size_spin.value()) if hasattr(self, "musetalk_debug_brush_size_spin") else 12
        feather = int(self.musetalk_debug_brush_feather_spin.value()) if hasattr(self, "musetalk_debug_brush_feather_spin") else 6
        try:
            self.musetalk_ui.set_debug_mask_brush(radius=radius, feather=feather)
        except Exception:
            pass

    def _zoom_musetalk_debug_preview(self, factor_delta):
        if self.musetalk_ui is None:
            return
        try:
            self.musetalk_ui.adjust_preview_zoom(float(factor_delta))
        except Exception:
            pass

    def _reset_musetalk_debug_preview_zoom(self):
        if self.musetalk_ui is None:
            return
        try:
            self.musetalk_ui.reset_preview_zoom()
        except Exception:
            pass

    def _musetalk_debug_overlay_enabled(self):
        primary = getattr(self, "musetalk_debug_show_mask_overlay_checkbox", None)
        return bool(primary.isChecked()) if primary is not None else False

    def _set_musetalk_debug_overlay_checked(self, checked, *, source=None):
        checked = bool(checked)
        for widget_name in ("musetalk_debug_show_mask_overlay_checkbox", "musetalk_debug_show_mask_overlay_quick_checkbox"):
            widget = getattr(self, widget_name, None)
            if widget is None or widget is source:
                continue
            was_blocked = widget.blockSignals(True)
            try:
                widget.setChecked(checked)
            finally:
                widget.blockSignals(was_blocked)
        if source is None:
            primary = getattr(self, "musetalk_debug_show_mask_overlay_checkbox", None)
            if primary is not None and primary.isChecked() != checked:
                was_blocked = primary.blockSignals(True)
                try:
                    primary.setChecked(checked)
                finally:
                    primary.blockSignals(was_blocked)
            secondary = getattr(self, "musetalk_debug_show_mask_overlay_quick_checkbox", None)
            if secondary is not None and secondary.isChecked() != checked:
                was_blocked = secondary.blockSignals(True)
                try:
                    secondary.setChecked(checked)
                finally:
                    secondary.blockSignals(was_blocked)

    def _on_musetalk_debug_overlay_checkbox_toggled(self, checked):
        source = self.sender() if hasattr(self, "sender") else None
        self._set_musetalk_debug_overlay_checked(bool(checked), source=source)
        self._on_musetalk_debug_preview_mode_toggled(bool(checked))

    def _sync_musetalk_debug_mask_editor(self, result):
        if self.musetalk_ui is None:
            return False
        should_enable = (
            bool(result)
            and str(result.get("mode", "")) == "debug"
            and hasattr(self, "musetalk_debug_show_mask_overlay_checkbox")
            and self._musetalk_debug_overlay_enabled()
        )
        if not should_enable:
            self.musetalk_ui.clear_debug_mask_editor()
            return False
        input_frame_path = str(result.get("input_frame_path", "") or "")
        mask_frame_path = str(result.get("mask_frame_path", "") or "")
        bbox = list(result.get("bbox", []) or [])
        crop_box = list(result.get("crop_box", []) or [])
        debug_dir = str(result.get("debug_dir", "") or result.get("frame_dir", "") or "")
        modified_mask_path = str(result.get("modified_mask_path", "") or (str(Path(debug_dir) / "debug_mask_modified.png") if debug_dir else ""))
        if input_frame_path and mask_frame_path and len(bbox) == 4 and len(crop_box) == 4:
            configured = bool(
                self.musetalk_ui.configure_debug_mask_editor(
                    base_frame_path=input_frame_path,
                    mask_frame_path=mask_frame_path,
                    bbox=bbox,
                    crop_box=crop_box,
                    modified_mask_path=modified_mask_path,
                )
            )
            if configured:
                self._on_musetalk_debug_brush_settings_changed()
            return configured
        self.musetalk_ui.clear_debug_mask_editor()
        return False

    def _publish_musetalk_debug_preview_result(self, result, *, mode_label=None, preserve_zoom=False):
        if not result or self.musetalk_ui is None:
            return False
        selected_frame_path = str(result.get("frame_path", "") or "")
        if str(result.get("mode", "")) == "debug" and hasattr(self, "musetalk_debug_show_mask_overlay_checkbox") and self._musetalk_debug_overlay_enabled():
            overlay_path = str(result.get("mask_overlay_path", "") or "")
            if overlay_path:
                selected_frame_path = overlay_path
        if not selected_frame_path:
            self.musetalk_ui.clear_debug_mask_editor()
            return False
        preview_loaded = bool(
            self.musetalk_ui.publish_preview_frame(
                frame_path=selected_frame_path,
                avatar_id=str(result.get("avatar_id", "") or ""),
                mode_label=mode_label or ("Debug first frame" if str(result.get("mode", "")) == "debug" else "First-frame test"),
            )
        )
        self._sync_musetalk_debug_mask_editor(result)
        if not preserve_zoom and str(result.get("mode", "")) == "debug":
            self._reset_musetalk_debug_preview_zoom()
        return preview_loaded

    def _on_musetalk_debug_preview_mode_toggled(self, _checked):
        result = dict(self._last_musetalk_debug_preview or {})
        if not result or str(result.get("mode", "")) != "debug":
            if self.musetalk_ui is not None:
                self.musetalk_ui.clear_debug_mask_editor()
            return
        preview_loaded = self._publish_musetalk_debug_preview_result(result, mode_label="Debug first frame", preserve_zoom=True)
        if hasattr(self, "musetalk_avatar_status_label"):
            actual_frame_index = result.get("actual_frame_index")
            frame_suffix = f" (frame {int(actual_frame_index)})" if actual_frame_index is not None else ""
            preview_kind = "mask overlay" if hasattr(self, "musetalk_debug_show_mask_overlay_checkbox") and self._musetalk_debug_overlay_enabled() else "debug result"
            detail = f" and shown in preview ({preview_kind})." if preview_loaded else f": {preview_kind} saved."
            if preview_loaded and preview_kind == "mask overlay":
                detail = " and shown in preview (mask overlay). Left mouse adds mask, right mouse erases inside the bbox."
            self.musetalk_avatar_status_label.setText(
                f"Debug first frame ready for '{result.get('avatar_id', '')}'{frame_suffix}" + detail
            )

    def save_musetalk_avatar_metadata(self):
        avatar_id = self._sanitize_avatar_id(self.musetalk_avatar_id_edit.text())
        avatar_root = self._musetalk_target_avatar_root(avatar_id)
        if not avatar_root.exists():
            self._warn(
                "MuseTalk Avatar",
                f"Prepared avatar folder not found:\n{avatar_root}\n\nPreprocess the avatar first.",
            )
            return
        pose_path = self._write_musetalk_avatar_metadata(avatar_id, avatar_root)
        live_adapter = getattr(engine, "avatar_gui", None)
        if live_adapter is not None and hasattr(live_adapter, "_reload_avatar_pose_connections"):
            try:
                live_adapter._reload_avatar_pose_connections()
            except Exception:
                pass
        try:
            engine.get_available_emotion_names(force_refresh=True)
        except Exception:
            pass
        self._refresh_musetalk_pack_emotion_editor()
        self.musetalk_avatar_status_label.setText(f"Saved tag mapping for '{avatar_id}'.")
        print(f"[QtGUI] MuseTalk avatar metadata saved: {pose_path}")

    @QtCore.Slot()
    def _apply_pending_musetalk_prepare_result(self):
        with self._musetalk_prepare_lock:
            result = dict(self._pending_musetalk_prepare_result or {})
            self._pending_musetalk_prepare_result = None
        self._set_musetalk_prepare_busy(False)
        avatar_id = str(result.get("avatar_id", "") or "").strip()
        if result.get("ok"):
            avatar_path = str(result.get("avatar_path", "") or "")
            pose_path = ""
            emotion_tags_text = self.musetalk_emotion_tags_edit.text() if hasattr(self, "musetalk_emotion_tags_edit") else ""
            if avatar_id and avatar_path:
                try:
                    pose_path = str(self._write_musetalk_avatar_metadata(avatar_id, avatar_path, emotion_tags_text=emotion_tags_text))
                except Exception as exc:
                    print(f"[QtGUI] MuseTalk avatar metadata auto-save failed for {avatar_id}: {exc}")
            self.refresh_musetalk_avatar_list()
            if avatar_id and hasattr(self, "musetalk_avatar_combo"):
                index = self.musetalk_avatar_combo.findText(avatar_id)
                if index >= 0:
                    self.musetalk_avatar_combo.setCurrentIndex(index)
            if hasattr(self, "musetalk_emotion_tags_edit"):
                self.musetalk_emotion_tags_edit.setText(str(emotion_tags_text or ""))
            live_adapter = getattr(engine, "avatar_gui", None)
            if live_adapter is not None and hasattr(live_adapter, "_reload_avatar_pose_connections"):
                try:
                    live_adapter._reload_avatar_pose_connections()
                except Exception:
                    pass
            try:
                engine.get_available_emotion_names(force_refresh=True)
            except Exception:
                pass
            self._refresh_musetalk_pack_emotion_editor()
            if hasattr(self, "musetalk_avatar_status_label"):
                status_text = f"Prepared '{avatar_id}' successfully."
                tags = self._parse_musetalk_emotion_tags(
                    self.musetalk_emotion_tags_edit.text() if hasattr(self, "musetalk_emotion_tags_edit") else ""
                )
                if tags:
                    status_text += " Emotion tags saved."
                self.musetalk_avatar_status_label.setText(status_text)
            print(f"[QtGUI] MuseTalk avatar prepared: {avatar_id} -> {avatar_path}")
            if pose_path:
                print(f"[QtGUI] MuseTalk avatar metadata auto-saved: {pose_path}")
        else:
            error_text = str(result.get("error", "Unknown MuseTalk preparation error") or "Unknown MuseTalk preparation error")
            if hasattr(self, "musetalk_avatar_status_label"):
                self.musetalk_avatar_status_label.setText(f"Preparation failed for '{avatar_id}'.")
            print(f"[QtGUI] MuseTalk avatar preparation failed for {avatar_id}: {error_text}")
            self._warn("MuseTalk Avatar", error_text[:4000])

    @QtCore.Slot()
    def _apply_pending_musetalk_first_frame_result(self):
        with self._musetalk_first_frame_lock:
            result = dict(self._pending_musetalk_first_frame_result or {})
            self._pending_musetalk_first_frame_result = None
        if result.get("ok"):
            self._last_musetalk_debug_preview = dict(result)
            mode_label = "Debug first frame" if str(result.get("mode", "")) == "debug" else "First-frame test"
            if self.musetalk_ui is None:
                self._warn("MuseTalk Avatar", "MuseTalk UI service is unavailable, so the preview could not be updated.")
                preview_loaded = False
            else:
                preview_loaded = self._publish_musetalk_debug_preview_result(result, mode_label=mode_label, preserve_zoom=True)
            if hasattr(self, "musetalk_avatar_status_label"):
                actual_frame_index = result.get("actual_frame_index")
                frame_suffix = ""
                if actual_frame_index is not None:
                    frame_suffix = f" (frame {int(actual_frame_index)})"
                if str(result.get("mode", "")) == "debug" and hasattr(self, "musetalk_debug_show_mask_overlay_checkbox") and self._musetalk_debug_overlay_enabled():
                    shown_name = Path(str(result.get("mask_overlay_path", "") or result.get("frame_path", ""))).name
                else:
                    shown_name = Path(str(result.get("frame_path", "") or "")).name if str(result.get("frame_path", "") or "") else "PNG saved."
                self.musetalk_avatar_status_label.setText(
                    f"{mode_label} ready for '{result.get('avatar_id', '')}'{frame_suffix}"
                    + (" and shown in preview." if preview_loaded else f": {shown_name}")
                )
        else:
            if self.musetalk_ui is not None:
                self.musetalk_ui.clear_debug_mask_editor()
            error_text = str(result.get("error", "MuseTalk first-frame test failed.") or "MuseTalk first-frame test failed.")
            if hasattr(self, "musetalk_avatar_status_label"):
                self.musetalk_avatar_status_label.setText("MuseTalk first-frame test failed.")
            self._warn("MuseTalk Avatar", error_text[:4000])
        self._set_musetalk_prepare_busy(False)
