from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core.addons.base import BaseAddon

DEFAULT_MAX_SIDE = 5120
DEFAULT_MAX_WIDTH = 5120
DEFAULT_MAX_HEIGHT = 2880
MIN_MAX_SIDE = 256
MAX_MAX_SIDE = 5120
DEFAULT_JPEG_QUALITY = 85
MIN_JPEG_QUALITY = 40
MAX_JPEG_QUALITY = 95
SCREEN_INDEX_ALL = -1
DEFAULT_SCREEN_INDEX = SCREEN_INDEX_ALL
CAPTURE_MODE_FULL = "full"
CAPTURE_MODE_REGION = "region"
CAPTURE_MODE_SQUARE = "square"
CAPTURE_MODES = {CAPTURE_MODE_FULL, CAPTURE_MODE_REGION, CAPTURE_MODE_SQUARE}


def _load_metadata(root_dir: Path) -> dict:
    path = root_dir / "sensory_metadata.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _clamp_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = int(default)
    return max(int(minimum), min(int(maximum), number))


def _normalize_capture_mode(value) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in CAPTURE_MODES else CAPTURE_MODE_FULL


def _normalize_screen_index(value) -> int:
    try:
        number = int(value)
    except Exception:
        number = DEFAULT_SCREEN_INDEX
    if number < 0:
        return SCREEN_INDEX_ALL
    return max(0, min(32, number))


def _normalize_region(value) -> dict:
    if not isinstance(value, dict):
        return {}
    try:
        x = int(value.get("x"))
        y = int(value.get("y"))
        width = int(value.get("width"))
        height = int(value.get("height"))
    except Exception:
        return {}
    if width <= 0 or height <= 0:
        return {}
    x = max(-100000, min(100000, x))
    y = max(-100000, min(100000, y))
    width = max(1, min(100000, width))
    height = max(1, min(100000, height))
    return {
        "x": int(x),
        "y": int(y),
        "width": int(width),
        "height": int(height),
    }


def _region_label(region) -> str:
    payload = _normalize_region(region)
    if not payload:
        return "none selected"
    return f"{payload['width']} x {payload['height']} px at {payload['x']}, {payload['y']}"


def _screen_label(screen_info: dict) -> str:
    bounds = _normalize_region((screen_info or {}).get("bounds"))
    if not bounds:
        return "All screens"
    prefix = f"Screen {int((screen_info or {}).get('index', 0)) + 1}"
    name = str((screen_info or {}).get("name") or "").strip()
    primary = " primary" if bool((screen_info or {}).get("primary", False)) else ""
    suffix = f" - {name}" if name else ""
    return f"{prefix}{suffix}: {bounds['width']} x {bounds['height']} px at {bounds['x']}, {bounds['y']}{primary}"


