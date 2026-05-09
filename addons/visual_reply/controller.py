import os
import time
from pathlib import Path

from PIL import Image
from PySide6 import QtCore, QtGui, QtUiTools, QtWidgets

from addons.visual_reply import state as visual_reply_state


class AddonAltWheelZoomScrollArea(QtWidgets.QScrollArea):
    zoomRequested = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    def _handle_alt_zoom_event(self, event):
        modifiers = event.modifiers()
        if not modifiers:
            try:
                modifiers = QtWidgets.QApplication.keyboardModifiers()
            except Exception:
                modifiers = QtCore.Qt.NoModifier
        if not modifiers:
            try:
                modifiers = QtGui.QGuiApplication.queryKeyboardModifiers()
            except Exception:
                modifiers = QtCore.Qt.NoModifier
        alt_down = bool(modifiers & QtCore.Qt.AltModifier)
        if not alt_down:
            return False
        angle_delta = event.angleDelta()
        delta_y = float(angle_delta.y()) if angle_delta is not None else 0.0
        if abs(delta_y) < 0.001:
            return False
        self.zoomRequested.emit(delta_y)
        event.accept()
        return True

    def wheelEvent(self, event):
        if self._handle_alt_zoom_event(event):
            return
        super().wheelEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QtCore.QEvent.Wheel:
            if self._handle_alt_zoom_event(event):
                return True
        return super().eventFilter(watched, event)


