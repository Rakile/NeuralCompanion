"""Addon-owned screen capture service for native QML."""

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
        self._sync_runtime_setting("screen_source_capture_screen_index", int(self.capture_screen_index))
        sensory_service = context.capabilities.sensory_targets
        self._sensory_service = sensory_service
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
        context.logger.info("Screen source native service initialized.")

    def shutdown(self):
        sensory_service = getattr(self, "_sensory_service", None)
        if sensory_service is not None:
            try:
                sensory_service.unregister_provider(self.PROVIDER_ID)
            except Exception:
                pass
        self._sensory_service = None
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

    def capture_screen_catalog(self):
        """Return the finite monitor catalog used by native settings surfaces."""

        items = []
        virtual = self._virtual_desktop_region()
        if virtual:
            items.append(
                {
                    "value": SCREEN_INDEX_ALL,
                    "label": (
                        f"All screens: {virtual['width']} x {virtual['height']} px "
                        f"at {virtual['x']}, {virtual['y']}"
                    ),
                }
            )
        else:
            items.append({"value": SCREEN_INDEX_ALL, "label": "All screens"})
        for screen_info in self._available_screen_infos():
            items.append(
                {
                    "value": int(screen_info.get("index", 0) or 0),
                    "label": _screen_label(screen_info),
                }
            )
        return items

    def select_capture_region(self, *, square=False):
        selected = self._select_capture_region(square=bool(square))
        return {
            "accepted": bool(selected),
            "state": self.export_session_state(),
        }

    def _virtual_desktop_rect(self):
        try:
            from PySide6 import QtCore, QtGui

            screens = list(QtGui.QGuiApplication.screens() or [])
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
            from PySide6 import QtGui

            app_screens = list(QtGui.QGuiApplication.screens() or [])
            primary = QtGui.QGuiApplication.primaryScreen()
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
        self._notify_settings_changed()

    def _select_capture_region(self, *, square: bool = False) -> bool:
        try:
            from ui.qml_bridge.region_selector import select_region
        except Exception as exc:
            print(f"[ScreenSource] Region selection is unavailable: {exc}")
            return False
        bounds = list(select_region(square=bool(square)) or [])
        region = _normalize_region(
            {
                "x": bounds[0],
                "y": bounds[1],
                "width": bounds[2],
                "height": bounds[3],
            }
            if len(bounds) >= 4
            else {}
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
        context = getattr(self, "context", None)
        return getattr(getattr(context, "capabilities", None), "runtime_config", None)

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
        context = getattr(self, "context", None)
        session = getattr(getattr(context, "capabilities", None), "shell_session", None)
        notifier = getattr(session, "notify_settings_changed", None)
        if callable(notifier):
            try:
                notifier()
            except Exception:
                pass