class Addon(BaseAddon):
    PROVIDER_ID = "screen"
    CAPTURE_TAB_ID = "screen_source_capture_tab"

    def initialize(self, context):
        super().initialize(context)
        self._metadata_payload = _load_metadata(context.manifest.root_dir)
        fallback_max_side = _clamp_int(os.environ.get("NC_SCREEN_SOURCE_MAX_SIDE"), DEFAULT_MAX_SIDE, MIN_MAX_SIDE, MAX_MAX_SIDE)
        self.max_width = _clamp_int(os.environ.get("NC_SCREEN_SOURCE_MAX_WIDTH"), fallback_max_side, MIN_MAX_SIDE, MAX_MAX_SIDE)
        self.max_height = _clamp_int(os.environ.get("NC_SCREEN_SOURCE_MAX_HEIGHT"), fallback_max_side, MIN_MAX_SIDE, MAX_MAX_SIDE)
        self.max_side = max(int(self.max_width), int(self.max_height))
        self.jpeg_quality = _clamp_int(
            os.environ.get("NC_SCREEN_SOURCE_JPEG_QUALITY"),
            DEFAULT_JPEG_QUALITY,
            MIN_JPEG_QUALITY,
            MAX_JPEG_QUALITY,
        )
        self.capture_screen_index = _normalize_screen_index(os.environ.get("NC_SCREEN_SOURCE_CAPTURE_SCREEN_INDEX"))
        self.capture_mode = _normalize_capture_mode(os.environ.get("NC_SCREEN_SOURCE_CAPTURE_MODE"))
        self.capture_region = _normalize_region({})
        self.auto_attach_next_user_turn = False
        self.full_max_width = int(self.max_width)
        self.full_max_height = int(self.max_height)
        self._tab_refreshers = []
        self._sync_runtime_setting("screen_source_capture_screen_index", int(self.capture_screen_index))
        sensory_service = context.get_service("qt.sensory")
        if sensory_service is not None:
            sensory_service.register_provider(
                provider_id=self.PROVIDER_ID,
                label=str(self._metadata_payload.get("label") or "Screen"),
                instruction=str(self._metadata_payload.get("instruction") or ""),
                description=str(self._metadata_payload.get("description") or ""),
                order=int(self._metadata_payload.get("order", 100) or 100),
                capture_handler=self._capture_sensory_snapshot,
                metadata=dict(self._metadata_payload.get("metadata") or {}),
            )
        context.ui.register_manifest_designer_tab(
            id=self.CAPTURE_TAB_ID,
            binder=self._bind_capture_tab,
        )
        context.logger.info("Screen source addon initialized.")

    def shutdown(self):
        sensory_service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if sensory_service is not None:
            try:
                sensory_service.unregister_provider(self.PROVIDER_ID)
            except Exception:
                pass
        self._tab_refreshers = []
        return None

    def export_session_state(self):
        self.auto_attach_next_user_turn = self._auto_attach_from_runtime_config()
        return {
            "screen_source_max_width": int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
            "screen_source_max_height": int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
            "screen_source_max_side": max(
                int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
                int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
            ),
            "screen_source_jpeg_quality": int(getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY)),
            "screen_source_capture_screen_index": _normalize_screen_index(getattr(self, "capture_screen_index", DEFAULT_SCREEN_INDEX)),
            "screen_source_capture_mode": _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL)),
            "screen_source_capture_region": _normalize_region(getattr(self, "capture_region", {})),
            "screen_source_auto_attach_next_user_turn": bool(getattr(self, "auto_attach_next_user_turn", False)),
            "screen_source_full_max_width": int(getattr(self, "full_max_width", DEFAULT_MAX_WIDTH)),
            "screen_source_full_max_height": int(getattr(self, "full_max_height", DEFAULT_MAX_HEIGHT)),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = dict(session or {})
        fallback_max_side = _clamp_int(
            payload.get("screen_source_max_side", getattr(self, "max_side", DEFAULT_MAX_SIDE)),
            max(DEFAULT_MAX_WIDTH, DEFAULT_MAX_HEIGHT),
            MIN_MAX_SIDE,
            MAX_MAX_SIDE,
        )
        width_default = fallback_max_side if "screen_source_max_side" in payload else getattr(self, "max_width", fallback_max_side)
        height_default = fallback_max_side if "screen_source_max_side" in payload else getattr(self, "max_height", fallback_max_side)
        self.max_width = _clamp_int(
            payload.get("screen_source_max_width", width_default),
            fallback_max_side,
            MIN_MAX_SIDE,
            MAX_MAX_SIDE,
        )
        self.max_height = _clamp_int(
            payload.get("screen_source_max_height", height_default),
            fallback_max_side,
            MIN_MAX_SIDE,
            MAX_MAX_SIDE,
        )
        self.max_side = max(int(self.max_width), int(self.max_height))
        self.jpeg_quality = _clamp_int(
            payload.get("screen_source_jpeg_quality", getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY)),
            DEFAULT_JPEG_QUALITY,
            MIN_JPEG_QUALITY,
            MAX_JPEG_QUALITY,
        )
        self.capture_screen_index = _normalize_screen_index(
            payload.get("screen_source_capture_screen_index", getattr(self, "capture_screen_index", DEFAULT_SCREEN_INDEX))
        )
        self.full_max_width = _clamp_int(
            payload.get("screen_source_full_max_width", getattr(self, "full_max_width", self.max_width)),
            DEFAULT_MAX_WIDTH,
            MIN_MAX_SIDE,
            MAX_MAX_SIDE,
        )
        self.full_max_height = _clamp_int(
            payload.get("screen_source_full_max_height", getattr(self, "full_max_height", self.max_height)),
            DEFAULT_MAX_HEIGHT,
            MIN_MAX_SIDE,
            MAX_MAX_SIDE,
        )
        self.capture_region = _normalize_region(payload.get("screen_source_capture_region", getattr(self, "capture_region", {})))
        self.capture_mode = _normalize_capture_mode(payload.get("screen_source_capture_mode", getattr(self, "capture_mode", CAPTURE_MODE_FULL)))
        self.auto_attach_next_user_turn = bool(
            payload.get("screen_source_auto_attach_next_user_turn", getattr(self, "auto_attach_next_user_turn", False))
        )
        if self.capture_mode != CAPTURE_MODE_FULL and not self.capture_region:
            self.capture_mode = CAPTURE_MODE_FULL
        self._sync_runtime_setting("screen_source_capture_screen_index", int(self.capture_screen_index))
        self._notify_tab_refreshers()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def _virtual_desktop_rect(self):
        try:
            from PySide6 import QtCore, QtWidgets

            screens = list(QtWidgets.QApplication.screens() or [])
            if not screens:
                return None
            rect = QtCore.QRect(screens[0].geometry())
            for screen in screens[1:]:
                rect = rect.united(screen.geometry())
            return rect
        except Exception:
            return None

    def _available_screen_infos(self) -> list[dict]:
        try:
            from PySide6 import QtWidgets

            app_screens = list(QtWidgets.QApplication.screens() or [])
            primary = QtWidgets.QApplication.primaryScreen()
        except Exception:
            return []
        items = []
        for index, screen in enumerate(app_screens):
            try:
                geometry = screen.geometry()
                available = screen.availableGeometry()
                items.append(
                    {
                        "index": int(index),
                        "name": str(screen.name() or ""),
                        "primary": bool(primary is not None and screen is primary),
                        "bounds": {
                            "x": int(geometry.x()),
                            "y": int(geometry.y()),
                            "width": int(geometry.width()),
                            "height": int(geometry.height()),
                        },
                        "available_bounds": {
                            "x": int(available.x()),
                            "y": int(available.y()),
                            "width": int(available.width()),
                            "height": int(available.height()),
                        },
                    }
                )
            except Exception:
                continue
        return items

    def _virtual_desktop_region(self) -> dict:
        rect = self._virtual_desktop_rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return {}
        return {
            "x": int(rect.x()),
            "y": int(rect.y()),
            "width": int(rect.width()),
            "height": int(rect.height()),
        }

    def _selected_screen_info(self) -> dict:
        index = _normalize_screen_index(getattr(self, "capture_screen_index", DEFAULT_SCREEN_INDEX))
        if index == SCREEN_INDEX_ALL:
            return {}
        for item in self._available_screen_infos():
            if int(item.get("index", -2)) == int(index):
                return dict(item)
        return {}

    def _selected_screen_region(self) -> dict:
        info = self._selected_screen_info()
        return _normalize_region(info.get("bounds") if info else {})

    def _screen_selection_label(self) -> str:
        index = _normalize_screen_index(getattr(self, "capture_screen_index", DEFAULT_SCREEN_INDEX))
        if index == SCREEN_INDEX_ALL:
            virtual = self._virtual_desktop_region()
            if virtual:
                return f"All screens: {virtual['width']} x {virtual['height']} px at {virtual['x']}, {virtual['y']}"
            return "All screens"
        info = self._selected_screen_info()
        if info:
            return _screen_label(info)
        return f"Screen {index + 1} unavailable"

    def _effective_region(self):
        mode = _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL))
        if mode == CAPTURE_MODE_FULL:
            return self._selected_screen_region()
        return _normalize_region(getattr(self, "capture_region", {}))

    def _effective_capture_bounds(self) -> dict:
        region = self._effective_region()
        if region:
            return region
        return self._virtual_desktop_region()

    def _restore_full_capture_cap(self):
        self.max_width = _clamp_int(
            getattr(self, "full_max_width", DEFAULT_MAX_WIDTH),
            DEFAULT_MAX_WIDTH,
            MIN_MAX_SIDE,
            MAX_MAX_SIDE,
        )
        self.max_height = _clamp_int(
            getattr(self, "full_max_height", DEFAULT_MAX_HEIGHT),
            DEFAULT_MAX_HEIGHT,
            MIN_MAX_SIDE,
            MAX_MAX_SIDE,
        )
        self.max_side = max(int(self.max_width), int(self.max_height))

    def _remember_full_capture_cap(self):
        if _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL)) == CAPTURE_MODE_FULL:
            self.full_max_width = _clamp_int(
                getattr(self, "max_width", DEFAULT_MAX_WIDTH),
                DEFAULT_MAX_WIDTH,
                MIN_MAX_SIDE,
                MAX_MAX_SIDE,
            )
            self.full_max_height = _clamp_int(
                getattr(self, "max_height", DEFAULT_MAX_HEIGHT),
                DEFAULT_MAX_HEIGHT,
                MIN_MAX_SIDE,
                MAX_MAX_SIDE,
            )

    def _apply_region_capture_cap(self, region):
        payload = _normalize_region(region)
        if not payload:
            return
        self.max_width = _clamp_int(payload.get("width"), DEFAULT_MAX_WIDTH, MIN_MAX_SIDE, MAX_MAX_SIDE)
        self.max_height = _clamp_int(payload.get("height"), DEFAULT_MAX_HEIGHT, MIN_MAX_SIDE, MAX_MAX_SIDE)
        self.max_side = max(int(self.max_width), int(self.max_height))

    def _set_capture_mode(self, mode):
        next_mode = _normalize_capture_mode(mode)
        current_mode = _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL))
        if current_mode == CAPTURE_MODE_FULL and next_mode != CAPTURE_MODE_FULL:
            self._remember_full_capture_cap()
        self.capture_mode = next_mode
        if self.capture_mode == CAPTURE_MODE_FULL:
            self._restore_full_capture_cap()
        elif self.capture_region:
            self._apply_region_capture_cap(self.capture_region)
        else:
            self.capture_mode = CAPTURE_MODE_FULL
            self._restore_full_capture_cap()
        self._notify_tab_refreshers()
        self._notify_settings_changed()

    def _select_capture_region(self, *, square: bool = False) -> bool:
        try:
            from PySide6 import QtCore, QtGui, QtWidgets
        except Exception as exc:
            print(f"[ScreenSource] Region selection is unavailable: {exc}")
            return False
        virtual_rect = self._virtual_desktop_rect()
        if virtual_rect is None or virtual_rect.isEmpty():
            print("[ScreenSource] Region selection failed: no screen geometry is available.")
            return False

        class RegionSelectionOverlay(QtWidgets.QDialog):
            def __init__(self, geometry, *, square_mode=False):
                super().__init__(None)
                self.square_mode = bool(square_mode)
                self.origin = None
                self.current = None
                self.selected_rect = QtCore.QRect()
                self.setWindowTitle("Select screen capture region")
                self.setWindowFlags(
                    QtCore.Qt.FramelessWindowHint
                    | QtCore.Qt.WindowStaysOnTopHint
                    | QtCore.Qt.Tool
                )
                self.setWindowModality(QtCore.Qt.ApplicationModal)
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                self.setMouseTracking(True)
                self.setCursor(QtCore.Qt.CrossCursor)
                self.setGeometry(geometry)

            def _selection_rect(self):
                if self.origin is None or self.current is None:
                    return QtCore.QRect()
                end = QtCore.QPoint(self.current)
                if self.square_mode:
                    dx = end.x() - self.origin.x()
                    dy = end.y() - self.origin.y()
                    side = max(1, min(abs(dx), abs(dy)))
                    end = QtCore.QPoint(
                        self.origin.x() + (side if dx >= 0 else -side),
                        self.origin.y() + (side if dy >= 0 else -side),
                    )
                return QtCore.QRect(self.origin, end).normalized()

            def paintEvent(self, _event):
                painter = QtGui.QPainter(self)
                painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 96))
                selection = self._selection_rect()
                if not selection.isNull():
                    painter.fillRect(selection, QtGui.QColor(80, 170, 255, 55))
                    pen = QtGui.QPen(QtGui.QColor(120, 210, 255), 2)
                    painter.setPen(pen)
                    painter.drawRect(selection.adjusted(0, 0, -1, -1))
                    painter.setPen(QtGui.QColor(230, 245, 255))
                    painter.drawText(
                        selection.adjusted(8, 8, -8, -8),
                        QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                        f"{selection.width()} x {selection.height()}",
                    )
                else:
                    painter.setPen(QtGui.QColor(230, 245, 255))
                    painter.drawText(
                        self.rect(),
                        QtCore.Qt.AlignCenter,
                        "Drag to select the screen area. Esc cancels.",
                    )

            def mousePressEvent(self, event):
                if event.button() != QtCore.Qt.LeftButton:
                    return
                self.origin = event.position().toPoint()
                self.current = QtCore.QPoint(self.origin)
                self.update()

            def mouseMoveEvent(self, event):
                if self.origin is None:
                    return
                self.current = event.position().toPoint()
                self.update()

            def mouseReleaseEvent(self, event):
                if event.button() != QtCore.Qt.LeftButton or self.origin is None:
                    return
                self.current = event.position().toPoint()
                selected = self._selection_rect()
                if selected.width() < 8 or selected.height() < 8:
                    self.reject()
                    return
                self.selected_rect = selected.translated(self.geometry().topLeft())
                self.accept()

            def keyPressEvent(self, event):
                if event.key() == QtCore.Qt.Key_Escape:
                    self.reject()
                    return
                super().keyPressEvent(event)

        overlay = RegionSelectionOverlay(virtual_rect, square_mode=square)
        if overlay.exec() != QtWidgets.QDialog.Accepted:
            return False
        rect = overlay.selected_rect
        region = _normalize_region(
            {
                "x": rect.x(),
                "y": rect.y(),
                "width": rect.width(),
                "height": rect.height(),
            }
        )
        if not region:
            return False
        if _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL)) == CAPTURE_MODE_FULL:
            self._remember_full_capture_cap()
        self.capture_region = region
        self.capture_mode = CAPTURE_MODE_SQUARE if square else CAPTURE_MODE_REGION
        self._apply_region_capture_cap(region)
        self._notify_tab_refreshers()
        self._notify_settings_changed()
        return True

    def _capture_screen(self, output_path: Path):
        try:
            from PIL import ImageGrab, Image
            image = ImageGrab.grab(all_screens=True)
        except Exception as exc:
            raise RuntimeError(f"Screen capture failed: {exc}") from exc
        image = image.convert("RGB")
        desktop_dimensions = [int(image.width), int(image.height)]
        region = self._effective_region()
        capture_bounds = self._effective_capture_bounds()
        crop = []
        if region:
            virtual_rect = self._virtual_desktop_rect()
            if virtual_rect is not None and virtual_rect.width() > 0 and virtual_rect.height() > 0:
                x_scale = image.width / max(1, int(virtual_rect.width()))
                y_scale = image.height / max(1, int(virtual_rect.height()))
                left = int(round((int(region["x"]) - int(virtual_rect.x())) * x_scale))
                top = int(round((int(region["y"]) - int(virtual_rect.y())) * y_scale))
                right = int(round((int(region["x"]) + int(region["width"]) - int(virtual_rect.x())) * x_scale))
                bottom = int(round((int(region["y"]) + int(region["height"]) - int(virtual_rect.y())) * y_scale))
                left = max(0, min(image.width - 1, left))
                top = max(0, min(image.height - 1, top))
                right = max(left + 1, min(image.width, right))
                bottom = max(top + 1, min(image.height, bottom))
                crop = [int(left), int(top), int(right), int(bottom)]
                image = image.crop(tuple(crop))
        max_width = _clamp_int(getattr(self, "max_width", DEFAULT_MAX_WIDTH), DEFAULT_MAX_WIDTH, MIN_MAX_SIDE, MAX_MAX_SIDE)
        max_height = _clamp_int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT), DEFAULT_MAX_HEIGHT, MIN_MAX_SIDE, MAX_MAX_SIDE)
        jpeg_quality = _clamp_int(
            getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY),
            DEFAULT_JPEG_QUALITY,
            MIN_JPEG_QUALITY,
            MAX_JPEG_QUALITY,
        )
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        dimensions = image.size
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="JPEG", quality=jpeg_quality, optimize=True)
        metadata = {
            "desktop_width": int(desktop_dimensions[0]),
            "desktop_height": int(desktop_dimensions[1]),
            "capture_screen_index": _normalize_screen_index(getattr(self, "capture_screen_index", DEFAULT_SCREEN_INDEX)),
            "capture_screen_label": self._screen_selection_label(),
            "screen_bounds": _normalize_region(capture_bounds),
            "crop": list(crop),
        }
        return output_path, dimensions, metadata

    def _capture_sensory_snapshot(self, context=None):
        timestamp = int(time.time() * 1000)
        output_root = Path(str((context or {}).get("output_dir") or (self.context.app_root / "runtime" / "sensory_feedback")))
        output_path, dimensions, capture_metadata = self._capture_screen(output_root / f"screen_{timestamp}.jpg")
        return {
            "captured_at": time.time(),
            "image_path": str(output_path),
            "source": self.PROVIDER_ID,
            "content_text": "Hidden sensory feedback only, not a user request. Source: screen. Use as ambient context only if relevant.",
            "metadata": {
                "width": int(dimensions[0]),
                "height": int(dimensions[1]),
                "desktop_width": int(capture_metadata.get("desktop_width", 0) or 0),
                "desktop_height": int(capture_metadata.get("desktop_height", 0) or 0),
                "capture_mode": _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL)),
                "capture_screen_index": int(capture_metadata.get("capture_screen_index", DEFAULT_SCREEN_INDEX)),
                "capture_screen_label": str(capture_metadata.get("capture_screen_label") or ""),
                "screen_bounds": _normalize_region(capture_metadata.get("screen_bounds", {})),
                "crop": list(capture_metadata.get("crop") or []),
                "capture_region": _normalize_region(getattr(self, "capture_region", {})),
                "max_width": int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
                "max_height": int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
                "max_side": max(
                    int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
                    int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
                ),
                "jpeg_quality": int(getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY)),
            },
        }

    def _runtime_config_service(self):
        return self.context.get_service("qt.runtime_config") if getattr(self, "context", None) is not None else None

    def _sync_runtime_setting(self, key, value):
        service = self._runtime_config_service()
        if service is None:
            return
        try:
            service.update(str(key), value)
        except Exception:
            pass

    def _auto_attach_from_runtime_config(self):
        service = self._runtime_config_service()
        if service is None:
            return bool(getattr(self, "auto_attach_next_user_turn", False))
        try:
            return bool(service.get("screen_source_auto_attach_next_user_turn", bool(getattr(self, "auto_attach_next_user_turn", False))))
        except Exception:
            return bool(getattr(self, "auto_attach_next_user_turn", False))

    def _bind_capture_tab(self, widget, context):
        QtWidgets = self._qt_widgets()
        mount = widget.findChild(QtWidgets.QWidget, "addon_designer_mount") if widget is not None else None
        runtime_widget = self._build_capture_settings_widget(context)
        if mount is not None:
            layout = mount.layout()
            if layout is None:
                layout = QtWidgets.QVBoxLayout(mount)
                layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(runtime_widget)
            return widget
        return runtime_widget

    def _build_capture_settings_widget(self, context):
        QtWidgets = self._qt_widgets()

        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        mode_combo = QtWidgets.QComboBox()
        mode_combo.addItem("Whole screen", CAPTURE_MODE_FULL)
        mode_combo.addItem("Selected region", CAPTURE_MODE_REGION)
        mode_combo.addItem("Selected square", CAPTURE_MODE_SQUARE)
        mode_combo.setToolTip("Choose whether screen snapshots capture the whole desktop or a selected area.")
        form.addRow("Capture area", mode_combo)

        screen_combo = QtWidgets.QComboBox()
        screen_combo.setToolTip(
            "Choose which monitor is captured when Capture area is Whole screen. "
            "Selected regions and squares keep their own desktop coordinates."
        )
        form.addRow("Screen", screen_combo)

        max_width_spin = QtWidgets.QSpinBox()
        max_width_spin.setRange(MIN_MAX_SIDE, MAX_MAX_SIDE)
        max_width_spin.setSingleStep(128)
        max_width_spin.setSuffix(" px")
        max_width_spin.setValue(_clamp_int(getattr(self, "max_width", DEFAULT_MAX_WIDTH), DEFAULT_MAX_WIDTH, MIN_MAX_SIDE, MAX_MAX_SIDE))
        max_width_spin.setToolTip("Maximum width for hidden screen snapshots.")
        form.addRow("Max width", max_width_spin)

        max_height_spin = QtWidgets.QSpinBox()
        max_height_spin.setRange(MIN_MAX_SIDE, MAX_MAX_SIDE)
        max_height_spin.setSingleStep(128)
        max_height_spin.setSuffix(" px")
        max_height_spin.setValue(_clamp_int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT), DEFAULT_MAX_HEIGHT, MIN_MAX_SIDE, MAX_MAX_SIDE))
        max_height_spin.setToolTip("Maximum height for hidden screen snapshots.")
        form.addRow("Max height", max_height_spin)

        quality_spin = QtWidgets.QSpinBox()
        quality_spin.setRange(MIN_JPEG_QUALITY, MAX_JPEG_QUALITY)
        quality_spin.setSingleStep(1)
        quality_spin.setSuffix("%")
        quality_spin.setValue(
            _clamp_int(getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY), DEFAULT_JPEG_QUALITY, MIN_JPEG_QUALITY, MAX_JPEG_QUALITY)
        )
        quality_spin.setToolTip("JPEG quality for the hidden screen snapshot file.")
        form.addRow("JPEG quality", quality_spin)

        layout.addLayout(form)

        auto_attach_checkbox = QtWidgets.QCheckBox("Attach screen capture to every next user turn")
        auto_attach_checkbox.setToolTip(
            "When enabled, each user message captures the current screen with these Capture settings and sends it as that turn's image attachment."
        )
        auto_attach_checkbox.setChecked(bool(getattr(self, "auto_attach_next_user_turn", False)))
        layout.addWidget(auto_attach_checkbox)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)

        select_region_button = QtWidgets.QPushButton("Select region")
        select_region_button.setToolTip("Drag a rectangle on the screen. Future screen snapshots will use only that region.")
        button_row.addWidget(select_region_button)

        select_square_button = QtWidgets.QPushButton("Select square")
        select_square_button.setToolTip("Drag a square on the screen. Future screen snapshots will use only that square.")
        button_row.addWidget(select_square_button)

        use_full_button = QtWidgets.QPushButton("Use whole screen")
        use_full_button.setToolTip("Return to full-screen capture and restore the previous full-screen width and height cap.")
        button_row.addWidget(use_full_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        hint = QtWidgets.QLabel(
            "Bigger snapshots preserve small UI text and details, but they increase vision-token use, latency, and API cost. "
            "The image keeps its original aspect ratio inside the width and height limits. Selected areas are cropped before resizing."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(hint)

        current_label = QtWidgets.QLabel()
        current_label.setWordWrap(True)
        current_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        layout.addWidget(current_label)

        def refresh_screen_combo():
            selected = _normalize_screen_index(getattr(self, "capture_screen_index", DEFAULT_SCREEN_INDEX))
            screen_combo.blockSignals(True)
            screen_combo.clear()
            virtual = self._virtual_desktop_region()
            if virtual:
                screen_combo.addItem(
                    f"All screens: {virtual['width']} x {virtual['height']} px at {virtual['x']}, {virtual['y']}",
                    SCREEN_INDEX_ALL,
                )
            else:
                screen_combo.addItem("All screens", SCREEN_INDEX_ALL)
            for screen_info in self._available_screen_infos():
                try:
                    screen_combo.addItem(_screen_label(screen_info), int(screen_info.get("index", 0)))
                except Exception:
                    continue
            selected_index = screen_combo.findData(selected)
            if selected_index < 0 and selected != SCREEN_INDEX_ALL:
                screen_combo.addItem(f"Screen {selected + 1} unavailable", selected)
                selected_index = screen_combo.findData(selected)
            screen_combo.setCurrentIndex(max(0, selected_index))
            screen_combo.setEnabled(_normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL)) == CAPTURE_MODE_FULL)
            screen_combo.blockSignals(False)

        def refresh():
            self.auto_attach_next_user_turn = self._auto_attach_from_runtime_config()
            current_mode = _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL))
            mode_index = mode_combo.findData(current_mode)
            if mode_index < 0:
                mode_index = 0
            if mode_combo.currentIndex() != mode_index:
                mode_combo.blockSignals(True)
                mode_combo.setCurrentIndex(mode_index)
                mode_combo.blockSignals(False)
            mode_label = {
                CAPTURE_MODE_FULL: "whole screen",
                CAPTURE_MODE_REGION: "selected region",
                CAPTURE_MODE_SQUARE: "selected square",
            }.get(current_mode, "whole screen")
            refresh_screen_combo()
            current_label.setText(
                f"Current cap: {int(getattr(self, 'max_width', DEFAULT_MAX_WIDTH))} x "
                f"{int(getattr(self, 'max_height', DEFAULT_MAX_HEIGHT))} px, "
                f"JPEG {int(getattr(self, 'jpeg_quality', DEFAULT_JPEG_QUALITY))}%. "
                f"Capture area: {mode_label}; screen: {self._screen_selection_label()}; "
                f"region: {_region_label(getattr(self, 'capture_region', {}))}."
            )
            if max_width_spin.value() != int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)):
                max_width_spin.blockSignals(True)
                max_width_spin.setValue(int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)))
                max_width_spin.blockSignals(False)
            if max_height_spin.value() != int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)):
                max_height_spin.blockSignals(True)
                max_height_spin.setValue(int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)))
                max_height_spin.blockSignals(False)
            if quality_spin.value() != int(getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY)):
                quality_spin.blockSignals(True)
                quality_spin.setValue(int(getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY)))
                quality_spin.blockSignals(False)
            if auto_attach_checkbox.isChecked() != bool(getattr(self, "auto_attach_next_user_turn", False)):
                auto_attach_checkbox.blockSignals(True)
                auto_attach_checkbox.setChecked(bool(getattr(self, "auto_attach_next_user_turn", False)))
                auto_attach_checkbox.blockSignals(False)

        def set_capture_mode_from_combo(_index):
            self._set_capture_mode(mode_combo.currentData())

        def set_capture_screen_from_combo(_index):
            self.capture_screen_index = _normalize_screen_index(screen_combo.currentData())
            self._sync_runtime_setting("screen_source_capture_screen_index", int(self.capture_screen_index))
            refresh()
            self._notify_settings_changed()

        def set_max_width(value):
            self.max_width = _clamp_int(value, DEFAULT_MAX_WIDTH, MIN_MAX_SIDE, MAX_MAX_SIDE)
            self.max_side = max(int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)), int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)))
            if _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL)) == CAPTURE_MODE_FULL:
                self.full_max_width = int(self.max_width)
            refresh()
            self._notify_settings_changed()

        def set_max_height(value):
            self.max_height = _clamp_int(value, DEFAULT_MAX_HEIGHT, MIN_MAX_SIDE, MAX_MAX_SIDE)
            self.max_side = max(int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)), int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)))
            if _normalize_capture_mode(getattr(self, "capture_mode", CAPTURE_MODE_FULL)) == CAPTURE_MODE_FULL:
                self.full_max_height = int(self.max_height)
            refresh()
            self._notify_settings_changed()

        def set_quality(value):
            self.jpeg_quality = _clamp_int(value, DEFAULT_JPEG_QUALITY, MIN_JPEG_QUALITY, MAX_JPEG_QUALITY)
            refresh()
            self._notify_settings_changed()

        def set_auto_attach(checked):
            self.auto_attach_next_user_turn = bool(checked)
            service = self._runtime_config_service()
            if service is not None:
                try:
                    service.update("screen_source_auto_attach_next_user_turn", bool(checked))
                except Exception:
                    pass
            refresh()
            self._notify_settings_changed()

        mode_combo.currentIndexChanged.connect(set_capture_mode_from_combo)
        screen_combo.currentIndexChanged.connect(set_capture_screen_from_combo)
        max_width_spin.valueChanged.connect(set_max_width)
        max_height_spin.valueChanged.connect(set_max_height)
        quality_spin.valueChanged.connect(set_quality)
        auto_attach_checkbox.toggled.connect(set_auto_attach)
        select_region_button.clicked.connect(lambda: self._select_capture_region(square=False))
        select_square_button.clicked.connect(lambda: self._select_capture_region(square=True))
        use_full_button.clicked.connect(lambda: self._set_capture_mode(CAPTURE_MODE_FULL))
        self._register_tab_refresher(refresh)
        root.destroyed.connect(lambda *_args, callback=refresh: self._unregister_tab_refresher(callback))
        refresh()
        layout.addStretch(1)
        return root

    def _qt_widgets(self):
        from PySide6 import QtWidgets

        return QtWidgets

    def _register_tab_refresher(self, callback):
        if callable(callback):
            self._tab_refreshers.append(callback)

    def _unregister_tab_refresher(self, callback):
        self._tab_refreshers = [item for item in list(getattr(self, "_tab_refreshers", []) or []) if item is not callback]

    def _notify_tab_refreshers(self):
        keep = []
        for callback in list(getattr(self, "_tab_refreshers", []) or []):
            try:
                callback()
                keep.append(callback)
            except RuntimeError:
                pass
            except Exception:
                pass
        self._tab_refreshers = keep

    def _notify_settings_changed(self):
        shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
        notifier = getattr(shell, "notify_settings_changed", None)
        if callable(notifier):
            try:
                notifier()
            except Exception:
                pass