class AddonVisualReplyPanel(QtWidgets.QWidget):
    loadRequested = QtCore.Signal()
    captionRequested = QtCore.Signal()
    clearRequested = QtCore.Signal()

    def __init__(self, capability_bridge=None, parent=None, **_legacy_options):
        super().__init__(parent)
        self._capability_bridge = capability_bridge
        self._build_shell()

        self.current_pixmap = None
        self.current_image_path = ""
        self.current_caption = ""
        self.preview_zoom_factor = 1.0
        self._last_visual_reply_updated_at = 0.0

        self.image_label.installEventFilter(self)
        self.image_scroll.installEventFilter(self)
        self.image_scroll.viewport().installEventFilter(self)
        self.clear_visual_reply()
        self._refresh_storage_summary()

        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.poll_state)
        self.poll_timer.start(250)

    def _build_shell(self):
        if self._build_designer_shell():
            return
        self._build_python_fallback_shell()

    def _build_designer_shell(self):
        ui_path = Path(__file__).resolve().parent / "ui" / "visual_reply_panel.ui"
        if not ui_path.exists():
            return False
        ui_file = QtCore.QFile(str(ui_path))
        if not ui_file.open(QtCore.QIODevice.ReadOnly):
            return False
        try:
            loaded = QtUiTools.QUiLoader().load(ui_file)
        except Exception:
            loaded = None
        finally:
            ui_file.close()
        if loaded is None:
            return False

        self.status_label = loaded.findChild(QtWidgets.QLabel, "visual_reply_status")
        self.storage_label = loaded.findChild(QtWidgets.QLabel, "visual_reply_storage_label")
        self.prev_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_previous_button")
        self.load_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_load_button")
        self.next_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_next_button")
        self.load_story_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_load_current_story_button")
        self.use_style_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_use_current_style_button")
        self.caption_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_caption_button")
        self.delete_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_delete_button")
        self.clear_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_clear_button")
        self.delete_all_button = loaded.findChild(QtWidgets.QPushButton, "visual_reply_delete_all_button")
        self.content_stack = loaded.findChild(QtWidgets.QStackedWidget, "visual_reply_content_stack")
        self.placeholder = loaded.findChild(QtWidgets.QLabel, "visual_reply_placeholder")
        self.caption_label = loaded.findChild(QtWidgets.QLabel, "visual_reply_caption_label")
        if not all(
            (
                self.status_label,
                self.storage_label,
                self.prev_button,
                self.load_button,
                self.next_button,
                self.load_story_button,
                self.use_style_button,
                self.caption_button,
                self.delete_button,
                self.clear_button,
                self.delete_all_button,
                self.content_stack,
                self.placeholder,
                self.caption_label,
            )
        ):
            loaded.deleteLater()
            return False

        loaded.setParent(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(loaded)

        self._install_image_viewer()
        self._connect_controls()
        return True

    def _install_image_viewer(self):
        self.image_label = QtWidgets.QLabel()
        self.image_label.setObjectName("visual_reply_image_label")
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.image_label.setMinimumSize(0, 0)
        self.image_label.setStyleSheet("background: transparent; border: 0;")

        self.image_scroll = AddonAltWheelZoomScrollArea()
        self.image_scroll.setObjectName("visual_reply_image_scroll")
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(QtCore.Qt.AlignCenter)
        self.image_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.image_scroll.setStyleSheet("QScrollArea { background: #0f141b; border: 1px solid #273342; border-radius: 10px; }")
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.zoomRequested.connect(self._handle_scroll_zoom_request)
        self.content_stack.addWidget(self.image_scroll)

    def _connect_controls(self):
        self.prev_button.clicked.connect(self.show_previous_stored_image)
        self.next_button.clicked.connect(self.show_next_stored_image)
        self.load_button.clicked.connect(self.loadRequested.emit)
        self.load_story_button.clicked.connect(self.load_current_story_image)
        self.use_style_button.clicked.connect(self.use_current_image_style)
        self.caption_button.clicked.connect(self.captionRequested.emit)
        self.delete_button.clicked.connect(self.delete_current_image)
        self.clear_button.clicked.connect(self.clearRequested.emit)
        self.delete_all_button.clicked.connect(self.delete_all_stored_images)

    def _build_python_fallback_shell(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.status_label = QtWidgets.QLabel("Visual Reply idle")
        self.status_label.setStyleSheet("font-weight: 600; color: #d8dee9;")

        self.storage_label = QtWidgets.QLabel("Storage: empty")
        self.storage_label.setWordWrap(True)
        self.storage_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")

        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.prev_button = QtWidgets.QPushButton("Previous")
        self.load_button = QtWidgets.QPushButton("Load Image")
        self.next_button = QtWidgets.QPushButton("Next")
        self.load_story_button = QtWidgets.QPushButton("Load Current Story Image")
        self.use_style_button = QtWidgets.QPushButton("Use Current Image Style")
        self.caption_button = QtWidgets.QPushButton("Caption")
        self.delete_button = QtWidgets.QPushButton("Delete Image")
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.delete_all_button = QtWidgets.QPushButton("Delete All")
        self.prev_button.clicked.connect(self.show_previous_stored_image)
        self.next_button.clicked.connect(self.show_next_stored_image)
        self.load_button.clicked.connect(self.loadRequested.emit)
        self.load_story_button.clicked.connect(self.load_current_story_image)
        self.use_style_button.clicked.connect(self.use_current_image_style)
        self.caption_button.clicked.connect(self.captionRequested.emit)
        self.delete_button.clicked.connect(self.delete_current_image)
        self.clear_button.clicked.connect(self.clearRequested.emit)
        self.delete_all_button.clicked.connect(self.delete_all_stored_images)
        controls.addWidget(self.prev_button, 0)
        controls.addWidget(self.load_button, 0)
        controls.addWidget(self.next_button, 0)
        controls.addWidget(self.load_story_button, 0)
        controls.addWidget(self.use_style_button, 0)
        controls.addWidget(self.caption_button, 0)
        controls.addWidget(self.delete_button, 0)
        controls.addWidget(self.clear_button, 0)
        controls.addWidget(self.delete_all_button, 0)
        controls.addStretch(1)

        self.content_stack = QtWidgets.QStackedWidget()

        self.placeholder = QtWidgets.QLabel("No visual reply yet.\nWhen NC creates an image, it will appear here.")
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet(
            "background: #0f141b; border: 1px solid #273342; border-radius: 10px;"
            " color: #8ea3b8; padding: 18px;"
        )

        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.image_label.setMinimumSize(0, 0)
        self.image_label.setStyleSheet("background: transparent; border: 0;")

        self.image_scroll = AddonAltWheelZoomScrollArea()
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(QtCore.Qt.AlignCenter)
        self.image_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.image_scroll.setStyleSheet("QScrollArea { background: #0f141b; border: 1px solid #273342; border-radius: 10px; }")
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.zoomRequested.connect(self._handle_scroll_zoom_request)

        self.content_stack.addWidget(self.placeholder)
        self.content_stack.addWidget(self.image_scroll)

        self.caption_label = QtWidgets.QLabel("")
        self.caption_label.setWordWrap(True)
        self.caption_label.setStyleSheet("color: #9fb3c8; font-size: 11px; padding: 2px 2px 0 2px;")
        self.caption_label.hide()

        layout.addWidget(self.status_label)
        layout.addWidget(self.storage_label)
        layout.addLayout(controls)
        layout.addWidget(self.content_stack, 1)
        layout.addWidget(self.caption_label)

    def eventFilter(self, watched, event):
        if watched is self.image_label or watched is self.image_scroll or watched is self.image_scroll.viewport():
            if event.type() == QtCore.QEvent.Resize:
                self._refresh_displayed_pixmap()
        return super().eventFilter(watched, event)

    def _scaled_pixmap_for_label(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return pixmap
        target_size = self.image_scroll.viewport().contentsRect().size() if hasattr(self, "image_scroll") else self.image_label.contentsRect().size()
        if not target_size.isValid() or target_size.width() <= 1 or target_size.height() <= 1:
            return pixmap
        fit_size = pixmap.size().scaled(target_size, QtCore.Qt.KeepAspectRatio)
        if fit_size.width() <= 0 or fit_size.height() <= 0:
            return pixmap
        zoom_factor = max(0.25, float(getattr(self, "preview_zoom_factor", 1.0) or 1.0))
        if abs(zoom_factor - 1.0) < 0.001:
            scaled_size = fit_size
        else:
            scaled_size = QtCore.QSize(
                max(1, int(round(fit_size.width() * zoom_factor))),
                max(1, int(round(fit_size.height() * zoom_factor))),
            )
        return pixmap.scaled(scaled_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

    def _refresh_displayed_pixmap(self):
        if self.current_pixmap is None or self.current_pixmap.isNull():
            return
        display_pixmap = self._scaled_pixmap_for_label(self.current_pixmap)
        self.image_label.setPixmap(display_pixmap)
        self.image_label.resize(display_pixmap.size())

    def _handle_scroll_zoom_request(self, delta):
        step = 0.1 if delta > 0 else -0.1
        return self.adjust_zoom(step)

    def _visual_reply_storage_dir(self):
        target = Path(__file__).resolve().parents[2] / "runtime" / "visual_replies"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _visual_reply_image_paths(self):
        storage_dir = self._visual_reply_storage_dir()
        if not storage_dir.exists():
            return []
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        entries = []
        try:
            for item in storage_dir.iterdir():
                if item.is_file() and item.suffix.lower() in allowed:
                    entries.append(item)
        except Exception:
            return []
        entries.sort(key=lambda item: (item.stat().st_mtime, item.name.lower()))
        return entries

    def _visual_reply_storage_stats(self):
        entries = self._visual_reply_image_paths()
        total_bytes = 0
        for item in entries:
            try:
                total_bytes += int(item.stat().st_size)
            except Exception:
                pass
        return entries, total_bytes

    def _visual_reply_caption_from_image(self, image_path):
        path = str(image_path or "").strip()
        if not path or not os.path.isfile(path):
            return ""
        try:
            with Image.open(path) as image:
                candidates = []
                info = dict(getattr(image, "info", {}) or {})
                for key in ("Comment", "comment", "Description", "description", "Prompt", "prompt"):
                    value = info.get(key)
                    if value:
                        candidates.append(value)
                text_map = getattr(image, "text", None)
                if isinstance(text_map, dict):
                    for key in ("Comment", "comment", "Description", "description", "Prompt", "prompt"):
                        value = text_map.get(key)
                        if value:
                            candidates.append(value)
                for value in candidates:
                    if isinstance(value, bytes):
                        for encoding in ("utf-8", "utf-16", "latin-1"):
                            try:
                                value = value.decode(encoding, errors="ignore")
                                break
                            except Exception:
                                continue
                    caption_text = str(value or "").strip()
                    if caption_text:
                        return caption_text
        except Exception:
            return ""
        return ""

    def _format_storage_bytes(self, value):
        try:
            amount = float(value or 0.0)
        except Exception:
            amount = 0.0
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        unit_index = 0
        while amount >= 1024.0 and unit_index < len(units) - 1:
            amount /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(amount)} {units[unit_index]}"
        return f"{amount:.1f} {units[unit_index]}"

    def _current_storage_index(self, entries):
        if not entries:
            return -1
        current_path = str(getattr(self, "current_image_path", "") or "").strip()
        if current_path:
            current_abspath = os.path.abspath(current_path)
            for index, item in enumerate(entries):
                try:
                    if os.path.abspath(str(item)) == current_abspath:
                        return index
                except Exception:
                    continue
        return len(entries) - 1

    def _refresh_storage_summary(self):
        entries, total_bytes = self._visual_reply_storage_stats()
        if not entries:
            summary = "Storage: empty"
        else:
            current_index = self._current_storage_index(entries)
            if current_index >= 0:
                summary = (
                    f"Storage: {len(entries)} image(s), {self._format_storage_bytes(total_bytes)} total"
                    f" | Current: {current_index + 1}/{len(entries)}"
                )
            else:
                summary = f"Storage: {len(entries)} image(s), {self._format_storage_bytes(total_bytes)} total"
        self.storage_label.setText(summary)
        self.storage_label.update()
        return summary

    def _show_storage_image_by_offset(self, offset):
        entries, _ = self._visual_reply_storage_stats()
        if not entries:
            self._refresh_storage_summary()
            return False
        current_index = self._current_storage_index(entries)
        if current_index < 0:
            current_index = len(entries) - 1 if offset < 0 else 0
        target_index = max(0, min(len(entries) - 1, current_index + int(offset)))
        target_path = entries[target_index]
        caption_text = self._visual_reply_caption_from_image(target_path)
        loaded = self.show_image(str(target_path), status_text="Visual Reply history", caption=caption_text)
        if loaded:
            visual_reply_state.set_current_visual_reply_data(
                {
                    "status": "ready",
                    "status_text": "Visual Reply history",
                    "detail_text": "",
                    "image_path": str(target_path),
                    "caption": caption_text,
                    "request_id": "",
                    "updated_at": time.time(),
                }
            )
        self._refresh_storage_summary()
        return loaded

    def show_previous_stored_image(self):
        return self._show_storage_image_by_offset(-1)

    def show_next_stored_image(self):
        return self._show_storage_image_by_offset(1)

    def _invoke_addon_capability(self, capability, payload=None):
        bridge = getattr(self, "_capability_bridge", None)
        invoker = getattr(bridge, "invoke", None)
        if not callable(invoker):
            self.status_label.setText("Audio Story Mode unavailable")
            return None
        try:
            return invoker(str(capability or ""), dict(payload or {}))
        except Exception:
            self.status_label.setText("Audio Story Mode request failed")
            return None

    def load_current_story_image(self):
        result = self._invoke_addon_capability("audio_story_mode.load_current_image", {})
        if isinstance(result, dict) and result.get("ok"):
            self.status_label.setText("Story image loaded" if result.get("image_ready") else "Story image generation queued")
            return True
        self.status_label.setText("No audio story is loaded")
        return False

    def use_current_image_style(self):
        result = self._invoke_addon_capability("audio_story_mode.refresh_master_style_anchor", {})
        if isinstance(result, dict) and result.get("ok"):
            self.status_label.setText("Current image style refresh queued")
            return True
        self.status_label.setText("No audio story is loaded")
        return False

    def delete_all_stored_images(self):
        entries, _ = self._visual_reply_storage_stats()
        if not entries:
            self._refresh_storage_summary()
            return False
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete Visual Reply Images",
            f"Delete all {len(entries)} stored visual reply image(s)?",
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return False
        removed = 0
        for item in entries:
            try:
                item.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
        self.clear_visual_reply(
            status_text="Visual Reply storage cleared",
            detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.",
        )
        visual_reply_state.set_current_visual_reply_data(
            {
                "status": "idle",
                "status_text": "Visual Reply storage cleared",
                "detail_text": "No visual reply yet.\nWhen NC creates an image, it will appear here.",
                "image_path": "",
                "caption": "",
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        self._refresh_storage_summary()
        return bool(removed)

    def delete_current_image(self):
        current_path = str(getattr(self, "current_image_path", "") or "").strip()
        if not current_path or not os.path.isfile(current_path):
            return False
        storage_dir = os.path.abspath(str(self._visual_reply_storage_dir()))
        current_abs = os.path.abspath(current_path)
        try:
            within_storage = os.path.commonpath([current_abs, storage_dir]) == storage_dir
        except Exception:
            within_storage = False
        label = "Delete current image"
        if within_storage:
            entries, _ = self._visual_reply_storage_stats()
            current_index = self._current_storage_index(entries)
            if current_index < 0:
                current_index = 0
            prompt = f"Delete the currently displayed visual reply image?\n\n{current_path}"
            if len(entries) > 1:
                prompt += "\n\nThe browser will move to the next available image."
        else:
            prompt = f"Delete the currently displayed image file?\n\n{current_path}"
        answer = QtWidgets.QMessageBox.question(self, label, prompt)
        if answer != QtWidgets.QMessageBox.Yes:
            return False
        try:
            os.remove(current_path)
        except Exception:
            return False
        if within_storage:
            remaining = [item for item in self._visual_reply_image_paths() if os.path.abspath(str(item)) != current_abs]
            if remaining:
                entries = remaining
                if "current_index" not in locals():
                    current_index = 0
                target_index = min(current_index, len(entries) - 1)
                target_path = entries[target_index]
                caption_text = self._visual_reply_caption_from_image(target_path)
                self.show_image(str(target_path), status_text="Visual Reply history", caption=caption_text)
                visual_reply_state.set_current_visual_reply_data(
                    {
                        "status": "ready",
                        "status_text": "Visual Reply history",
                        "detail_text": "",
                        "image_path": str(target_path),
                        "caption": caption_text,
                        "request_id": "",
                        "updated_at": time.time(),
                    }
                )
            else:
                self.clear_visual_reply(
                    status_text="Visual Reply image deleted",
                    detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.",
                )
                visual_reply_state.set_current_visual_reply_data(
                    {
                        "status": "idle",
                        "status_text": "Visual Reply image deleted",
                        "detail_text": "No visual reply yet.\nWhen NC creates an image, it will appear here.",
                        "image_path": "",
                        "caption": "",
                        "request_id": "",
                        "updated_at": time.time(),
                    }
                )
            self._refresh_storage_summary()
        else:
            self.clear_visual_reply(
                status_text="Visual Reply image deleted",
                detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.",
            )
            visual_reply_state.set_current_visual_reply_data(
                {
                    "status": "idle",
                    "status_text": "Visual Reply image deleted",
                    "detail_text": "No visual reply yet.\nWhen NC creates an image, it will appear here.",
                    "image_path": "",
                    "caption": "",
                    "request_id": "",
                    "updated_at": time.time(),
                }
            )
        return True

    def adjust_zoom(self, delta):
        updated = max(0.25, min(4.0, float(getattr(self, "preview_zoom_factor", 1.0) or 1.0) + float(delta)))
        if abs(updated - float(getattr(self, "preview_zoom_factor", 1.0) or 1.0)) < 0.001:
            return False
        self.preview_zoom_factor = updated
        self._refresh_displayed_pixmap()
        return True

    def reset_zoom(self):
        self.preview_zoom_factor = 1.0
        self._refresh_displayed_pixmap()
        return True

    def clear_visual_reply(self, status_text="Visual Reply idle", detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here."):
        self.current_pixmap = None
        self.current_image_path = ""
        self.current_caption = ""
        self.preview_zoom_factor = 1.0
        self.image_label.clear()
        self.placeholder.setText(str(detail_text or "No visual reply yet."))
        self.status_label.setText(str(status_text or "Visual Reply idle"))
        self.caption_label.clear()
        self.caption_label.hide()
        self.content_stack.setCurrentWidget(self.placeholder)
        self._refresh_storage_summary()

    def set_caption(self, caption=""):
        caption_text = str(caption or "").strip()
        self.current_caption = caption_text
        if caption_text:
            self.caption_label.setText(caption_text)
            self.caption_label.show()
        else:
            self.caption_label.clear()
            self.caption_label.hide()
        return True

    def set_loading_state(self, status_text="Visual Reply generating...", detail_text="Preparing image...", *, keep_current_image=False):
        keep_current = bool(
            (keep_current_image or self.current_image_path)
            and self.current_pixmap is not None
            and self.current_image_path
        )
        if not keep_current:
            self.current_pixmap = None
            self.current_image_path = ""
            self.current_caption = ""
            self.preview_zoom_factor = 1.0
            self.image_label.clear()
        self.placeholder.setText(str(detail_text or "Preparing image..."))
        self.status_label.setText(str(status_text or "Visual Reply generating..."))
        if keep_current:
            self.content_stack.setCurrentWidget(self.image_scroll)
        else:
            self.caption_label.clear()
            self.caption_label.hide()
            self.content_stack.setCurrentWidget(self.placeholder)
        self._refresh_storage_summary()

    def show_image(self, image_path, status_text="Visual Reply", caption=""):
        path = str(image_path or "").strip()
        if not path or not os.path.isfile(path):
            return False
        image = QtGui.QImage(path)
        if image.isNull():
            return False
        self.current_image_path = path
        self.current_pixmap = QtGui.QPixmap.fromImage(image)
        self.preview_zoom_factor = 1.0
        self.status_label.setText(str(status_text or "Visual Reply"))
        resolved_caption = str(caption or "").strip() or self._visual_reply_caption_from_image(path)
        self.current_caption = resolved_caption
        self.set_caption(resolved_caption)
        self.content_stack.setCurrentWidget(self.image_scroll)
        self._refresh_displayed_pixmap()
        self._refresh_storage_summary()
        return True

    def poll_state(self):
        try:
            state = dict(getattr(visual_reply_state, "current_visual_reply_data", {}) or {})
            updated_at = float(state.get("updated_at", 0.0) or 0.0)
            if updated_at <= 0.0 or updated_at == self._last_visual_reply_updated_at:
                return
            self._last_visual_reply_updated_at = updated_at
            status = str(state.get("status", "idle") or "idle").strip().lower()
            host_window = self.window()
            try:
                import engine

                auto_show_enabled = bool(getattr(engine, "RUNTIME_CONFIG", {}).get("visual_reply_auto_show_dock", True))
            except Exception:
                auto_show_enabled = True
            if auto_show_enabled and status in {"loading", "ready", "error"} and hasattr(host_window, "show_visual_reply_dock"):
                try:
                    host_window.show_visual_reply_dock()
                except Exception:
                    pass
            if status == "ready":
                image_path = str(state.get("image_path", "") or "").strip()
                if image_path and os.path.isfile(image_path):
                    self.show_image(
                        image_path,
                        status_text=str(state.get("status_text", "Visual Reply") or "Visual Reply"),
                        caption=str(state.get("caption", "") or ""),
                    )
                else:
                    self.clear_visual_reply(
                        status_text="Visual Reply unavailable",
                        detail_text=str(state.get("detail_text", "The requested image could not be loaded.") or "The requested image could not be loaded."),
                    )
            elif status == "loading":
                keep_current_image = bool(state.get("keep_current_image", False))
                retained_image_path = str(state.get("image_path", "") or "").strip()
                if keep_current_image and retained_image_path and os.path.isfile(retained_image_path):
                    if not self.current_image_path or self.current_image_path != retained_image_path or self.current_pixmap is None:
                        self.show_image(
                            retained_image_path,
                            status_text=str(state.get("status_text", "Visual Reply generating...") or "Visual Reply generating..."),
                            caption=str(state.get("caption", "") or ""),
                        )
                self.set_loading_state(
                    status_text=str(state.get("status_text", "Visual Reply generating...") or "Visual Reply generating..."),
                    detail_text=str(state.get("detail_text", "Preparing image...") or "Preparing image..."),
                    keep_current_image=keep_current_image,
                )
            elif status == "error":
                self.clear_visual_reply(
                    status_text=str(state.get("status_text", "Visual Reply failed") or "Visual Reply failed"),
                    detail_text=str(state.get("detail_text", "Image generation failed.") or "Image generation failed."),
                )
            else:
                self.clear_visual_reply(
                    status_text=str(state.get("status_text", "Visual Reply idle") or "Visual Reply idle"),
                    detail_text=str(state.get("detail_text", "No visual reply yet.\nWhen NC creates an image, it will appear here.") or "No visual reply yet.\nWhen NC creates an image, it will appear here."),
                )
        except Exception:
            pass


class VisualReplyController:
    def __init__(self, context):
        self.context = context
        self._visual_reply_service = context.get_service("qt.visual_reply")
        if self._visual_reply_service is None:
            raise RuntimeError("Qt visual reply host service is unavailable.")
        self._capability_bridge = context.get_service("addons.capabilities")
        self.panel = None

    def install_panel(self):
        self.panel = AddonVisualReplyPanel(capability_bridge=self._capability_bridge)
        self._visual_reply_service.replace_panel(self.panel)

    def build_runtime_panel(self, *, capability_bridge=None):
        return AddonVisualReplyPanel(capability_bridge=capability_bridge or self._capability_bridge)

    def _ui_child(self, root, name, cls=None):
        if root is None:
            return None
        try:
            return root.findChild(cls or QtCore.QObject, name)
        except Exception:
            return None

    def _bind_core_settings_widgets(self, tab):
        snapshot = dict(self._visual_reply_service.settings_snapshot() or {})
        mode_combo = self._ui_child(tab, "visual_reply_mode_combo", QtWidgets.QComboBox)
        provider_combo = self._ui_child(tab, "visual_reply_provider_combo", QtWidgets.QComboBox)
        size_combo = self._ui_child(tab, "visual_reply_size_combo", QtWidgets.QComboBox)
        model_edit = self._ui_child(tab, "visual_reply_model_edit", QtWidgets.QLineEdit)
        auto_show_checkbox = self._ui_child(tab, "visual_reply_auto_show_checkbox", QtWidgets.QCheckBox)
        hint_label = self._ui_child(tab, "visual_reply_hint_label", QtWidgets.QLabel)
        required = (mode_combo, provider_combo, size_combo, model_edit, auto_show_checkbox, hint_label)
        if any(item is None for item in required):
            raise RuntimeError("Visual Reply Designer UI is missing one or more required controls.")

        mode_combo.addItems(list(self._visual_reply_service.mode_labels()))
        mode_combo.setCurrentText(self._visual_reply_service.mode_label_from_value(snapshot.get("mode_value", "auto")))
        provider_combo.addItems(list(self._visual_reply_service.provider_labels()))
        provider_combo.setCurrentText(self._visual_reply_service.provider_label_from_value(snapshot.get("provider_value", "openai")))
        size_combo.addItems(list(self._visual_reply_service.size_labels()))
        size_combo.setCurrentText(self._visual_reply_service.size_label_from_value(snapshot.get("size_value", "1024x1024")))
        model_edit.setText(str(snapshot.get("model_name", "gpt-image-1") or "gpt-image-1"))
        auto_show_checkbox.setChecked(bool(snapshot.get("auto_show", True)))

        self._visual_reply_service.attach_settings_widgets(
            mode_combo=mode_combo,
            provider_combo=provider_combo,
            size_combo=size_combo,
            model_edit=model_edit,
            auto_show_checkbox=auto_show_checkbox,
            hint_label=hint_label,
        )

        mode_combo.currentTextChanged.connect(self._visual_reply_service.apply_mode)
        provider_combo.currentTextChanged.connect(self._visual_reply_service.apply_provider)
        size_combo.currentTextChanged.connect(self._visual_reply_service.apply_size)
        model_edit.editingFinished.connect(self._visual_reply_service.apply_model)
        auto_show_checkbox.toggled.connect(self._visual_reply_service.apply_auto_show)
        self._visual_reply_service.refresh_hint()
        return tab

    def bind_core_tab(self, tab):
        if tab is None:
            raise RuntimeError("Visual Reply Designer UI did not provide a widget.")
        return self._bind_core_settings_widgets(tab)
