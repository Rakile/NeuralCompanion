import os
import queue
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

try:
    import cv2
except Exception:  # pragma: no cover - optional debug-mask dependency
    cv2 = None
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from addons.musetalk_avatar import state as musetalk_state
from ui.widgets.basic import AltWheelZoomScrollArea

QT_PREVIEW_CACHE_LIMIT = 384
QT_PREVIEW_INITIAL_PRELOAD = 32
QT_PREVIEW_AHEAD_PRELOAD = 32
QT_PREVIEW_POLL_INTERVAL_MS = 8
QT_MUSETALK_LOOP_FADE_MS = 180

class QtMuseTalkPreviewPanel(QtWidgets.QWidget):
    focusModeRequested = QtCore.Signal()
    showInterfaceRequested = QtCore.Signal()

    def __init__(self, parent=None, *, theme_provider=None, runtime_config=None):
        super().__init__(parent)
        self._theme_provider = theme_provider
        self._runtime_config = runtime_config if runtime_config is not None else {}
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self._root_layout = QtWidgets.QVBoxLayout(self)
        self._root_layout.setContentsMargins(10, 10, 10, 10)
        self._root_layout.setSpacing(8)
        self.focus_mode_active = False

        self.preview_label = QtWidgets.QLabel("MuseTalk preview idle")
        self.preview_label.setMinimumWidth(0)
        self.preview_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.preview_label.setStyleSheet("font-weight: 600; color: #d8dee9;")
        self.show_interface_button = QtWidgets.QPushButton("Show Interface")
        self.show_interface_button.clicked.connect(self.showInterfaceRequested.emit)
        self.focus_mode_button = QtWidgets.QPushButton("Avatar Focus")
        self.focus_mode_button.clicked.connect(self.focusModeRequested.emit)
        self.reset_zoom_button = QtWidgets.QPushButton("Reset Zoom")
        self.reset_zoom_button.clicked.connect(self.reset_zoom)
        top_row = QtWidgets.QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_row.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        top_row.addWidget(self.preview_label, 1)
        top_row.addWidget(self.reset_zoom_button, 0)
        top_row.addWidget(self.show_interface_button, 0)
        top_row.addWidget(self.focus_mode_button, 0)
        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.image_label.setMinimumSize(0, 0)
        self.image_label.setStyleSheet("background: transparent; border: 0;")
        self.image_scroll = AltWheelZoomScrollArea()
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(QtCore.Qt.AlignCenter)
        self.image_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.image_scroll.setStyleSheet("QScrollArea { background: #0f141b; border: 1px solid #273342; border-radius: 10px; }")
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.zoomRequested.connect(self._handle_scroll_zoom_request)
        self._root_layout.addLayout(top_row)
        self._root_layout.addWidget(self.image_scroll, 1)
        self.apply_theme_palette()

        self.current_sync_time = 0.0
        self.frame_paths = []
        self.frame_dir = ""
        self.current_frame_index = -1
        self.current_frame_path = None
        self.current_pixmap = None
        self.current_qimage = None
        self.last_avatar_id = None
        self.loop_fade_active = False
        self.loop_fade_from_image = None
        self.loop_fade_started_at = 0.0
        self.loop_fade_lock_until = 0.0
        self.loop_fade_duration_seconds = float(max(0, int(self._runtime_config.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS))) / 1000.0
        self.loop_fade_timer = QtCore.QTimer(self)
        self.loop_fade_timer.setInterval(16)
        self.loop_fade_timer.timeout.connect(self._on_loop_fade_timer_tick)
        self.fps = 24
        self.duration_seconds = 0.0
        self.expected_frame_count = 0
        self.trim_start_frames = 0
        self.source_indices = []
        self.chunk_started_at = 0.0
        self.next_frame_dir_scan_at = 0.0
        self.last_chunk_id = None
        self.last_start_index = 0
        self.last_feed_seq = 0
        self.last_presented_source_index = None
        self.last_presented_chunk_id = None
        self.last_presented_at = 0.0
        self.last_slow_render_log_at = 0.0
        self.pending_handoff = None
        self.last_published_at = 0.0
        self.last_audio_started_at = 0.0
        self.last_is_first_reply_chunk = False
        self.static_preview_override = False
        self.static_preview_release_sync_time = None
        self.static_preview_resume_chunk_id = None
        self.debug_mask_editor_enabled = False
        self.debug_mask_drawing = False
        self.debug_mask_draw_value = 255
        self.debug_mask_brush_radius = 12
        self.debug_mask_brush_feather = 6
        self.debug_mask_brush_transparency = 0
        self.debug_mask_base_frame = None
        self.debug_mask_full_mask = None
        self.debug_mask_bbox = None
        self.debug_mask_crop_box = None
        self.debug_mask_modified_path = None
        self.debug_mask_overlay_frame = None
        self.debug_mask_overlay_dirty_rect = None
        self.debug_mask_overlay_refresh_pending = False
        self.debug_mask_overlay_last_refresh_at = 0.0
        self.debug_mask_stroke_base_mask = None
        self.debug_mask_stroke_accumulator = None
        self.debug_mask_stroke_add_mask = True
        self.preview_zoom_factor = 1.0
        self.preloaded_frame_images = OrderedDict()
        self.preload_generation = 0
        self.preload_target_size = None
        self.preload_frontier = -1
        self.preload_lock = threading.Lock()
        self.preload_requests = queue.Queue(maxsize=256)
        self.preload_enqueued = set()
        self._preload_shutdown = False
        self.preload_worker_thread = threading.Thread(target=self._preload_worker, daemon=True)
        self.preload_worker_thread.start()

        self.image_label.installEventFilter(self)
        self.image_scroll.installEventFilter(self)
        self.image_scroll.viewport().installEventFilter(self)

        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.poll_timer.timeout.connect(self.poll_state)
        self.poll_timer.start(QT_PREVIEW_POLL_INTERVAL_MS)

    def _theme_palette(self):
        provider = getattr(self, "_theme_provider", None)
        if callable(provider):
            try:
                return dict(provider() or {})
            except Exception:
                pass
        return {
            "text_strong": "#f2f5f9",
            "window_bg": "#11161d",
            "field_bg": "#0f141b",
            "surface_border": "#273342",
        }
    def apply_theme_palette(self):
        palette = self._theme_palette()
        self.preview_label.setStyleSheet(f"font-weight: 600; color: {palette.get('text_strong', '#f2f5f9')};")
        self._apply_image_scroll_theme()

    def _apply_image_scroll_theme(self):
        palette = self._theme_palette()
        if self.focus_mode_active:
            background = palette.get("window_bg", "#11161d")
            border = "transparent"
            radius = "0"
            border_width = "0"
        else:
            background = palette.get("field_bg", "#0f141b")
            border = palette.get("surface_border", "#273342")
            radius = "10px"
            border_width = "1px"
        self.image_scroll.setStyleSheet(
            f"QScrollArea {{ background: {background}; border: {border_width} solid {border}; border-radius: {radius}; }}"
        )

    def set_focus_mode(self, enabled):
        self.focus_mode_active = bool(enabled)
        self.focus_mode_button.setText("Exit Avatar Focus" if self.focus_mode_active else "Avatar Focus")
        self.preview_label.setVisible(not self.focus_mode_active)
        if self.focus_mode_active:
            self._root_layout.setContentsMargins(4, 4, 4, 4)
        else:
            self._root_layout.setContentsMargins(10, 10, 10, 10)
        self._apply_image_scroll_theme()
        self._refresh_displayed_pixmap()
        return True

    def _publish_preview_position(self):
        state = getattr(musetalk_state, "current_musetalk_frame_data", None)
        if not isinstance(state, dict):
            return
        state["preview_chunk_id"] = self.last_chunk_id
        state["preview_frame_index"] = self.current_frame_index
        state["preview_source_index"] = self._source_index_for_frame(self.current_frame_index)
        with self.preload_lock:
            state["preview_cache_entries"] = len(self.preloaded_frame_images)
            state["preview_preload_pending"] = len(self.preload_enqueued)

    def eventFilter(self, watched, event):
        if watched is self.image_label or watched is self.image_scroll or watched is self.image_scroll.viewport():
            if event.type() == QtCore.QEvent.Resize:
                self._refresh_displayed_pixmap()
            elif watched is self.image_label and self.debug_mask_editor_enabled:
                if event.type() == QtCore.QEvent.MouseButtonPress:
                    button = event.button()
                    if button in (QtCore.Qt.LeftButton, QtCore.Qt.RightButton):
                        image_point = self._map_label_pos_to_image(event.position())
                        if image_point is not None:
                            self.debug_mask_drawing = True
                            self.debug_mask_draw_value = 255 if button == QtCore.Qt.LeftButton else 0
                            self.debug_mask_stroke_add_mask = self.debug_mask_draw_value > 0
                            self.debug_mask_stroke_base_mask = self.debug_mask_full_mask.copy() if self.debug_mask_full_mask is not None else None
                            self.debug_mask_stroke_accumulator = np.zeros_like(self.debug_mask_full_mask, dtype=np.uint8) if self.debug_mask_full_mask is not None else None
                            self._apply_debug_mask_brush(image_point[0], image_point[1], add_mask=self.debug_mask_stroke_add_mask)
                            return True
                elif event.type() == QtCore.QEvent.MouseMove and self.debug_mask_drawing:
                    image_point = self._map_label_pos_to_image(event.position())
                    if image_point is not None:
                        buttons = event.buttons()
                        add_mask = bool(buttons & QtCore.Qt.LeftButton) or not bool(buttons & QtCore.Qt.RightButton and not buttons & QtCore.Qt.LeftButton)
                        if buttons & (QtCore.Qt.LeftButton | QtCore.Qt.RightButton):
                            if buttons & QtCore.Qt.RightButton and not buttons & QtCore.Qt.LeftButton:
                                add_mask = False
                            self._apply_debug_mask_brush(image_point[0], image_point[1], add_mask=add_mask)
                            return True
                elif event.type() == QtCore.QEvent.MouseButtonRelease and self.debug_mask_drawing:
                    self.debug_mask_drawing = False
                    self._flush_debug_mask_overlay_preview()
                    self._save_debug_mask_modified()
                    self.debug_mask_stroke_base_mask = None
                    self.debug_mask_stroke_accumulator = None
                    return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        if getattr(self, "_preload_shutdown", False):
            return
        self._preload_shutdown = True
        for timer_name in ("poll_timer", "loop_fade_timer"):
            timer = getattr(self, timer_name, None)
            if timer is None:
                continue
            try:
                timer.stop()
            except Exception:
                pass
        try:
            self.image_label.removeEventFilter(self)
        except Exception:
            pass
        try:
            self.image_scroll.removeEventFilter(self)
        except Exception:
            pass
        try:
            self.image_scroll.viewport().removeEventFilter(self)
        except Exception:
            pass
        with self.preload_lock:
            self.preload_generation += 1
            self.preload_enqueued.clear()
            self.preloaded_frame_images.clear()
        while True:
            try:
                self.preload_requests.get_nowait()
                self.preload_requests.task_done()
            except queue.Empty:
                break
            except Exception:
                break
        try:
            self.preload_requests.put_nowait((None, None))
        except Exception:
            pass
        worker = getattr(self, "preload_worker_thread", None)
        if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
            try:
                worker.join(timeout=0.35)
            except Exception:
                pass

    def _map_label_pos_to_image(self, pos):
        if self.current_pixmap is None or self.current_pixmap.isNull():
            return None
        display_pixmap = self.image_label.pixmap()
        if display_pixmap is None or display_pixmap.isNull():
            return None
        label_rect = self.image_label.contentsRect()
        display_size = display_pixmap.size()
        if display_size.width() <= 0 or display_size.height() <= 0:
            return None
        offset_x = label_rect.x() + max(0, (label_rect.width() - display_size.width()) // 2)
        offset_y = label_rect.y() + max(0, (label_rect.height() - display_size.height()) // 2)
        local_x = float(pos.x()) - float(offset_x)
        local_y = float(pos.y()) - float(offset_y)
        if local_x < 0 or local_y < 0 or local_x >= display_size.width() or local_y >= display_size.height():
            return None
        scale_x = float(self.current_pixmap.width()) / float(display_size.width())
        scale_y = float(self.current_pixmap.height()) / float(display_size.height())
        image_x = int(max(0, min(self.current_pixmap.width() - 1, round(local_x * scale_x))))
        image_y = int(max(0, min(self.current_pixmap.height() - 1, round(local_y * scale_y))))
        return image_x, image_y

    def _update_debug_mask_cursor(self):
        if not self.debug_mask_editor_enabled:
            self.image_label.setCursor(QtCore.Qt.ArrowCursor)
            return
        display_pixmap = self.image_label.pixmap()
        scale_x = 1.0
        if (
            display_pixmap is not None
            and not display_pixmap.isNull()
            and self.current_pixmap is not None
            and not self.current_pixmap.isNull()
            and self.current_pixmap.width() > 0
        ):
            scale_x = float(display_pixmap.width()) / float(self.current_pixmap.width())
        outer_radius = max(1.0, float(self.debug_mask_brush_radius) * scale_x)
        feather_width = max(0.0, float(self.debug_mask_brush_feather) * scale_x)
        inner_radius = max(0.0, outer_radius - feather_width)
        cursor_radius = max(6.0, outer_radius)
        size = max(24, int(round(cursor_radius * 2 + 10)))
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        center = QtCore.QPointF(size / 2.0, size / 2.0)
        if feather_width > 0.5 and inner_radius > 0.5:
            feather_pen = QtGui.QPen(QtGui.QColor(255, 190, 70, 180), max(1.0, min(feather_width, 4.0)))
            painter.setPen(feather_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            feather_mid_radius = inner_radius + feather_width / 2.0
            painter.drawEllipse(center, feather_mid_radius, feather_mid_radius)
        if inner_radius > 0.5:
            inner_pen = QtGui.QPen(QtGui.QColor(255, 245, 170), 1.2)
            painter.setPen(inner_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(center, inner_radius, inner_radius)
        outer_pen = QtGui.QPen(QtGui.QColor(255, 225, 120), 1.6)
        painter.setPen(outer_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, outer_radius, outer_radius)
        painter.end()
        self.image_label.setCursor(QtGui.QCursor(pixmap, int(size / 2), int(size / 2)))

    def _set_debug_mask_editor_enabled(self, enabled):
        self.debug_mask_editor_enabled = bool(enabled and self.debug_mask_base_frame is not None and self.debug_mask_full_mask is not None)
        self.debug_mask_drawing = False
        self.debug_mask_stroke_base_mask = None
        self.debug_mask_stroke_accumulator = None
        self._update_debug_mask_cursor()

    def set_debug_mask_brush(self, *, radius=None, feather=None, transparency=None):
        if radius is not None:
            self.debug_mask_brush_radius = max(1, int(radius))
        if feather is not None:
            self.debug_mask_brush_feather = max(0, int(feather))
        if transparency is not None:
            self.debug_mask_brush_transparency = max(0, min(99, int(transparency)))
        self._update_debug_mask_cursor()
        return True

    def _handle_scroll_zoom_request(self, factor_delta, anchor_x, anchor_y):
        self.adjust_zoom(factor_delta, QtCore.QPointF(float(anchor_x), float(anchor_y)))

    def set_zoom_factor(self, zoom_factor, anchor_pos=None):
        new_zoom = max(0.25, min(8.0, float(zoom_factor or 1.0)))
        old_display = self.image_label.pixmap()
        hbar = self.image_scroll.horizontalScrollBar() if hasattr(self, "image_scroll") else None
        vbar = self.image_scroll.verticalScrollBar() if hasattr(self, "image_scroll") else None
        anchor_ratio_x = None
        anchor_ratio_y = None
        anchor_point = None
        if anchor_pos is not None and old_display is not None and not old_display.isNull() and hbar is not None and vbar is not None:
            try:
                anchor_point = QtCore.QPointF(anchor_pos)
            except Exception:
                anchor_point = QtCore.QPointF(float(anchor_pos.x()), float(anchor_pos.y()))
            old_width = max(1, old_display.width())
            old_height = max(1, old_display.height())
            anchor_ratio_x = (hbar.value() + anchor_point.x()) / float(old_width)
            anchor_ratio_y = (vbar.value() + anchor_point.y()) / float(old_height)
        self.preview_zoom_factor = new_zoom
        self._refresh_displayed_pixmap()
        new_display = self.image_label.pixmap()
        if anchor_point is not None and new_display is not None and not new_display.isNull() and hbar is not None and vbar is not None:
            new_width = max(1, new_display.width())
            new_height = max(1, new_display.height())
            new_h = int(round(anchor_ratio_x * new_width - anchor_point.x()))
            new_v = int(round(anchor_ratio_y * new_height - anchor_point.y()))
            hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), new_h)))
            vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), new_v)))
        return True

    def adjust_zoom(self, factor_delta, anchor_pos=None):
        factor_delta = float(factor_delta or 1.0)
        if factor_delta <= 0:
            return False
        return self.set_zoom_factor(self.preview_zoom_factor * factor_delta, anchor_pos=anchor_pos)

    def reset_zoom(self):
        self.preview_zoom_factor = 1.0
        self._refresh_displayed_pixmap()
        return True

    def clear_debug_mask_editor(self):
        self.debug_mask_base_frame = None
        self.debug_mask_full_mask = None
        self.debug_mask_bbox = None
        self.debug_mask_crop_box = None
        self.debug_mask_modified_path = None
        self.debug_mask_overlay_frame = None
        self.debug_mask_overlay_dirty_rect = None
        self.debug_mask_overlay_refresh_pending = False
        self.debug_mask_overlay_last_refresh_at = 0.0
        self.debug_mask_stroke_base_mask = None
        self.debug_mask_stroke_accumulator = None
        self._set_debug_mask_editor_enabled(False)

    def configure_debug_mask_editor(self, *, base_frame_path, mask_frame_path, bbox, crop_box, modified_mask_path=None):
        base_frame_path = str(base_frame_path or "").strip()
        mask_frame_path = str(mask_frame_path or "").strip()
        modified_mask_path = str(modified_mask_path or "").strip()
        if not base_frame_path or not mask_frame_path or not os.path.isfile(base_frame_path) or not os.path.isfile(mask_frame_path):
            self.clear_debug_mask_editor()
            return False
        base_frame = cv2.imread(base_frame_path)
        mask_path = modified_mask_path if modified_mask_path and os.path.isfile(modified_mask_path) else mask_frame_path
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if base_frame is None or mask is None:
            self.clear_debug_mask_editor()
            return False
        try:
            crop_values = [int(v) for v in list(crop_box or [])[:4]]
            bbox_values = [int(v) for v in list(bbox or [])[:4]]
        except Exception:
            self.clear_debug_mask_editor()
            return False
        if len(crop_values) != 4 or len(bbox_values) != 4:
            self.clear_debug_mask_editor()
            return False
        full_mask = np.zeros(base_frame.shape[:2], dtype=np.uint8)
        x_s, y_s, x_e, y_e = crop_values
        dest_x1 = max(0, x_s)
        dest_y1 = max(0, y_s)
        dest_x2 = min(base_frame.shape[1], x_e)
        dest_y2 = min(base_frame.shape[0], y_e)
        if dest_x2 > dest_x1 and dest_y2 > dest_y1:
            src_x1 = dest_x1 - x_s
            src_y1 = dest_y1 - y_s
            src_x2 = min(mask.shape[1], src_x1 + (dest_x2 - dest_x1))
            src_y2 = min(mask.shape[0], src_y1 + (dest_y2 - dest_y1))
            dest_x2 = dest_x1 + (src_x2 - src_x1)
            dest_y2 = dest_y1 + (src_y2 - src_y1)
            if src_x2 > src_x1 and src_y2 > src_y1 and dest_x2 > dest_x1 and dest_y2 > dest_y1:
                full_mask[dest_y1:dest_y2, dest_x1:dest_x2] = mask[src_y1:src_y2, src_x1:src_x2]
        self.debug_mask_base_frame = base_frame
        self.debug_mask_full_mask = full_mask
        self.debug_mask_bbox = bbox_values
        self.debug_mask_crop_box = crop_values
        self.debug_mask_modified_path = modified_mask_path or str(Path(mask_frame_path).with_name('debug_mask_modified.png'))
        self._set_debug_mask_editor_enabled(True)
        self._refresh_debug_mask_overlay_preview()
        return True

    def _save_debug_mask_modified(self):
        if self.debug_mask_full_mask is None or not self.debug_mask_modified_path or not self.debug_mask_crop_box:
            return False
        x_s, y_s, x_e, y_e = [int(v) for v in self.debug_mask_crop_box]
        crop_width = max(1, x_e - x_s)
        crop_height = max(1, y_e - y_s)
        crop_mask = np.zeros((crop_height, crop_width), dtype=np.uint8)
        dest_x1 = max(0, x_s)
        dest_y1 = max(0, y_s)
        dest_x2 = min(self.debug_mask_full_mask.shape[1], x_e)
        dest_y2 = min(self.debug_mask_full_mask.shape[0], y_e)
        if dest_x2 > dest_x1 and dest_y2 > dest_y1:
            src_x1 = dest_x1 - x_s
            src_y1 = dest_y1 - y_s
            src_x2 = src_x1 + (dest_x2 - dest_x1)
            src_y2 = src_y1 + (dest_y2 - dest_y1)
            crop_mask[src_y1:src_y2, src_x1:src_x2] = self.debug_mask_full_mask[dest_y1:dest_y2, dest_x1:dest_x2]
        Path(self.debug_mask_modified_path).parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(self.debug_mask_modified_path, crop_mask))

    def _refresh_debug_mask_overlay_preview(self):
        if self.debug_mask_base_frame is None or self.debug_mask_full_mask is None:
            return False
        mask_overlay = self.debug_mask_base_frame.copy()
        self._blend_debug_mask_overlay_region(mask_overlay, 0, 0, mask_overlay.shape[1], mask_overlay.shape[0])
        if self.debug_mask_bbox and len(self.debug_mask_bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in self.debug_mask_bbox]
            cv2.rectangle(mask_overlay, (x1, y1), (x2, y2), (0, 220, 255), 3)
        cv2.putText(mask_overlay, 'MASK OVERLAY (EDIT)', (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2, cv2.LINE_AA)
        self.debug_mask_overlay_frame = mask_overlay
        rgb = cv2.cvtColor(mask_overlay, cv2.COLOR_BGR2RGB)
        qimage = QtGui.QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QtGui.QImage.Format_RGB888).copy()
        self.current_pixmap = QtGui.QPixmap.fromImage(qimage)
        self._refresh_displayed_pixmap()
        self.preview_label.setText('MuseTalk debug mask overlay (editable)')
        return True

    def _blend_debug_mask_overlay_region(self, overlay_frame, x_start, y_start, x_end, y_end):
        if self.debug_mask_base_frame is None or self.debug_mask_full_mask is None:
            return False
        height, width = self.debug_mask_full_mask.shape[:2]
        x_start = max(0, min(width, int(x_start)))
        y_start = max(0, min(height, int(y_start)))
        x_end = max(x_start, min(width, int(x_end)))
        y_end = max(y_start, min(height, int(y_end)))
        if x_end <= x_start or y_end <= y_start:
            return False
        base_patch = self.debug_mask_base_frame[y_start:y_end, x_start:x_end]
        mask_patch = self.debug_mask_full_mask[y_start:y_end, x_start:x_end]
        alpha = (mask_patch.astype(np.float32) / 255.0)[:, :, None] * 0.75
        overlay_color = np.zeros_like(base_patch)
        overlay_color[:, :, 2] = 255
        overlay_color[:, :, 1] = 40
        overlay_frame[y_start:y_end, x_start:x_end] = (
            base_patch.astype(np.float32) * (1.0 - alpha) + overlay_color.astype(np.float32) * alpha
        ).clip(0, 255).astype(np.uint8)
        return True

    def _merge_debug_mask_dirty_rect(self, rect):
        if rect is None:
            return
        x_start, y_start, x_end, y_end = [int(v) for v in rect]
        if self.debug_mask_overlay_dirty_rect is None:
            self.debug_mask_overlay_dirty_rect = (x_start, y_start, x_end, y_end)
            return
        old_x1, old_y1, old_x2, old_y2 = self.debug_mask_overlay_dirty_rect
        self.debug_mask_overlay_dirty_rect = (
            min(old_x1, x_start),
            min(old_y1, y_start),
            max(old_x2, x_end),
            max(old_y2, y_end),
        )

    def _schedule_debug_mask_overlay_preview(self, rect):
        self._merge_debug_mask_dirty_rect(rect)
        now = time.time()
        min_interval = 1.0 / 30.0
        elapsed = now - float(self.debug_mask_overlay_last_refresh_at or 0.0)
        if elapsed >= min_interval:
            self._flush_debug_mask_overlay_preview()
            return
        if self.debug_mask_overlay_refresh_pending:
            return
        self.debug_mask_overlay_refresh_pending = True
        delay_ms = max(1, int(round((min_interval - elapsed) * 1000.0)))
        QtCore.QTimer.singleShot(delay_ms, self._flush_debug_mask_overlay_preview)

    def _flush_debug_mask_overlay_preview(self):
        self.debug_mask_overlay_refresh_pending = False
        if (
            self.debug_mask_base_frame is None
            or self.debug_mask_full_mask is None
            or self.debug_mask_overlay_dirty_rect is None
        ):
            return False
        if self.debug_mask_overlay_frame is None:
            return self._refresh_debug_mask_overlay_preview()
        x_start, y_start, x_end, y_end = self.debug_mask_overlay_dirty_rect
        self.debug_mask_overlay_dirty_rect = None
        if not self._blend_debug_mask_overlay_region(self.debug_mask_overlay_frame, x_start, y_start, x_end, y_end):
            return False
        if self.debug_mask_bbox and len(self.debug_mask_bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in self.debug_mask_bbox]
            cv2.rectangle(self.debug_mask_overlay_frame, (x1, y1), (x2, y2), (0, 220, 255), 3)
        cv2.putText(self.debug_mask_overlay_frame, 'MASK OVERLAY (EDIT)', (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2, cv2.LINE_AA)
        rgb = cv2.cvtColor(self.debug_mask_overlay_frame, cv2.COLOR_BGR2RGB)
        qimage = QtGui.QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QtGui.QImage.Format_RGB888).copy()
        self.current_pixmap = QtGui.QPixmap.fromImage(qimage)
        self._refresh_displayed_pixmap()
        self.debug_mask_overlay_last_refresh_at = time.time()
        self.preview_label.setText('MuseTalk debug mask overlay (editable)')
        return True

    def _apply_debug_mask_brush(self, image_x, image_y, *, add_mask):
        if self.debug_mask_full_mask is None or not self.debug_mask_bbox:
            return False
        x1, y1, x2, y2 = [int(v) for v in self.debug_mask_bbox]
        if image_x < x1 or image_x > x2 or image_y < y1 or image_y > y2:
            return False
        radius = max(1, int(self.debug_mask_brush_radius))
        feather = max(0, int(self.debug_mask_brush_feather))
        transparency = max(0, min(99, int(getattr(self, "debug_mask_brush_transparency", 0) or 0)))
        strength = max(1, 100 - transparency) / 100.0
        outer_radius = float(radius)
        inner_radius = max(0.0, float(radius - feather))
        x_start = max(0, int(image_x - radius))
        y_start = max(0, int(image_y - radius))
        x_end = min(self.debug_mask_full_mask.shape[1], int(image_x + radius + 1))
        y_end = min(self.debug_mask_full_mask.shape[0], int(image_y + radius + 1))
        x_start = max(x_start, x1)
        y_start = max(y_start, y1)
        x_end = min(x_end, x2 + 1)
        y_end = min(y_end, y2 + 1)
        if x_end <= x_start or y_end <= y_start:
            return False
        yy, xx = np.ogrid[y_start:y_end, x_start:x_end]
        distances = np.sqrt((xx - float(image_x)) ** 2 + (yy - float(image_y)) ** 2)
        alpha = np.zeros((y_end - y_start, x_end - x_start), dtype=np.float32)
        alpha[distances <= inner_radius] = 1.0
        if outer_radius > inner_radius:
            ring = (distances > inner_radius) & (distances <= outer_radius)
            alpha[ring] = ((outer_radius - distances[ring]) / max(0.001, outer_radius - inner_radius)).astype(np.float32)
        elif inner_radius <= 0:
            alpha[distances <= outer_radius] = 1.0
        brush_patch = np.clip(alpha * 255.0 * strength, 0, 255).astype(np.uint8)
        if self.debug_mask_stroke_base_mask is None or self.debug_mask_stroke_accumulator is None:
            self.debug_mask_stroke_base_mask = self.debug_mask_full_mask.copy()
            self.debug_mask_stroke_accumulator = np.zeros_like(self.debug_mask_full_mask, dtype=np.uint8)
            self.debug_mask_stroke_add_mask = bool(add_mask)
        acc_patch = self.debug_mask_stroke_accumulator[y_start:y_end, x_start:x_end]
        self.debug_mask_stroke_accumulator[y_start:y_end, x_start:x_end] = np.maximum(acc_patch, brush_patch)
        if self.debug_mask_stroke_add_mask:
            base_patch = self.debug_mask_stroke_base_mask[y_start:y_end, x_start:x_end]
            acc_patch = self.debug_mask_stroke_accumulator[y_start:y_end, x_start:x_end]
            self.debug_mask_full_mask[y_start:y_end, x_start:x_end] = np.maximum(base_patch, acc_patch)
        else:
            base_patch = self.debug_mask_stroke_base_mask[y_start:y_end, x_start:x_end].astype(np.float32)
            alpha_mask = self.debug_mask_stroke_accumulator[y_start:y_end, x_start:x_end].astype(np.float32) / 255.0
            self.debug_mask_full_mask[y_start:y_end, x_start:x_end] = np.clip(base_patch * (1.0 - alpha_mask), 0, 255).astype(np.uint8)
        self._schedule_debug_mask_overlay_preview((x_start, y_start, x_end, y_end))
        return True

    def reset_preview(self):
        self.current_sync_time = 0.0
        self.frame_paths = []
        self.frame_dir = ""
        self.current_frame_index = -1
        self.current_frame_path = None
        self.current_pixmap = None
        self.current_qimage = None
        self.last_avatar_id = None
        self._stop_loop_fade()
        self.duration_seconds = 0.0
        self.expected_frame_count = 0
        self.trim_start_frames = 0
        self.source_indices = []
        self.chunk_started_at = 0.0
        self.next_frame_dir_scan_at = 0.0
        self.last_chunk_id = None
        self.last_start_index = 0
        self.last_feed_seq = 0
        self.last_presented_source_index = None
        self.last_presented_chunk_id = None
        self.last_presented_at = 0.0
        self.last_slow_render_log_at = 0.0
        self.pending_handoff = None
        self.last_published_at = 0.0
        self.last_audio_started_at = 0.0
        self.last_is_first_reply_chunk = False
        self.static_preview_override = False
        self.static_preview_release_sync_time = None
        self.static_preview_resume_chunk_id = None
        self._invalidate_cache_for_resize()
        self.image_label.clear()
        self.preview_label.setText("MuseTalk preview idle")
        state = getattr(musetalk_state, "current_musetalk_frame_data", None)
        if isinstance(state, dict):
            state["preview_chunk_id"] = None
            state["preview_frame_index"] = -1
            state["preview_source_index"] = None

    def _invalidate_cache_for_resize(self):
        self.preload_generation += 1
        self.preload_target_size = None
        self.preload_frontier = -1
        with self.preload_lock:
            self.preloaded_frame_images = OrderedDict()
            self.preload_enqueued = set()

    def _restart_preload_window(self):
        self.preload_generation += 1
        self.preload_frontier = -1
        with self.preload_lock:
            self.preload_enqueued = set()

    def _get_target_size(self):
        return None

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
        return pixmap.scaled(
            scaled_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

    def _refresh_displayed_pixmap(self):
        if self.current_pixmap is None or self.current_pixmap.isNull():
            return
        display_pixmap = self._scaled_pixmap_for_label(self.current_pixmap)
        self.image_label.setPixmap(display_pixmap)
        self.image_label.resize(display_pixmap.size())
        if self.debug_mask_editor_enabled:
            self._update_debug_mask_cursor()

    def show_static_frame(self, frame_path, status_text=None):
        frame_path = str(frame_path or "").strip()
        if not frame_path or not os.path.isfile(frame_path):
            return False
        image = QtGui.QImage(frame_path)
        if image.isNull():
            return False
        self.current_sync_time = 0.0
        self.frame_paths = [frame_path]
        self.frame_dir = str(Path(frame_path).parent)
        self.current_frame_index = 0
        self.current_frame_path = frame_path
        self.current_qimage = image.copy()
        self.current_pixmap = QtGui.QPixmap.fromImage(self.current_qimage)
        self._stop_loop_fade()
        self.expected_frame_count = 1
        self.duration_seconds = 0.0
        self.trim_start_frames = 0
        self.source_indices = [0]
        self.last_chunk_id = Path(frame_path).parent.name
        self.last_start_index = 0
        self.pending_handoff = None
        self.last_presented_chunk_id = self.last_chunk_id
        self.last_presented_source_index = 0
        state = getattr(musetalk_state, "current_musetalk_frame_data", None)
        current_sync_time = None
        if isinstance(state, dict):
            try:
                current_sync_time = float(state.get("sync_time", 0.0) or 0.0)
            except Exception:
                current_sync_time = 0.0
            self.static_preview_resume_chunk_id = state.get("chunk_id")
        else:
            self.static_preview_resume_chunk_id = None
        self.static_preview_override = True
        self.static_preview_release_sync_time = current_sync_time
        self._refresh_displayed_pixmap()
        if status_text:
            self.preview_label.setText(str(status_text))
        else:
            self.preview_label.setText("MuseTalk first-frame test")
        return True

    def _source_index_for_frame(self, frame_index):
        if 0 <= frame_index < len(self.source_indices):
            try:
                return int(self.source_indices[frame_index])
            except Exception:
                pass
        return self.last_start_index + max(frame_index, 0)

    def _build_cached_preview_image(self, frame_path, _target_size):
        image = QtGui.QImage(str(frame_path))
        if image.isNull():
            raise ValueError(f"Could not load preview frame: {frame_path}")
        return image.copy()

    def _get_cached_preview_image(self, frame_path):
        with self.preload_lock:
            cached = self.preloaded_frame_images.get(frame_path)
            if cached is not None:
                self.preloaded_frame_images.move_to_end(frame_path)
                return cached
        return None

    def _store_cached_preview_image(self, frame_path, image):
        with self.preload_lock:
            self.preloaded_frame_images[frame_path] = image
            self.preloaded_frame_images.move_to_end(frame_path)
            while len(self.preloaded_frame_images) > QT_PREVIEW_CACHE_LIMIT:
                self.preloaded_frame_images.popitem(last=False)

    def _start_frame_preload(self, start_index=0, count=12, *, wrap=False):
        if getattr(self, "_preload_shutdown", False):
            return
        if not self.frame_paths or not self.isVisible():
            return
        target_size = self._get_target_size()
        if target_size != self.preload_target_size:
            self._invalidate_cache_for_resize()
            self.preload_target_size = target_size
        generation = self.preload_generation
        if wrap:
            total = len(self.frame_paths)
            if total <= 0:
                return
            start_index = int(start_index or 0) % total
            preload_paths = [self.frame_paths[(start_index + offset) % total] for offset in range(max(0, int(count or 0)))]
        else:
            requested_end = min(len(self.frame_paths), max(0, int(start_index or 0)) + max(0, int(count or 0)))
            if requested_end <= self.preload_frontier:
                return
            preload_start = max(0, min(len(self.frame_paths), max(int(start_index or 0), self.preload_frontier)))
            self.preload_frontier = requested_end
            preload_paths = list(self.frame_paths[preload_start:requested_end])
        with self.preload_lock:
            for frame_path in preload_paths:
                key = (generation, frame_path)
                if key in self.preload_enqueued:
                    continue
                try:
                    self.preload_requests.put_nowait(key)
                    self.preload_enqueued.add(key)
                except queue.Full:
                    break

    def _preload_worker(self):
        while True:
            generation, frame_path = self.preload_requests.get()
            try:
                if generation is None and frame_path is None:
                    break
                if getattr(self, "_preload_shutdown", False):
                    continue
                if generation != self.preload_generation:
                    continue
                if not frame_path or not os.path.exists(frame_path):
                    continue
                if self._get_cached_preview_image(frame_path) is not None:
                    continue
                try:
                    image = self._build_cached_preview_image(frame_path, self.preload_target_size)
                except Exception:
                    continue
                if getattr(self, "_preload_shutdown", False):
                    continue
                self._store_cached_preview_image(frame_path, image)
            finally:
                with self.preload_lock:
                    self.preload_enqueued.discard((generation, frame_path))
                self.preload_requests.task_done()

    def _refresh_frame_paths_from_dir(self):
        if not self.frame_dir or not os.path.isdir(self.frame_dir):
            return
        scanned = sorted(
            os.path.join(self.frame_dir, name)
            for name in os.listdir(self.frame_dir)
            if name.lower().endswith(".png")
        )
        if self.trim_start_frames > 0 and scanned:
            trimmed = scanned[min(self.trim_start_frames, len(scanned) - 1):]
            if trimmed:
                scanned = trimmed
        self.frame_paths = scanned
        if len(self.frame_paths) > self.expected_frame_count:
            self.expected_frame_count = len(self.frame_paths)

    def _ensure_preview_argb32(self, image):
        if image is None or image.isNull():
            return None
        if image.format() == QtGui.QImage.Format_ARGB32:
            return image
        return image.convertToFormat(QtGui.QImage.Format_ARGB32)

    def _compose_loop_fade_image(self, alpha):
        source = self._ensure_preview_argb32(self.loop_fade_from_image)
        target = self._ensure_preview_argb32(self.current_qimage)
        if source is None or target is None:
            return None
        target_size = target.size()
        if source.size() != target_size:
            source = source.scaled(target_size, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
        alpha = max(0.0, min(float(alpha), 1.0))
        composed = QtGui.QImage(target_size, QtGui.QImage.Format_ARGB32)
        composed.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(composed)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.setOpacity(max(0.0, 1.0 - alpha))
        painter.drawImage(0, 0, source)
        painter.setOpacity(alpha)
        painter.drawImage(0, 0, target)
        painter.end()
        return composed

    def _stop_loop_fade(self):
        self.loop_fade_active = False
        self.loop_fade_from_image = None
        self.loop_fade_lock_until = 0.0
        if hasattr(self, 'loop_fade_timer') and self.loop_fade_timer.isActive():
            self.loop_fade_timer.stop()

    def _on_loop_fade_timer_tick(self):
        if not self._update_loop_fade_display():
            self._stop_loop_fade()

    def _compute_runtime_frame_index(self, state=None, now=None):
        if not self.frame_paths or not self.chunk_started_at:
            return None
        state = state or (musetalk_state.current_musetalk_frame_data or {})
        now = time.time() if now is None else float(now)
        elapsed = max(0.0, now - self.chunk_started_at)
        if state.get("loop", False):
            if str(state.get("chunk_id", "") or "") == "idle" and self.current_frame_index >= 0:
                frame_interval = 1.0 / max(self.fps, 1)
                last_presented = float(self.last_presented_at or self.chunk_started_at or now)
                if (now - last_presented) < (frame_interval * 0.85):
                    return self.current_frame_index
                return (self.current_frame_index + 1) % len(self.frame_paths)
            return int(elapsed * max(self.fps, 1)) % len(self.frame_paths)
        if self.duration_seconds > 0:
            progress = min(elapsed / self.duration_seconds, 1.0)
            expected_count = max(self.expected_frame_count, len(self.frame_paths), 1)
            frame_span = max(expected_count - 1, 1)
            target_index = min(int(progress * frame_span), expected_count - 1)
            return min(target_index, len(self.frame_paths) - 1)
        return min(int(elapsed * max(self.fps, 1)), len(self.frame_paths) - 1)

    def _catch_up_preview_after_loop_fade(self):
        if self.loop_fade_active:
            return
        frame_index = self._compute_runtime_frame_index()
        if frame_index is None or frame_index == self.current_frame_index:
            return
        next_frame_path = self.frame_paths[frame_index]
        if not os.path.exists(next_frame_path):
            return
        self.current_frame_index = frame_index
        self.current_frame_path = next_frame_path
        state = musetalk_state.current_musetalk_frame_data or {}
        if not state.get("loop", False):
            self._start_frame_preload(
                start_index=frame_index + 1,
                count=min(
                    max(len(self.frame_paths) - (frame_index + 1), 0),
                    QT_PREVIEW_AHEAD_PRELOAD,
                ),
            )
        self.render_current_frame()

    def _update_loop_fade_display(self, *, force=False):
        if not self.loop_fade_active:
            return False
        if self.loop_fade_from_image is None or self.current_qimage is None:
            self._stop_loop_fade()
            return False
        elapsed = max(0.0, time.time() - float(self.loop_fade_started_at or 0.0))
        duration = max(0.001, float(self.loop_fade_duration_seconds or 0.001))
        alpha = 1.0 if force else min(elapsed / duration, 1.0)
        blended = self._compose_loop_fade_image(alpha)
        if blended is None:
            self._stop_loop_fade()
            return False
        self.current_pixmap = QtGui.QPixmap.fromImage(blended)
        self._refresh_displayed_pixmap()
        if alpha >= 1.0:
            self._stop_loop_fade()
            QtCore.QTimer.singleShot(0, self._catch_up_preview_after_loop_fade)
        return True

    def _start_loop_fade_if_needed(self, previous_avatar_id, next_avatar_id, state, previous_chunk_id=None):
        previous_avatar = str(previous_avatar_id or '').strip()
        next_avatar = str(next_avatar_id or '').strip()
        next_chunk_id = str((state or {}).get('chunk_id', '') or '')
        previous_chunk_id = str(previous_chunk_id or '').strip()
        is_plan_to_speech_handoff = bool(
            previous_chunk_id.startswith('first_chunk_plan:')
            and next_chunk_id
            and not next_chunk_id.startswith('first_chunk_plan:')
        )
        avatar_changed = bool(previous_avatar and next_avatar and previous_avatar != next_avatar)
        if not avatar_changed and not is_plan_to_speech_handoff:
            return False
        fade_ms = max(0, int(self._runtime_config.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or 0))
        self.loop_fade_duration_seconds = float(fade_ms) / 1000.0
        if fade_ms <= 0:
            self.loop_fade_active = False
            self.loop_fade_from_image = None
            return False
        source_image = None
        if self.current_pixmap is not None and not self.current_pixmap.isNull():
            try:
                source_image = self.current_pixmap.toImage()
            except Exception:
                source_image = None
        if source_image is None or source_image.isNull():
            if self.current_qimage is None or self.current_qimage.isNull():
                self.loop_fade_active = False
                self.loop_fade_from_image = None
                return False
            source_image = self.current_qimage
        self.loop_fade_from_image = source_image.copy()
        self.loop_fade_started_at = time.time()
        self.loop_fade_lock_until = self.loop_fade_started_at + self.loop_fade_duration_seconds
        self.loop_fade_active = True
        if not self.loop_fade_timer.isActive():
            self.loop_fade_timer.start()
        return True

    def render_current_frame(self):
        if not self.current_frame_path or not os.path.exists(self.current_frame_path):
            return
        render_started_at = time.time()
        load_ms = 0.0
        cache_hit = False
        cached = self._get_cached_preview_image(self.current_frame_path)
        if cached is None:
            try:
                load_started_at = time.time()
                cached = self._build_cached_preview_image(self.current_frame_path, self._get_target_size())
                load_ms = (time.time() - load_started_at) * 1000.0
            except Exception:
                return
            self._store_cached_preview_image(self.current_frame_path, cached)
        else:
            cache_hit = True
        self.current_qimage = cached.copy()
        pixmap = QtGui.QPixmap.fromImage(self.current_qimage)
        if pixmap.isNull():
            return
        self.current_pixmap = pixmap
        set_started_at = time.time()
        if not self._update_loop_fade_display():
            self._refresh_displayed_pixmap()
        set_ms = (time.time() - set_started_at) * 1000.0
        render_ms = (time.time() - render_started_at) * 1000.0
        now = time.time()
        displayed_source = self._source_index_for_frame(self.current_frame_index)
        self.last_presented_source_index = displayed_source
        self.last_presented_chunk_id = self.last_chunk_id
        self.last_presented_at = now
        self._publish_preview_position()
        if self.pending_handoff and self.last_chunk_id == self.pending_handoff.get("chunk_id"):
            message = (
                f"🚪 [MuseTalkPreview] First-frame handoff: "
                f"from={self.pending_handoff.get('previous_chunk_id')} "
                f"to={self.pending_handoff.get('chunk_id')} "
                f"prev_source={self.pending_handoff.get('previous_source_index')} "
                f"next_start={self.pending_handoff.get('next_start_index')} "
                f"displayed_source={displayed_source} "
                f"present={(now - self.pending_handoff.get('armed_at', now)) * 1000.0:.1f} ms "
                f"render={render_ms:.1f} ms "
                f"load={load_ms:.1f} ms "
                f"set={set_ms:.1f} ms "
                f"cache={'hit' if cache_hit else 'miss'} "
                f"preview_cache_entries={len(self.preloaded_frame_images)} "
                f"preview_preload_pending={len(self.preload_enqueued)}"
            )
            if self.last_is_first_reply_chunk:
                if self.last_published_at:
                    message += f" publish_to_present={(now - self.last_published_at) * 1000.0:.1f} ms"
                if self.last_audio_started_at:
                    message += f" audio_to_present={(now - self.last_audio_started_at) * 1000.0:.1f} ms"
            musetalk_state.append_musetalk_preview_log(message)
            print(message)
            self.pending_handoff = None
        if render_ms >= 20.0 and (now - self.last_slow_render_log_at) > 0.25:
            self.last_slow_render_log_at = now
            message = (
                f"🖼️ [MuseTalkPreview] Slow frame render: {render_ms:.1f} ms "
                f"(chunk={self.last_chunk_id}, frame={self.current_frame_index}, "
                f"cache={'hit' if cache_hit else 'miss'}, load={load_ms:.1f} ms, set={set_ms:.1f} ms, "
                f"preview_cache_entries={len(self.preloaded_frame_images)}, preview_preload_pending={len(self.preload_enqueued)})"
            )
            musetalk_state.append_musetalk_preview_log(message)
            print(message)

    def _set_preview_status(self, state):
        status = state.get("status", "idle")
        should_loop = bool(state.get("loop", False))
        text = (state.get("text", "") or "").strip()
        chunk_id = state.get("chunk_id")
        if status == "ready":
            self.preview_label.setText(f"MuseTalk: {text[:60]}")
        elif chunk_id and str(chunk_id).startswith("first_chunk_plan:"):
            self.preview_label.setText("MuseTalk warming speech")
        elif should_loop:
            self.preview_label.setText("MuseTalk idle")
        else:
            self.preview_label.setText("MuseTalk preview idle")

    def _apply_new_state(self, state):
        previous_chunk_id = self.last_chunk_id
        previous_frame_index = self.current_frame_index
        previous_source = self.last_presented_source_index
        previous_avatar_id = self.last_avatar_id
        self.current_sync_time = float(state.get("sync_time", 0.0) or 0.0)
        self.frame_paths = list(state.get("frame_paths", []) or [])
        self.frame_dir = state.get("frame_dir", "")
        self.current_frame_index = -1
        self.current_frame_path = None
        self.fps = int(state.get("fps", 24) or 24)
        self.duration_seconds = float(state.get("duration_seconds", 0.0) or 0.0)
        self.expected_frame_count = int(state.get("expected_frame_count", 0) or len(self.frame_paths))
        self.trim_start_frames = int(state.get("trim_start_frames", 0) or 0)
        self.source_indices = list(state.get("source_indices", []) or [])
        self.chunk_started_at = self.current_sync_time
        self.next_frame_dir_scan_at = 0.0
        self.last_chunk_id = state.get("chunk_id")
        self.last_start_index = int(state.get("start_index", 0) or 0)
        self.last_published_at = float(state.get("published_at", 0.0) or 0.0)
        self.last_audio_started_at = float(state.get("audio_started_at", 0.0) or 0.0)
        self.last_is_first_reply_chunk = bool(state.get("is_first_reply_chunk", False))
        self.last_avatar_id = str(state.get("avatar_id", "") or "").strip() or None
        self._restart_preload_window()
        self._set_preview_status(state)
        if previous_chunk_id and self.last_chunk_id and previous_chunk_id != self.last_chunk_id:
            previous_source_index = previous_source
            if previous_source_index is None and previous_frame_index >= 0:
                previous_source_index = self.last_start_index + max(previous_frame_index, 0)
            message = (
                f"🧪 [MuseTalkPreview] Handoff {previous_chunk_id} -> {self.last_chunk_id}: "
                f"prev_frame={previous_frame_index}, prev_source={previous_source_index}, "
                f"next_start={self.last_start_index}, buffered={len(self.frame_paths)}, expected={self.expected_frame_count}, "
                f"preview_cache_entries={len(self.preloaded_frame_images)}, preview_preload_pending={len(self.preload_enqueued)}"
            )
            musetalk_state.append_musetalk_preview_log(message)
            print(message)
            self.pending_handoff = {
                "previous_chunk_id": previous_chunk_id,
                "previous_source_index": previous_source_index,
                "chunk_id": self.last_chunk_id,
                "next_start_index": self.last_start_index,
                "armed_at": time.time(),
            }

        if not self.frame_paths and self.frame_dir:
            self._refresh_frame_paths_from_dir()
        if not self.frame_paths:
            self.image_label.clear()
            return

        initial_frame_index = 0
        is_idle_to_first_plan = (
            previous_chunk_id == "idle"
            and self.last_chunk_id
            and str(self.last_chunk_id).startswith("first_chunk_plan:")
        )
        is_idle_to_speech = (
            previous_chunk_id == "idle"
            and self.last_chunk_id
            and not str(self.last_chunk_id).startswith("first_chunk_plan:")
            and not bool(state.get("loop", False))
        )
        is_first_plan_handoff = (
            previous_chunk_id
            and str(previous_chunk_id).startswith("first_chunk_plan:")
            and self.last_chunk_id
            and not str(self.last_chunk_id).startswith("first_chunk_plan:")
            and not bool(state.get("loop", False))
        )
        if is_idle_to_first_plan and self.source_indices:
            target_start = self.last_start_index
            for idx, source_index in enumerate(self.source_indices):
                try:
                    if int(source_index) >= int(target_start):
                        initial_frame_index = idx
                        break
                except Exception:
                    continue
        elif is_idle_to_speech:
            target_start = self.last_start_index
            if self.source_indices:
                for idx, source_index in enumerate(self.source_indices):
                    try:
                        if int(source_index) >= int(target_start):
                            initial_frame_index = idx
                            break
                    except Exception:
                        continue
            else:
                initial_frame_index = max(0, target_start - self.last_start_index)
                initial_frame_index = min(initial_frame_index, max(len(self.frame_paths) - 1, 0))
        elif not is_first_plan_handoff and previous_source is not None:
            for idx in range(len(self.frame_paths)):
                if self._source_index_for_frame(idx) > previous_source:
                    initial_frame_index = idx
                    break
        elif is_first_plan_handoff and self.source_indices:
            target_start = self.last_start_index
            for idx, source_index in enumerate(self.source_indices):
                try:
                    if int(source_index) >= int(target_start):
                        initial_frame_index = idx
                        break
                except Exception:
                    continue
        elif state.get("loop", False) and previous_source is None and self.frame_paths:
            # If the preview is attached after the idle loop has already started,
            # begin near the live idle frame instead of frame 0. Otherwise the
            # next poll jumps far ahead of the preload window and every displayed
            # idle frame becomes a disk cache miss for a while.
            try:
                elapsed = max(0.0, time.time() - float(self.chunk_started_at or time.time()))
                initial_frame_index = int(elapsed * max(self.fps, 1)) % len(self.frame_paths)
            except Exception:
                initial_frame_index = 0
        self.current_frame_index = initial_frame_index
        self.current_frame_path = self.frame_paths[initial_frame_index]
        self._start_loop_fade_if_needed(previous_avatar_id, self.last_avatar_id, state, previous_chunk_id=previous_chunk_id)
        self._start_frame_preload(
            start_index=initial_frame_index,
            count=QT_PREVIEW_INITIAL_PRELOAD if bool(state.get("loop", False)) else min(max(len(self.frame_paths) - initial_frame_index, 1), QT_PREVIEW_INITIAL_PRELOAD),
            wrap=bool(state.get("loop", False)),
        )
        self.render_current_frame()

    def poll_state(self):
        try:
            if self.loop_fade_active:
                self._update_loop_fade_display()
            fade_locked = bool(self.loop_fade_active and time.time() < float(self.loop_fade_lock_until or 0.0))
            state = musetalk_state.current_musetalk_frame_data or {}
            sync_time = float(state.get("sync_time", 0.0) or 0.0)
            if self.static_preview_override:
                incoming_chunk_id = state.get("chunk_id")
                if not incoming_chunk_id or incoming_chunk_id == self.static_preview_resume_chunk_id:
                    return
                self.static_preview_override = False
                self.static_preview_release_sync_time = None
                self.static_preview_resume_chunk_id = None
            if sync_time != self.current_sync_time:
                self._apply_new_state(state)

            feed_updates = musetalk_state.consume_musetalk_preview_feed(self.last_feed_seq)
            if feed_updates:
                latest = feed_updates[-1]
                self.last_feed_seq = int(latest.get("_seq", self.last_feed_seq) or self.last_feed_seq)
                frame_path = latest.get("frame_path")
                if frame_path and os.path.exists(frame_path) and not fade_locked:
                    next_chunk_id = latest.get("chunk_id", self.last_chunk_id)
                    next_frame_index = int(latest.get("frame_index", 0) or 0)
                    next_source_index = int(latest.get("source_index", next_frame_index) or next_frame_index)
                    is_feed_rollback = (
                        not bool(state.get("loop", False))
                        and next_chunk_id == self.last_chunk_id
                        and self.last_presented_source_index is not None
                        and next_source_index < int(self.last_presented_source_index)
                    )
                    if is_feed_rollback:
                        return
                    if not (
                        next_chunk_id == self.last_presented_chunk_id
                        and next_source_index == self.last_presented_source_index
                    ):
                        self.last_chunk_id = next_chunk_id
                        self.current_frame_index = next_frame_index
                        self.last_start_index = next_source_index - next_frame_index
                        self.current_frame_path = frame_path
                        if self.frame_dir and (
                            not self.frame_paths
                            or self.current_frame_index + QT_PREVIEW_AHEAD_PRELOAD >= len(self.frame_paths)
                        ):
                            self._refresh_frame_paths_from_dir()
                        if self.frame_paths:
                            self._start_frame_preload(
                                start_index=self.current_frame_index + 1,
                                count=min(
                                    max(len(self.frame_paths) - (self.current_frame_index + 1), 0),
                                    QT_PREVIEW_AHEAD_PRELOAD,
                                ),
                                wrap=bool(state.get("loop", False)),
                            )
                        self.render_current_frame()

            now = time.time()
            should_scan = (
                self.frame_dir
                and os.path.isdir(self.frame_dir)
                and len(self.frame_paths) < max(self.expected_frame_count, len(self.frame_paths))
                and now >= self.next_frame_dir_scan_at
            )
            if should_scan:
                self._refresh_frame_paths_from_dir()
                buffered_ratio = len(self.frame_paths) / max(self.expected_frame_count, 1)
                self.next_frame_dir_scan_at = now + (0.08 if buffered_ratio >= 0.9 else 0.04)

            if self.frame_paths and self.chunk_started_at and not fade_locked:
                frame_index = self._compute_runtime_frame_index(state=state)
                if frame_index is not None and frame_index != self.current_frame_index:
                    self.current_frame_index = frame_index
                    next_frame_path = self.frame_paths[frame_index]
                    if os.path.exists(next_frame_path):
                        self.current_frame_path = next_frame_path
                        if not state.get("loop", False):
                            self._start_frame_preload(
                                start_index=frame_index + 1,
                                count=min(
                                    max(len(self.frame_paths) - (frame_index + 1), 0),
                                    QT_PREVIEW_AHEAD_PRELOAD,
                                ),
                            )
                        else:
                            self._start_frame_preload(
                                start_index=frame_index + 1,
                                count=QT_PREVIEW_AHEAD_PRELOAD,
                                wrap=True,
                            )
                        self.render_current_frame()
        except Exception:
            pass
