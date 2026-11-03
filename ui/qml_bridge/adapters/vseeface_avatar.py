"""Native QML body, dynamics, and hand controls for VSeeFace."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping
from PySide6 import QtCore, QtGui

from ui.shell_specs import UI_SHELL_BODY_EMOTIONS, UI_SHELL_BODY_POSE_SPECS
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
from addons.vseeface_avatar.body_profiles import DEFAULT_POSE, complete_body_profile, complete_hand_calibration


_HAND_AXES = ("finger_x", "finger_y", "finger_z", "thumb_x", "thumb_y", "thumb_z")

_VSEEFACE_SETUP_INSTRUCTIONS = (
    "Download and extract VSeeFace, choose its folder below, then use Check setup. "
    "Approve installing or updating the bridge while VSeeFace is closed. "
    "Use Start VSeeFace in Overview to open the saved installation.\n\n"
    "Inside VSeeFace, open General settings → VMC protocol and set:\n\n"
    "ON (checked)\n"
    "• VMC receiver (disables tracking) — port 39539\n"
    "• Apply VSeeFace tracking\n"
    "• Track face features\n"
    "• Track blendshapes\n\n"
    "OFF (unchecked)\n"
    "• Send data with VMC protocol\n"
    "• Apply expressions\n"
    "• Track eye bones\n"
    "• Track jaw bone\n"
    "• Track head and neck\n\n"
    "Start with Blendshape smoothing and Bone smoothing at minimum.\n"
    "Also enable Audio lip sync in VSeeFace's General settings.\n\n"
    "This lets NC control the body, head, eyes and emotional expressions while "
    "VSeeFace adds speech lip sync. Set these options in VSeeFace itself; "
    "NC does not change them automatically."
)


def _same_installation(left, right):
    if not left or not right:
        return str(left or '') == str(right or '')
    try:
        return Path(left).resolve() == Path(right).resolve()
    except (OSError, ValueError):
        return False


def _plain_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for key, item in value.items():
        result[str(key)] = _plain_mapping(item) if isinstance(item, Mapping) else item
    return result


class VSeeFaceAvatarNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        focus_request: Callable[[str], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._focus_request = focus_request
        self._revision = 0
        self._selected_body = ""
        self._hand_preset = "relaxed"
        self._restore_controls_state()
        body = self._application.body.snapshot()
        profile = complete_body_profile(body.profile)
        calibration = complete_hand_calibration(body.hand_calibration)
        if profile != body.profile:
            self._raise_if_rejected(self._application.body.update_profile(profile), "Could not initialize body profiles.")
        if calibration != body.hand_calibration:
            self._raise_if_rejected(self._application.body.update_hand_calibration(calibration), "Could not initialize hand calibration.")

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "VSeeFace controls are unavailable."))
            )
        return result.value

    def _body_catalog(self) -> tuple[str, ...]:
        return tuple(str(item) for item in list(self._invoke("runtime.body_profiles.catalog") or []))

    def snapshot(self) -> NativeSurface:
        body = self._application.body.snapshot()
        hand_payload = dict(self._invoke("runtime.hand.snapshot") or {})
        hand_debug = dict(hand_payload.get("debug") or {})
        catalog = self._body_catalog()
        if self._selected_body not in catalog:
            self._selected_body = catalog[0] if catalog else ""
        current_emotion = str(body.edit_emotion or "neutral").strip().lower()
        profile_values = dict(body.profile.get(current_emotion if body.force_edit_mode else "neutral") or {})
        values: dict[str, object] = {
            "body_combo": self._selected_body,
            "emotion_combo": current_emotion,
            "live_sync_checkbox": not body.force_edit_mode,
            "hand_debug_active": bool(hand_debug.get("active", False)),
            "hand_calibration_preset": self._hand_preset,
            "vseeface_runtime_summary": "VMC/OSC avatar control · estimated overhead 0.8 GiB",
        }
        config = getattr(self._application, 'config', None)
        selected = str(config.get('vseeface_bridge_install_path', '') if config else '')
        bridge = dict(self._invoke('runtime.speech_bridge.status') or {})
        if not _same_installation(bridge.get('installation', ''), selected):
            bridge = dict(state='not_checked', message='Folder selection changed. Check setup before installing or enabling.', plans={})
        plans = dict(bridge.get('plans') or {})
        values.update(vseeface_bridge_install_path=selected,
                      vseeface_bridge_enabled=bool(config.get('vseeface_bridge_enabled', False)) if config else False,
                      vseeface_bridge_status=str(bridge.get('message', 'Check setup to inspect this installation.')),
                      vseeface_bridge_instructions=_VSEEFACE_SETUP_INSTRUCTIONS)
        for key, spec in UI_SHELL_BODY_POSE_SPECS.items():
            scale = int(spec.get("scale", 1) or 1)
            raw = profile_values.get(key, body.state.get(key, spec.get("default", 0.0)))
            values[key] = round(float(raw or 0.0) * scale)
        for key in _HAND_AXES:
            values[f"hand_{key}"] = round(float(hand_debug.get(key, 0.0)) * 10)
        config = getattr(self._application, 'config', None)
        saved_cards = config.get('vseeface_collapsed_cards', {}) if config else {}
        values['btn_vseeface_card_collapse'] = dict(saved_cards) if isinstance(saved_cards, Mapping) else {}
        controls = []
        for control in self._surface.controls:
            updates: dict[str, object] = {
                "value": values.get(control.id, control.default_value)
            }
            if control.id == "body_combo":
                updates["choices"] = tuple(
                    NativeChoice(name, name) for name in catalog
                ) or (NativeChoice("", "No Configs"),)
            if control.id == 'btn_vseeface_start':
                updates['enabled'] = bool(selected)
            if control.id.startswith('btn_vseeface_bridge_') and control.id.rsplit('_', 1)[1] in {'install','adopt','repair','remove'}:
                operation = control.id.rsplit('_', 1)[1]
                plan = plans.get(operation)
                updates['enabled'] = bool(plan)
                if plan:
                    updates['metadata'] = dict(control.metadata, confirmAction=True,
                        confirmationTitle=control.label,
                        confirmationText=f"{control.label} in:\n{plan['installation']}\n\nThis action manages the BepInEx loader and NCVSeeFaceBridge files. Original VSeeFace EXE/assemblies and other plugins are preserved. Installation, update and removal require VSeeFace to be closed.",
                        confirmationAcceptText=control.label,
                        confirmationTone='danger' if operation=='remove' else 'primary',
                        confirmationPayload={'approval_token': plan['approval_token']})
            controls.append(replace(control, **updates))
        return replace(self._surface, controls=tuple(controls), revision=self._revision)

    @staticmethod
    def _raise_if_rejected(result: object, message: str) -> None:
        if not bool(getattr(result, "accepted", False)):
            failure = getattr(result, "failure", None)
            raise RuntimeError(str(getattr(failure, "message", message)))

    def _restore_controls_state(self) -> None:
        config = getattr(self._application, 'config', None)
        saved = config.get('vseeface_controls_state', {}) if config else {}
        if not saved:
            return
        if not isinstance(saved, Mapping):
            raise ValueError('Saved VSeeFace controls must be a settings object.')
        for key, command, complete in (
            ('profile', self._application.body.update_profile, complete_body_profile),
            ('hand_calibration', self._application.body.update_hand_calibration, complete_hand_calibration),
        ):
            if key in saved:
                self._raise_if_rejected(command(complete(saved[key])), 'Could not restore VSeeFace ' + key + '.')
        if 'edit_emotion' in saved:
            self._raise_if_rejected(self._application.body.select_emotion(saved['edit_emotion']),
                                    'Could not restore the selected body emotion.')
        if 'live_sync' in saved:
            self._raise_if_rejected(self._application.body.set_live_sync(saved['live_sync']),
                                    'Could not restore Live Sync.')
        self._selected_body = str(saved.get('selected_body') or '')
        self._hand_preset = str(saved.get('hand_preset') or 'relaxed')
        debug = saved.get('hand_debug') or {}
        for axis in _HAND_AXES:
            if axis in debug:
                self._invoke('runtime.hand.set_axis', {'key': axis, 'value': debug[axis]})
        if 'active' in debug:
            self._invoke('runtime.hand.set_active', {'active': debug['active']})

    def _persist_state(self) -> None:
        config = getattr(self._application, 'config', None)
        if config is not None:
            body = self._application.body.snapshot()
            hands = dict(self._invoke('runtime.hand.snapshot') or {})
            state = dict(profile=_plain_mapping(body.profile),
                         hand_calibration=_plain_mapping(body.hand_calibration),
                         edit_emotion=body.edit_emotion, live_sync=not body.force_edit_mode,
                         selected_body=self._selected_body, hand_preset=self._hand_preset,
                         hand_debug=dict(hands.get('debug') or {}))
            self._raise_if_rejected(config.update('vseeface_controls_state', state),
                                    'Could not save VSeeFace controls.')
        if callable(self._persist):
            if self._persist() is False:
                raise RuntimeError('VSeeFace settings could not be saved: the session is read-only.')

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key in {'vseeface_bridge_enabled', 'vseeface_bridge_install_path'}:
            config = getattr(self._application, 'config', None)
            if config is None: raise RuntimeError('Runtime settings are unavailable.')
            if key == 'vseeface_bridge_enabled':
                value = bool(value)
                if not value:
                    self._invoke('runtime.speech_bridge.disable')
                else:
                    state = dict(self._invoke('runtime.speech_bridge.status') or {})
                    if not state.get('can_adopt') or not _same_installation(state.get('installation'), config.get('vseeface_bridge_install_path', '')):
                        raise ValueError('Check setup and install/adopt a verified bridge before enabling it.')
            else:
                value = str(value or '').strip()
            self._raise_if_rejected(config.update(key, value), 'Could not save VSeeFace bridge settings.')
            self._persist_state()
        elif key == "body_combo":
            selected = str(value or "").strip()
            if selected and selected not in self._body_catalog():
                raise ValueError(f"Unknown body profile '{value}'.")
            self._selected_body = selected
            self._persist_state()
        elif key == "emotion_combo":
            emotion = str(value or "neutral").strip().lower()
            self._raise_if_rejected(
                self._application.body.select_emotion(emotion),
                "Could not select VSeeFace body emotion.",
            )
            self._persist_state()
        elif key == "live_sync_checkbox":
            self._raise_if_rejected(
                self._application.body.set_live_sync(bool(value)),
                "Could not update VSeeFace live sync.",
            )
            self._persist_state()
        elif key in UI_SHELL_BODY_POSE_SPECS:
            control = self._controls[key]
            normalized = RuntimeConfigNativeAdapter._normalize(control, value)
            scale = int(UI_SHELL_BODY_POSE_SPECS[key].get("scale", 1) or 1)
            self._raise_if_rejected(
                self._application.body.update_pose(key, float(normalized) / scale),
                f"Could not update VSeeFace pose field '{key}'.",
            )
            self._persist_state()
        elif key == "hand_debug_active":
            self._invoke("runtime.hand.set_active", {"active": bool(value)})
            self._persist_state()
        elif key == "hand_calibration_preset":
            preset = str(value or "").strip().lower()
            if preset not in {"relaxed", "fist"}:
                raise ValueError(f"Unknown hand calibration preset '{value}'.")
            self._hand_preset = preset
            self._persist_state()
        elif key.startswith("hand_") and key.removeprefix("hand_") in _HAND_AXES:
            axis = key.removeprefix("hand_")
            control = self._controls[key]
            normalized = RuntimeConfigNativeAdapter._normalize(control, value)
            self._invoke(
                "runtime.hand.set_axis",
                {"key": axis, "value": float(normalized) / 10.0},
            )
            self._persist_state()
        else:
            raise KeyError(f"Unknown VSeeFace setting '{control_id}'.")
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        action = str(control_id or "").strip()
        if action == 'btn_vseeface_card_collapse':
            if not isinstance(payload, Mapping) or not isinstance(payload.get('collapsed'), bool):
                raise ValueError('Choose whether to expand or collapse the card.')
            card = str(payload.get('card', ''))
            section, separator, name = card.partition('::')
            if section not in self._surface.sections or not separator or not name:
                raise ValueError('Unknown VSeeFace card.')
            config = getattr(self._application, 'config', None)
            if config is None:
                raise RuntimeError('Runtime settings are unavailable.')
            previous = config.get('vseeface_collapsed_cards', {})
            if not isinstance(previous, Mapping):
                raise ValueError('Saved card preferences are invalid; they have been left untouched.')
            self._raise_if_rejected(config.update('vseeface_collapsed_cards',
                dict(previous, **{card: payload['collapsed']})), 'Could not save card display preferences.')
            self._persist_state()
        elif action == 'btn_vseeface_start':
            self._invoke('runtime.speech_bridge.launch')
        elif action == 'btn_vseeface_bridge_folder':
            chosen = payload[0] if isinstance(payload, (list, tuple)) and payload else payload
            if not chosen: return
            url = QtCore.QUrl(str(chosen))
            self.set_value('vseeface_bridge_install_path', url.toLocalFile() if url.isLocalFile() else str(chosen))
            self._invoke('runtime.speech_bridge.inspect')
        elif action == 'btn_vseeface_bridge_refresh':
            self._invoke('runtime.speech_bridge.inspect')
        elif action.startswith('btn_vseeface_bridge_') and action.rsplit('_',1)[1] in {'install','adopt','repair','remove'}:
            if not isinstance(payload, Mapping) or not payload.get('approval_token'):
                raise ValueError('Review and approve the bridge confirmation first.')
            self._invoke('runtime.speech_bridge.execute', dict(payload))
            self._persist_state()
        elif action in {'btn_vseeface_bridge_download', 'btn_vseeface_bridge_source', 'btn_vseeface_bridge_build_help'}:
            source = Path(__file__).resolve().parents[3]/'addons/vseeface_avatar/bridge_source'
            url = (QtCore.QUrl('https://www.vseeface.icu/#download') if action.endswith('_download') else
                   QtCore.QUrl.fromLocalFile(str(source/'README.md' if action.endswith('_help') else source)))
            if not QtGui.QDesktopServices.openUrl(url): raise RuntimeError('Could not open the VSeeFace download/source location.')
        elif action == "btn_body_load":
            if not self._selected_body:
                raise ValueError("Select a body profile to load.")
            loaded = dict(
                self._invoke(
                    "runtime.body_profiles.load",
                    {"name": self._selected_body},
                )
                or {}
            )
            self._raise_if_rejected(
                self._application.body.update_profile(complete_body_profile(_plain_mapping(loaded.get("profile")))),
                "Could not apply the VSeeFace body profile.",
            )
            hands = _plain_mapping(loaded.get("hands"))
            if hands:
                self._raise_if_rejected(
                    self._application.body.update_hand_calibration(complete_hand_calibration(hands)),
                    "Could not apply VSeeFace hand calibration.",
                )
            self._persist_state()
        elif action in {"btn_body_save", "btn_body_save_as"}:
            name = self._selected_body
            if action == "btn_body_save_as":
                name = str(payload or "").strip()
            if not name:
                raise ValueError("Enter a body profile name.")
            body = self._application.body.snapshot()
            self._invoke(
                "runtime.body_profiles.save",
                {
                    "name": name,
                    "profile": _plain_mapping(body.profile),
                    "hands": _plain_mapping(body.hand_calibration),
                },
            )
            self._selected_body = name
            self._persist_state()
        elif action == "btn_body_delete":
            if not self._selected_body:
                raise ValueError("Select a body profile to delete.")
            self._invoke(
                "runtime.body_profiles.delete",
                {"name": self._selected_body},
            )
            self._selected_body = ""
            self._persist_state()
        elif action == "btn_vseeface_hide_interface":
            if not callable(self._focus_request):
                raise RuntimeError("The native avatar focus window is unavailable.")
            self._focus_request("VSeeFace")
        elif action == "hand_load_preset":
            self._invoke(
                "runtime.hand.load_preset",
                {"preset_id": self._hand_preset,
                 "calibration": _plain_mapping(self._application.body.snapshot().hand_calibration)},
            )
            self._persist_state()
        elif action == "hand_save_preset":
            values = dict(
                self._invoke(
                    "runtime.hand.save_preset",
                    {"preset_id": self._hand_preset},
                )
                or {}
            )
            body = self._application.body.snapshot()
            calibration = _plain_mapping(body.hand_calibration)
            calibration[self._hand_preset] = values
            self._raise_if_rejected(
                self._application.body.update_hand_calibration(calibration),
                "Could not save hand calibration.",
            )
            self._persist_state()
        else:
            raise KeyError(f"Unknown VSeeFace action '{control_id}'.")
        self._revision += 1
        self.changed.emit()


def _pose_control(key: str, spec: Mapping[str, object]) -> NativeControl:
    scale = int(spec.get("scale", 1) or 1)
    section = "Dynamics" if key in {
        "eye_activity", "breath_speed", "shoulder_lift", "idle_speed", "idle_intensity"
    } else "Body"
    return NativeControl(
        key,
        str(spec.get("title") or key),
        NativeControlKind.SLIDER,
        section,
        minimum=round(float(spec.get("minimum", 0.0)) * scale),
        maximum=round(float(spec.get("maximum", 100.0)) * scale),
        step=1,
        default_value=round(float(DEFAULT_POSE.get(key, spec.get("default", 0.0))) * scale),
        metadata={"displayScale": scale},
    )


def build_vseeface_avatar_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
    focus_request: Callable[[str], object] | None = None,
) -> VSeeFaceAvatarNativeAdapter:
    controls = [
        NativeControl("vseeface_runtime_summary", "VSeeFace runtime", NativeControlKind.DISPLAY, "Overview"),
        NativeControl('btn_vseeface_start', 'Start VSeeFace', NativeControlKind.ACTION, 'Overview', description='Open the saved VSeeFace installation. An already running copy is not started again.'),
        NativeControl("btn_vseeface_hide_interface", "Hide NC Interface", NativeControlKind.ACTION, "Overview", metadata={"execution": "ui"}),
        NativeControl('vseeface_bridge_instructions', 'VSeeFace setup and required settings',
                      NativeControlKind.DISPLAY, 'Speech lip sync', metadata={'stackedLayout': True}),
        NativeControl('vseeface_bridge_install_path', 'VSeeFace folder', NativeControlKind.TEXT, 'Speech lip sync', description='The extracted folder containing VSeeFace.exe. Folder changes apply at the next chat initialization.'),
        NativeControl('btn_vseeface_bridge_folder', 'Choose VSeeFace folder', NativeControlKind.ACTION, 'Speech lip sync', metadata={'folderPicker': True, 'dialogTitle': 'Choose the extracted VSeeFace folder'}),
        NativeControl('btn_vseeface_bridge_download', 'Download VSeeFace', NativeControlKind.ACTION, 'Speech lip sync', metadata={'execution': 'ui'}),
        NativeControl('vseeface_bridge_enabled', 'Enable speech lip sync', NativeControlKind.BOOLEAN, 'Speech lip sync', default_value=False, description='Enabling applies at the next chat initialization. Disabling stops lip sync immediately; audible NC speech continues.'),
        NativeControl('vseeface_bridge_status', 'Last checked status', NativeControlKind.DISPLAY, 'Speech lip sync'),
        NativeControl('btn_vseeface_bridge_refresh', 'Check setup / refresh status', NativeControlKind.ACTION, 'Speech lip sync'),
        NativeControl('btn_vseeface_bridge_install', 'Install bridge', NativeControlKind.ACTION, 'Speech lip sync'),
        NativeControl('btn_vseeface_bridge_adopt', 'Use installed bridge', NativeControlKind.ACTION, 'Speech lip sync'),
        NativeControl('btn_vseeface_bridge_repair', 'Update / repair bridge', NativeControlKind.ACTION, 'Speech lip sync'),
        NativeControl('btn_vseeface_bridge_remove', 'Remove bridge', NativeControlKind.ACTION, 'Speech lip sync'),
        NativeControl('btn_vseeface_bridge_source', 'Open bridge source', NativeControlKind.ACTION, 'Speech lip sync', metadata={'execution': 'ui'}),
        NativeControl('btn_vseeface_bridge_build_help', 'Self-build instructions', NativeControlKind.ACTION, 'Speech lip sync', metadata={'execution': 'ui'}),
        NativeControl("body_combo", "Body preset", NativeControlKind.CHOICE, "Body", choices=(NativeChoice("", "No Configs"),)),
        NativeControl("btn_body_load", "Load", NativeControlKind.ACTION, "Body"),
        NativeControl("btn_body_save", "Save", NativeControlKind.ACTION, "Body"),
        NativeControl("btn_body_save_as", "Save As", NativeControlKind.ACTION, "Body", metadata={"execution": "ui", "inputPrompt": True, "dialogTitle": "Save Body Config", "inputLabel": "Body config name", "placeholderText": "New body profile"}),
        NativeControl("btn_body_delete", "Delete", NativeControlKind.ACTION, "Body", metadata={"destructive": True}),
        NativeControl("emotion_combo", "Body emotion", NativeControlKind.CHOICE, "Body", default_value="neutral", choices=choices(tuple((str(item).lower(), str(item)) for item in UI_SHELL_BODY_EMOTIONS))),
        NativeControl("live_sync_checkbox", "Live Sync", NativeControlKind.BOOLEAN, "Body", default_value=False),
    ]
    controls.extend(_pose_control(key, spec) for key, spec in UI_SHELL_BODY_POSE_SPECS.items())
    controls.extend(
        (
            NativeControl("hand_debug_active", "Activate Debug Override", NativeControlKind.BOOLEAN, "Hand Doctor", default_value=False),
            NativeControl("hand_calibration_preset", "Calibration preset", NativeControlKind.CHOICE, "Hand Doctor", default_value="relaxed", choices=choices((("relaxed", "Relaxed"), ("fist", "Fist")))),
            NativeControl("hand_load_preset", "Load preset to edit", NativeControlKind.ACTION, "Hand Doctor"),
            NativeControl("hand_finger_x", "Finger X", NativeControlKind.SLIDER, "Hand Doctor", minimum=-1800, maximum=1800, step=1, default_value=0, metadata={"displayScale": 10}),
            NativeControl("hand_finger_y", "Finger Y", NativeControlKind.SLIDER, "Hand Doctor", minimum=-1800, maximum=1800, step=1, default_value=0, metadata={"displayScale": 10}),
            NativeControl("hand_finger_z", "Finger Z", NativeControlKind.SLIDER, "Hand Doctor", minimum=-1800, maximum=1800, step=1, default_value=0, metadata={"displayScale": 10}),
            NativeControl("hand_thumb_x", "Thumb X", NativeControlKind.SLIDER, "Hand Doctor", minimum=-1800, maximum=1800, step=1, default_value=0, metadata={"displayScale": 10}),
            NativeControl("hand_thumb_y", "Thumb Y", NativeControlKind.SLIDER, "Hand Doctor", minimum=-1800, maximum=1800, step=1, default_value=0, metadata={"displayScale": 10}),
            NativeControl("hand_thumb_z", "Thumb Z", NativeControlKind.SLIDER, "Hand Doctor", minimum=-1800, maximum=1800, step=1, default_value=0, metadata={"displayScale": 10}),
            NativeControl("hand_save_preset", "Save calibration preset", NativeControlKind.ACTION, "Hand Doctor"),
        )
    )
    surface = NativeSurface(
        id="vseeface_avatar_tab",
        title="VSeeFace",
        addon_id="nc.vseeface_avatar",
        sections=("Overview", "Speech lip sync", "Body", "Dynamics", "Hand Doctor"),
        description="Configure VSeeFace body pose, dynamics, and hand calibration.",
        controls=apply_card_layout(tuple(controls)),
    )
    # Route presentation preferences through the existing native action contract.
    # Sharing the first card's placement prevents an empty hidden-action card.
    state_action = NativeControl('btn_vseeface_card_collapse', 'Card display',
        NativeControlKind.ACTION, 'Overview', default_value={},
        metadata=dict(surface.controls[0].metadata, visible=False))
    surface = replace(surface, controls=(*surface.controls, state_action))
    return VSeeFaceAvatarNativeAdapter(
        application_facade,
        surface,
        persist=persist,
        focus_request=focus_request,
    )


__all__ = ["VSeeFaceAvatarNativeAdapter", "build_vseeface_avatar_adapter"]
