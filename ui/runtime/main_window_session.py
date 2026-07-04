"""Session persistence helpers for the runtime-backed main window."""

import base64
import json
import os
from collections import OrderedDict
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from addons.visual_reply.session_schema import group_visual_reply_session, with_flat_visual_reply_settings
from core import long_term_memory
from core.sensory_source_selection import normalize_companion_orb_target_source_selection
from core.chat_runtime_session_schema import group_chat_runtime_session, with_flat_chat_runtime_settings
from core.chunking_session_schema import group_chunking_session, with_flat_chunking_settings
from core.dry_run_session_schema import group_dry_run_session, with_flat_dry_run_settings
from core.musetalk_session_schema import group_musetalk_session, with_flat_musetalk_settings
from core.persona_session_schema import group_persona_session, with_flat_persona_settings
from core.runtime_controls_session_schema import group_runtime_controls_session, with_flat_runtime_controls_settings
from core.sensory_session_schema import group_sensory_session, with_flat_sensory_settings
from core.stt_session_schema import group_stt_runtime_session, with_flat_stt_runtime_settings
from core.tts_session_schema import group_tts_runtime_session, with_flat_tts_runtime_settings
from core.ui_session_schema import group_ui_session, with_flat_ui_settings
from core.vam_session_schema import group_vam_session, with_flat_vam_settings
from ui.runtime import engine_access as engine
from ui.runtime.engine_access import RUNTIME_CONFIG, update_runtime_config
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES, UI_SHELL_MUSE_VRAM_MODE_LABELS

SESSION_PATH = Path("qt_session.json")
QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_CHUNKING_VALUES = UI_SHELL_DEFAULT_CHUNKING_VALUES
DEFAULT_MAX_RESPONSE_TOKENS = 600
MUSE_VRAM_MODE_LABELS = OrderedDict(UI_SHELL_MUSE_VRAM_MODE_LABELS)


