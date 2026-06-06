from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from addons.scenic_avatar import pack_runtime
from addons.musetalk_avatar import state as preview_state


class ScenicController(QtCore.QObject):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.runtime_config = context.get_service("qt.runtime_config") if context is not None else None
        self.dialogs = context.get_service("qt.dialogs") if context is not None else None
        self.shell = context.get_service("qt.shell") if context is not None else None
        self._pack: pack_runtime.ScenicPack | None = None
        self._widget = self._build_widget()
        self._refresh_packs()

    def widget(self):
        return self._widget

    def _build_widget(self):
        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        pack_box = QtWidgets.QGroupBox("Scenic Pack")
        pack_layout = QtWidgets.QGridLayout(pack_box)
        pack_layout.setColumnStretch(1, 1)
        self.pack_combo = QtWidgets.QComboBox()
        self.pack_combo.setObjectName("scenic_pack_combo")
        self.pack_combo.currentIndexChanged.connect(self._on_pack_changed)
        self.new_pack_button = QtWidgets.QPushButton("New Pack")
        self.new_pack_button.clicked.connect(self._create_pack)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh_packs)
        self.open_folder_button = QtWidgets.QPushButton("Open Packs Folder")
        self.open_folder_button.clicked.connect(self._open_packs_folder)
        self.save_pack_button = QtWidgets.QPushButton("Save Pack")
        self.save_pack_button.clicked.connect(self._save_pack)
        pack_layout.addWidget(QtWidgets.QLabel("Pack"), 0, 0)
        pack_layout.addWidget(self.pack_combo, 0, 1)
        pack_layout.addWidget(self.new_pack_button, 0, 2)
        pack_layout.addWidget(self.refresh_button, 0, 3)
        pack_layout.addWidget(self.save_pack_button, 0, 4)
        pack_layout.addWidget(self.open_folder_button, 0, 5)
        layout.addWidget(pack_box)

        editor_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        editor_split.setChildrenCollapsible(False)

        list_box = QtWidgets.QGroupBox("Images")
        list_layout = QtWidgets.QVBoxLayout(list_box)
        self.image_list = QtWidgets.QListWidget()
        self.image_list.currentRowChanged.connect(self._on_image_selected)
        list_layout.addWidget(self.image_list)
        editor_split.addWidget(list_box)

        edit_box = QtWidgets.QGroupBox("Selected Image")
        edit_outer_layout = QtWidgets.QVBoxLayout(edit_box)
        edit_outer_layout.setSpacing(10)
        edit_layout = QtWidgets.QGridLayout()
        edit_layout.setColumnStretch(1, 1)
        self.tag_edit = QtWidgets.QLineEdit()
        self.tag_edit.setPlaceholderText("neutral, happy, thinking...")
        self.path_label = QtWidgets.QLabel("No image selected.")
        self.path_label.setWordWrap(True)
        self.preview_label = QtWidgets.QLabel("No preview")
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setMinimumSize(280, 220)
        self.preview_label.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.add_image_button = QtWidgets.QPushButton("Add Image")
        self.add_image_button.clicked.connect(self._add_image)
        self.remove_image_button = QtWidgets.QPushButton("Remove Selected")
        self.remove_image_button.clicked.connect(self._remove_selected)
        self.update_tag_button = QtWidgets.QPushButton("Update Selected Tag")
        self.update_tag_button.clicked.connect(self._update_selected_tag)
        self.preview_button = QtWidgets.QPushButton("Show In MuseTalk Preview")
        self.preview_button.clicked.connect(self._preview_selected)
        edit_layout.addWidget(QtWidgets.QLabel("Tag"), 0, 0)
        edit_layout.addWidget(self.tag_edit, 0, 1, 1, 4)
        edit_layout.addWidget(QtWidgets.QLabel("Relative path"), 1, 0)
        edit_layout.addWidget(self.path_label, 1, 1, 1, 4)
        edit_outer_layout.addLayout(edit_layout)
        edit_outer_layout.addWidget(self.preview_label, 1)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.add_image_button)
        button_layout.addWidget(self.update_tag_button)
        button_layout.addWidget(self.remove_image_button)
        button_layout.addWidget(self.preview_button)
        edit_outer_layout.addLayout(button_layout)
        editor_split.addWidget(edit_box)
        editor_split.setStretchFactor(0, 2)
        editor_split.setStretchFactor(1, 3)
        layout.addWidget(editor_split, 1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return root

    def _runtime_snapshot(self) -> dict:
        if self.runtime_config is not None and hasattr(self.runtime_config, "snapshot"):
            return self.runtime_config.snapshot()
        return {}

    def _set_runtime_pack(self, pack_id: str) -> None:
        if self.runtime_config is not None and hasattr(self.runtime_config, "set"):
            self.runtime_config.set("scenic_pack_id", str(pack_id or ""))
            invalidate = self.runtime_config.engine_attr("invalidate_available_emotion_names", None)
            if callable(invalidate):
                invalidate()

    def _refresh_packs(self):
        packs = pack_runtime.discover_packs()
        current = str(self._runtime_snapshot().get("scenic_pack_id") or "").strip()
        if not current and self._pack is not None:
            current = self._pack.pack_id
        self.pack_combo.blockSignals(True)
        self.pack_combo.clear()
        for pack_id, pack in packs.items():
            label = f"{pack.pack_name} ({len(pack.images)} image{'s' if len(pack.images) != 1 else ''})"
            self.pack_combo.addItem(label, pack_id)
        self.pack_combo.blockSignals(False)
        if packs:
            index = self.pack_combo.findData(current)
            if index < 0:
                index = 0
            self.pack_combo.setCurrentIndex(index)
            self._load_selected_pack()
        else:
            self._pack = None
            self._refresh_image_list()
            self.status_label.setText("No Scenic Packs found. Create a pack to begin.")

    def _on_pack_changed(self):
        self._load_selected_pack()

    def _load_selected_pack(self):
        pack_id = str(self.pack_combo.currentData() or "").strip()
        self._pack = pack_runtime.load_pack(pack_id) if pack_id else None
        if self._pack is not None:
            self._set_runtime_pack(self._pack.pack_id)
            self.status_label.setText(f"Selected pack: {self._pack.pack_name}")
        self._refresh_image_list()

    def _refresh_image_list(self):
        self.image_list.clear()
        pack = self._pack
        if pack is None:
            self.tag_edit.clear()
            self.path_label.setText("No pack selected.")
            self.preview_label.setText("No preview")
            self.preview_label.setPixmap(QtGui.QPixmap())
            return
        for image in pack.images:
            item = QtWidgets.QListWidgetItem(f"[{image.tag}]  {image.image_path}")
            item.setData(QtCore.Qt.UserRole, image.tag)
            self.image_list.addItem(item)
        self._on_image_selected(self.image_list.currentRow())

    def _create_pack(self):
        name, accepted = QtWidgets.QInputDialog.getText(self._widget, "New Scenic Pack", "Pack name:")
        if not accepted:
            return
        try:
            pack = pack_runtime.create_pack(name)
        except Exception as exc:
            self._show_warning("Scenic Pack", str(exc))
            return
        self._pack = pack
        self._set_runtime_pack(pack.pack_id)
        self._refresh_packs()

    def _add_image(self):
        pack = self._pack
        if pack is None:
            self._show_warning("Scenic Pack", "Create or select a Scenic Pack first.")
            return
        tag = self.tag_edit.text().strip()
        if not tag:
            self._show_warning("Scenic Pack", "Enter a tag before adding an image.")
            return
        if self.dialogs is not None:
            path, _selected = self.dialogs.open_file(
                "Add Scenic Image",
                str(Path.home()),
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
        else:
            path, _selected = QtWidgets.QFileDialog.getOpenFileName(
                self._widget,
                "Add Scenic Image",
                str(Path.home()),
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
        if not path:
            return
        try:
            self._pack = pack_runtime.add_image(pack, path, tag)
        except Exception as exc:
            self._show_warning("Scenic Pack", str(exc))
            return
        self._set_runtime_pack(self._pack.pack_id)
        self._refresh_image_list()
        self._select_tag(tag)

    def _remove_selected(self):
        pack = self._pack
        item = self.image_list.currentItem()
        if pack is None or item is None:
            return
        tag = str(item.data(QtCore.Qt.UserRole) or "").strip()
        if not tag:
            return
        self._pack = pack_runtime.remove_tag(pack, tag)
        self._set_runtime_pack(self._pack.pack_id)
        self._refresh_image_list()

    def _update_selected_tag(self):
        pack = self._pack
        item = self.image_list.currentItem()
        if pack is None or item is None:
            return
        old_tag = str(item.data(QtCore.Qt.UserRole) or "").strip()
        new_tag = self.tag_edit.text().strip()
        old_clean = pack_runtime.normalize_tag(old_tag)
        new_clean = pack_runtime.normalize_tag(new_tag)
        replace_existing = False
        if old_clean != new_clean and new_clean in pack.tags():
            if not self._confirm_replace_tag(new_clean):
                return
            replace_existing = True
        try:
            self._pack = pack_runtime.update_tag(pack, old_tag, new_tag, replace_existing=replace_existing)
        except Exception as exc:
            self._show_warning("Scenic Pack", str(exc))
            return
        self._set_runtime_pack(self._pack.pack_id)
        self._refresh_image_list()
        self._select_tag(new_tag)
        self.status_label.setText(f"Updated tag '{old_tag}' -> '{pack_runtime.normalize_tag(new_tag)}'.")

    def _save_pack(self):
        pack = self._pack
        if pack is None:
            self._show_warning("Scenic Pack", "Create or select a Scenic Pack first.")
            return
        try:
            pack_runtime.save_pack(pack)
        except Exception as exc:
            self._show_warning("Scenic Pack", str(exc))
            return
        self._set_runtime_pack(pack.pack_id)
        self.status_label.setText(f"Saved Scenic Pack: {pack.pack_name}")

    def _preview_selected(self):
        pack = self._pack
        row = self.image_list.currentRow()
        if pack is None or row < 0 or row >= len(pack.images):
            self._show_warning("Scenic Pack", "Select an image first.")
            return
        image = pack.images[row]
        image_path = image.absolute_path(pack.root)
        if not image_path.is_file():
            self._show_warning("Scenic Pack", "The selected image file is missing.")
            return
        now = QtCore.QDateTime.currentMSecsSinceEpoch()
        chunk_id = f"scenic-preview:{pack.pack_id}:{image.tag}:{now}"
        frame_path = str(image_path)
        payload = {
            "frame_paths": [frame_path],
            "frame_dir": "",
            "fps": 1,
            "sync_time": 0.0,
            "duration_seconds": 0.0,
            "expected_frame_count": 1,
            "trim_start_frames": 0,
            "chunk_id": chunk_id,
            "text": f"Scenic preview for [{image.tag}]",
            "status": "ready",
            "loop": False,
            "avatar_id": f"scenic:{pack.pack_id}",
            "preview_chunk_id": chunk_id,
            "preview_frame_index": 0,
            "preview_source_index": 0,
            "scenic_pack_id": pack.pack_id,
            "scenic_tag": image.tag,
        }
        preview_state.set_current_musetalk_frame_data(payload)
        preview_state.write_musetalk_preview_frame(
            {
                "chunk_id": chunk_id,
                "frame_path": frame_path,
                "frame_index": 0,
                "source_index": 0,
                "fps": 1,
                "status": "ready",
                "loop": False,
                "emitted_at": QtCore.QDateTime.currentMSecsSinceEpoch() / 1000.0,
                "avatar_id": f"scenic:{pack.pack_id}",
                "scenic_pack_id": pack.pack_id,
                "scenic_tag": image.tag,
                "force_repaint": True,
            }
        )
        self.status_label.setText(f"Sent [{image.tag}] to the MuseTalk Preview window.")

    def _on_image_selected(self, row: int):
        pack = self._pack
        if pack is None or row < 0 or row >= len(pack.images):
            self.path_label.setText("No image selected.")
            self.preview_label.setText("No preview")
            self.preview_label.setPixmap(QtGui.QPixmap())
            return
        image = pack.images[row]
        self.tag_edit.setText(image.tag)
        self.path_label.setText(image.image_path)
        pixmap = QtGui.QPixmap(str(image.absolute_path(pack.root)))
        if pixmap.isNull():
            self.preview_label.setText("Image missing or unreadable.")
            self.preview_label.setPixmap(QtGui.QPixmap())
            return
        scaled = pixmap.scaled(
            self.preview_label.size(),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def _select_tag(self, tag: str):
        clean = pack_runtime.normalize_tag(tag)
        for row in range(self.image_list.count()):
            item = self.image_list.item(row)
            if str(item.data(QtCore.Qt.UserRole) or "") == clean:
                self.image_list.setCurrentRow(row)
                return

    def _open_packs_folder(self):
        root = pack_runtime.packs_root()
        if self.shell is not None and hasattr(self.shell, "open_local_path"):
            self.shell.open_local_path(root)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(root)))

    def _show_warning(self, title: str, message: str):
        if self.dialogs is not None and hasattr(self.dialogs, "warning"):
            self.dialogs.warning(title, message)
        else:
            QtWidgets.QMessageBox.warning(self._widget, title, message)

    def _confirm_replace_tag(self, tag: str) -> bool:
        message = (
            f"A Scenic image with the tag '{tag}' already exists in this pack.\n\n"
            "Replace that tag and its image with the selected image?"
        )
        answer = QtWidgets.QMessageBox.question(
            self._widget,
            "Replace Scenic Tag",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return answer == QtWidgets.QMessageBox.Yes
