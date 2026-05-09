from __future__ import annotations

from pathlib import Path

from addons.musetalk_avatar import state as musetalk_state


class QtMuseTalkUIService:
    _VRAM_LABELS = {
        "quality": "Quality",
        "balanced": "Balanced",
        "low_vram": "Low VRAM",
        "very_low_vram": "Very Low VRAM",
    }

    def __init__(self, window):
        self._window = window

    def _preview_widget(self):
        return getattr(self._window, "embedded_musetalk_preview", None)

    def _combo_text(self, name: str, default: str = "") -> str:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "currentText"):
            try:
                text = str(widget.currentText() or "").strip()
                if text:
                    return text
            except Exception:
                pass
        return str(default or "").strip()

    def _combo_data(self, name: str, default: str = "") -> str:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "currentData"):
            try:
                value = str(widget.currentData() or "").strip()
                if value:
                    return value
            except Exception:
                pass
        return str(default or "").strip()

    def _spin_value(self, name: str, default: int = 0) -> int:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "value"):
            try:
                return int(widget.value())
            except Exception:
                pass
        return int(default)

    def _checked(self, name: str, default: bool = False) -> bool:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "isChecked"):
            try:
                return bool(widget.isChecked())
            except Exception:
                pass
        return bool(default)

    def _vram_key_from_label(self, label: str) -> str:
        wanted = str(label or "").strip()
        for key, value in self._VRAM_LABELS.items():
            if value == wanted:
                return key
        return "quality"

    def export_avatar_runtime_settings(self):
        import engine

        runtime = getattr(engine, "RUNTIME_CONFIG", {}) or {}
        default_fade = int(getattr(engine, "QT_MUSETALK_LOOP_FADE_MS", 150) or 150)
        return {
            "musetalk_avatar_pack_id": self._combo_data("musetalk_avatar_pack_combo", runtime.get("musetalk_avatar_pack_id", "")),
            "musetalk_vram_mode": self._vram_key_from_label(self._combo_text("musetalk_vram_combo", self._VRAM_LABELS.get(str(runtime.get("musetalk_vram_mode", "quality") or "quality"), "Quality"))),
            "musetalk_loop_fade_ms": self._spin_value("musetalk_loop_fade_spin", int(runtime.get("musetalk_loop_fade_ms", default_fade) or default_fade)),
            "musetalk_use_frame_cache": self._checked("musetalk_use_frame_cache_checkbox", bool(runtime.get("musetalk_use_frame_cache", True))),
        }

    def _set_combo_text_quietly(self, name: str, text: str):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setCurrentText"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setCurrentText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_spin_value_quietly(self, name: str, value: int):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setValue"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setValue(int(value))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_checked_quietly(self, name: str, checked: bool):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setChecked"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setChecked(bool(checked))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _select_avatar_pack_quietly(self, pack_id: str):
        refresh = getattr(self._window, "refresh_musetalk_avatar_pack_list", None)
        if callable(refresh):
            refresh(selected_pack_id=pack_id)
        widget = getattr(self._window, "musetalk_avatar_pack_combo", None)
        if widget is None or not hasattr(widget, "findData"):
            return
        index = widget.findData(str(pack_id or ""))
        if index < 0:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setCurrentIndex(index)
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def import_avatar_runtime_settings(self, payload):
        import engine

        data = dict(payload or {})
        keys = {
            "musetalk_avatar_pack_id",
            "musetalk_vram_mode",
            "musetalk_loop_fade_ms",
            "musetalk_use_frame_cache",
        }
        if not any(key in data for key in keys):
            return None
        if "musetalk_avatar_pack_id" in data:
            pack_id = str(data.get("musetalk_avatar_pack_id") or "").strip()
            engine.update_runtime_config("musetalk_avatar_pack_id", pack_id)
            self._select_avatar_pack_quietly(pack_id)
        if "musetalk_vram_mode" in data:
            mode = str(data.get("musetalk_vram_mode") or "quality").strip().lower()
            if mode not in self._VRAM_LABELS:
                mode = "quality"
            engine.update_runtime_config("musetalk_vram_mode", mode)
            self._set_combo_text_quietly("musetalk_vram_combo", self._VRAM_LABELS.get(mode, "Quality"))
        if "musetalk_loop_fade_ms" in data:
            fade_ms = max(0, int(data.get("musetalk_loop_fade_ms") or 0))
            engine.update_runtime_config("musetalk_loop_fade_ms", fade_ms)
            self._set_spin_value_quietly("musetalk_loop_fade_spin", fade_ms)
        if "musetalk_use_frame_cache" in data:
            enabled = bool(data.get("musetalk_use_frame_cache"))
            engine.update_runtime_config("musetalk_use_frame_cache", enabled)
            self._set_checked_quietly("musetalk_use_frame_cache_checkbox", enabled)
        return None

    def publish_preview_frame(self, *, frame_path: str, avatar_id: str, mode_label: str) -> bool:
        import time

        publish_time = time.time()
        frame_identity = Path(frame_path).stem if frame_path else "frame"
        chunk_id = f"first_frame_test:{avatar_id}:{frame_identity}"
        musetalk_state.set_current_musetalk_frame_data({
            "frame_paths": [frame_path] if frame_path else [],
            "frame_dir": str(Path(frame_path).parent) if frame_path else "",
            "fps": 24,
            "sync_time": publish_time,
            "duration_seconds": 0.0,
            "expected_frame_count": 1,
            "trim_start_frames": 0,
            "chunk_id": chunk_id,
            "text": f"{mode_label} for {avatar_id}",
            "status": "ready",
            "loop": False,
            "start_index": 0,
            "source_indices": [0],
            "avatar_id": avatar_id,
            "published_at": publish_time,
        })
        musetalk_state.write_musetalk_preview_frame({
            "chunk_id": chunk_id,
            "status": "ready",
            "loop": False,
            "frame_path": frame_path,
            "frame_index": 0,
            "source_index": 0,
            "fps": 24,
            "emitted_at": publish_time,
        })
        preview_loaded = False
        preview_dock = getattr(self._window, "preview_dock", None)
        if preview_dock is not None:
            preview_dock.show()
            preview_dock.raise_()
        preview_widget = self._preview_widget()
        if preview_widget is not None:
            preview_loaded = bool(
                preview_widget.show_static_frame(
                    frame_path,
                    f"MuseTalk {mode_label.lower()}: {avatar_id}",
                )
            )
        return preview_loaded

    def configure_debug_mask_editor(self, *, base_frame_path: str, mask_frame_path: str, bbox, crop_box, modified_mask_path: str | None = None) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "configure_debug_mask_editor"):
            return False
        return bool(
            preview_widget.configure_debug_mask_editor(
                base_frame_path=base_frame_path,
                mask_frame_path=mask_frame_path,
                bbox=bbox,
                crop_box=crop_box,
                modified_mask_path=modified_mask_path,
            )
        )

    def set_debug_mask_brush(self, *, radius: int | None = None, feather: int | None = None) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "set_debug_mask_brush"):
            return False
        return bool(preview_widget.set_debug_mask_brush(radius=radius, feather=feather))

    def adjust_preview_zoom(self, factor_delta: float) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "adjust_zoom"):
            return False
        return bool(preview_widget.adjust_zoom(factor_delta))

    def reset_preview_zoom(self) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "reset_zoom"):
            return False
        return bool(preview_widget.reset_zoom())

    def clear_debug_mask_editor(self) -> None:
        preview_widget = self._preview_widget()
        if preview_widget is not None and hasattr(preview_widget, "clear_debug_mask_editor"):
            preview_widget.clear_debug_mask_editor()