class MainWindowSessionMixin:
    _PERSISTED_TAB_ORDER_ALIASES = {
        "addons": "left_tabs",
        "host": "host_settings_tabs",
    }
    _PERSISTED_TAB_ORDER_OBJECTS = {
        value: key for key, value in _PERSISTED_TAB_ORDER_ALIASES.items()
    }
    _PERSISTED_HIDDEN_TAB_ALIASES = {
        "addons": "left_tabs",
    }
    _PERSISTED_HIDDEN_TAB_OBJECTS = {
        value: key for key, value in _PERSISTED_HIDDEN_TAB_ALIASES.items()
    }

    def _session_ui_layout(self, session, *, create=False):
        if not isinstance(session, dict):
            return {}
        ui = session.get("ui")
        if not isinstance(ui, dict):
            if not create:
                return {}
            ui = {}
            session["ui"] = ui
        layout = ui.get("layout")
        if not isinstance(layout, dict):
            if not create:
                return {}
            layout = {}
            ui["layout"] = layout
        return layout

    def _tab_order_widget(self, object_name):
        return getattr(self, str(object_name or ""), None)

    def _persisted_tab_identity(self, tabs, index):
        label = ""
        try:
            label = str(tabs.tabBar().tabData(int(index)) or "").strip()
        except Exception:
            label = ""
        if not label:
            try:
                label = str(tabs.tabToolTip(int(index)) or "").strip()
            except Exception:
                label = ""
        if not label:
            try:
                label = str(tabs.tabText(int(index)) or "").strip()
            except Exception:
                label = ""
        try:
            widget = tabs.widget(int(index))
        except Exception:
            widget = None
        if widget is not None:
            try:
                addon_id = str(widget.property("addon_id") or "").strip()
                addon_tab_id = str(widget.property("addon_tab_id") or "").strip()
            except Exception:
                addon_id = ""
                addon_tab_id = ""
            if addon_id and addon_tab_id:
                return f"addon:{addon_id}:{addon_tab_id}"
            try:
                object_name = str(tabs.objectName() or "").strip()
            except Exception:
                object_name = ""
            if object_name == "host_settings_tabs" and label:
                return f"label:{label}"
            try:
                widget_name = str(widget.objectName() or "").strip()
            except Exception:
                widget_name = ""
            if widget_name:
                return f"widget:{widget_name}"
        if label:
            return f"label:{label}"
        return ""

    def _current_persisted_tab_order(self, object_name):
        tabs = self._tab_order_widget(object_name)
        if tabs is None or not hasattr(tabs, "count"):
            return []
        order = []
        seen = set()
        try:
            count = int(tabs.count())
        except Exception:
            return []
        for index in range(count):
            identity = self._persisted_tab_identity(tabs, index)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            order.append(identity)
        return order

    def _tab_visible_for_persistence(self, tabs, index):
        try:
            if hasattr(tabs, "isTabVisible"):
                return bool(tabs.isTabVisible(int(index)))
        except Exception:
            pass
        return True

    def _set_tab_visible_for_persistence(self, tabs, index, visible):
        try:
            if hasattr(tabs, "setTabVisible"):
                tabs.setTabVisible(int(index), bool(visible))
                return True
        except Exception:
            pass
        return False

    def _current_persisted_hidden_tabs(self, object_name):
        tabs = self._tab_order_widget(object_name)
        if tabs is None or not hasattr(tabs, "count"):
            return []
        hidden = []
        seen = set()
        try:
            count = int(tabs.count())
        except Exception:
            return []
        for index in range(count):
            if self._tab_visible_for_persistence(tabs, index):
                continue
            identity = self._persisted_tab_identity(tabs, index)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            hidden.append(identity)
        return hidden

    def _save_persisted_tab_orders(self, session):
        tab_order = {}
        for alias, object_name in self._PERSISTED_TAB_ORDER_ALIASES.items():
            order = self._current_persisted_tab_order(object_name)
            if order:
                tab_order[alias] = order
        layout = self._session_ui_layout(session, create=bool(tab_order))
        if tab_order:
            layout["tab_order"] = tab_order
        elif isinstance(layout, dict):
            layout.pop("tab_order", None)

    def _save_persisted_hidden_tabs(self, session):
        hidden_tabs = {}
        for alias, object_name in self._PERSISTED_HIDDEN_TAB_ALIASES.items():
            hidden = self._current_persisted_hidden_tabs(object_name)
            if hidden:
                hidden_tabs[alias] = hidden
        layout = self._session_ui_layout(session, create=bool(hidden_tabs))
        if hidden_tabs:
            layout["hidden_tabs"] = hidden_tabs
        elif isinstance(layout, dict):
            layout.pop("hidden_tabs", None)

    def _restore_persisted_tab_orders(self, session):
        layout = self._session_ui_layout(session)
        raw_orders = layout.get("tab_order") if isinstance(layout, dict) else None
        if not isinstance(raw_orders, dict):
            self._persisted_tab_orders = {}
            return
        restored = {}
        for alias, object_name in self._PERSISTED_TAB_ORDER_ALIASES.items():
            raw_order = raw_orders.get(alias)
            if not isinstance(raw_order, list):
                continue
            restored[object_name] = [
                str(item or "").strip()
                for item in raw_order
                if str(item or "").strip()
            ]
        self._persisted_tab_orders = restored

    def _restore_persisted_hidden_tabs(self, session):
        layout = self._session_ui_layout(session)
        raw_hidden_tabs = layout.get("hidden_tabs") if isinstance(layout, dict) else None
        if not isinstance(raw_hidden_tabs, dict):
            self._persisted_hidden_tabs = {}
            return
        restored = {}
        for alias, object_name in self._PERSISTED_HIDDEN_TAB_ALIASES.items():
            raw_hidden = raw_hidden_tabs.get(alias)
            if not isinstance(raw_hidden, list):
                continue
            restored[object_name] = {
                str(item or "").strip()
                for item in raw_hidden
                if str(item or "").strip()
            }
        self._persisted_hidden_tabs = restored

    def _apply_persisted_tab_order(self, object_name):
        tabs = self._tab_order_widget(object_name)
        if tabs is None or not hasattr(tabs, "tabBar") or not hasattr(tabs, "count"):
            return
        desired = list(getattr(self, "_persisted_tab_orders", {}).get(str(object_name or ""), []) or [])
        if not desired:
            return
        tab_bar = tabs.tabBar()
        previous_suspend = bool(getattr(self, "_suspend_tab_order_save", False))
        self._suspend_tab_order_save = True
        try:
            insert_at = 0
            for identity in desired:
                current_index = -1
                try:
                    count = int(tabs.count())
                except Exception:
                    count = 0
                for index in range(count):
                    if self._persisted_tab_identity(tabs, index) == identity:
                        current_index = index
                        break
                if current_index < 0:
                    continue
                if current_index != insert_at and tab_bar is not None:
                    try:
                        tab_bar.moveTab(current_index, insert_at)
                    except Exception:
                        continue
                insert_at += 1
        finally:
            self._suspend_tab_order_save = previous_suspend

    def _apply_persisted_tab_orders(self):
        for object_name in self._PERSISTED_TAB_ORDER_OBJECTS:
            self._apply_persisted_tab_order(object_name)

    def _apply_persisted_hidden_tabs_for(self, object_name):
        tabs = self._tab_order_widget(object_name)
        if tabs is None or not hasattr(tabs, "count"):
            return
        desired = set(getattr(self, "_persisted_hidden_tabs", {}).get(str(object_name or ""), set()) or set())
        if not desired:
            return
        visible_count = 0
        first_hidden_index = -1
        try:
            count = int(tabs.count())
        except Exception:
            count = 0
        for index in range(count):
            identity = self._persisted_tab_identity(tabs, index)
            should_hide = bool(identity and identity in desired)
            if should_hide and self._set_tab_visible_for_persistence(tabs, index, False):
                if first_hidden_index < 0:
                    first_hidden_index = index
            if self._tab_visible_for_persistence(tabs, index):
                visible_count += 1
        if count > 0 and visible_count <= 0 and first_hidden_index >= 0:
            self._set_tab_visible_for_persistence(tabs, first_hidden_index, True)

    def _apply_persisted_hidden_tabs(self):
        for object_name in self._PERSISTED_HIDDEN_TAB_OBJECTS:
            self._apply_persisted_hidden_tabs_for(object_name)

    def _install_persisted_tab_order(self, object_name, tabs):
        if tabs is None or not hasattr(tabs, "tabBar"):
            return
        tab_bar = tabs.tabBar()
        if tab_bar is None:
            return
        try:
            if bool(tab_bar.property("_nc_tab_order_persistence_installed")):
                return
        except Exception:
            pass
        try:
            tab_bar.setMovable(True)
        except Exception:
            pass
        try:
            tab_bar.tabMoved.connect(
                lambda _from, _to, name=str(object_name or ""): self._on_persisted_tab_moved(name)
            )
            tab_bar.setProperty("_nc_tab_order_persistence_installed", True)
        except Exception:
            pass

    def _on_persisted_tab_moved(self, object_name):
        if bool(getattr(self, "_suspend_tab_order_save", False)):
            return
        if str(object_name or "") not in self._PERSISTED_TAB_ORDER_OBJECTS:
            return
        try:
            self.save_session()
        except Exception:
            pass

    def _addon_session_surface_specs(self):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return []
        try:
            return [
                dict(spec)
                for spec in list(manager.get_ui_disabled_surface_specs() or [])
                if str((spec or {}).get("session_visible_key") or "").strip()
            ]
        except Exception:
            return []

    def _save_addon_session_surface_visibility(self, session):
        for spec in self._addon_session_surface_specs():
            key = str(spec.get("session_visible_key") or "").strip()
            dock_name = str(spec.get("dock_name") or "").strip()
            if not key or not dock_name:
                continue
            dock = getattr(self, dock_name, None)
            enabled = True
            addon_id = str(spec.get("addon_id") or "").strip()
            checker = getattr(self, "_addon_surface_runtime_available", None) or getattr(self, "_addon_effectively_enabled", None)
            if callable(checker) and addon_id:
                try:
                    enabled = bool(checker(addon_id))
                except Exception:
                    enabled = True
            try:
                session[key] = bool(enabled and dock is not None and dock.isVisible())
            except Exception:
                session[key] = False

    def _restore_addon_session_surface_visibility(self, session, *, suppress_aux_docks=False):
        for spec in self._addon_session_surface_specs():
            key = str(spec.get("session_visible_key") or "").strip()
            dock_name = str(spec.get("dock_name") or "").strip()
            if not key or not dock_name:
                continue
            dock = getattr(self, dock_name, None)
            if dock is None:
                continue
            addon_id = str(spec.get("addon_id") or "").strip()
            enabled = True
            checker = getattr(self, "_addon_surface_runtime_available", None) or getattr(self, "_addon_effectively_enabled", None)
            if callable(checker) and addon_id:
                try:
                    enabled = bool(checker(addon_id))
                except Exception:
                    enabled = True
            try:
                if bool(session.get(key, False)) and not suppress_aux_docks and enabled:
                    dock.show()
                else:
                    dock.hide()
            except Exception:
                pass

    def _session_model_name(self):
        active_model_getter = getattr(self, "_current_active_chat_provider_model_name", None)
        if callable(active_model_getter):
            active_model = str(active_model_getter() or "").strip()
            if active_model:
                return active_model
        if hasattr(self, "model_combo"):
            model_combo_text = str(self.model_combo.currentText() or "").strip()
        else:
            model_combo_text = ""
        is_placeholder = getattr(self, "_is_model_catalog_placeholder", None)
        if model_combo_text and not (callable(is_placeholder) and is_placeholder(model_combo_text)):
            return model_combo_text
        runtime_model = str(RUNTIME_CONFIG.get("model_name", "") or "").strip()
        return runtime_model

    def _session_model_supports_images(self, model_name):
        model_name = str(model_name or "").strip()
        is_placeholder = getattr(self, "_is_model_catalog_placeholder", None)
        if model_name and not (callable(is_placeholder) and is_placeholder(model_name)) and hasattr(self, "_current_model_supports_images_value"):
            return self._current_model_supports_images_value(model_name)
        return RUNTIME_CONFIG.get("model_supports_images", None)

    def _ai_presence_session_settings(self):
        def _checked(attr, key, default=False):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "isChecked"):
                return bool(widget.isChecked())
            return bool(RUNTIME_CONFIG.get(key, default))

        def _slider(attr, key, default):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "value"):
                try:
                    return widget.value()
                except Exception:
                    pass
            return RUNTIME_CONFIG.get(key, default)

        def _combo(attr, key, default):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "currentData"):
                try:
                    data = widget.currentData()
                    if data:
                        return data
                except Exception:
                    pass
            return RUNTIME_CONFIG.get(key, default)

        def _number(value, default):
            return default if value is None else value

        return {
            "ai_presence_enabled": _checked("ai_presence_enabled_checkbox", "ai_presence_enabled", False),
            "ai_presence_display_mode": str(_combo("ai_presence_display_mode_combo", "ai_presence_display_mode", "fullscreen") or "fullscreen"),
            "ai_presence_visual_style": str(_combo("ai_presence_visual_style_combo", "ai_presence_visual_style", "neural_network_pulse") or "neural_network_pulse"),
            "ai_presence_fullscreen": _checked("ai_presence_fullscreen_checkbox", "ai_presence_fullscreen", True),
            "ai_presence_overlay_opacity": float(_slider("ai_presence_opacity_slider", "ai_presence_overlay_opacity", 0.72) or 0.72),
            "ai_presence_floating_opacity": float(_slider("ai_presence_floating_opacity_slider", "ai_presence_floating_opacity", 0.92) or 0.92),
            "ai_presence_floating_always_on_top": _checked("ai_presence_floating_always_on_top_checkbox", "ai_presence_floating_always_on_top", True),
            "ai_presence_remember_floating_geometry": _checked("ai_presence_remember_floating_geometry_checkbox", "ai_presence_remember_floating_geometry", True),
            "ai_presence_transparent_background": _checked("ai_presence_transparent_background_checkbox", "ai_presence_transparent_background", False),
            "ai_presence_floating_geometry": RUNTIME_CONFIG.get("ai_presence_floating_geometry", []),
            "ai_presence_external_runtime_enabled": _checked("ai_presence_external_runtime_enabled_checkbox", "ai_presence_external_runtime_enabled", False),
            "ai_presence_thinking_pulse": float(_slider("ai_presence_thinking_slider", "ai_presence_thinking_pulse", 0.55) or 0.55),
            "ai_presence_speaking_reactivity": float(_slider("ai_presence_speaking_slider", "ai_presence_speaking_reactivity", 0.85) or 0.85),
            "ai_presence_audio_refresh_hz": int(_slider("ai_presence_audio_refresh_slider", "ai_presence_audio_refresh_hz", 30) or 30),
            "ai_presence_node_density": int(_slider("ai_presence_density_slider", "ai_presence_node_density", 32) or 32),
            "ai_presence_particle_density": int(_slider("ai_presence_particle_density_slider", "ai_presence_particle_density", 28) or 28),
            "ai_presence_reduced_effects": _checked("ai_presence_reduced_effects_checkbox", "ai_presence_reduced_effects", False),
            "ai_presence_shaders_enabled": _checked("ai_presence_shaders_enabled_checkbox", "ai_presence_shaders_enabled", True),
            "ai_presence_particles_enabled": _checked("ai_presence_particles_enabled_checkbox", "ai_presence_particles_enabled", True),
            "ai_presence_space_closes_fullscreen": _checked("ai_presence_space_closes_fullscreen_checkbox", "ai_presence_space_closes_fullscreen", True),
            "ai_presence_music_reactivity_enabled": _checked("ai_presence_music_reactivity_enabled_checkbox", "ai_presence_music_reactivity_enabled", False),
            "ai_presence_music_reactivity": float(_number(_slider("ai_presence_music_reactivity_slider", "ai_presence_music_reactivity", 0.65), 0.65)),
            "ai_presence_neural_face_enabled": _checked("ai_presence_neural_face_enabled_checkbox", "ai_presence_neural_face_enabled", True),
            "ai_presence_neural_face_variant": str(_combo("ai_presence_neural_face_variant_combo", "ai_presence_neural_face_variant", "auto") or "auto"),
            "ai_presence_neural_face_size": float(_slider("ai_presence_neural_face_size_slider", "ai_presence_neural_face_size", 1.0) or 1.0),
            "ai_presence_neural_face_opacity": float(_slider("ai_presence_neural_face_opacity_slider", "ai_presence_neural_face_opacity", 0.92) or 0.92),
            "ai_presence_neural_face_animation_intensity": float(_number(_slider("ai_presence_neural_face_animation_slider", "ai_presence_neural_face_animation_intensity", 0.78), 0.78)),
            "ai_presence_neural_face_lipsync_strength": float(_number(_slider("ai_presence_neural_face_lipsync_slider", "ai_presence_neural_face_lipsync_strength", 1.0), 1.0)),
            "ai_presence_neural_face_eye_movement_enabled": _checked("ai_presence_neural_face_eye_movement_checkbox", "ai_presence_neural_face_eye_movement_enabled", True),
            "ai_presence_neural_face_blink_enabled": _checked("ai_presence_neural_face_blink_checkbox", "ai_presence_neural_face_blink_enabled", True),
            "ai_presence_neural_face_glow_enabled": _checked("ai_presence_neural_face_glow_checkbox", "ai_presence_neural_face_glow_enabled", True),
            "ai_presence_neural_face_emotion_enabled": _checked("ai_presence_neural_face_emotion_checkbox", "ai_presence_neural_face_emotion_enabled", True),
            "ai_presence_neural_face_use_tts_emotion": _checked("ai_presence_neural_face_tts_emotion_checkbox", "ai_presence_neural_face_use_tts_emotion", True),
            "ai_presence_neural_face_audio_lipsync_enabled": _checked("ai_presence_neural_face_audio_lipsync_checkbox", "ai_presence_neural_face_audio_lipsync_enabled", True),
            "ai_presence_neural_face_reduced_animation": _checked("ai_presence_neural_face_reduced_checkbox", "ai_presence_neural_face_reduced_animation", False),
            "ai_presence_female_neural_face_enabled": _checked("ai_presence_female_neural_face_enabled_checkbox", "ai_presence_female_neural_face_enabled", True),
            "ai_presence_female_reference_nodes": _checked("ai_presence_female_reference_nodes_checkbox", "ai_presence_female_reference_nodes", True),
            "ai_presence_female_show_wire_nodes": _checked("ai_presence_female_show_nodes_checkbox", "ai_presence_female_show_wire_nodes", True),
            "ai_presence_female_show_wire_lines": _checked("ai_presence_female_show_lines_checkbox", "ai_presence_female_show_wire_lines", True),
            "ai_presence_female_node_glow_enabled": _checked("ai_presence_female_node_glow_checkbox", "ai_presence_female_node_glow_enabled", True),
            "ai_presence_female_wire_pulse_enabled": _checked("ai_presence_female_wire_pulse_checkbox", "ai_presence_female_wire_pulse_enabled", True),
            "ai_presence_female_depth_enabled": _checked("ai_presence_female_depth_checkbox", "ai_presence_female_depth_enabled", True),
        }

    def _restore_ai_presence_session_settings(self, session):
        config = {
            "ai_presence_enabled": bool(session.get("ai_presence_enabled", RUNTIME_CONFIG.get("ai_presence_enabled", False))),
            "ai_presence_display_mode": str(session.get("ai_presence_display_mode", RUNTIME_CONFIG.get("ai_presence_display_mode", "fullscreen")) or "fullscreen"),
            "ai_presence_visual_style": str(session.get("ai_presence_visual_style", RUNTIME_CONFIG.get("ai_presence_visual_style", "neural_network_pulse")) or "neural_network_pulse"),
            "ai_presence_fullscreen": bool(session.get("ai_presence_fullscreen", RUNTIME_CONFIG.get("ai_presence_fullscreen", True))),
            "ai_presence_overlay_opacity": float(session.get("ai_presence_overlay_opacity", RUNTIME_CONFIG.get("ai_presence_overlay_opacity", 0.72)) or 0.72),
            "ai_presence_floating_opacity": float(session.get("ai_presence_floating_opacity", RUNTIME_CONFIG.get("ai_presence_floating_opacity", 0.92)) or 0.92),
            "ai_presence_floating_always_on_top": bool(session.get("ai_presence_floating_always_on_top", RUNTIME_CONFIG.get("ai_presence_floating_always_on_top", True))),
            "ai_presence_remember_floating_geometry": bool(session.get("ai_presence_remember_floating_geometry", RUNTIME_CONFIG.get("ai_presence_remember_floating_geometry", True))),
            "ai_presence_transparent_background": bool(session.get("ai_presence_transparent_background", RUNTIME_CONFIG.get("ai_presence_transparent_background", False))),
            "ai_presence_floating_geometry": session.get("ai_presence_floating_geometry", RUNTIME_CONFIG.get("ai_presence_floating_geometry", [])),
            "ai_presence_external_runtime_enabled": bool(
                session.get("ai_presence_external_runtime_enabled", RUNTIME_CONFIG.get("ai_presence_external_runtime_enabled", False))
            ),
            "ai_presence_thinking_pulse": float(session.get("ai_presence_thinking_pulse", RUNTIME_CONFIG.get("ai_presence_thinking_pulse", 0.55)) or 0.55),
            "ai_presence_speaking_reactivity": float(session.get("ai_presence_speaking_reactivity", RUNTIME_CONFIG.get("ai_presence_speaking_reactivity", 0.85)) or 0.85),
            "ai_presence_audio_refresh_hz": int(session.get("ai_presence_audio_refresh_hz", RUNTIME_CONFIG.get("ai_presence_audio_refresh_hz", 30)) or 30),
            "ai_presence_node_density": int(session.get("ai_presence_node_density", RUNTIME_CONFIG.get("ai_presence_node_density", 32)) or 32),
            "ai_presence_particle_density": int(session.get("ai_presence_particle_density", RUNTIME_CONFIG.get("ai_presence_particle_density", 28)) or 28),
            "ai_presence_reduced_effects": bool(session.get("ai_presence_reduced_effects", RUNTIME_CONFIG.get("ai_presence_reduced_effects", False))),
            "ai_presence_shaders_enabled": bool(session.get("ai_presence_shaders_enabled", RUNTIME_CONFIG.get("ai_presence_shaders_enabled", True))),
            "ai_presence_particles_enabled": bool(session.get("ai_presence_particles_enabled", RUNTIME_CONFIG.get("ai_presence_particles_enabled", True))),
            "ai_presence_space_closes_fullscreen": bool(session.get("ai_presence_space_closes_fullscreen", RUNTIME_CONFIG.get("ai_presence_space_closes_fullscreen", True))),
            "ai_presence_music_reactivity_enabled": bool(session.get("ai_presence_music_reactivity_enabled", RUNTIME_CONFIG.get("ai_presence_music_reactivity_enabled", False))),
            "ai_presence_music_reactivity": float(session.get("ai_presence_music_reactivity", RUNTIME_CONFIG.get("ai_presence_music_reactivity", 0.65))),
            "ai_presence_neural_face_enabled": bool(session.get("ai_presence_neural_face_enabled", RUNTIME_CONFIG.get("ai_presence_neural_face_enabled", True))),
            "ai_presence_neural_face_variant": str(session.get("ai_presence_neural_face_variant", RUNTIME_CONFIG.get("ai_presence_neural_face_variant", "auto")) or "auto"),
            "ai_presence_neural_face_size": float(session.get("ai_presence_neural_face_size", RUNTIME_CONFIG.get("ai_presence_neural_face_size", 1.0)) or 1.0),
            "ai_presence_neural_face_opacity": float(session.get("ai_presence_neural_face_opacity", RUNTIME_CONFIG.get("ai_presence_neural_face_opacity", 0.92)) or 0.92),
            "ai_presence_neural_face_animation_intensity": float(session.get("ai_presence_neural_face_animation_intensity", RUNTIME_CONFIG.get("ai_presence_neural_face_animation_intensity", 0.78)) or 0.78),
            "ai_presence_neural_face_lipsync_strength": float(session.get("ai_presence_neural_face_lipsync_strength", RUNTIME_CONFIG.get("ai_presence_neural_face_lipsync_strength", 1.0)) or 1.0),
            "ai_presence_neural_face_eye_movement_enabled": bool(session.get("ai_presence_neural_face_eye_movement_enabled", RUNTIME_CONFIG.get("ai_presence_neural_face_eye_movement_enabled", True))),
            "ai_presence_neural_face_blink_enabled": bool(session.get("ai_presence_neural_face_blink_enabled", RUNTIME_CONFIG.get("ai_presence_neural_face_blink_enabled", True))),
            "ai_presence_neural_face_glow_enabled": bool(session.get("ai_presence_neural_face_glow_enabled", RUNTIME_CONFIG.get("ai_presence_neural_face_glow_enabled", True))),
            "ai_presence_neural_face_emotion_enabled": bool(session.get("ai_presence_neural_face_emotion_enabled", RUNTIME_CONFIG.get("ai_presence_neural_face_emotion_enabled", True))),
            "ai_presence_neural_face_use_tts_emotion": bool(session.get("ai_presence_neural_face_use_tts_emotion", RUNTIME_CONFIG.get("ai_presence_neural_face_use_tts_emotion", True))),
            "ai_presence_neural_face_audio_lipsync_enabled": bool(session.get("ai_presence_neural_face_audio_lipsync_enabled", RUNTIME_CONFIG.get("ai_presence_neural_face_audio_lipsync_enabled", True))),
            "ai_presence_neural_face_reduced_animation": bool(session.get("ai_presence_neural_face_reduced_animation", RUNTIME_CONFIG.get("ai_presence_neural_face_reduced_animation", False))),
            "ai_presence_female_neural_face_enabled": bool(session.get("ai_presence_female_neural_face_enabled", RUNTIME_CONFIG.get("ai_presence_female_neural_face_enabled", True))),
            "ai_presence_female_reference_nodes": bool(session.get("ai_presence_female_reference_nodes", RUNTIME_CONFIG.get("ai_presence_female_reference_nodes", True))),
            "ai_presence_female_show_wire_nodes": bool(session.get("ai_presence_female_show_wire_nodes", RUNTIME_CONFIG.get("ai_presence_female_show_wire_nodes", True))),
            "ai_presence_female_show_wire_lines": bool(session.get("ai_presence_female_show_wire_lines", RUNTIME_CONFIG.get("ai_presence_female_show_wire_lines", True))),
            "ai_presence_female_node_glow_enabled": bool(session.get("ai_presence_female_node_glow_enabled", RUNTIME_CONFIG.get("ai_presence_female_node_glow_enabled", True))),
            "ai_presence_female_wire_pulse_enabled": bool(session.get("ai_presence_female_wire_pulse_enabled", RUNTIME_CONFIG.get("ai_presence_female_wire_pulse_enabled", True))),
            "ai_presence_female_depth_enabled": bool(session.get("ai_presence_female_depth_enabled", RUNTIME_CONFIG.get("ai_presence_female_depth_enabled", True))),
        }
        if config["ai_presence_display_mode"] not in {"off", "fullscreen", "floating", "both"}:
            config["ai_presence_display_mode"] = "fullscreen"
        if config["ai_presence_visual_style"] not in {
            "neural_network_pulse",
            "neural_face_male",
            "neural_face_female",
            "neural_face_auto",
        }:
            config["ai_presence_visual_style"] = "neural_network_pulse"
        config["ai_presence_overlay_opacity"] = max(0.10, min(1.00, config["ai_presence_overlay_opacity"]))
        config["ai_presence_floating_opacity"] = max(0.35, min(1.00, config["ai_presence_floating_opacity"]))
        config["ai_presence_thinking_pulse"] = max(0.10, min(1.00, config["ai_presence_thinking_pulse"]))
        config["ai_presence_speaking_reactivity"] = max(0.10, min(1.50, config["ai_presence_speaking_reactivity"]))
        config["ai_presence_music_reactivity"] = max(0.00, min(1.50, config["ai_presence_music_reactivity"]))
        config["ai_presence_audio_refresh_hz"] = max(5, min(30, config["ai_presence_audio_refresh_hz"]))
        config["ai_presence_node_density"] = max(8, min(96, config["ai_presence_node_density"]))
        config["ai_presence_particle_density"] = max(0, min(120, config["ai_presence_particle_density"]))
        if config["ai_presence_neural_face_variant"] not in {"auto", "male", "female"}:
            config["ai_presence_neural_face_variant"] = "auto"
        config["ai_presence_neural_face_size"] = max(0.55, min(1.35, config["ai_presence_neural_face_size"]))
        config["ai_presence_neural_face_opacity"] = max(0.15, min(1.00, config["ai_presence_neural_face_opacity"]))
        config["ai_presence_neural_face_animation_intensity"] = max(0.00, min(1.50, config["ai_presence_neural_face_animation_intensity"]))
        config["ai_presence_neural_face_lipsync_strength"] = max(0.00, min(1.75, config["ai_presence_neural_face_lipsync_strength"]))
        if not (isinstance(config["ai_presence_floating_geometry"], (list, tuple)) and len(config["ai_presence_floating_geometry"]) == 4):
            config["ai_presence_floating_geometry"] = []
        for key, value in config.items():
            update_runtime_config(key, value)

        widget_specs = [
            ("ai_presence_enabled_checkbox", "ai_presence_enabled", "checked"),
            ("ai_presence_display_mode_combo", "ai_presence_display_mode", "combo"),
            ("ai_presence_visual_style_combo", "ai_presence_visual_style", "combo"),
            ("ai_presence_fullscreen_checkbox", "ai_presence_fullscreen", "checked"),
            ("ai_presence_floating_always_on_top_checkbox", "ai_presence_floating_always_on_top", "checked"),
            ("ai_presence_remember_floating_geometry_checkbox", "ai_presence_remember_floating_geometry", "checked"),
            ("ai_presence_transparent_background_checkbox", "ai_presence_transparent_background", "checked"),
            ("ai_presence_external_runtime_enabled_checkbox", "ai_presence_external_runtime_enabled", "checked"),
            ("ai_presence_reduced_effects_checkbox", "ai_presence_reduced_effects", "checked"),
            ("ai_presence_shaders_enabled_checkbox", "ai_presence_shaders_enabled", "checked"),
            ("ai_presence_particles_enabled_checkbox", "ai_presence_particles_enabled", "checked"),
            ("ai_presence_space_closes_fullscreen_checkbox", "ai_presence_space_closes_fullscreen", "checked"),
            ("ai_presence_music_reactivity_enabled_checkbox", "ai_presence_music_reactivity_enabled", "checked"),
            ("ai_presence_neural_face_enabled_checkbox", "ai_presence_neural_face_enabled", "checked"),
            ("ai_presence_neural_face_eye_movement_checkbox", "ai_presence_neural_face_eye_movement_enabled", "checked"),
            ("ai_presence_neural_face_blink_checkbox", "ai_presence_neural_face_blink_enabled", "checked"),
            ("ai_presence_neural_face_glow_checkbox", "ai_presence_neural_face_glow_enabled", "checked"),
            ("ai_presence_neural_face_emotion_checkbox", "ai_presence_neural_face_emotion_enabled", "checked"),
            ("ai_presence_neural_face_tts_emotion_checkbox", "ai_presence_neural_face_use_tts_emotion", "checked"),
            ("ai_presence_neural_face_audio_lipsync_checkbox", "ai_presence_neural_face_audio_lipsync_enabled", "checked"),
            ("ai_presence_neural_face_reduced_checkbox", "ai_presence_neural_face_reduced_animation", "checked"),
            ("ai_presence_female_neural_face_enabled_checkbox", "ai_presence_female_neural_face_enabled", "checked"),
            ("ai_presence_female_reference_nodes_checkbox", "ai_presence_female_reference_nodes", "checked"),
            ("ai_presence_female_show_nodes_checkbox", "ai_presence_female_show_wire_nodes", "checked"),
            ("ai_presence_female_show_lines_checkbox", "ai_presence_female_show_wire_lines", "checked"),
            ("ai_presence_female_node_glow_checkbox", "ai_presence_female_node_glow_enabled", "checked"),
            ("ai_presence_female_wire_pulse_checkbox", "ai_presence_female_wire_pulse_enabled", "checked"),
            ("ai_presence_female_depth_checkbox", "ai_presence_female_depth_enabled", "checked"),
            ("ai_presence_opacity_slider", "ai_presence_overlay_opacity", "slider"),
            ("ai_presence_floating_opacity_slider", "ai_presence_floating_opacity", "slider"),
            ("ai_presence_thinking_slider", "ai_presence_thinking_pulse", "slider"),
            ("ai_presence_speaking_slider", "ai_presence_speaking_reactivity", "slider"),
            ("ai_presence_audio_refresh_slider", "ai_presence_audio_refresh_hz", "slider"),
            ("ai_presence_density_slider", "ai_presence_node_density", "slider"),
            ("ai_presence_particle_density_slider", "ai_presence_particle_density", "slider"),
            ("ai_presence_music_reactivity_slider", "ai_presence_music_reactivity", "slider"),
            ("ai_presence_neural_face_variant_combo", "ai_presence_neural_face_variant", "combo"),
            ("ai_presence_neural_face_size_slider", "ai_presence_neural_face_size", "slider"),
            ("ai_presence_neural_face_opacity_slider", "ai_presence_neural_face_opacity", "slider"),
            ("ai_presence_neural_face_animation_slider", "ai_presence_neural_face_animation_intensity", "slider"),
            ("ai_presence_neural_face_lipsync_slider", "ai_presence_neural_face_lipsync_strength", "slider"),
        ]
        for attr, key, kind in widget_specs:
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            try:
                widget.blockSignals(True)
                if kind == "checked" and hasattr(widget, "setChecked"):
                    widget.setChecked(bool(config[key]))
                elif kind == "slider" and hasattr(widget, "set_value"):
                    widget.set_value(config[key])
                elif kind == "combo" and hasattr(widget, "count"):
                    value = str(config[key] or "").strip().lower()
                    for index in range(widget.count()):
                        if str(widget.itemData(index) or "").strip().lower() == value:
                            widget.setCurrentIndex(index)
                            break
            finally:
                try:
                    widget.blockSignals(False)
                except Exception:
                    pass

    def save_session(self):
        if bool(getattr(self, "_session_read_only", False)):
            return
        if bool(getattr(self, "_suspend_session_save", False)):
            return
        preserved_main_ui_real_layout = None
        try:
            if SESSION_PATH.exists():
                previous_session = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if isinstance(previous_session, dict):
                    previous_session = with_flat_ui_settings(previous_session)
                    preserved_main_ui_real_layout = previous_session.get("main_ui_real_layout")
        except Exception:
            preserved_main_ui_real_layout = None
        session_model_name = self._session_model_name()
        active_chat_context_path = str(RUNTIME_CONFIG.get("active_chat_context_path", "") or "")
        active_chat_context_name = str(RUNTIME_CONFIG.get("active_chat_context_name", "") or "")
        last_chat_context_path = active_chat_context_path or str(getattr(self, "_last_chat_context_path", "") or "")
        last_chat_context_name = active_chat_context_name or str(getattr(self, "_last_chat_context_name", "") or "")
        companion_orb_sensory_target_enabled = (
            bool(self.companion_orb_sensory_target_checkbox.isChecked())
            if hasattr(self, "companion_orb_sensory_target_checkbox")
            else bool(RUNTIME_CONFIG.get("companion_orb_sensory_target_enabled", False))
        )
        sensory_feedback_source = (
            self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText())
            if hasattr(self, "sensory_feedback_source_combo")
            else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off")
        )
        sensory_feedback_source = ",".join(
            normalize_companion_orb_target_source_selection(
                sensory_feedback_source,
                companion_orb_sensory_target_enabled,
            )
        ) or "off"
        session = {
            "first_run": bool(self.first_run),
            "ui_theme_preset": self.current_app_theme_preset(),
            "avatar_mode": self._current_avatar_mode_value(),
            "audio_input_device": self.audio_input_device_combo.currentText() if hasattr(self, "audio_input_device_combo") else str(RUNTIME_CONFIG.get("audio_input_device", "Default Input") or "Default Input"),
            "show_all_audio_input_devices": bool(self.show_all_audio_inputs_checkbox.isChecked()) if hasattr(self, "show_all_audio_inputs_checkbox") else bool(RUNTIME_CONFIG.get("show_all_audio_input_devices", False)),
            "audio_output_device": self.audio_output_device_combo.currentText() if hasattr(self, "audio_output_device_combo") else str(RUNTIME_CONFIG.get("audio_output_device", "Default Output") or "Default Output"),
            "voice_file": self._current_voice_file_value() if hasattr(self, "voice_combo") else "",
            "input_mode": self.input_mode_combo.currentText(),
            "input_message_role": self.input_role_combo.currentText(),
            "hotkeys": dict(engine.get_hotkey_settings()),
            "stream_mode": self.stream_mode_combo.currentText(),
            "stt_backend": self._current_stt_backend_value() if hasattr(self, "stt_backend_combo") else str(RUNTIME_CONFIG.get("stt_backend", "none") or "none"),
            "stt_model_size": self._current_stt_model_value() if hasattr(self, "stt_model_combo") else str(RUNTIME_CONFIG.get("stt_model_size", "tiny.en") or "tiny.en"),
            "stt_language": self._current_stt_language_value() if hasattr(self, "stt_language_combo") else str(RUNTIME_CONFIG.get("stt_language", "en") or "en"),
            "stt_backend_settings": dict(RUNTIME_CONFIG.get("stt_backend_settings", {}) or {}),
            "tts_backend": self._current_tts_backend_value(),
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "chat_provider_generation_settings": dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {}),
            "chat_font_size": int(self.chat_font_size_combo.currentData() or 12) if hasattr(self, "chat_font_size_combo") else 12,
            "chat_message_timestamps_enabled": bool(RUNTIME_CONFIG.get("chat_message_timestamps_enabled", False)),
            "chat_runtime_expanded": self.chat_runtime_section.isExpanded() if hasattr(self, "chat_runtime_section") else True,
            "stt_runtime_expanded": self.stt_runtime_section.isExpanded() if hasattr(self, "stt_runtime_section") else True,
            "tts_runtime_expanded": self.tts_runtime_section.isExpanded() if hasattr(self, "tts_runtime_section") else True,
            "model_name": session_model_name,
            "model_requires_vision": self.model_requires_vision_checkbox.isChecked() if hasattr(self, "model_requires_vision_checkbox") else False,
            "model_supports_images": self._session_model_supports_images(session_model_name),
            "allow_proactive_replies": self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else False,
            "require_first_user_before_proactive": self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False,
            "listen_idle_window_seconds": float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0,
            "proactive_delay_seconds": float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0,
            "chat_context_window_messages": int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20,
            "stored_chat_history_limit": int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0,
            "chat_context_overflow_policy": self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window",
            "spellcheck_enabled": bool(self.spellcheck_enabled_checkbox.isChecked()) if hasattr(self, "spellcheck_enabled_checkbox") else bool(RUNTIME_CONFIG.get("spellcheck_enabled", True)),
            "spellcheck_language": str(self.spellcheck_language_combo.currentText() or "en_US").strip() if hasattr(self, "spellcheck_language_combo") else str(RUNTIME_CONFIG.get("spellcheck_language", "en_US") or "en_US"),
            **self._ai_presence_session_settings(),
            "continuity_memory_id": "",
            "active_chat_context_path": "",
            "active_chat_context_name": "",
            "last_chat_context_path": last_chat_context_path,
            "last_chat_context_name": last_chat_context_name,
            "continuity_memory_enabled": bool(self.long_term_memory_enabled_checkbox.isChecked()) if hasattr(self, "long_term_memory_enabled_checkbox") else bool(RUNTIME_CONFIG.get("continuity_memory_enabled", RUNTIME_CONFIG.get("long_term_memory_enabled", False))),
            "continuity_memory_auto_summarize": bool(self.long_term_memory_update_on_save_checkbox.isChecked()) if hasattr(self, "long_term_memory_update_on_save_checkbox") else bool(RUNTIME_CONFIG.get("continuity_memory_auto_summarize", RUNTIME_CONFIG.get("continuity_memory_update_on_save", RUNTIME_CONFIG.get("long_term_memory_update_on_save", False)))),
            "continuity_memory_auto_turns": int(self.continuity_memory_auto_turns_spin.value()) if hasattr(self, "continuity_memory_auto_turns_spin") else int(RUNTIME_CONFIG.get("continuity_memory_auto_turns", 120) or 120),
            "continuity_memory_inject": bool(self.long_term_memory_inject_checkbox.isChecked()) if hasattr(self, "long_term_memory_inject_checkbox") else bool(RUNTIME_CONFIG.get("continuity_memory_inject", RUNTIME_CONFIG.get("long_term_memory_inject", False))),
            "continuity_memory_max_chars": int(self.long_term_memory_max_chars_spin.value()) if hasattr(self, "long_term_memory_max_chars_spin") else int(RUNTIME_CONFIG.get("continuity_memory_max_chars", RUNTIME_CONFIG.get("long_term_memory_max_chars", 3000)) or 3000),
            "long_term_memory_retrieval_enabled": bool(self.long_term_memory_retrieval_enabled_checkbox.isChecked()) if hasattr(self, "long_term_memory_retrieval_enabled_checkbox") else bool(RUNTIME_CONFIG.get("long_term_memory_retrieval_enabled", False)),
            "long_term_memory_retrieval_max_items": int(self.long_term_memory_retrieval_max_items_spin.value()) if hasattr(self, "long_term_memory_retrieval_max_items_spin") else int(RUNTIME_CONFIG.get("long_term_memory_retrieval_max_items", 6) or 6),
            "long_term_memory_recall_image_limit": long_term_memory.normalize_image_recall_limit(self.long_term_memory_recall_image_limit_spin.value(), default=1) if hasattr(self, "long_term_memory_recall_image_limit_spin") else long_term_memory.normalize_image_recall_limit(RUNTIME_CONFIG.get("long_term_memory_recall_image_limit", 1), default=1),
            "long_term_memory_auto_archive_enabled": bool(self.long_term_memory_auto_archive_enabled_checkbox.isChecked()) if hasattr(self, "long_term_memory_auto_archive_enabled_checkbox") else bool(RUNTIME_CONFIG.get("long_term_memory_auto_archive_enabled", False)),
            "long_term_memory_archive_batch_turns": int(self.long_term_memory_archive_batch_turns_spin.value()) if hasattr(self, "long_term_memory_archive_batch_turns_spin") else int(RUNTIME_CONFIG.get("long_term_memory_archive_batch_turns", 120) or 120),
            "long_term_memory_embedding_enabled": bool(self.long_term_memory_embedding_enabled_checkbox.isChecked()) if hasattr(self, "long_term_memory_embedding_enabled_checkbox") else bool(RUNTIME_CONFIG.get("long_term_memory_embedding_enabled", False)),
            "long_term_memory_embedding_model": (
                str(self.long_term_memory_embedding_model_edit.currentText() or "").strip()
                if hasattr(self, "long_term_memory_embedding_model_edit") and hasattr(self.long_term_memory_embedding_model_edit, "currentText")
                else (
                    str(self.long_term_memory_embedding_model_edit.text() or "").strip()
                    if hasattr(self, "long_term_memory_embedding_model_edit") and hasattr(self.long_term_memory_embedding_model_edit, "text")
                    else str(RUNTIME_CONFIG.get("long_term_memory_embedding_model", "text-embedding-bge-m3") or "text-embedding-bge-m3")
                )
            ),
            "long_term_memory_embedding_context_length": int(self.long_term_memory_embedding_context_length_spin.value()) if hasattr(self, "long_term_memory_embedding_context_length_spin") else int(RUNTIME_CONFIG.get("long_term_memory_embedding_context_length", 8192) or 8192),
            "long_term_memory_embedding_base_url": str(self.long_term_memory_embedding_base_url_edit.text() or "").strip() if hasattr(self, "long_term_memory_embedding_base_url_edit") else str(RUNTIME_CONFIG.get("long_term_memory_embedding_base_url", "http://127.0.0.1:1234/v1") or "http://127.0.0.1:1234/v1"),
            "limit_response_length": self.limit_response_checkbox.isChecked() if hasattr(self, "limit_response_checkbox") else False,
            "max_response_tokens": int(self.max_response_tokens_spin.value()) if hasattr(self, "max_response_tokens_spin") else DEFAULT_MAX_RESPONSE_TOKENS,
            "sensory_feedback_source": sensory_feedback_source,
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "companion_orb_sensory_target_enabled": companion_orb_sensory_target_enabled,
            "companion_orb_full_screen_context_enabled": bool(RUNTIME_CONFIG.get("companion_orb_full_screen_context_enabled", False)),
            "companion_orb_include_process_name": bool(RUNTIME_CONFIG.get("companion_orb_include_process_name", True)),
            "companion_orb_target_info": dict(RUNTIME_CONFIG.get("companion_orb_target_info", {}) or {}),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
            "sensory_provider_metadata_overrides": self._current_sensory_provider_metadata_override_map() if hasattr(self, "_current_sensory_provider_metadata_override_map") else dict(RUNTIME_CONFIG.get("sensory_provider_metadata_overrides", {}) or {}),
            "screen_source_auto_attach_next_user_turn": bool(RUNTIME_CONFIG.get("screen_source_auto_attach_next_user_turn", False)),
            "performance_profile": self.performance_profile_combo.currentData() if hasattr(self, "performance_profile_combo") else "",
            "emotional_instructions": self.emotional_text.toPlainText().strip() if hasattr(self, "emotional_text") else str(RUNTIME_CONFIG.get("emotional_instructions", "") or ""),
            "system_prompt": self.system_prompt_text.toPlainText().strip() if hasattr(self, "system_prompt_text") else str(RUNTIME_CONFIG.get("system_prompt", "") or ""),
            "temperature": self.brain_sliders["temperature"].value() if "temperature" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("temperature", 1.22) or 1.22),
            "top_p": self.brain_sliders["top_p"].value() if "top_p" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("top_p", 0.9) or 0.9),
            "top_k": int(self.brain_sliders["top_k"].value()) if "top_k" in getattr(self, "brain_sliders", {}) else int(RUNTIME_CONFIG.get("top_k", 40) or 40),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value() if "repeat_penalty" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("repeat_penalty", 1.15) or 1.15),
            "min_p": self.brain_sliders["min_p"].value() if "min_p" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("min_p", 0.05) or 0.05),
            "chunking": {key: slider.value() for key, slider in self.chunking_sliders.items()},
            "dry_run_target_samples": self.dry_run_target_spin.value(),
            "dry_run_auto_replies": self.dry_run_auto_replies_checkbox.isChecked(),
            "last_preset": self.preset_combo.currentText(),
            "last_body": self._live_combo_text("body_combo", RUNTIME_CONFIG.get("last_body", "")),
            "live_sync": self._live_checked("live_sync_checkbox", RUNTIME_CONFIG.get("live_sync", False)),
            "geometry": [self.x(), self.y(), self.width(), self.height()],
            "main_splitter_sizes": self.main_splitter.sizes() if hasattr(self, "main_splitter") else [400, 980],
            "pinned_floating_docks": sorted(getattr(self, "_pinned_floating_dock_names", set()) or []),
            "always_on_top_floating_docks": sorted(getattr(self, "_always_on_top_floating_dock_names", set()) or []),
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "performance_guidance_visible": bool(hasattr(self, "guidance_box") and self.guidance_box.isVisible()),
            "window_state": base64.b64encode(self.saveState().data()).decode("ascii"),
            "right_dock_state": (
                base64.b64encode(self.right_dock_host.saveState().data()).decode("ascii")
                if hasattr(self, "right_dock_host")
                else ""
            ),
        }
        self._save_persisted_tab_orders(session)
        self._save_persisted_hidden_tabs(session)
        self._save_addon_session_surface_visibility(session)
        if isinstance(preserved_main_ui_real_layout, dict):
            session["main_ui_real_layout"] = preserved_main_ui_real_layout
        if self._addon_manager is not None:
            session.update(self._addon_manager.export_session_state())
        active_chat_provider = str(session.get("chat_provider") or "").strip().lower()
        if active_chat_provider:
            provider_settings = dict(session.get("chat_provider_settings", {}) or {})
            active_provider_settings = dict(provider_settings.get(active_chat_provider, {}) or {})
            active_provider_settings["model_name"] = session.get("model_name", "")
            active_provider_settings["model_requires_vision"] = bool(session.get("model_requires_vision", False))
            active_provider_settings["model_supports_images"] = bool(session.get("model_supports_images", False))
            active_provider_settings["model_supports_reasoning"] = bool(RUNTIME_CONFIG.get("model_supports_reasoning", False))
            active_provider_settings["model_supports_reasoning_toggle"] = bool(RUNTIME_CONFIG.get("model_supports_reasoning_toggle", False))
            provider_settings[active_chat_provider] = active_provider_settings
            session["chat_provider_settings"] = provider_settings
        session = group_persona_session(session)
        session = group_runtime_controls_session(session)
        session = group_dry_run_session(session)
        session = group_chunking_session(session)
        session = group_chat_runtime_session(session)
        session = group_sensory_session(session)
        session = group_musetalk_session(session)
        session = group_stt_runtime_session(session)
        session = group_tts_runtime_session(session)
        session = group_visual_reply_session(session)
        session = group_vam_session(session)
        session = group_ui_session(session)
        SESSION_PATH.write_text(json.dumps(session, indent=4), encoding="utf-8")

    def _ensure_window_on_screen(self):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        client = self.geometry()
        width = min(max(client.width(), 200), max(available.width(), 200))
        height = min(max(client.height(), 200), max(available.height(), 200))
        x = frame.x()
        y = frame.y()
        if x < available.left():
            x = available.left()
        if y < available.top():
            y = available.top()
        if x + width > available.right() + 1:
            x = max(available.left(), available.right() - width + 1)
        if y + height > available.bottom() + 1:
            y = max(available.top(), available.bottom() - height + 1)
        self.setGeometry(x, y, width, height)
        self.move(x, y)

    def _maybe_prompt_resume_last_chat_context(self):
        if bool(getattr(self, "_resume_last_chat_context_prompted", False)):
            return
        self._resume_last_chat_context_prompted = True
        active_path = str(RUNTIME_CONFIG.get("active_chat_context_path", "") or "").strip()
        if active_path:
            return
        raw_path = str(getattr(self, "_last_chat_context_path", "") or "").strip()
        if not raw_path:
            return
        target = Path(raw_path)
        if not target.exists():
            self._last_chat_context_path = ""
            self._last_chat_context_name = ""
            self.save_session()
            return
        display_name = str(getattr(self, "_last_chat_context_name", "") or "").strip() or target.stem
        choice = QtWidgets.QMessageBox.question(
            self,
            "Load Previous Chat Session",
            f"Load previous chat session '{display_name}'?\n\n"
            "Choose Yes to resume it now. Choose No to start a fresh empty conversation.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            loader = getattr(self, "_load_chat_context_from_path", None)
            if callable(loader):
                try:
                    loader(str(target))
                    return
                except Exception as exc:
                    QtWidgets.QMessageBox.warning(self, "Load Previous Chat Session", f"Could not load previous chat session:\n{exc}")
            return
        self._last_chat_context_path = ""
        self._last_chat_context_name = ""
        reset = getattr(self, "reset_chat_session", None)
        if callable(reset):
            reset()
        else:
            engine.reset_session_state()
        self.save_session()

    def restore_session(self):
        if not SESSION_PATH.exists():
            return
        try:
            session = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[QtGUI] Session Restore Failed: {exc}")
            return
        session = with_flat_chat_runtime_settings(
            with_flat_sensory_settings(
                with_flat_musetalk_settings(
                    with_flat_stt_runtime_settings(
                        with_flat_tts_runtime_settings(
                            with_flat_visual_reply_settings(
                                with_flat_persona_settings(
                                    with_flat_runtime_controls_settings(
                                        with_flat_dry_run_settings(
                                            with_flat_chunking_settings(
                                                with_flat_ui_settings(with_flat_vam_settings(session))
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
        self._restore_persisted_tab_orders(session)
        self._restore_persisted_hidden_tabs(session)
        previous_suspend = bool(getattr(self, "_suspend_session_save", False))
        self._suspend_session_save = True
        self._restoring_session = True
        try:
            self.first_run = bool(session.get("first_run", True))
            ui_theme_preset = session.get("ui_theme_preset")
            if ui_theme_preset is not None:
                self.apply_app_theme_preset(ui_theme_preset, save_session=False)
            geometry = session.get("geometry")
            if geometry and len(geometry) == 4:
                self.setGeometry(*geometry)
                self._ensure_window_on_screen()
            preset = session.get("last_preset")
            if preset:
                index = self.preset_combo.findText(preset)
                if index >= 0:
                    self.preset_combo.setCurrentIndex(index)
                    update_runtime_config("active_preset_name", preset)

            engine_choice = session.get("avatar_mode")
            if isinstance(engine_choice, str) and engine_choice.strip().lower() == "lam":
                engine_choice = "MuseTalk"
            if engine_choice:
                index = self.engine_combo.findData(str(engine_choice).strip().lower())
                if index < 0:
                    index = self.engine_combo.findText(engine_choice)
                if index >= 0:
                    self.engine_combo.setCurrentIndex(index)
            vam_play_audio = self._live_widget_attr("vam_play_audio_in_vam_checkbox")
            if str(engine_choice or "").strip().lower() == "vam" and vam_play_audio is not None:
                vam_play_audio.setChecked(True)
                self.on_vam_play_audio_in_vam_changed(True)
            show_all_audio_inputs = bool(session.get("show_all_audio_input_devices", False))
            update_runtime_config("show_all_audio_input_devices", show_all_audio_inputs)
            if hasattr(self, "show_all_audio_inputs_checkbox"):
                self.show_all_audio_inputs_checkbox.blockSignals(True)
                self.show_all_audio_inputs_checkbox.setChecked(show_all_audio_inputs)
                self.show_all_audio_inputs_checkbox.blockSignals(False)
                self._refresh_audio_input_device_options(session.get("audio_input_device", "Default Input"))
            audio_input_device = session.get("audio_input_device")
            if audio_input_device is not None:
                audio_input_device = self._resolve_audio_device_label(audio_input_device, direction="input")
                update_runtime_config("audio_input_device", str(audio_input_device or "Default Input") or "Default Input")
                if hasattr(self, "audio_input_device_combo"):
                    self.audio_input_device_combo.blockSignals(True)
                    index = self.audio_input_device_combo.findText(str(audio_input_device))
                    if index >= 0:
                        self.audio_input_device_combo.setCurrentIndex(index)
                    self.audio_input_device_combo.blockSignals(False)
            audio_output_device = session.get("audio_output_device")
            if audio_output_device is not None:
                audio_output_device = self._resolve_audio_device_label(audio_output_device, direction="output")
                update_runtime_config("audio_output_device", str(audio_output_device or "Default Output") or "Default Output")
                if hasattr(self, "audio_output_device_combo"):
                    self.audio_output_device_combo.blockSignals(True)
                    index = self.audio_output_device_combo.findText(str(audio_output_device))
                    if index >= 0:
                        self.audio_output_device_combo.setCurrentIndex(index)
                    self.audio_output_device_combo.blockSignals(False)
            input_mode = session.get("input_mode")
            if input_mode:
                mode_text = self._input_mode_label_from_value(input_mode)
                index = self.input_mode_combo.findText(mode_text)
                if index >= 0:
                    self.input_mode_combo.setCurrentIndex(index)
            voice_file = str(session.get("voice_file", "") or "").strip()
            if voice_file and voice_file != "No .wav found" and hasattr(self, "voice_combo"):
                index = self.voice_combo.findText(voice_file)
                if index >= 0:
                    self.voice_combo.blockSignals(True)
                    try:
                        self.voice_combo.setCurrentIndex(index)
                    finally:
                        self.voice_combo.blockSignals(False)
                    update_runtime_config("voice_path", os.path.join("voices", voice_file))
                else:
                    update_runtime_config("voice_path", "")
            hotkeys = session.get("hotkeys")
            if hotkeys is not None:
                engine.set_hotkey_settings(hotkeys)
            else:
                legacy_hotkeys = {}
                push_to_talk_hotkey = session.get("push_to_talk_hotkey")
                if push_to_talk_hotkey is not None:
                    legacy_hotkeys["push_to_talk"] = push_to_talk_hotkey
                manual_action_hotkeys = session.get("manual_action_hotkeys")
                if manual_action_hotkeys is not None:
                    legacy_hotkeys["manual_actions"] = manual_action_hotkeys
                ui_action_hotkeys = session.get("ui_action_hotkeys")
                if ui_action_hotkeys is not None:
                    legacy_hotkeys["ui_actions"] = ui_action_hotkeys
                if legacy_hotkeys:
                    engine.set_hotkey_settings(legacy_hotkeys)
            input_role = session.get("input_message_role")
            if input_role:
                index = self.input_role_combo.findText(input_role)
                if index >= 0:
                    self.input_role_combo.setCurrentIndex(index)
            stream_mode = session.get("stream_mode")
            if stream_mode is not None:
                if isinstance(stream_mode, str):
                    index = self.stream_mode_combo.findText(stream_mode)
                    if index >= 0:
                        self.stream_mode_combo.setCurrentIndex(index)
                else:
                    self.stream_mode_combo.setCurrentText("On" if bool(stream_mode) else "Off")
            stt_backend_settings = session.get("stt_backend_settings")
            if stt_backend_settings is not None:
                update_runtime_config("stt_backend_settings", stt_backend_settings)
            stt_backend = session.get("stt_backend")
            if stt_backend is not None and hasattr(self, "stt_backend_combo"):
                self._populate_stt_backend_combo(selected_value=stt_backend)
                index = self.stt_backend_combo.findData(str(stt_backend or "").strip().lower())
                if index >= 0:
                    self.stt_backend_combo.setCurrentIndex(index)
                self.on_stt_backend_change(self.stt_backend_combo.currentText())
            stt_model_size = session.get("stt_model_size")
            if stt_model_size is not None and hasattr(self, "stt_model_combo"):
                self._populate_stt_model_combo(selected_value=stt_model_size)
                index = self.stt_model_combo.findData(str(stt_model_size or "").strip())
                if index >= 0:
                    self.stt_model_combo.setCurrentIndex(index)
                self.on_stt_model_change(self.stt_model_combo.currentText())
            stt_language = session.get("stt_language")
            if stt_language is not None and hasattr(self, "stt_language_combo"):
                self._populate_stt_language_combo(selected_value=stt_language)
                self.on_stt_language_change(self.stt_language_combo.currentText())
            tts_backend = session.get("tts_backend")
            if tts_backend:
                desired_backend = str(tts_backend or "").strip().lower()
                self._populate_tts_backend_combo(selected_value=desired_backend)
                index = self.tts_backend_combo.findData(desired_backend)
                if index >= 0:
                    self.tts_backend_combo.setCurrentIndex(index)
                self.on_tts_backend_change(self.tts_backend_combo.currentText())
            chat_provider = session.get("chat_provider")
            if chat_provider is not None and hasattr(self, "chat_provider_combo"):
                normalized_provider = self._set_chat_provider_selection(chat_provider)
                update_runtime_config("chat_provider", normalized_provider)
            chat_provider_settings = session.get("chat_provider_settings")
            if chat_provider_settings is not None:
                update_runtime_config("chat_provider_settings", chat_provider_settings)
                self._refresh_chat_provider_card()
            chat_provider_generation_settings = session.get("chat_provider_generation_settings")
            if chat_provider_generation_settings is None:
                preset_name = str(session.get("last_preset") or "").strip()
                preset_path = Path("presets") / f"{preset_name}.json" if preset_name else None
                if preset_path is not None and preset_path.exists():
                    try:
                        preset_data = json.loads(preset_path.read_text(encoding="utf-8"))
                        chat_provider_generation_settings = preset_data.get("chat_provider_generation_settings")
                    except Exception:
                        chat_provider_generation_settings = None
            if chat_provider_generation_settings is not None:
                update_runtime_config("chat_provider_generation_settings", chat_provider_generation_settings)
                self._refresh_chat_provider_generation_card()
            chat_font_size = session.get("chat_font_size")
            if chat_font_size is not None and hasattr(self, "chat_font_size_combo"):
                size = max(8, min(20, int(chat_font_size)))
                index = self.chat_font_size_combo.findData(size)
                if index >= 0:
                    self.chat_font_size_combo.setCurrentIndex(index)
                self._apply_chat_font_size(size, update_combo=False)
            update_runtime_config("chat_message_timestamps_enabled", bool(session.get("chat_message_timestamps_enabled", False)))
            if hasattr(self, "_update_chat_timestamp_button"):
                self._update_chat_timestamp_button()
            if "chat_runtime_expanded" in session and hasattr(self, "chat_runtime_section"):
                self.chat_runtime_section.setExpanded(bool(session.get("chat_runtime_expanded", True)))
            if "stt_runtime_expanded" in session and hasattr(self, "stt_runtime_section"):
                self.stt_runtime_section.setExpanded(bool(session.get("stt_runtime_expanded", True)))
            if "tts_runtime_expanded" in session and hasattr(self, "tts_runtime_section"):
                self.tts_runtime_section.setExpanded(bool(session.get("tts_runtime_expanded", True)))
            saved_model_name = str(session.get("model_name") or "").strip()
            if saved_model_name:
                self._pending_restored_model_name = saved_model_name
                update_runtime_config("model_name", saved_model_name)
            model_requires_vision = session.get("model_requires_vision")
            if model_requires_vision is not None and hasattr(self, "model_requires_vision_checkbox"):
                self.model_requires_vision_checkbox.blockSignals(True)
                try:
                    self.model_requires_vision_checkbox.setChecked(bool(model_requires_vision))
                finally:
                    self.model_requires_vision_checkbox.blockSignals(False)
                update_runtime_config("model_requires_vision", bool(model_requires_vision))
            if "model_supports_images" in session:
                update_runtime_config("model_supports_images", session.get("model_supports_images"))
            allow_proactive_replies = session.get("allow_proactive_replies")
            if allow_proactive_replies is not None and hasattr(self, "allow_proactive_checkbox"):
                self.allow_proactive_checkbox.setChecked(bool(allow_proactive_replies))
                self.on_allow_proactive_replies_changed(bool(allow_proactive_replies))
            require_first_user_before_proactive = session.get("require_first_user_before_proactive")
            if require_first_user_before_proactive is not None and hasattr(self, "require_first_user_checkbox"):
                self.require_first_user_checkbox.setChecked(bool(require_first_user_before_proactive))
                self.on_require_first_user_before_proactive_changed(bool(require_first_user_before_proactive))
            listen_idle_window_seconds = session.get("listen_idle_window_seconds")
            if listen_idle_window_seconds is not None and hasattr(self, "listen_idle_window_spin"):
                listen_seconds = max(0.5, float(listen_idle_window_seconds))
                self.listen_idle_window_spin.setValue(listen_seconds)
                self.on_listen_idle_window_changed(listen_seconds)
            proactive_delay_seconds = session.get("proactive_delay_seconds")
            if proactive_delay_seconds is not None and hasattr(self, "proactive_delay_spin"):
                proactive_seconds = max(0.5, float(proactive_delay_seconds))
                self.proactive_delay_spin.setValue(proactive_seconds)
                self.on_proactive_delay_changed(proactive_seconds)
            chat_context_window_messages = session.get("chat_context_window_messages")
            if chat_context_window_messages is not None and hasattr(self, "chat_context_window_spin"):
                context_messages = max(4, int(chat_context_window_messages))
                self.chat_context_window_spin.setValue(context_messages)
                self.on_chat_context_window_changed(context_messages)
            stored_chat_history_limit = session.get("stored_chat_history_limit")
            if stored_chat_history_limit is not None and hasattr(self, "stored_chat_history_limit_spin"):
                stored_limit = max(0, int(stored_chat_history_limit))
                self.stored_chat_history_limit_spin.setValue(stored_limit)
                self.on_stored_chat_history_limit_changed(stored_limit)
            chat_context_overflow_policy = session.get("chat_context_overflow_policy")
            if chat_context_overflow_policy is not None and hasattr(self, "chat_overflow_policy_combo"):
                policy_text = self._chat_overflow_policy_label_from_value(chat_context_overflow_policy)
                self.chat_overflow_policy_combo.setCurrentText(policy_text)
                self.on_chat_overflow_policy_changed(policy_text)
            spellcheck_enabled = session.get("spellcheck_enabled")
            if spellcheck_enabled is not None and hasattr(self, "spellcheck_enabled_checkbox"):
                self.spellcheck_enabled_checkbox.setChecked(bool(spellcheck_enabled))
                self.on_spellcheck_enabled_changed(bool(spellcheck_enabled))
            spellcheck_language = session.get("spellcheck_language")
            if spellcheck_language is not None and hasattr(self, "spellcheck_language_combo"):
                language = str(spellcheck_language or "en_US").strip() or "en_US"
                if self.spellcheck_language_combo.findText(language) < 0:
                    self.spellcheck_language_combo.addItem(language)
                self.spellcheck_language_combo.setCurrentText(language)
                self.on_spellcheck_language_changed(language)
            self._restore_ai_presence_session_settings(session)
            last_chat_context_path = session.get("last_chat_context_path", session.get("active_chat_context_path", ""))
            last_chat_context_name = session.get("last_chat_context_name", session.get("active_chat_context_name", ""))
            self._last_chat_context_path = str(last_chat_context_path or "").strip()
            self._last_chat_context_name = str(last_chat_context_name or "").strip()
            continuity_memory_enabled = session.get("continuity_memory_enabled", session.get("long_term_memory_enabled"))
            if continuity_memory_enabled is not None and hasattr(self, "long_term_memory_enabled_checkbox"):
                self.long_term_memory_enabled_checkbox.setChecked(bool(continuity_memory_enabled))
                self.on_continuity_memory_enabled_changed(bool(continuity_memory_enabled))
            continuity_memory_auto_summarize = session.get("continuity_memory_auto_summarize", session.get("continuity_memory_update_on_save", session.get("long_term_memory_update_on_save")))
            if continuity_memory_auto_summarize is not None and hasattr(self, "long_term_memory_update_on_save_checkbox"):
                self.long_term_memory_update_on_save_checkbox.setChecked(bool(continuity_memory_auto_summarize))
                self.on_continuity_memory_update_on_save_changed(bool(continuity_memory_auto_summarize))
            continuity_memory_auto_turns = session.get("continuity_memory_auto_turns")
            if continuity_memory_auto_turns is not None and hasattr(self, "continuity_memory_auto_turns_spin"):
                auto_turns = max(1, min(10000, int(continuity_memory_auto_turns or 120)))
                self.continuity_memory_auto_turns_spin.setValue(auto_turns)
                self.on_continuity_memory_auto_turns_changed(auto_turns)
            continuity_memory_inject = session.get("continuity_memory_inject", session.get("long_term_memory_inject"))
            if continuity_memory_inject is not None and hasattr(self, "long_term_memory_inject_checkbox"):
                self.long_term_memory_inject_checkbox.setChecked(bool(continuity_memory_inject))
                self.on_continuity_memory_inject_changed(bool(continuity_memory_inject))
            continuity_memory_max_chars = session.get("continuity_memory_max_chars", session.get("long_term_memory_max_chars"))
            if continuity_memory_max_chars is not None and hasattr(self, "long_term_memory_max_chars_spin"):
                memory_chars = max(500, min(20000, int(continuity_memory_max_chars)))
                self.long_term_memory_max_chars_spin.setValue(memory_chars)
                self.on_continuity_memory_max_chars_changed(memory_chars)
            retrieval_enabled = session.get("long_term_memory_retrieval_enabled")
            if retrieval_enabled is not None and hasattr(self, "long_term_memory_retrieval_enabled_checkbox"):
                self.long_term_memory_retrieval_enabled_checkbox.setChecked(bool(retrieval_enabled))
                self.on_long_term_memory_retrieval_enabled_changed(bool(retrieval_enabled))
            retrieval_max_items = session.get("long_term_memory_retrieval_max_items")
            if retrieval_max_items is not None and hasattr(self, "long_term_memory_retrieval_max_items_spin"):
                max_items = max(1, min(12, int(retrieval_max_items)))
                self.long_term_memory_retrieval_max_items_spin.setValue(max_items)
                self.on_long_term_memory_retrieval_max_items_changed(max_items)
            recall_image_limit = session.get("long_term_memory_recall_image_limit")
            if recall_image_limit is not None and hasattr(self, "long_term_memory_recall_image_limit_spin"):
                image_limit = long_term_memory.normalize_image_recall_limit(recall_image_limit, default=1)
                self.long_term_memory_recall_image_limit_spin.setValue(image_limit)
                self.on_long_term_memory_recall_image_limit_changed(image_limit)
            auto_archive_enabled = session.get("long_term_memory_auto_archive_enabled")
            if auto_archive_enabled is not None and hasattr(self, "long_term_memory_auto_archive_enabled_checkbox"):
                self.long_term_memory_auto_archive_enabled_checkbox.setChecked(bool(auto_archive_enabled))
                self.on_long_term_memory_auto_archive_enabled_changed(bool(auto_archive_enabled))
            archive_batch_turns = session.get("long_term_memory_archive_batch_turns")
            if archive_batch_turns is not None and hasattr(self, "long_term_memory_archive_batch_turns_spin"):
                batch_turns = max(1, min(10000, int(archive_batch_turns or 120)))
                self.long_term_memory_archive_batch_turns_spin.setValue(batch_turns)
                self.on_long_term_memory_archive_batch_turns_changed(batch_turns)
            embedding_enabled = session.get("long_term_memory_embedding_enabled")
            if embedding_enabled is not None and hasattr(self, "long_term_memory_embedding_enabled_checkbox"):
                self.long_term_memory_embedding_enabled_checkbox.setChecked(bool(embedding_enabled))
                self.on_long_term_memory_embedding_enabled_changed(bool(embedding_enabled))
            embedding_model = session.get("long_term_memory_embedding_model")
            if embedding_model is not None and hasattr(self, "long_term_memory_embedding_model_edit"):
                widget = self.long_term_memory_embedding_model_edit
                if hasattr(widget, "setCurrentText"):
                    widget.setCurrentText(str(embedding_model or "text-embedding-bge-m3"))
                elif hasattr(widget, "setText"):
                    widget.setText(str(embedding_model or "text-embedding-bge-m3"))
                self.on_long_term_memory_embedding_model_changed()
            embedding_context_length = session.get("long_term_memory_embedding_context_length")
            if embedding_context_length is not None and hasattr(self, "long_term_memory_embedding_context_length_spin"):
                context_length = max(512, min(262144, int(embedding_context_length or 8192)))
                self.long_term_memory_embedding_context_length_spin.setValue(context_length)
                self.on_long_term_memory_embedding_context_length_changed(context_length)
            embedding_base_url = session.get("long_term_memory_embedding_base_url")
            if embedding_base_url is not None and hasattr(self, "long_term_memory_embedding_base_url_edit"):
                self.long_term_memory_embedding_base_url_edit.setText(str(embedding_base_url or "http://127.0.0.1:1234/v1"))
                self.on_long_term_memory_embedding_base_url_changed()
            refresh_chat_context_save_controls = getattr(self, "_refresh_chat_context_save_controls", None)
            if callable(refresh_chat_context_save_controls):
                refresh_chat_context_save_controls()
            limit_response_length = session.get("limit_response_length")
            if limit_response_length is not None:
                self.limit_response_checkbox.setChecked(bool(limit_response_length))
                self.on_limit_response_length_changed(bool(limit_response_length))
            max_response_tokens = session.get("max_response_tokens")
            if max_response_tokens is not None:
                tokens = max(32, int(max_response_tokens))
                self.max_response_tokens_spin.setValue(tokens)
                self.on_max_response_tokens_changed(tokens)
            self.refresh_performance_profile_list()
            performance_profile = session.get("performance_profile")
            if performance_profile and hasattr(self, "performance_profile_combo"):
                for index in range(self.performance_profile_combo.count()):
                    if self.performance_profile_combo.itemData(index) == performance_profile:
                        self.performance_profile_combo.setCurrentIndex(index)
                        break
            sensory_feedback_source = session.get("sensory_feedback_source")
            if sensory_feedback_source is not None and hasattr(self, "sensory_feedback_source_combo"):
                source_value = str(sensory_feedback_source or "off")
                if "companion_orb_sensory_target_enabled" in session:
                    source_value = ",".join(
                        normalize_companion_orb_target_source_selection(
                            source_value,
                            bool(session.get("companion_orb_sensory_target_enabled")),
                        )
                    ) or "off"
                self.refresh_sensory_feedback_source_options(selected_value=source_value)
                self.on_sensory_feedback_source_changed(source_value)
            sensory_feedback_interval_seconds = session.get("sensory_feedback_interval_seconds")
            if sensory_feedback_interval_seconds is not None and hasattr(self, "sensory_feedback_interval_spin"):
                interval_seconds = max(2.0, float(sensory_feedback_interval_seconds))
                self.sensory_feedback_interval_spin.setValue(interval_seconds)
                self.on_sensory_feedback_interval_changed(interval_seconds)
            sensory_pingpong_enabled = session.get("sensory_pingpong_enabled")
            if sensory_pingpong_enabled is not None and hasattr(self, "sensory_pingpong_checkbox"):
                pingpong_enabled = bool(sensory_pingpong_enabled)
                self.sensory_pingpong_checkbox.setChecked(pingpong_enabled)
                self.on_sensory_pingpong_enabled_changed(pingpong_enabled)
            sensory_allow_hidden_proactive_speech = session.get("sensory_allow_hidden_proactive_speech")
            if sensory_allow_hidden_proactive_speech is not None and hasattr(self, "sensory_allow_hidden_proactive_checkbox"):
                proactive_enabled = bool(sensory_allow_hidden_proactive_speech)
                self.sensory_allow_hidden_proactive_checkbox.setChecked(proactive_enabled)
                self.on_sensory_allow_hidden_proactive_changed(proactive_enabled)
            sensory_allow_hidden_visual_generation = session.get("sensory_allow_hidden_visual_generation")
            if sensory_allow_hidden_visual_generation is not None and hasattr(self, "sensory_allow_hidden_visual_checkbox"):
                visual_enabled = bool(sensory_allow_hidden_visual_generation)
                self.sensory_allow_hidden_visual_checkbox.setChecked(visual_enabled)
                self.on_sensory_allow_hidden_visual_changed(visual_enabled)
            screen_source_auto_attach_next_user_turn = session.get("screen_source_auto_attach_next_user_turn")
            if screen_source_auto_attach_next_user_turn is not None:
                screen_auto_attach_enabled = bool(screen_source_auto_attach_next_user_turn)
                update_runtime_config("screen_source_auto_attach_next_user_turn", screen_auto_attach_enabled)
            companion_orb_sensory_target_enabled = session.get("companion_orb_sensory_target_enabled")
            if companion_orb_sensory_target_enabled is not None:
                orb_target_enabled = bool(companion_orb_sensory_target_enabled)
                update_runtime_config("companion_orb_sensory_target_enabled", orb_target_enabled)
                if hasattr(self, "companion_orb_sensory_target_checkbox"):
                    try:
                        self.companion_orb_sensory_target_checkbox.blockSignals(True)
                        self.companion_orb_sensory_target_checkbox.setChecked(orb_target_enabled)
                    finally:
                        self.companion_orb_sensory_target_checkbox.blockSignals(False)
                if hasattr(self, "_sync_companion_orb_sensory_target_controls"):
                    self._sync_companion_orb_sensory_target_controls()
            if "companion_orb_full_screen_context_enabled" in session:
                update_runtime_config("companion_orb_full_screen_context_enabled", bool(session.get("companion_orb_full_screen_context_enabled")))
            if "companion_orb_include_process_name" in session:
                update_runtime_config("companion_orb_include_process_name", bool(session.get("companion_orb_include_process_name", True)))
            companion_orb_target_info = session.get("companion_orb_target_info")
            if isinstance(companion_orb_target_info, dict):
                update_runtime_config("companion_orb_target_info", dict(companion_orb_target_info))
            sensory_pingpong_history_depth = session.get("sensory_pingpong_history_depth")
            if sensory_pingpong_history_depth is not None and hasattr(self, "sensory_pingpong_history_spin"):
                pingpong_depth = max(0, int(sensory_pingpong_history_depth))
                self.sensory_pingpong_history_spin.setValue(pingpong_depth)
                self.on_sensory_pingpong_history_depth_changed(pingpong_depth)
            sensory_pingpong_prompt = session.get("sensory_pingpong_prompt")
            if sensory_pingpong_prompt is not None and hasattr(self, "sensory_pingpong_prompt_text"):
                prompt_text = str(sensory_pingpong_prompt or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")).strip() or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")
                self.sensory_pingpong_prompt_text.setPlainText(prompt_text)
                update_runtime_config("sensory_pingpong_prompt", prompt_text)
            sensory_pingpong_source_prompts = session.get("sensory_pingpong_source_prompts")
            if sensory_pingpong_source_prompts is not None:
                prompt_map = self._normalize_sensory_pingpong_source_prompt_map(sensory_pingpong_source_prompts) if hasattr(self, "_normalize_sensory_pingpong_source_prompt_map") else dict(sensory_pingpong_source_prompts or {})
                update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
                self._refresh_sensory_feedback_source_tabs()
            sensory_provider_metadata_overrides = session.get("sensory_provider_metadata_overrides")
            if sensory_provider_metadata_overrides is not None:
                metadata_map = self._normalize_sensory_provider_metadata_override_map(sensory_provider_metadata_overrides) if hasattr(self, "_normalize_sensory_provider_metadata_override_map") else dict(sensory_provider_metadata_overrides or {})
                update_runtime_config("sensory_provider_metadata_overrides", metadata_map)
                self._refresh_sensory_feedback_source_tabs()
            emotional_instructions = session.get("emotional_instructions")
            if emotional_instructions is not None and hasattr(self, "emotional_text"):
                self.emotional_text.setPlainText(str(emotional_instructions or ""))
                update_runtime_config("emotional_instructions", self.emotional_text.toPlainText().strip())
            system_prompt = session.get("system_prompt")
            if system_prompt is not None and hasattr(self, "system_prompt_text"):
                self.system_prompt_text.setPlainText(str(system_prompt or ""))
                update_runtime_config("system_prompt", self.system_prompt_text.toPlainText().strip())
            for key in ("temperature", "top_p", "top_k", "repeat_penalty", "min_p"):
                if key in session and key in getattr(self, "brain_sliders", {}):
                    self.brain_sliders[key].set_value(session[key])
                    self.update_brain_value(key, session[key], key == "top_k")
            chunking = session.get("chunking")
            if isinstance(chunking, dict):
                for key, value in chunking.items():
                    if key in self.chunking_sliders:
                        self.chunking_sliders[key].set_value(value)
                        update_runtime_config(key, value)
            dry_run_target = session.get("dry_run_target_samples")
            if dry_run_target is not None:
                self.dry_run_target_spin.setValue(max(0, min(12, int(dry_run_target))))
            dry_run_auto_replies = session.get("dry_run_auto_replies")
            if dry_run_auto_replies is not None:
                self.dry_run_auto_replies_checkbox.setChecked(bool(dry_run_auto_replies))
            body = session.get("last_body")
            body_combo = self._live_widget_attr("body_combo")
            if body and body_combo is not None:
                index = body_combo.findText(body)
                if index >= 0:
                    body_combo.setCurrentIndex(index)
                    self.load_body_config_from_combo()
            if self._addon_manager is not None:
                self._addon_manager.import_session_state(session)
                self._refresh_addon_group_tabs()
            live_sync_checkbox = self._live_widget_attr("live_sync_checkbox")
            if live_sync_checkbox is not None:
                live_sync_checkbox.setChecked(bool(session.get("live_sync", False)))
            splitter_sizes = session.get("main_splitter_sizes")
            if isinstance(splitter_sizes, list) and len(splitter_sizes) == 2 and hasattr(self, "main_splitter"):
                try:
                    self.main_splitter.setSizes([max(220, int(splitter_sizes[0])), max(320, int(splitter_sizes[1]))])
                except Exception:
                    pass
            window_state = session.get("window_state")
            if window_state:
                try:
                    self.restoreState(QtCore.QByteArray.fromBase64(window_state.encode("ascii")))
                except Exception:
                    pass
            right_dock_state = session.get("right_dock_state")
            if right_dock_state and hasattr(self, "right_dock_host"):
                try:
                    self.right_dock_host.restoreState(QtCore.QByteArray.fromBase64(right_dock_state.encode("ascii")))
                except Exception:
                    pass
            self._pinned_floating_dock_names = {
                str(item or "").strip()
                for item in list(session.get("pinned_floating_docks", []) or [])
                if str(item or "").strip()
            }
            self._always_on_top_floating_dock_names = {
                str(item or "").strip()
                for item in list(session.get("always_on_top_floating_docks", []) or [])
                if str(item or "").strip()
            }
            self._apply_legacy_dock_title_widgets()
            suppress_aux_docks = bool(getattr(self, "_suppress_restored_aux_docks", False))
            preview_dock = getattr(self, "preview_dock", None)
            if preview_dock is not None:
                if bool(session.get("preview_visible", False)) and not suppress_aux_docks:
                    preview_dock.show()
                else:
                    preview_dock.hide()
            self._restore_addon_session_surface_visibility(session, suppress_aux_docks=suppress_aux_docks)
            performance_guidance_visible = bool(session.get("performance_guidance_visible", False))
            if hasattr(self, "performance_guidance_toggle"):
                self.performance_guidance_toggle.setChecked(performance_guidance_visible)
                self._toggle_performance_guidance(performance_guidance_visible)
            self._refresh_hotkey_shortcuts()
            self._refresh_hotkey_labels()
            self._apply_disabled_addon_surfaces()
            self._update_restart_sensitive_controls()
            self.refresh_dry_run_status()
            QtCore.QTimer.singleShot(0, self._ensure_window_on_screen)
            self._apply_persisted_tab_orders()
            self._apply_persisted_hidden_tabs()
        finally:
            self._suspend_session_save = previous_suspend
            self._restoring_session = False
        self.save_session()
        QtCore.QTimer.singleShot(700, self._finalize_session_restore_dirty_state)
