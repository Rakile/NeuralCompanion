"""Native Qt Quick window controller for AI Presence Mode.

The production desktop process is a ``QGuiApplication``. Presence windows are
therefore native ``QQuickView`` instances with no widget compatibility path.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable

import shiboken6
from PySide6 import QtCore, QtGui, QtQuick

from . import runtime as presence_runtime
from .external_runtime_client import ExternalAIPresenceRuntimeClient
from .visual_presence_bridge import VisualPresenceBridge
from .windows_floating_drag import WindowsFloatingDrag


VALID_DISPLAY_MODES = {"off", "fullscreen", "floating", "both"}
FLOATING_STYLE_CYCLE = [
    "classic_neural_orb",
    "breathing_orb",
    "neural_network_pulse",
    "living_voice_thread",
    "silk_drift",
    "blue_flame_smoke",
    "vector_voice_orb",
    "circular_audio_waveform",
    "halo_rings",
    "minimal_dot",
    "hologram_core",
    "signal_bloom",
    "crystal_prism",
]

_LIVE_SETTING_RANGES = {
    "ai_presence_overlay_opacity": (0.10, 1.0, float),
    "ai_presence_fullscreen_opacity": (0.0, 1.0, float),
    "ai_presence_floating_window_opacity": (0.0, 1.0, float),
    "ai_presence_thinking_pulse": (0.10, 1.0, float),
    "ai_presence_speaking_reactivity": (0.10, 1.5, float),
    "ai_presence_voice_thread_peak_emphasis": (0.0, 4.0, float),
    "ai_presence_voice_thread_glow_radius": (0.25, 4.0, float),
    "ai_presence_voice_thread_reflection_distance": (0.0, 4.0, float),
    "ai_presence_voice_thread_audio_reactivity": (0.0, 4.0, float),
    "ai_presence_voice_thread_motion_scale": (0.0, 4.0, float),
    "ai_presence_voice_thread_idle_motion": (0.0, 3.0, float),
    "ai_presence_voice_thread_animation_speed": (0.25, 3.0, float),
    "ai_presence_voice_thread_response_smoothing": (0.0, 2.0, float),
    "ai_presence_voice_thread_spectrum_smoothing": (0.0, 2.0, float),
    "ai_presence_voice_thread_spectrum_scale": (0.0, 4.0, float),
    "ai_presence_voice_thread_glow_intensity": (0.0, 4.0, float),
    "ai_presence_voice_thread_flux_strength": (0.0, 4.0, float),
    "ai_presence_voice_thread_fiber_spread": (0.25, 4.0, float),
    "ai_presence_voice_thread_bendiness": (0.0, 4.0, float),
    "ai_presence_voice_thread_organic_variation": (0.0, 4.0, float),
    "ai_presence_voice_thread_phrase_motion": (0.0, 4.0, float),
    "ai_presence_voice_thread_gesture_intensity": (0.0, 4.0, float),
    "ai_presence_voice_thread_motion_memory": (0.0, 2.0, float),
    "ai_presence_voice_thread_accent_sensitivity": (0.0, 4.0, float),
    "ai_presence_music_reactivity": (0.0, 4.0, float),
    "ai_presence_voice_thread_ambient_smoothing": (0.0, 2.0, float),
    "ai_presence_voice_thread_ambient_noise_gate": (0.0, 0.25, float),
    "ai_presence_voice_thread_ambient_quiet_detail": (0.0, 2.5, float),
    "ai_presence_voice_thread_ambient_transient_punch": (0.0, 3.0, float),
    "ai_presence_voice_thread_ambient_attack_ms": (5, 250, int),
    "ai_presence_voice_thread_ambient_release_ms": (40, 700, int),
    "ai_presence_voice_thread_ambient_mix": (0.0, 2.0, float),
    "ai_presence_voice_thread_ambient_shape_strength": (0.0, 3.0, float),
    "ai_presence_voice_thread_ambient_travel_strength": (0.0, 3.0, float),
    "ai_presence_voice_thread_ambient_glow_strength": (0.0, 3.0, float),
    "ai_presence_voice_thread_ambient_fiber_strength": (0.0, 3.0, float),
    "ai_presence_voice_thread_ambient_color_strength": (0.0, 3.0, float),
    "ai_presence_voice_thread_color_vividness": (0.0, 4.0, float),
    "ai_presence_voice_thread_color_bass_influence": (0.0, 4.0, float),
    "ai_presence_voice_thread_color_mid_influence": (0.0, 4.0, float),
    "ai_presence_voice_thread_color_high_influence": (0.0, 4.0, float),
    "ai_presence_voice_thread_color_smoothing": (0.0, 2.0, float),
    "ai_presence_voice_thread_ambient_motion_ceiling": (0.25, 3.0, float),
    "ai_presence_voice_thread_ambient_bass_bend": (0.0, 4.0, float),
    "ai_presence_voice_thread_ambient_mid_ripple": (0.0, 4.0, float),
    "ai_presence_voice_thread_ambient_high_shimmer": (0.0, 4.0, float),
    "ai_presence_voice_thread_physics_slack": (0.0, 4.0, float),
    "ai_presence_voice_thread_interaction_area": (1.2, 5.0, float),
    "ai_presence_voice_thread_gravity": (0.2, 4.0, float),
    "ai_presence_voice_thread_retension_time": (0.2, 2.0, float),
    "ai_presence_voice_thread_size": (0.25, 6.0, float),
    "ai_presence_voice_thread_horizontal_span": (1.0, 4.0, float),
    "ai_presence_voice_thread_position_x": (0.0, 1.0, float),
    "ai_presence_voice_thread_position_y": (0.0, 1.0, float),
    "ai_presence_voice_thread_strand_multiplier": (1, 5, int),
    "ai_presence_voice_thread_frame_rate": (15, 120, int),
    "ai_presence_glow_strength": (0.0, 1.75, float),
    "ai_presence_animation_speed": (0.35, 1.75, float),
    "ai_presence_idle_motion_strength": (0.0, 1.0, float),
    "ai_presence_mood_color_intensity": (0.0, 1.0, float),
    "ai_presence_primary_color_strength": (0.0, 1.5, float),
    "ai_presence_secondary_color_strength": (0.0, 1.5, float),
    "ai_presence_background_darkness": (0.0, 1.0, float),
    "ai_presence_particle_density": (0, 120, int),
    "ai_presence_node_density": (8, 96, int),
    "ai_presence_halo_thickness": (0.35, 2.0, float),
    "ai_presence_waveform_strength": (0.2, 2.0, float),
    "ai_presence_ring_expansion_speed": (0.25, 2.0, float),
    "ai_presence_blur_softness": (0.0, 1.0, float),
    "ai_presence_line_brightness": (0.2, 2.0, float),
}

_LIVE_BOOLEAN_SETTINGS = {
    "ai_presence_reduced_effects",
    "ai_presence_particles_enabled",
    "ai_presence_shaders_enabled",
    "ai_presence_voice_thread_mouse_physics_enabled",
    "ai_presence_voice_thread_show_placement_guide",
    "ai_presence_voice_thread_reflection_enabled",
    "ai_presence_voice_thread_ambient_link_main_controls",
    "ai_presence_voice_thread_ambient_fiber_spread_enabled",
    "ai_presence_voice_thread_audio_colors_enabled",
    "ai_presence_voice_thread_voice_colors_enabled",
    "ai_presence_voice_thread_desktop_colors_enabled",
}

_LIVE_CHOICE_SETTINGS = {
    "ai_presence_voice_thread_physics_feel": {"natural", "silk", "cable"},
}


def _normalize_display_mode(value: Any) -> str:
    mode = str(value or "fullscreen").strip().lower()
    return mode if mode in VALID_DISPLAY_MODES else "fullscreen"


def _next_visual_style(current: Any) -> str:
    style = str(current or "").strip().lower()
    if style not in FLOATING_STYLE_CYCLE:
        return FLOATING_STYLE_CYCLE[0]
    return FLOATING_STYLE_CYCLE[(FLOATING_STYLE_CYCLE.index(style) + 1) % len(FLOATING_STYLE_CYCLE)]


def _no_shadow_window_hint() -> QtCore.Qt.WindowType:
    return getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))


def _transparent_for_input_hint() -> QtCore.Qt.WindowType:
    return getattr(QtCore.Qt, "WindowTransparentForInput", QtCore.Qt.WindowType(0))


class _PresenceCommandProxy(QtCore.QObject):
    state_requested = QtCore.Signal(str)
    level_requested = QtCore.Signal(float)
    music_level_requested = QtCore.Signal(float)
    music_spectrum_requested = QtCore.Signal(object)
    voice_analysis_requested = QtCore.Signal(object, float, float)
    user_voice_analysis_requested = QtCore.Signal(
        object, float, float, float, float, bool
    )
    mood_requested = QtCore.Signal(str)
    settings_requested = QtCore.Signal(dict)
    reset_floating_requested = QtCore.Signal()


class VisualPresenceController(QtCore.QObject):
    """Own the two native Qt Quick presence windows and their runtime bridge."""

    def __init__(
        self,
        main_window: QtGui.QWindow | None,
        runtime_config: dict[str, Any] | None = None,
        *,
        config_update: Callable[[str, Any], object] | None = None,
        config_subscribe: Callable[[Callable[..., None]], object] | None = None,
        persist: Callable[[], object] | None = None,
    ) -> None:
        parent = main_window if isinstance(main_window, QtCore.QObject) else None
        super().__init__(parent)
        self.main_window = main_window
        if main_window is not None:
            main_window.destroyed.connect(self._on_main_window_destroyed)
        self.bridge = VisualPresenceBridge(self)
        self.available = False
        self.error = ""
        self._shutdown = False
        self._config_update = config_update
        self._persist = persist
        self._config_subscription = None
        self._fullscreen_window: QtQuick.QQuickView | None = None
        self._floating_window: QtQuick.QQuickView | None = None
        self._floating_drag_offset: QtCore.QPoint | None = None
        self._floating_thread_drag_offset: QtCore.QPoint | None = None
        self._display_mode = "fullscreen"
        self._fullscreen = True
        self._fullscreen_suppressed = False
        self._last_live_controls_visible = bool(self.bridge.liveControlsVisible)
        self._right_drag = WindowsFloatingDrag(self, logger=print)
        self._floating_geometry_restored = False
        self._last_runtime_config = dict(runtime_config or {})
        self._external_runtime: ExternalAIPresenceRuntimeClient | None = None

        self._proxy = _PresenceCommandProxy(self)
        queued = QtCore.Qt.ConnectionType.QueuedConnection
        self._proxy.state_requested.connect(self._set_ai_state, queued)
        self._proxy.level_requested.connect(self._set_audio_level, queued)
        self._proxy.music_level_requested.connect(self._set_music_level, queued)
        self._proxy.music_spectrum_requested.connect(self._set_music_spectrum, queued)
        self._proxy.voice_analysis_requested.connect(self._set_voice_analysis, queued)
        self._proxy.user_voice_analysis_requested.connect(
            self._set_user_voice_analysis,
            queued,
        )
        self._proxy.mood_requested.connect(self._set_presence_mood, queued)
        self._proxy.settings_requested.connect(self.apply_runtime_config, queued)
        self._proxy.reset_floating_requested.connect(self.reset_floating_position, queued)
        self.bridge.live_setting_requested.connect(self._apply_live_setting, queued)
        self.bridge.floating_thread_drag_started.connect(
            self._begin_floating_thread_drag
        )
        self.bridge.floating_thread_drag_finished.connect(
            self._end_floating_thread_drag
        )

        self._geometry_timer = QtCore.QTimer(self)
        self._geometry_timer.setInterval(350)
        self._geometry_timer.timeout.connect(self._sync_geometry)
        self._floating_save_timer = QtCore.QTimer(self)
        self._floating_save_timer.setSingleShot(True)
        self._floating_save_timer.setInterval(350)
        self._floating_save_timer.timeout.connect(self._save_floating_geometry)
        self._live_settings_save_timer = QtCore.QTimer(self)
        self._live_settings_save_timer.setSingleShot(True)
        self._live_settings_save_timer.setInterval(850)
        self._live_settings_save_timer.timeout.connect(self._save_live_settings_session)

        self._right_drag.drag_finished.connect(self._schedule_save_floating_geometry, queued)
        self.bridge.settings_changed.connect(self._refresh_live_controls_input, queued)
        self._install_key_filter()
        self._create_fullscreen_window()
        self._create_floating_window()
        self.apply_runtime_config(dict(runtime_config or {}))
        if callable(config_subscribe):
            self._config_subscription = config_subscribe(self._on_runtime_config_changed)

    def _on_runtime_config_changed(self, event: object) -> None:
        if self._shutdown:
            return
        snapshot = getattr(event, "snapshot", None)
        values = getattr(snapshot, "values", None)
        if values is not None:
            # Config subscribers run on the caller's thread, including addon
            # jobs holding their own locks. Never touch native windows there.
            if QtCore.QThread.currentThread() == self.thread():
                self.apply_runtime_config(dict(values))
            else:
                self._proxy.settings_requested.emit(dict(values))

    @QtCore.Slot()
    def _on_main_window_destroyed(self) -> None:
        # The QML root can be destroyed before QGuiApplication.aboutToQuit.
        # Drop the wrapper first so no queued geometry update touches a dead
        # QQuickWindow, then release the config subscription and timers.
        self.main_window = None
        self.shutdown()

    def _update_runtime_config(self, key: str, value: Any) -> object | None:
        if not callable(self._config_update):
            return None
        try:
            return self._config_update(str(key), value)
        except Exception:
            return None

    def _install_key_filter(self) -> None:
        app = QtGui.QGuiApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        try:
            event_type = event.type()
            if self._fullscreen_overlay_visible():
                if event_type == QtCore.QEvent.Type.KeyPress:
                    if event.key() == QtCore.Qt.Key.Key_Escape:
                        self.hide_fullscreen_temporarily()
                        event.accept()
                        return True
                    if bool(self.bridge.spaceClosesFullscreen) and event.key() == QtCore.Qt.Key.Key_Space:
                        self.hide_fullscreen_temporarily()
                        event.accept()
                        return True
            if event_type == QtCore.QEvent.Type.KeyPress and self._presence_window_visible() and not self._focus_is_text_input():
                if self._live_controls_shortcut_pressed(event):
                    self.bridge.toggleLiveControls()
                    event.accept()
                    return True
                if event.key() == QtCore.Qt.Key.Key_Escape and bool(self.bridge.liveControlsVisible):
                    self.bridge.setLiveControlsVisible(False)
                    event.accept()
                    return True
            if watched is self._floating_window:
                if event_type == QtCore.QEvent.Type.Hide:
                    self._right_drag.configure(0, False)
                elif event_type == QtCore.QEvent.Type.Show:
                    self._sync_right_drag()
                if event_type in {QtCore.QEvent.Type.Move, QtCore.QEvent.Type.Resize}:
                    self._schedule_save_floating_geometry()
                if event_type == QtCore.QEvent.Type.MouseButtonDblClick and event.button() == QtCore.Qt.MouseButton.RightButton:
                    self._cycle_floating_visual_style()
                    event.accept()
                    return True
                drag_button = (
                    QtCore.Qt.MouseButton.RightButton
                    if (
                        bool(self.bridge.rightDragMoveEnabled)
                        or self._voice_thread_mouse_physics_active()
                    )
                    else QtCore.Qt.MouseButton.LeftButton
                )
                if event_type == QtCore.QEvent.Type.MouseButtonPress and event.button() == drag_button:
                    self._floating_drag_offset = self._event_global_pos(event) - self._floating_window.position()
                    event.accept()
                    return True
                if (
                    event_type == QtCore.QEvent.Type.MouseMove
                    and self._floating_thread_drag_offset is not None
                ):
                    self._floating_window.setPosition(
                        self._event_global_pos(event)
                        - self._floating_thread_drag_offset
                    )
                    event.accept()
                    return True
                if event_type == QtCore.QEvent.Type.MouseMove and self._floating_drag_offset is not None:
                    self._floating_window.setPosition(self._event_global_pos(event) - self._floating_drag_offset)
                    event.accept()
                    return True
                if event_type == QtCore.QEvent.Type.MouseButtonRelease:
                    self._floating_drag_offset = None
                    if (
                        event.button() == QtCore.Qt.MouseButton.LeftButton
                        and self._floating_thread_drag_offset is not None
                    ):
                        self._end_floating_thread_drag()
        except Exception:
            pass
        return super().eventFilter(watched, event)

    @staticmethod
    def _event_global_pos(event: QtCore.QEvent) -> QtCore.QPoint:
        try:
            return event.globalPosition().toPoint()
        except Exception:
            return QtCore.QPoint()

    def _fullscreen_overlay_visible(self) -> bool:
        return bool(self._fullscreen_window is not None and self._fullscreen_window.isVisible())

    def _voice_thread_mouse_physics_active(self) -> bool:
        return bool(self.bridge.voiceThreadMousePhysicsEnabled) and (
            str(self.bridge.visualStyle or "").strip().lower()
            in {"living_voice_thread", "silk_drift"}
        )

    @QtCore.Slot(float, float)
    def _begin_floating_thread_drag(
        self,
        offset_x: float,
        offset_y: float,
    ) -> None:
        if self._floating_window is None:
            return
        self._floating_thread_drag_offset = QtCore.QPoint(
            round(float(offset_x)),
            round(float(offset_y)),
        )

    @QtCore.Slot()
    def _end_floating_thread_drag(self) -> None:
        if self._floating_thread_drag_offset is None:
            return
        self._floating_thread_drag_offset = None
        self._schedule_save_floating_geometry()

    def _presence_window_visible(self) -> bool:
        return any(window is not None and window.isVisible() for window in (self._fullscreen_window, self._floating_window))

    @staticmethod
    def _focus_is_text_input() -> bool:
        focus = QtGui.QGuiApplication.focusObject()
        return VisualPresenceController._focus_object_is_text_input(focus)

    @staticmethod
    def _focus_object_is_text_input(focus: object) -> bool:
        """Recognize editable Qt/QML controls, including wrapped NC fields."""

        current = focus
        for _depth in range(8):
            if current is None:
                return False
            try:
                class_name = str(current.metaObject().className() or "").lower()
            except Exception:
                class_name = type(current).__name__.lower()
            if any(
                token in class_name
                for token in (
                    "textinput",
                    "textarea",
                    "textfield",
                    "lineedit",
                    "textedit",
                    "plaintextedit",
                    "spinbox",
                    "combobox",
                    "searchfield",
                )
            ):
                return True
            try:
                current = current.parent()
            except Exception:
                return False
        return False

    @staticmethod
    def _live_controls_shortcut_pressed(event: QtCore.QEvent) -> bool:
        """Reserve a non-typing chord instead of consuming a bare letter."""

        if event.key() != QtCore.Qt.Key.Key_H:
            return False
        required = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.ShiftModifier
        )
        return event.modifiers() == required

    def _window_flags(self, *, floating: bool) -> QtCore.Qt.WindowType:
        flags = QtCore.Qt.WindowType.Tool | QtCore.Qt.WindowType.FramelessWindowHint | _no_shadow_window_hint()
        if floating:
            flags |= QtCore.Qt.WindowType.Window
            if bool(self.bridge.floatingAlwaysOnTop):
                flags |= QtCore.Qt.WindowType.WindowStaysOnTopHint
        else:
            # Fullscreen is a desktop overlay: never intercept clicks, even
            # when the independent floating-window click-through option is off.
            flags |= (
                QtCore.Qt.WindowType.WindowStaysOnTopHint
                | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
                | _transparent_for_input_hint()
            )
        return flags

    def _create_qml_window(self, *, floating: bool) -> QtQuick.QQuickView:
        window = QtQuick.QQuickView()
        window.setObjectName("ai_presence_floating_window" if floating else "ai_presence_overlay_window")
        window.setTitle("AI Presence Mode")
        window.setFlags(self._window_flags(floating=floating))
        window.setResizeMode(QtQuick.QQuickView.ResizeMode.SizeRootObjectToView)
        surface_format = window.format()
        surface_format.setAlphaBufferSize(8)
        window.setFormat(surface_format)
        window.setColor(QtGui.QColor(0, 0, 0, 0))
        if floating:
            window.setMinimumSize(QtCore.QSize(220, 180))
            window.resize(QtCore.QSize(420, 360))
        window.rootContext().setContextProperty("presenceBridge", self.bridge)
        window.rootContext().setContextProperty(
            "presenceWindowRole",
            "floating" if floating else "fullscreen",
        )
        window.setSource(QtCore.QUrl.fromLocalFile(str(Path(__file__).with_name("visual_overlay.qml"))))
        if window.status() == QtQuick.QQuickView.Status.Error:
            errors = "; ".join(str(error.toString()) for error in window.errors())
            window.deleteLater()
            raise RuntimeError(errors or "AI Presence QML load failed")
        window.installEventFilter(self)
        window.hide()
        return window

    def _create_fullscreen_window(self) -> None:
        try:
            self._fullscreen_window = self._create_qml_window(floating=False)
            self.available = True
            self._sync_geometry()
            print("[AI Presence] Native Qt Quick fullscreen overlay ready.")
        except Exception as exc:
            self.error = str(exc)
            self._fullscreen_window = None
            print(f"[AI Presence] Fullscreen overlay unavailable: {exc}")

    def _create_floating_window(self) -> None:
        try:
            self._floating_window = self._create_qml_window(floating=True)
            self.available = True
            self._restore_floating_geometry()
            print("[AI Presence] Native Qt Quick floating window ready.")
        except Exception as exc:
            self.error = str(exc)
            self._floating_window = None
            print(f"[AI Presence] Floating window unavailable: {exc}")

    def request_ai_state(self, state: Any) -> None:
        if not self._shutdown:
            self._proxy.state_requested.emit(str(state or "idle"))

    def request_audio_level(self, level: Any) -> None:
        if self._shutdown:
            return
        try:
            value = float(level)
        except Exception:
            value = 0.0
        self._proxy.level_requested.emit(value)

    def request_music_level(self, level: Any) -> None:
        if self._shutdown:
            return
        try:
            value = float(level)
        except Exception:
            value = 0.0
        self._proxy.music_level_requested.emit(value)

    def request_music_spectrum(self, values: Any) -> None:
        if not self._shutdown:
            self._proxy.music_spectrum_requested.emit(list(values or ()))

    def request_voice_analysis(
        self,
        values: Any,
        flux: Any = 0.0,
        centroid: Any = 0.0,
    ) -> None:
        if self._shutdown:
            return
        try:
            normalized_flux = float(flux)
        except Exception:
            normalized_flux = 0.0
        try:
            normalized_centroid = float(centroid)
        except Exception:
            normalized_centroid = 0.0
        self._proxy.voice_analysis_requested.emit(
            list(values or ()),
            normalized_flux,
            normalized_centroid,
        )

    def request_user_voice_analysis(
        self,
        values: Any,
        level: Any = 0.0,
        peak: Any = 0.0,
        flux: Any = 0.0,
        centroid: Any = 0.0,
        active: Any = False,
    ) -> None:
        if self._shutdown:
            return
        numbers = []
        for candidate in (level, peak, flux, centroid):
            try:
                numbers.append(float(candidate))
            except Exception:
                numbers.append(0.0)
        self._proxy.user_voice_analysis_requested.emit(
            list(values or ()),
            numbers[0],
            numbers[1],
            numbers[2],
            numbers[3],
            bool(active),
        )

    def request_presence_mood(self, mood: Any) -> None:
        if not self._shutdown:
            self._proxy.mood_requested.emit(str(mood or "neutral"))

    def request_settings(self, settings: dict[str, Any] | None) -> None:
        if not self._shutdown:
            self._proxy.settings_requested.emit(dict(settings or {}))

    def request_reset_floating_position(self) -> None:
        if not self._shutdown:
            self._proxy.reset_floating_requested.emit()

    def _external_runtime_enabled(self) -> bool:
        if not bool(self._last_runtime_config.get("ai_presence_external_runtime_enabled", False)):
            return False
        if not bool(self._last_runtime_config.get("ai_presence_enabled", False)):
            return False
        mode = str(self._last_runtime_config.get("ai_presence_display_mode", "off") or "off").strip().lower()
        return mode != "off"

    def _ensure_external_runtime(self) -> bool:
        if self._external_runtime is None:
            self._external_runtime = ExternalAIPresenceRuntimeClient(self._app_root(), logger=self._log_external_runtime)
        return self._external_runtime.start()

    def _stop_external_runtime(self) -> None:
        runtime = self._external_runtime
        self._external_runtime = None
        if runtime is not None:
            runtime.stop()

    def _send_external_runtime(self, payload: dict[str, Any]) -> bool:
        if not self._external_runtime_enabled() or not self._ensure_external_runtime():
            return False
        return bool(self._external_runtime is not None and self._external_runtime.send(dict(payload or {})))

    def _send_external_runtime_snapshot(self) -> None:
        if not self._external_runtime_enabled():
            return
        self._send_external_runtime({"type": "settings", "settings": dict(self._last_runtime_config)})
        self._send_external_runtime({"type": "state", "state": str(self.bridge.aiState or "idle")})
        self._send_external_runtime({"type": "audio_level", "level": float(self.bridge.audioLevel or 0.0)})
        self._send_external_runtime({"type": "music_level", "level": float(self.bridge.musicLevel or 0.0)})
        self._send_external_runtime({"type": "music_spectrum", "bands": list(self.bridge.musicSpectrum or ())})
        self._send_external_runtime(
            {
                "type": "voice_analysis",
                "bands": list(self.bridge.voiceSpectrum or ()),
                "flux": float(self.bridge.spectralFlux or 0.0),
                "centroid": float(self.bridge.spectralCentroid or 0.0),
            }
        )
        self._send_external_runtime(
            {
                "type": "user_voice_analysis",
                "bands": list(self.bridge.userVoiceSpectrum or ()),
                "level": float(self.bridge.userVoiceLevel or 0.0),
                "peak": float(self.bridge.userVoicePeak or 0.0),
                "flux": float(self.bridge.userSpectralFlux or 0.0),
                "centroid": float(self.bridge.userSpectralCentroid or 0.0),
                "active": bool(self.bridge.userVoiceActive),
            }
        )
        self._send_external_runtime({"type": "mood", "mood": str(self.bridge.moodName or "neutral")})

    def _hide_local_windows_for_external(self) -> None:
        self._right_drag.configure(0, False)
        for window in (self._fullscreen_window, self._floating_window):
            if window is not None:
                window.hide()
        self._geometry_timer.stop()

    @staticmethod
    def _app_root() -> Path:
        return Path(__file__).resolve().parents[1]

    @staticmethod
    def _log_external_runtime(message: str) -> None:
        print(f"[AI Presence] {message}")

    @QtCore.Slot(str)
    def _set_ai_state(self, state: str) -> None:
        if self._shutdown:
            return
        previous_state = str(self.bridge.aiState or "idle")
        self.bridge.setAiState(state)
        # Dismissal lasts through the current turn and idle refreshes. A new
        # AI turn can show fullscreen again, as can a new display choice.
        if previous_state in {"idle", "listening"} and self.bridge.aiState in {"thinking", "speaking"}:
            self._fullscreen_suppressed = False
        self._send_external_runtime({"type": "state", "state": str(self.bridge.aiState or "idle")})
        self._refresh_visibility()

    @QtCore.Slot(float)
    def _set_audio_level(self, level: float) -> None:
        if self._shutdown:
            return
        self.bridge.setAudioLevel(level)
        self._send_external_runtime({"type": "audio_level", "level": float(self.bridge.audioLevel or 0.0)})
        self._update_quick_windows()

    @QtCore.Slot(float)
    def _set_music_level(self, level: float) -> None:
        if self._shutdown:
            return
        self.bridge.setMusicLevel(level)
        self._send_external_runtime({"type": "music_level", "level": float(self.bridge.musicLevel or 0.0)})
        self._update_quick_windows()

    @QtCore.Slot(object)
    def _set_music_spectrum(self, values: object) -> None:
        if self._shutdown:
            return
        self.bridge.setMusicSpectrum(values)
        self._send_external_runtime(
            {"type": "music_spectrum", "bands": list(self.bridge.musicSpectrum or ())}
        )
        self._update_quick_windows()

    @QtCore.Slot(object, float, float)
    def _set_voice_analysis(
        self,
        values: object,
        flux: float,
        centroid: float,
    ) -> None:
        if self._shutdown:
            return
        self.bridge.setVoiceAnalysis(values, flux, centroid)
        self._send_external_runtime(
            {
                "type": "voice_analysis",
                "bands": list(self.bridge.voiceSpectrum or ()),
                "flux": float(self.bridge.spectralFlux or 0.0),
                "centroid": float(self.bridge.spectralCentroid or 0.0),
            }
        )
        self._update_quick_windows()

    @QtCore.Slot(object, float, float, float, float, bool)
    def _set_user_voice_analysis(
        self,
        values: object,
        level: float,
        peak: float,
        flux: float,
        centroid: float,
        active: bool,
    ) -> None:
        if self._shutdown:
            return
        self.bridge.setUserVoiceAnalysis(
            values,
            level,
            peak,
            flux,
            centroid,
            active,
        )
        self._send_external_runtime(
            {
                "type": "user_voice_analysis",
                "bands": list(self.bridge.userVoiceSpectrum or ()),
                "level": float(self.bridge.userVoiceLevel or 0.0),
                "peak": float(self.bridge.userVoicePeak or 0.0),
                "flux": float(self.bridge.userSpectralFlux or 0.0),
                "centroid": float(self.bridge.userSpectralCentroid or 0.0),
                "active": bool(self.bridge.userVoiceActive),
            }
        )
        self._update_quick_windows()

    @QtCore.Slot(str)
    def _set_presence_mood(self, mood: str) -> None:
        if self._shutdown:
            return
        self.bridge.setPresenceMood(mood)
        self._send_external_runtime({"type": "mood", "mood": str(self.bridge.moodName or "neutral")})
        self._update_quick_windows()

    def _cycle_floating_visual_style(self) -> None:
        if self._shutdown:
            return
        next_style = _next_visual_style(self.bridge.visualStyle)
        self._last_runtime_config["ai_presence_visual_style"] = next_style
        self._update_runtime_config("ai_presence_visual_style", next_style)
        self.bridge.apply_settings(self._last_runtime_config)
        self._apply_floating_window_settings()
        self._save_live_settings_session()

    @QtCore.Slot(str, object)
    def _apply_live_setting(self, key: str, value: Any) -> None:
        if self._shutdown:
            return
        key = str(key or "").strip()
        if (
            key not in _LIVE_SETTING_RANGES
            and key not in _LIVE_BOOLEAN_SETTINGS
            and key not in _LIVE_CHOICE_SETTINGS
        ):
            return
        normalized = self._normalize_live_setting(key, value)
        self._last_runtime_config[key] = normalized
        self._update_runtime_config(key, normalized)
        self.bridge.apply_settings(self._last_runtime_config)
        if key in {"ai_presence_voice_thread_mouse_physics_enabled", "ai_presence_floating_window_opacity", "ai_presence_overlay_opacity"}:
            self._apply_floating_window_settings()
        elif key == "ai_presence_voice_thread_horizontal_span":
            self._apply_voice_thread_horizontal_span(normalized)
        self._update_quick_windows()
        self._live_settings_save_timer.start()

    @staticmethod
    def _normalize_live_setting(key: str, value: Any) -> Any:
        if key in _LIVE_BOOLEAN_SETTINGS:
            return bool(value)
        if key in _LIVE_CHOICE_SETTINGS:
            normalized = str(value or "").strip().lower()
            allowed = _LIVE_CHOICE_SETTINGS[key]
            return normalized if normalized in allowed else "natural"
        minimum, maximum, value_type = _LIVE_SETTING_RANGES[key]
        try:
            numeric = float(value)
        except Exception:
            numeric = float(minimum)
        numeric = max(float(minimum), min(float(maximum), numeric))
        return int(round(numeric)) if value_type is int else float(numeric)

    def _save_live_settings_session(self) -> None:
        if callable(self._persist):
            try:
                self._persist()
            except Exception:
                pass

    def _update_quick_windows(self) -> None:
        if self._external_runtime_enabled():
            return
        for window in (self._fullscreen_window, self._floating_window):
            if window is not None and window.isVisible():
                window.update()

    @QtCore.Slot(dict)
    def apply_runtime_config(self, runtime_config: dict[str, Any]) -> None:
        if self._shutdown:
            return
        config = dict(runtime_config or {})
        previous_span = self._normalize_live_setting(
            "ai_presence_voice_thread_horizontal_span",
            self._last_runtime_config.get(
                "ai_presence_voice_thread_horizontal_span", 1.0
            ),
        )
        next_span = self._normalize_live_setting(
            "ai_presence_voice_thread_horizontal_span",
            config.get("ai_presence_voice_thread_horizontal_span", 1.0),
        )
        horizontal_span_changed = abs(next_span - previous_span) > 0.0001
        previous_display = (bool(self.bridge.enabled), self._display_mode)
        self._last_runtime_config = config
        self.bridge.apply_settings(config)
        self._display_mode = _normalize_display_mode(config.get("ai_presence_display_mode", self.bridge.displayMode))
        self._fullscreen = bool(config.get("ai_presence_fullscreen", True))
        if previous_display != (bool(self.bridge.enabled), self._display_mode):
            self._fullscreen_suppressed = False
        if self._external_runtime_enabled():
            self._hide_local_windows_for_external()
            self._send_external_runtime_snapshot()
            return
        self._stop_external_runtime()
        self._apply_floating_window_settings()
        self._restore_floating_geometry()
        if horizontal_span_changed:
            self._apply_voice_thread_horizontal_span(next_span)
        self._sync_geometry()
        self._refresh_visibility()

    @staticmethod
    def _primary_screen() -> QtGui.QScreen | None:
        return QtGui.QGuiApplication.primaryScreen()

    def _target_geometry(self) -> QtCore.QRect:
        main_window = self.main_window
        if main_window is None or not shiboken6.isValid(main_window):
            screen = self._primary_screen()
            return screen.geometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        if self._fullscreen:
            screen = main_window.screen()
            if screen is not None:
                return screen.geometry()
        try:
            return main_window.frameGeometry()
        except RuntimeError:
            screen = self._primary_screen()
            return screen.geometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)

    def _preferred_floating_screen(self) -> QtGui.QScreen | None:
        main_window = self.main_window
        if main_window is not None and shiboken6.isValid(main_window):
            try:
                screen = main_window.screen()
            except RuntimeError:
                screen = None
            if screen is not None:
                return screen
        window = self._floating_window
        if window is not None and shiboken6.isValid(window):
            try:
                screen = window.screen()
            except RuntimeError:
                screen = None
            if screen is not None:
                return screen
        return self._primary_screen()

    def _floating_default_geometry(self) -> QtCore.QRect:
        screen = self._preferred_floating_screen()
        available = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        width = min(520, max(320, int(available.width() * 0.28)))
        height = min(420, max(260, int(available.height() * 0.34)))
        main_window = self.main_window
        if main_window is not None and shiboken6.isValid(main_window):
            try:
                main_geometry = main_window.frameGeometry()
            except RuntimeError:
                main_geometry = QtCore.QRect()
            if main_geometry.isValid() and available.intersects(main_geometry):
                margin = 28
                if available.right() - main_geometry.right() >= width + margin:
                    x = main_geometry.right() + margin
                elif main_geometry.left() - available.left() >= width + margin:
                    x = main_geometry.left() - width - margin
                else:
                    x = main_geometry.right() - width - margin
                x = max(available.left(), min(x, available.right() - width + 1))
                y = max(
                    available.top(),
                    min(main_geometry.top() + 72, available.bottom() - height + 1),
                )
                return QtCore.QRect(x, y, width, height)
        return QtCore.QRect(available.right() - width - 28, available.top() + 72, width, height)

    def _horizontal_span_geometry(
        self,
        current: QtCore.QRect,
        span: float,
    ) -> QtCore.QRect:
        window = self._floating_window
        screen = next(
            (
                candidate
                for candidate in QtGui.QGuiApplication.screens()
                if candidate.availableGeometry().intersects(current)
            ),
            None,
        )
        if screen is None and window is not None and shiboken6.isValid(window):
            try:
                screen = window.screen()
            except RuntimeError:
                screen = None
        if screen is None:
            screen = self._preferred_floating_screen()
        available = (
            screen.availableGeometry()
            if screen is not None
            else QtCore.QRect(0, 0, 1280, 720)
        )
        compact_width = min(520, max(320, int(available.width() * 0.28)))
        normalized_span = max(1.0, min(4.0, float(span)))
        progress = (normalized_span - 1.0) / 3.0
        width = int(round(
            compact_width + (available.width() - compact_width) * progress
        ))
        width = max(220, min(width, available.width()))
        height = max(180, min(current.height(), available.height()))
        center_x = current.center().x() if current.isValid() else available.center().x()
        x = center_x - width // 2
        x = max(available.left(), min(x, available.right() - width + 1))
        y = max(
            available.top(),
            min(current.y(), available.bottom() - height + 1),
        )
        return QtCore.QRect(x, y, width, height)

    def _apply_voice_thread_horizontal_span(self, span: float) -> None:
        window = self._floating_window
        if (
            self._external_runtime_enabled()
            or window is None
            or not shiboken6.isValid(window)
        ):
            return
        geometry = self._horizontal_span_geometry(window.geometry(), span)
        if window.geometry() != geometry:
            window.setGeometry(geometry)
            self._schedule_save_floating_geometry()

    def _floating_center_geometry(self) -> QtCore.QRect:
        window = self._floating_window
        screen = self._preferred_floating_screen()
        available = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        current = window.geometry() if window is not None else self._floating_default_geometry()
        width = max(220, min(current.width(), available.width()))
        height = max(180, min(current.height(), available.height()))
        x = available.x() + max(0, (available.width() - width) // 2)
        y = available.y() + max(0, (available.height() - height) // 2)
        return QtCore.QRect(x, y, width, height)

    def _configured_floating_geometry(self) -> QtCore.QRect | None:
        raw = self._last_runtime_config.get("ai_presence_floating_geometry", [])
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            try:
                x, y, width, height = [int(value) for value in raw]
                geometry = QtCore.QRect(x, y, max(220, width), max(180, height))
                if any(
                    screen.availableGeometry().intersects(geometry)
                    for screen in QtGui.QGuiApplication.screens()
                ):
                    return geometry
            except (TypeError, ValueError):
                pass
        return None

    def _restore_floating_geometry(self) -> None:
        if self._floating_window is None or self._floating_geometry_restored:
            return
        geometry = self._configured_floating_geometry() if bool(self.bridge.rememberFloatingGeometry) else None
        if geometry is None:
            geometry = self._floating_default_geometry()
            geometry = self._horizontal_span_geometry(
                geometry,
                self._last_runtime_config.get(
                    "ai_presence_voice_thread_horizontal_span", 1.0
                ),
            )
        self._floating_window.setGeometry(geometry)
        self._floating_geometry_restored = True

    def _sync_geometry(self) -> None:
        if self._shutdown:
            return
        if (
            self._fullscreen_window is not None
            and shiboken6.isValid(self._fullscreen_window)
        ):
            self._fullscreen_window.setGeometry(self._target_geometry())

    def _floating_click_through_enabled(self) -> bool:
        return (
            bool(self.bridge.clickThroughDefault)
            and (not bool(self.bridge.rightDragMoveEnabled) or sys.platform == "win32")
            and not self._voice_thread_mouse_physics_active()
            and not bool(self.bridge.liveControlsVisible)
        )

    @QtCore.Slot()
    def _refresh_live_controls_input(self) -> None:
        if self._shutdown:
            return
        visible = bool(self.bridge.liveControlsVisible)
        if visible != self._last_live_controls_visible:
            self._last_live_controls_visible = visible
            self._apply_floating_window_settings()

    def _sync_right_drag(self) -> None:
        window = self._floating_window
        enabled = bool(
            not self._shutdown and window is not None and window.isVisible()
            and float(self.bridge.floatingOpacity) > 0.0
            and bool(self.bridge.rightDragMoveEnabled)
            and self._floating_click_through_enabled()
        )
        self._right_drag.configure(int(window.winId()) if window is not None else 0, enabled)

    def _apply_windows_floating_click_through(self, enabled: bool) -> None:
        window = self._floating_window
        if window is None:
            return
        window.setFlag(_transparent_for_input_hint(), enabled)
        try:
            import ctypes
            import sys

            if sys.platform.startswith("win"):
                handle = int(window.winId())
                current = ctypes.windll.user32.GetWindowLongW(handle, -20)
                layered = 0x00080000
                transparent = 0x00000020
                next_style = current | layered
                next_style = (next_style | transparent) if enabled else (next_style & ~transparent)
                ctypes.windll.user32.SetWindowLongW(handle, -20, next_style)
        except Exception:
            pass

    def _apply_floating_window_settings(self) -> None:
        window = self._floating_window
        if window is None:
            return
        was_visible = window.isVisible()
        # Keep the original QML/native split until floating opacity is edited;
        # moving legacy root alpha after compositing would change overlaps.
        native_opacity = float(self.bridge.floatingOpacity) / float(self.bridge.floatingContentOpacity)
        window.setOpacity(max(0.0, min(1.0, native_opacity)))
        window.setFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, bool(self.bridge.floatingAlwaysOnTop))
        window.setFlag(QtCore.Qt.WindowType.FramelessWindowHint, True)
        window.setFlag(_no_shadow_window_hint(), True)
        window.setColor(QtGui.QColor(0, 0, 0, 0))
        self._apply_windows_floating_click_through(self._floating_click_through_enabled())
        if was_visible:
            window.show()
        self._sync_right_drag()

    def _schedule_save_floating_geometry(self) -> None:
        if bool(self.bridge.rememberFloatingGeometry):
            self._floating_save_timer.start()

    def _save_floating_geometry(self) -> None:
        if self._floating_window is None or not bool(self.bridge.rememberFloatingGeometry):
            return
        geometry = self._floating_window.geometry()
        payload = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
        self._last_runtime_config["ai_presence_floating_geometry"] = payload
        self._update_runtime_config("ai_presence_floating_geometry", payload)

    @QtCore.Slot()
    def reset_floating_position(self) -> None:
        if self._shutdown:
            return
        if self._external_runtime_enabled():
            self._send_external_runtime({"type": "reset_floating_position"})
            return
        if self._floating_window is None:
            return
        geometry = self._floating_center_geometry()
        self._floating_window.setGeometry(geometry)
        self._floating_geometry_restored = True
        payload = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
        self._last_runtime_config["ai_presence_floating_geometry"] = payload
        self._update_runtime_config("ai_presence_floating_geometry", payload)
        self._save_live_settings_session()

    def hide_fullscreen_temporarily(self) -> None:
        self._fullscreen_suppressed = True
        if self._fullscreen_window is not None:
            self._fullscreen_window.hide()

    def _refresh_visibility(self) -> None:
        if self._external_runtime_enabled():
            self._hide_local_windows_for_external()
            self._send_external_runtime_snapshot()
            return
        enabled = bool(self.bridge.enabled) and self._display_mode != "off"
        show_fullscreen = bool(enabled and self._display_mode in {"fullscreen", "both"} and not self._fullscreen_suppressed)
        show_floating = bool(enabled and self._display_mode in {"floating", "both"})
        if self._fullscreen_window is not None:
            if show_fullscreen:
                self._sync_geometry()
                self._fullscreen_window.show()
                self._fullscreen_window.raise_()
            else:
                self._fullscreen_window.hide()
        if self._floating_window is not None:
            if show_floating:
                self._restore_floating_geometry()
                self._floating_window.show()
                if bool(self.bridge.floatingAlwaysOnTop):
                    self._floating_window.raise_()
            else:
                self._floating_window.hide()
        self._sync_right_drag()
        if show_fullscreen or show_floating:
            self._geometry_timer.start()
        else:
            self._geometry_timer.stop()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._right_drag.close()
        subscription = self._config_subscription
        self._config_subscription = None
        if subscription is not None:
            try:
                subscription.close()
            except Exception:
                pass
        presence_runtime.unregister_controller(self)
        self._stop_external_runtime()
        for timer in (self._geometry_timer, self._floating_save_timer, self._live_settings_save_timer):
            timer.stop()
        app = QtGui.QGuiApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._save_floating_geometry()
        self.bridge.setAudioLevel(0.0)
        self.bridge.setMusicLevel(0.0)
        self.bridge.setMusicSpectrum((0.0,) * 12)
        self.bridge.setVoiceAnalysis((0.0,) * 12, 0.0, 0.0)
        self.bridge.setAiState("idle")
        for window in (self._fullscreen_window, self._floating_window):
            if window is not None:
                window.hide()
                window.deleteLater()
        self._fullscreen_window = None
        self._floating_window = None


def install_visual_presence(
    main_window: QtGui.QWindow | None,
    runtime_config: dict[str, Any] | None = None,
    *,
    application: Any = None,
    persist: Callable[[], object] | None = None,
) -> VisualPresenceController:
    config_update = None
    config_subscribe = None
    if application is not None:
        runtime_config = dict(application.config.snapshot().values)
        config_update = application.config.update
        config_subscribe = application.subscriptions.config
    controller = VisualPresenceController(
        main_window,
        runtime_config,
        config_update=config_update,
        config_subscribe=config_subscribe,
        persist=persist,
    )
    presence_runtime.apply_settings(dict(runtime_config or {}))
    presence_runtime.register_controller(controller)
    if main_window is not None:
        setattr(main_window, "visual_presence_controller", controller)
    return controller


__all__ = [
    "FLOATING_STYLE_CYCLE",
    "VisualPresenceController",
    "install_visual_presence",
    "_next_visual_style",
]
