"""Native QML settings surface for Corsair Visual Instrument."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from PySide6 import QtCore

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter

_STATES = ("idle", "listening", "thinking", "speaking")
_ANIMATION_EFFECTS = (
    ("classic_idle", "Classic Idle Breath"),
    ("classic_listening", "Classic Listening Pulse"),
    ("classic_thinking", "Classic Thinking Scan"),
    ("equalizer", "Equalizer"),
    ("living_wave", "Living Wave"),
    ("center_ripple", "Center Ripple"),
    ("dual_comet", "Dual Comet"),
    ("plasma_field", "Plasma Field"),
    ("audio_columns", "Audio Columns"),
    ("center_shockwave", "Center Shockwave"),
    ("twin_voicefront", "Twin Voicefront"),
    ("voice_bloom", "Voice Bloom"),
)
_ANIMATION_FIELDS = frozenset(
    {"effect", "speed", "intensity", "size", "trail", "audio_reactivity", "detail"}
)
_SCALED_SETTINGS = frozenset(
    {"brightness", "sensitivity", "smoothing", "mood_tint_strength", "animation_speed"}
)
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

_CARD_LAYOUT: dict[str, tuple[str, str, int]] = {
    "enabled": ("corsair_connection", "Connection", 1),
    "corsair_status": ("corsair_connection", "Connection", 1),
    "corsair_status_detail": ("corsair_connection", "Connection", 1),
    "corsair_rescan": ("corsair_connection", "Connection", 1),
    "corsair_detected_keyboards": ("corsair_detected_keyboards", "Detected keyboards", 2),
    "k55_device_id": ("corsair_device_overrides", "Optional renderer overrides", 1),
    "k65_device_id": ("corsair_device_overrides", "Optional renderer overrides", 1),
    "k55_mode": ("corsair_zone_behavior", "Zone keyboard behavior", 2),
    "corsair_device_help": ("corsair_device_help", "Device setup", 2),
    "idle_color": ("corsair_state_colors", "State colors", 1),
    "listening_color": ("corsair_state_colors", "State colors", 1),
    "thinking_color": ("corsair_state_colors", "State colors", 1),
    "speaking_color": ("corsair_state_colors", "State colors", 1),
    "mood_tint_enabled": ("corsair_mood", "Mood", 1),
    "mood_tint_strength": ("corsair_mood", "Mood", 1),
    "corsair_keyboard_preview": ("keyboard_preview", "Keyboard preview", 1),
    "corsair_animation_state": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_animation_effect": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_animation_speed": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_animation_intensity": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_animation_size": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_animation_trail": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_animation_audio_reactivity": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_animation_detail": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_preview_audio": ("keyboard_animation_controls", "Animation controls", 1),
    "corsair_preview_selected": ("keyboard_animation_controls", "Animation controls", 1),
    "sensitivity": ("corsair_speech_response", "Speech response", 1),
    "smoothing": ("corsair_speech_response", "Speech response", 1),
    "brightness": ("corsair_global_output", "Global output", 1),
    "animation_speed": ("corsair_global_output", "Global output", 1),
    "frame_rate_hz": ("corsair_global_output", "Global output", 1),
    "sdk_dll_path": ("corsair_sdk", "Official iCUE SDK", 2),
    "corsair_select_sdk_dll": ("corsair_sdk", "Official iCUE SDK", 2),
    "corsair_sdk_note": ("corsair_sdk", "Official iCUE SDK", 2),
}


def _local_path(payload: object) -> str:
    values = list(payload or [])
    if not values:
        return ""
    text = str(values[0] or "").strip()
    url = QtCore.QUrl(text)
    return url.toLocalFile() if url.isLocalFile() else text


def _hex_color(value: object) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text.startswith("#"):
            text = "#" + text
        return text.upper()
    parts = list(value or [])
    if len(parts) != 3:
        return "#000000"
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(part))) for part in parts))


class CorsairVisualInstrumentNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._revision = 0
        self._animation_state = "speaking"
        self._preview_audio = 68

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Corsair lighting is unavailable."))
            )
        return result.value

    def _snapshot_payload(self) -> dict[str, object]:
        value = self._invoke("runtime.corsair.snapshot")
        if not isinstance(value, Mapping):
            raise RuntimeError(  # noqa: TRY004 - capability contract failure
                "Corsair lighting snapshot is not a mapping."
            )
        return dict(value)

    @staticmethod
    def _device_choices(
        devices: list[object],
        *,
        selected_id: str,
    ) -> tuple[NativeChoice, ...]:
        options = [NativeChoice(value="", label="Automatic by LED layout")]
        known_ids = set()
        for raw in devices:
            item = dict(raw or {})
            model = str(item.get("model") or "Corsair keyboard")
            device_id = str(item.get("device_id") or "").strip()
            if not device_id:
                continue
            known_ids.add(device_id)
            led_count = len(list(item.get("led_points") or []))
            detail = f"{led_count} LEDs" if led_count else "LED layout unavailable"
            options.append(
                NativeChoice(value=device_id, label=f"{model} — {detail} — {device_id}")
            )
        if selected_id and selected_id not in known_ids:
            options.append(
                NativeChoice(
                    value=selected_id,
                    label=f"Configured device (offline) — {selected_id}",
                )
            )
        return tuple(options)

    @staticmethod
    def _device_summary(
        devices: list[object], settings: Mapping[str, object]
    ) -> str:
        if not devices:
            return "No Corsair keyboards detected. Reconnect and rescan after enabling iCUE SDK device control."
        zone_override = str(settings.get("k55_device_id") or "").strip()
        spatial_override = str(settings.get("k65_device_id") or "").strip()
        lines = []
        for raw in devices:
            item = dict(raw or {})
            model = str(item.get("model") or "Corsair keyboard")
            device_id = str(item.get("device_id") or "").strip()
            led_count = len(list(item.get("led_points") or []))
            if led_count <= 0:
                lines.append(f"{model} — no controllable LEDs exposed by iCUE")
                continue
            renderer = "Zone renderer" if led_count <= 8 else "Per-key renderer"
            if device_id == zone_override:
                renderer = "Zone renderer"
            elif device_id == spatial_override:
                renderer = "Per-key renderer"
            active = (
                (renderer == "Zone renderer" and (not zone_override or device_id == zone_override))
                or (
                    renderer == "Per-key renderer"
                    and (not spatial_override or device_id == spatial_override)
                )
            )
            output = "Active" if active else "Excluded by renderer override"
            lines.append(
                f"{model} — {led_count} controllable LEDs — {renderer} — {output}"
            )
        return "\n".join(lines)

    def snapshot(self) -> NativeSurface:
        payload = self._snapshot_payload()
        settings = dict(payload.get("settings") or {})
        devices = list(payload.get("devices") or [])
        profile = dict(settings.get(f"k65_{self._animation_state}_animation") or {})
        effect = str(profile.get("effect") or "center_ripple")
        enabled = bool(settings.get("enabled", True))
        values: dict[str, object] = {
            "corsair_status": str(payload.get("status_state") or "unknown").replace("_", " ").title(),
            "corsair_status_detail": str(payload.get("status_detail") or ""),
            "corsair_detected_keyboards": self._device_summary(devices, settings),
            "corsair_animation_state": self._animation_state,
            "corsair_animation_effect": effect,
            "corsair_animation_speed": round(float(profile.get("speed", 1.0)) * 100),
            "corsair_animation_intensity": round(float(profile.get("intensity", 1.0)) * 100),
            "corsair_animation_size": round(float(profile.get("size", 1.0)) * 100),
            "corsair_animation_trail": round(float(profile.get("trail", 0.5)) * 100),
            "corsair_animation_audio_reactivity": round(float(profile.get("audio_reactivity", 1.0)) * 100),
            "corsair_animation_detail": round(float(profile.get("detail", 0.5)) * 100),
            "corsair_preview_audio": self._preview_audio,
            "corsair_keyboard_preview": {
                "state": self._animation_state,
                "effect": effect,
                "color": _hex_color(settings.get(f"{self._animation_state}_color")),
                "brightness": float(settings.get("brightness", 0.75)),
                "level": self._preview_audio / 100.0,
                "speed": float(profile.get("speed", 1.0)),
                "intensity": float(profile.get("intensity", 1.0)),
                "size": float(profile.get("size", 1.0)),
                "trail": float(profile.get("trail", 0.5)),
                "audio_reactivity": float(profile.get("audio_reactivity", 1.0)),
                "detail": float(profile.get("detail", 0.5)),
                "k55_mode": str(settings.get("k55_mode") or "state_lanes"),
            },
        }
        for key in ("idle_color", "listening_color", "thinking_color", "speaking_color"):
            values[key] = _hex_color(settings.get(key))
        for key in _SCALED_SETTINGS:
            values[key] = round(float(settings.get(key, 0.0)) * 100)
        controls = []
        for control in self._surface.controls:
            value = values.get(control.id, settings.get(control.id, control.default_value))
            updates: dict[str, object] = {"value": value}
            if control.id in {"k55_device_id", "k65_device_id"}:
                updates["choices"] = self._device_choices(
                    devices,
                    selected_id=str(settings.get(control.id) or ""),
                )
            elif control.id == "corsair_animation_audio_reactivity":
                updates["maximum"] = 400 if effect == "equalizer" else 200
            elif control.id in {"corsair_animation_speed", "corsair_animation_trail"}:
                updates["enabled"] = effect != "equalizer"
            elif control.id == "corsair_preview_audio":
                metadata = dict(control.metadata)
                metadata["visible"] = self._animation_state == "speaking"
                updates["metadata"] = metadata
            elif control.id == "corsair_preview_selected":
                updates["label"] = f"Preview {self._animation_state.title()}"
                updates["enabled"] = enabled
            elif control.kind is NativeControlKind.ACTION:
                updates["enabled"] = enabled or control.id == "corsair_rescan"
            controls.append(replace(control, **updates))
        return replace(
            self._surface,
            controls=apply_card_layout(controls, overrides=_CARD_LAYOUT),
            revision=self._revision,
        )

    def _update(self, changes: Mapping[str, object]) -> None:
        self._invoke("runtime.corsair.update", {"changes": dict(changes)})
        if callable(self._persist):
            self._persist()

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key == "corsair_animation_state":
            state = str(value or "").strip().lower()
            if state not in _STATES:
                raise ValueError(f"Unknown Corsair animation state '{value}'.")
            self._animation_state = state
        elif key == "corsair_preview_audio":
            self._preview_audio = max(0, min(100, int(value)))
        elif key.startswith("corsair_animation_"):
            field = key.removeprefix("corsair_animation_")
            if field not in _ANIMATION_FIELDS:
                raise KeyError(f"Unknown Corsair animation setting '{control_id}'.")
            payload = self._snapshot_payload()
            settings = dict(payload.get("settings") or {})
            profile_key = f"k65_{self._animation_state}_animation"
            profile = dict(settings.get(profile_key) or {})
            if field == "effect":
                effect = str(value or "").strip().lower()
                if effect not in {item[0] for item in _ANIMATION_EFFECTS}:
                    raise ValueError(f"Unknown Corsair animation effect '{value}'.")
                profile[field] = effect
            else:
                control = next(
                    item for item in self.snapshot().controls if item.id == key
                )
                normalized = RuntimeConfigNativeAdapter._normalize(control, value)
                profile[field] = float(normalized) / 100.0
            changes: dict[str, object] = {profile_key: profile}
            if self._animation_state == "speaking":
                changes["k65_speaking_mode"] = str(profile.get("effect") or "equalizer")
            self._update(changes)
        else:
            control = self._controls.get(key)
            if control is None or control.kind in {
                NativeControlKind.ACTION,
                NativeControlKind.DISPLAY,
            }:
                raise KeyError(f"Unknown Corsair lighting setting '{control_id}'.")
            normalized = RuntimeConfigNativeAdapter._normalize(control, value)
            if key in _SCALED_SETTINGS:
                normalized = float(normalized) / 100.0
            elif key.endswith("_color"):
                normalized = _hex_color(normalized)
                if not _HEX_COLOR.fullmatch(str(normalized)):
                    raise ValueError(f"Invalid RGB color '{value}'.")
            self._update({key: normalized})
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        action = str(control_id or "").strip()
        if action == "corsair_rescan":
            self._invoke("runtime.corsair.rescan")
        elif action == "corsair_select_sdk_dll":
            path = _local_path(payload)
            if path:
                self._update({"sdk_dll_path": path})
        elif action == "corsair_preview_selected":
            self._invoke(
                "runtime.corsair.preview_state",
                {"state": self._animation_state},
            )
        elif action.startswith("corsair_preview_"):
            state = action.removeprefix("corsair_preview_")
            if state not in _STATES:
                raise KeyError(f"Unknown Corsair preview action '{control_id}'.")
            self._invoke("runtime.corsair.preview_state", {"state": state})
        else:
            raise KeyError(f"Unknown Corsair action '{control_id}'.")
        self._revision += 1
        self.changed.emit()


def build_corsair_visual_instrument_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> CorsairVisualInstrumentNativeAdapter:
    surface = NativeSurface(
        id="corsair_visual_instrument_tab",
        title="Corsair LEDs",
        addon_id="nc.corsair_visual_instrument",
        sections=(
            "Connection",
            "Devices",
            "State colors & mood",
            "Keyboard animation designer",
            "Speech response",
            "Global output",
            "Advanced SDK",
        ),
        description="Render NeuralCompanion state, mood, and speech energy on Corsair keyboards.",
        controls=(
            NativeControl("enabled", "Enable Corsair visual lighting at startup", NativeControlKind.BOOLEAN, "Connection", default_value=True),
            NativeControl("corsair_status", "Connection status", NativeControlKind.DISPLAY, "Connection"),
            NativeControl("corsair_status_detail", "Status detail", NativeControlKind.DISPLAY, "Connection"),
            NativeControl("corsair_rescan", "Reconnect & Rescan", NativeControlKind.ACTION, "Connection", metadata={"execution": "ui"}),
            NativeControl("corsair_detected_keyboards", "Detected keyboards", NativeControlKind.DISPLAY, "Devices"),
            NativeControl("k55_device_id", "Force zone renderer", NativeControlKind.CHOICE, "Devices", choices=(NativeChoice("", "Automatic by LED layout"),)),
            NativeControl("k65_device_id", "Force per-key renderer", NativeControlKind.CHOICE, "Devices", choices=(NativeChoice("", "Automatic by LED layout"),)),
            NativeControl("k55_mode", "Zone display mode", NativeControlKind.CHOICE, "Devices", default_value="state_lanes", choices=choices((("state_lanes", "State Lanes"), ("unified", "Unified")))),
            NativeControl("corsair_device_help", "Keyboard discovery", NativeControlKind.DISPLAY, "Devices", default_value="Automatic mode drives every keyboard that exposes controllable LEDs. Renderer overrides keep the older single-device assignment behavior. In iCUE, leave Device Memory Mode, enable SDK access under Settings > SDK > Device Control, then reconnect."),
            NativeControl(
                "idle_color", "Idle", NativeControlKind.TEXT,
                "State colors & mood", default_value="#0F6469",
                metadata={
                    "renderer": "color",
                    "toolTip": "Choose the keyboard color used while NeuralCompanion is idle.",
                },
            ),
            NativeControl(
                "listening_color", "Listening", NativeControlKind.TEXT,
                "State colors & mood", default_value="#19A5FF",
                metadata={
                    "renderer": "color",
                    "toolTip": "Choose the keyboard color used while NeuralCompanion is listening.",
                },
            ),
            NativeControl(
                "thinking_color", "Thinking", NativeControlKind.TEXT,
                "State colors & mood", default_value="#9646FF",
                metadata={
                    "renderer": "color",
                    "toolTip": "Choose the keyboard color used while NeuralCompanion is thinking.",
                },
            ),
            NativeControl(
                "speaking_color", "Speaking", NativeControlKind.TEXT,
                "State colors & mood", default_value="#FF9123",
                metadata={
                    "renderer": "color",
                    "toolTip": "Choose the keyboard color used while NeuralCompanion is speaking.",
                },
            ),
            NativeControl("mood_tint_enabled", "Tint state colors with the current mood", NativeControlKind.BOOLEAN, "State colors & mood", default_value=True),
            NativeControl("mood_tint_strength", "Mood tint", NativeControlKind.SLIDER, "State colors & mood", minimum=0, maximum=45, step=1, default_value=25),
            NativeControl("corsair_keyboard_preview", "Keyboard preview", NativeControlKind.DISPLAY, "Keyboard animation designer", metadata={"renderer": "corsairKeyboard", "label": "unnamed_corsair_keyboard_preview", "stackedLayout": True}),
            NativeControl("corsair_animation_state", "State to edit", NativeControlKind.CHOICE, "Keyboard animation designer", default_value="speaking", choices=choices(tuple((state, state.title()) for state in _STATES))),
            NativeControl("corsair_animation_effect", "Animation", NativeControlKind.CHOICE, "Keyboard animation designer", default_value="equalizer", choices=choices(_ANIMATION_EFFECTS)),
            NativeControl("corsair_animation_speed", "Speed", NativeControlKind.SLIDER, "Keyboard animation designer", minimum=0, maximum=300, step=1, default_value=100),
            NativeControl("corsair_animation_intensity", "Intensity", NativeControlKind.SLIDER, "Keyboard animation designer", minimum=0, maximum=200, step=1, default_value=100),
            NativeControl("corsair_animation_size", "Animation size", NativeControlKind.SLIDER, "Keyboard animation designer", minimum=20, maximum=200, step=1, default_value=100),
            NativeControl("corsair_animation_trail", "Trail / softness", NativeControlKind.SLIDER, "Keyboard animation designer", minimum=0, maximum=100, step=1, default_value=50),
            NativeControl("corsair_animation_audio_reactivity", "Audio reactivity", NativeControlKind.SLIDER, "Keyboard animation designer", minimum=0, maximum=400, step=1, default_value=100),
            NativeControl("corsair_animation_detail", "Effect detail", NativeControlKind.SLIDER, "Keyboard animation designer", minimum=0, maximum=100, step=1, default_value=50),
            NativeControl("corsair_preview_audio", "Test audio level", NativeControlKind.SLIDER, "Keyboard animation designer", minimum=0, maximum=100, step=1, default_value=68),
            NativeControl("corsair_preview_selected", "Preview Speaking", NativeControlKind.ACTION, "Keyboard animation designer", metadata={"execution": "ui", "actionStrip": True}),
            NativeControl("sensitivity", "Speech sensitivity", NativeControlKind.SLIDER, "Speech response", minimum=0, maximum=100, step=1, default_value=80),
            NativeControl("smoothing", "Speech smoothing", NativeControlKind.SLIDER, "Speech response", minimum=0, maximum=100, step=1, default_value=55),
            NativeControl("brightness", "Brightness", NativeControlKind.SLIDER, "Global output", minimum=0, maximum=100, step=1, default_value=75),
            NativeControl("animation_speed", "Animation speed", NativeControlKind.SLIDER, "Global output", minimum=25, maximum=300, step=1, default_value=100),
            NativeControl("frame_rate_hz", "Frame cap", NativeControlKind.INTEGER, "Global output", minimum=5, maximum=30, step=1, default_value=24),
            NativeControl("sdk_dll_path", "64-bit SDK DLL", NativeControlKind.TEXT, "Advanced SDK"),
            NativeControl("corsair_select_sdk_dll", "Browse for SDK DLL", NativeControlKind.ACTION, "Advanced SDK", metadata={"execution": "ui", "filePicker": True, "dialogTitle": "Select official iCUE SDK DLL", "nameFilters": ["Windows DLL (*.dll)"]}),
            NativeControl("corsair_sdk_note", "SDK requirements", NativeControlKind.DISPLAY, "Advanced SDK", default_value="Keep iCUE running and enable SDK/game integrations. Shared lighting is used."),
        ),
    )
    return CorsairVisualInstrumentNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = [
    "CorsairVisualInstrumentNativeAdapter",
    "build_corsair_visual_instrument_adapter",
]
