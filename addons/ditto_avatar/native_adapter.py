"""Addon-local native QML controls; heavy Ditto work stays in its worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
import threading
import weakref

from PySide6.QtCore import QUrl, Qt, Signal, Slot
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind as Kind, NativeSurface, choices
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


class DittoNativeAdapter(NativeSurfaceAdapter):
    """Shared thin capability routing for the two Ditto addon surfaces."""

    _refreshRequested = Signal()

    title = "Ditto"
    setting_ids: frozenset[str] = frozenset()
    actions: dict[str, str] = {}
    pickers: dict[str, str] = {}
    snapshot_capability = 'snapshot'
    section_order = ('Avatar','Package emotions','Animation','Generation','Runtime','Preview','Advanced')

    def __init__(self, application_facade, surface_id, addon_id, *, persist=None, parent=None):
        super().__init__(surface_id, addon_id, parent)
        self._application = application_facade
        self._persist = persist
        self._revision = 0
        self._closed = False
        self._refresh_pending = False
        self._refresh_lock = threading.Lock()
        self._unsubscribe = None
        self._refreshRequested.connect(self._deliver_refresh, Qt.QueuedConnection)

    def _ensure_subscription(self):
        if self._closed or self._unsubscribe is not None:
            return
        reference = weakref.ref(self)
        def on_change():
            adapter = reference()
            if adapter is not None:
                adapter._request_refresh()
        try:
            unsubscribe = self._invoke('subscribe', {'callback':on_change})
        except Exception:
            # Disabled/unavailable addons must not prevent host startup.
            return
        if callable(unsubscribe):
            self._unsubscribe = unsubscribe
            self.destroyed.connect(unsubscribe)

    def _request_refresh(self):
        # Called by the producer: enqueue only, never call UI or read snapshots.
        with self._refresh_lock:
            if self._closed or self._refresh_pending:
                return
            self._refresh_pending = True
        try:
            self._refreshRequested.emit()
        except RuntimeError:
            # QObject teardown may race a notification already in flight.
            pass

    @Slot()
    def _deliver_refresh(self):
        with self._refresh_lock:
            self._refresh_pending = False
            if self._closed:
                return
        self._changed()

    def _invoke(self, capability, payload=None):
        result = self._application.addons.invoke_addon_capability(self.addon_id, f"runtime.ditto.{capability}", dict(payload or {}))
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(str(getattr(failure, "message", "Ditto addon is unavailable.")))
        value = result.value
        if isinstance(value, Mapping) and value.get("ok") is False:
            raise RuntimeError(str(value.get("error") or "Ditto action failed."))
        return value

    def _state(self):
        try:
            state = self._invoke(self.snapshot_capability)
            if not isinstance(state, Mapping):
                raise RuntimeError("Ditto addon is disabled or unavailable.")
            return dict(state), True
        except Exception as error:
            # An absent/disabled addon must never prevent host startup.
            return {"status": str(error) or "Ditto addon is unavailable."}, False

    def _field(self, state, key, label, kind, section, default=None, **kwargs):
        if kind == Kind.CHOICE and not kwargs.get('choices'):
            kwargs['choices'] = choices((('', 'Choose after creating a package'),))
        return NativeControl(key, label, kind, section, value=state.get(key, default), **kwargs)

    def _choice(self, state, key, label, section, default, values, **kwargs):
        return self._field(state, key, label, Kind.CHOICE, section, default, choices=choices((v, v) for v in values), **kwargs)

    @staticmethod
    def _button(key, label, section, **kwargs):
        return NativeControl(key, label, Kind.ACTION, section, metadata={"execution": "worker", **kwargs})

    def _runtime_controls(self, state):
        loaded = bool(state.get("loaded"))
        return (
            self._field(state, "ditto_repo_path", "Ditto installation", Kind.TEXT, "Advanced", "Ditto"),
            self._field(state, "ditto_python_path", "Ditto Python executable", Kind.TEXT, "Advanced", "", description="Leave blank to use the installation's .venv/Scripts/python.exe."),
            self._button("ditto_load", "Load models", "Runtime"),
            self._button("ditto_unload", "Unload models", "Runtime"),
            self._button("ditto_cancel", "Cancel and unload", "Runtime"),
            NativeControl("ditto_loaded", "Model state", Kind.DISPLAY, "Runtime", value="Loaded" if loaded else "Unloaded"),
            NativeControl("ditto_status", "Ditto status", Kind.DISPLAY, "Runtime", value=state.get("status", "Idle")),
            NativeControl("ditto_progress", "Progress", Kind.PROGRESS, "Runtime", value=float(state.get("progress", 0)) * 100, minimum=0, maximum=100),
        )

    def _preview_controls(self, state):
        result = state.get('last_result') or {}
        summary = (f"{result.get('frame_count', 0)} frames at {result.get('fps', 25)} FPS. "
                   f"{result.get('avatar_path') or result.get('frame_dir') or ''}") if result else ''
        return (
            NativeControl("ditto_preview", "Avatar preview", Kind.IMAGE, "Preview", value=QUrl.fromLocalFile(str(state['preview_path'])).toString() if state.get('preview_path') and not state.get('session_running') else '', description='During chat, use Avatar Preview for live playback.'),
            NativeControl("ditto_last_result", "Latest result", Kind.DISPLAY, "Preview", value=summary),
        )

    def controls(self, state):
        raise NotImplementedError

    def snapshot(self):
        self._ensure_subscription()
        state, available = self._state()
        busy = bool(state.get("busy"))
        loaded = bool(state.get("loaded"))
        controls = []
        for control in self.controls(state):
            enabled = available and not busy
            if control.kind in (Kind.DISPLAY, Kind.IMAGE, Kind.PROGRESS):
                enabled = True
            elif control.id == "ditto_cancel":
                enabled = available and busy
            elif control.id == "ditto_unload":
                enabled = available and (loaded or state.get('crop_models_loaded')) and not busy
            elif control.id == "ditto_load":
                enabled = available and not loaded and not busy
            elif control.id == "ditto_delete_package":
                from ui.qml_bridge.adapters.avatar_package_actions import can_maintain_packages
                enabled = (enabled and bool(control.metadata.get('confirmationPayload', {}).get('token'))
                    and not state.get('session_running') and not state.get('test_preview_active')
                    and not state.get('worker_running') and can_maintain_packages(self._application))
            if state.get('session_running') and control.id in ('ditto_repo_path','ditto_python_path','ditto_avatar_path','ditto_pack_id','ditto_variant_id'):
                enabled = False
            controls.append(replace(control, enabled=enabled))
        sections = tuple(dict.fromkeys(c.section for c in controls))
        sections = tuple(sorted(sections,key=lambda name:self.section_order.index(name) if name in self.section_order else len(self.section_order)))
        controls.sort(key=lambda control:sections.index(control.section))
        return NativeSurface(self.surface_id, self.title, self.addon_id, sections, apply_card_layout(controls), revision=self._revision)

    def _changed(self):
        self._revision += 1
        self.changed.emit()

    def set_value(self, control_id, value):
        if control_id not in self.setting_ids and not control_id.startswith('ditto_enable_'):
            raise KeyError(f"Unknown Ditto setting {control_id!r}.")
        try:
            self._invoke("update", {"key": control_id, "value": value})
            if self._persist is not None:
                self._persist()
        finally:
            self._changed()

    def trigger(self, control_id):
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id, payload):
        if control_id in self.pickers:
            selected = payload[0] if isinstance(payload, (list, tuple)) and payload else payload
            if selected:
                url = QUrl(str(selected))
                path = url.toLocalFile() if url.isLocalFile() else str(selected)
                if control_id == "ditto_choose_output":
                    path = str(Path(path) / "ditto-avatar")
                self.set_value(self.pickers[control_id], path)
            return
        action = self.actions.get(control_id)
        if action is None:
            raise KeyError(f"Unknown Ditto action {control_id!r}.")
        try:
            self._invoke("action", {"action": action, "payload": payload})
        finally:
            self._changed()

    def close(self):
        with self._refresh_lock:
            self._closed = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None


class DittoAvatarNativeAdapter(DittoNativeAdapter):
    title = "Ditto Avatar"
    setting_ids = frozenset(("ditto_repo_path", "ditto_python_path", "ditto_avatar_path", "ditto_emotion", "ditto_expression", "ditto_motion", "ditto_relative", "ditto_eyes", "ditto_blink_style", "ditto_conditioning", "ditto_steps", "ditto_smoothing", "ditto_seed", "ditto_source_smoothing", "ditto_pack_id", "ditto_variant_id", "ditto_avatar_selection", "ditto_emotion_selection",
        "ditto_pitch_strength", "ditto_yaw_strength", "ditto_roll_strength", "ditto_translation_strength",
        "ditto_blink_open", "ditto_pitch_offset", "ditto_yaw_offset", "ditto_roll_offset",
        "ditto_fade_in", "ditto_fade_out", "ditto_fade_target", "ditto_fade_keys",
        "ditto_eye_first_frame", "ditto_stitching"))
    actions = {"ditto_load": "load", "ditto_unload": "unload", "ditto_cancel": "cancel", "ditto_activate": "activate"}
    pickers = {"ditto_choose_avatar": "ditto_avatar_path"}

    def __init__(self, application_facade, *, persist=None, parent=None):
        super().__init__(application_facade, "ditto_avatar_tab", "nc.ditto_avatar", persist=persist, parent=parent)

    def trigger_with_payload(self, control_id, payload):
        if control_id != 'ditto_delete_package':
            return super().trigger_with_payload(control_id, payload)
        from ui.qml_bridge.adapters.avatar_package_actions import package_maintenance
        try:
            with package_maintenance(self._application):
                result = self._invoke('action', {'action':'delete_package', 'payload':payload})
                if not isinstance(result, Mapping) or result.get('ok') is not True:
                    raise RuntimeError('Package deletion was not confirmed by Ditto. Refresh and try again.')
                if callable(self._persist):
                    self._persist()
        finally:
            self._changed()

    def controls(self, state):
        pack = next((p for p in state.get('packages', ()) if p['id'] == state.get('ditto_pack_id')), {})
        name = pack.get('display_name') or state.get('ditto_pack_id') or 'selected package'
        return (
            *self._runtime_controls(state),
            NativeControl('ditto_tuning_scope', 'Animation and generation settings', Kind.DISPLAY, 'Avatar',
                value=('Saved automatically for avatar: ' + (next((v['display_name'] for v in state.get('variants', ())
                    if v['id'] == state.get('ditto_variant_id')), '') or state.get('ditto_variant_id') or 'base avatar')
                    + ' in package: ' + state['ditto_pack_id'] + '. Each avatar keeps its own tuning, including when selected by reply emotion.')
                    if state.get('ditto_pack_id') else 'No package selected: editing standalone defaults. Select a package to save its own tuning.'),
            self._field(state,'ditto_pack_id','Avatar package',Kind.CHOICE,'Avatar','', choices=choices(
                [('', 'Standalone prepared avatar')] + [(p['id'],p['display_name']) for p in state.get('packages',())])),
            self._button('ditto_delete_package', 'Delete package', 'Avatar', destructive=True,
                confirmationTitle='Permanently delete avatar package',
                confirmationText=f'Permanently delete “{name}” ({state.get("ditto_pack_id") or "none"}) and all files inside its managed package folder? This cannot be undone. Original media outside that folder is preserved. Stop chat or preview and unload Ditto first.',
                confirmationAcceptText='Delete permanently',
                confirmationPayload={'pack_id':state.get('ditto_pack_id',''), 'token':pack.get('delete_token',''), 'confirmed':True}),
            self._field(state,'ditto_variant_id','Fixed avatar',Kind.CHOICE,'Avatar','', choices=choices(
                (v['id'],v['display_name']) for v in state.get('variants',()))),
            self._choice(state,'ditto_avatar_selection','Source avatar selection','Avatar','Fixed',('Fixed','From reply emotion'),
                description='Reply emotions can select different prepared avatars in this package.'),
            *(self._field({**state, 'ditto_enable_'+tag:tag in state.get('enabled_package_emotions',state.get('package_emotions',()))},
                'ditto_enable_'+tag,'Enable '+tag,Kind.BOOLEAN,'Package emotions',True) for tag in state.get('package_emotions',())),
            self._field(state, "ditto_avatar_path", "Prepared Ditto avatar", Kind.TEXT, "Advanced", "", description="Standalone compatibility path; package selection fills this automatically."),
            self._button("ditto_choose_avatar", "Choose prepared avatar", "Advanced", execution="ui", folderPicker=True, dialogTitle="Select prepared Ditto avatar"),
            self._button("ditto_activate", "Use this avatar", "Avatar"),
            self._choice(state,'ditto_emotion_selection','Generated expression selection','Animation','Manual',('Manual','From reply emotion'),
                description='Independent of source-avatar selection. Maps each speech chunk to Ditto\'s native emotions.'),
            self._field(state, "ditto_emotion", "Emotion", Kind.CHOICE, "Animation", "Neutral", choices=choices((v, v) for v in ("Angry", "Disgust", "Fear", "Happy", "Neutral", "Sad", "Surprise", "Contempt"))),
            self._field(state, "ditto_expression", "Expression strength", Kind.NUMBER, "Animation", 1.0, minimum=0, maximum=2, step=0.05),
            self._field(state, "ditto_pitch_strength", "Pitch strength", Kind.NUMBER, "Animation", 1.0, minimum=0, maximum=2, step=0.05),
            self._field(state, "ditto_yaw_strength", "Yaw strength", Kind.NUMBER, "Animation", 1.0, minimum=0, maximum=2, step=0.05),
            self._field(state, "ditto_roll_strength", "Roll strength", Kind.NUMBER, "Animation", 1.0, minimum=0, maximum=2, step=0.05),
            self._field(state, "ditto_translation_strength", "Translation strength", Kind.NUMBER, "Animation", 1.0, minimum=0, maximum=2, step=0.05),
            self._choice(state, "ditto_motion", "Motion mode", "Animation", "Automatic", ("Automatic", "Expression only", "Animate head and expression")),
            self._field(state, "ditto_relative", "Relative motion", Kind.BOOLEAN, "Animation", True, description="Retains the source expression baseline. Disable to compare sustained emotional expressions."),
            self._choice(state, "ditto_conditioning", "Motion conditioning", "Animation", "Source face", ("Source face", "Checkpoint reference")),
            self._choice(state, "ditto_eyes", "Eye animation", "Animation", "Automatic", ("Automatic", "Enabled", "Disabled")),
            self._choice(state, "ditto_blink_style", "Eye motion source", "Animation", "Checkpoint blink sequence", ("Checkpoint blink sequence", "Generated eye motion")),
            self._field(state, "ditto_pitch_offset", "Pitch offset (degrees)", Kind.NUMBER, "Animation", 2.0, minimum=-90, maximum=90, step=0.1),
            self._field(state, "ditto_yaw_offset", "Yaw offset (degrees)", Kind.NUMBER, "Animation", 0.0, minimum=-90, maximum=90, step=0.1),
            self._field(state, "ditto_roll_offset", "Roll offset (degrees)", Kind.NUMBER, "Animation", 0.0, minimum=-90, maximum=90, step=0.1),
            self._field(state, "ditto_blink_open", "Open-eye frames", Kind.INTEGER, "Animation", 0, minimum=-1, maximum=10000, description="Open-eye frames between blinks. 0 = random spacing; -1 = no blink sequence. Requires eye animation and the checkpoint blink sequence."),
            self._field(state, "ditto_eye_first_frame", "Use first-frame eye conditioning", Kind.BOOLEAN, "Animation", False, description="Uses the first source frame's eye opening and gaze as the conditioning reference, rather than following source-video eye changes. Blinking controls still apply."),
            self._field(state, "ditto_steps", "Sampling steps", Kind.INTEGER, "Generation", 50, minimum=1, maximum=100),
            self._field(state, "ditto_smoothing", "Generated motion smoothing", Kind.INTEGER, "Generation", 3, minimum=1, maximum=79),
            self._field(state, "ditto_source_smoothing", "Source motion smoothing", Kind.INTEGER, "Generation", 13, minimum=1, maximum=101),
            self._field(state, "ditto_seed", "Seed", Kind.TEXT, "Generation", "", description="Blank chooses a random seed. Set the same number to compare settings."),
            self._field(state, "ditto_fade_in", "Fade in (frames)", Kind.INTEGER, "Generation", 0, minimum=0, maximum=1000000, description="Per rendered speech chunk at 25 FPS; 0 disables."),
            self._field(state, "ditto_fade_out", "Fade out (frames)", Kind.INTEGER, "Generation", 0, minimum=0, maximum=1000000, description="Per rendered speech chunk at 25 FPS; 0 disables."),
            self._choice(state, "ditto_fade_target", "Fade reference", "Generation", "Initial generated pose", ("Initial generated pose", "Source pose")),
            self._choice(state, "ditto_fade_keys", "Fade components", "Generation", "Expression only", ("Expression only", "Expression and head motion")),
            self._field(state, "ditto_stitching", "Use stitching correction", Kind.BOOLEAN, "Generation", True, description="Applies a final alignment correction between the animated face and its source. Usually keep this enabled."),
            NativeControl("ditto_render_capture", "Render job settings", Kind.DISPLAY, "Generation", value="Changes apply to the next speech chunk sent for rendering. Frames already being generated or waiting to play keep their current settings."),
            NativeControl("ditto_timing", "Output timing", Kind.DISPLAY, "Generation", value="Ditto generates at 25 FPS. The source loop continues across audio chunks."),
            NativeControl("ditto_poc_scope", "Local desktop preview", Kind.DISPLAY, "Generation", value="Uses Neural Companion's speech chunks, buffering and audio clock. Avatar Preview provides local playback."),
            *self._preview_controls(state),
        )


def build_ditto_avatar_adapter(application_facade, persist=None, parent=None):
    return DittoAvatarNativeAdapter(application_facade, persist=persist, parent=parent)


__all__ = ["DittoAvatarNativeAdapter", "DittoNativeAdapter", "build_ditto_avatar_adapter"]
