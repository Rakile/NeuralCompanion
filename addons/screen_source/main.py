from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core.addons.base import BaseAddon

DEFAULT_MAX_SIDE = 5120
DEFAULT_MAX_WIDTH = 5120
DEFAULT_MAX_HEIGHT = 2880
MIN_MAX_SIDE = 640
MAX_MAX_SIDE = 5120
DEFAULT_JPEG_QUALITY = 85
MIN_JPEG_QUALITY = 40
MAX_JPEG_QUALITY = 95


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
        self._tab_refreshers = []
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
        return {
            "screen_source_max_width": int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
            "screen_source_max_height": int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
            "screen_source_max_side": max(
                int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
                int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
            ),
            "screen_source_jpeg_quality": int(getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY)),
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
        self._notify_tab_refreshers()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def _capture_screen(self, output_path: Path):
        try:
            from PIL import ImageGrab, Image
            image = ImageGrab.grab(all_screens=True)
        except Exception as exc:
            raise RuntimeError(f"Screen capture failed: {exc}") from exc
        image = image.convert("RGB")
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
        return output_path, dimensions

    def _capture_sensory_snapshot(self, context=None):
        timestamp = int(time.time() * 1000)
        output_root = Path(str((context or {}).get("output_dir") or (self.context.app_root / "runtime" / "sensory_feedback")))
        output_path, dimensions = self._capture_screen(output_root / f"screen_{timestamp}.jpg")
        return {
            "captured_at": time.time(),
            "image_path": str(output_path),
            "source": self.PROVIDER_ID,
            "content_text": "Hidden sensory feedback only, not a user request. Source: screen. Use as ambient context only if relevant.",
            "metadata": {
                "width": int(dimensions[0]),
                "height": int(dimensions[1]),
                "max_width": int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
                "max_height": int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
                "max_side": max(
                    int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)),
                    int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)),
                ),
                "jpeg_quality": int(getattr(self, "jpeg_quality", DEFAULT_JPEG_QUALITY)),
            },
        }

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

        hint = QtWidgets.QLabel(
            "Bigger snapshots preserve small UI text and details, but they increase vision-token use, latency, and API cost. "
            "The image keeps its original aspect ratio inside the width and height limits."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(hint)

        current_label = QtWidgets.QLabel()
        current_label.setWordWrap(True)
        current_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        layout.addWidget(current_label)

        def refresh():
            current_label.setText(
                f"Current cap: {int(getattr(self, 'max_width', DEFAULT_MAX_WIDTH))} x "
                f"{int(getattr(self, 'max_height', DEFAULT_MAX_HEIGHT))} px, "
                f"JPEG {int(getattr(self, 'jpeg_quality', DEFAULT_JPEG_QUALITY))}%."
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

        def set_max_width(value):
            self.max_width = _clamp_int(value, DEFAULT_MAX_WIDTH, MIN_MAX_SIDE, MAX_MAX_SIDE)
            self.max_side = max(int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)), int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)))
            refresh()
            self._notify_settings_changed()

        def set_max_height(value):
            self.max_height = _clamp_int(value, DEFAULT_MAX_HEIGHT, MIN_MAX_SIDE, MAX_MAX_SIDE)
            self.max_side = max(int(getattr(self, "max_width", DEFAULT_MAX_WIDTH)), int(getattr(self, "max_height", DEFAULT_MAX_HEIGHT)))
            refresh()
            self._notify_settings_changed()

        def set_quality(value):
            self.jpeg_quality = _clamp_int(value, DEFAULT_JPEG_QUALITY, MIN_JPEG_QUALITY, MAX_JPEG_QUALITY)
            refresh()
            self._notify_settings_changed()

        max_width_spin.valueChanged.connect(set_max_width)
        max_height_spin.valueChanged.connect(set_max_height)
        quality_spin.valueChanged.connect(set_quality)
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
