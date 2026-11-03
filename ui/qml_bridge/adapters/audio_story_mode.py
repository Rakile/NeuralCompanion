"""Complete typed native-QML adapter for Audio Story Mode."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from PySide6 import QtGui

from addons.audio_story_mode.native_contract import NATIVE_CONTROL_SPECS
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.parity_contract import controls_from_specs, sections_from_specs
from ui.qml_bridge.native_contracts import NativeControl, NativeSurface, choices
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_ACTION_IDS = {
    str(spec["id"])
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}

_ACTION_METADATA: dict[str, dict[str, Any]] = {
    str(spec["id"]): dict(spec.get("metadata") or {})
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}

_ACTION_METADATA.update(
    {
        "audio_story_import_button": {
            "execution": "ui",
            "filePicker": True,
            "multiple": True,
            "dialogTitle": "Import story audio",
            "nameFilters": ["Audio files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.opus)", "All files (*)"],
        },
        "audio_story_project_add_audio_button": {
            "execution": "ui",
            "filePicker": True,
            "multiple": True,
            "dialogTitle": "Add chapter audio",
            "nameFilters": ["Audio files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.opus)", "All files (*)"],
        },
        "audio_story_project_relink_button": {
            "execution": "ui",
            "filePicker": True,
            "dialogTitle": "Relink chapter audio",
            "nameFilters": ["Audio files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.opus)", "All files (*)"],
        },
        "unnamed_qpushbutton_choose_chatlog_json": {
            "execution": "ui",
            "filePicker": True,
            "dialogTitle": "Choose chatlog JSON",
            "nameFilters": ["Chatlog JSON (*.json *.jsonl *.ndjson)", "All files (*)"],
        },
        "unnamed_qpushbutton_choose_markdown": {
            "execution": "ui",
            "filePicker": True,
            "dialogTitle": "Choose Markdown document",
            "nameFilters": ["Markdown documents (*.md *.markdown)", "All files (*)"],
        },
        "audio_story_project_new_button": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "New Audio Story project",
            "inputLabel": "Project name",
            "placeholderText": "Untitled Audio Story",
        },
        "audio_story_project_rename_button": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "Rename Audio Story project",
            "inputLabel": "New project name",
        },
        "audio_story_project_chapter_rename_button": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "Rename chapter",
            "inputLabel": "New chapter name",
        },
        "audio_story_project_save_current_button": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "Save current story as project",
            "inputLabel": "Project name",
        },
        "audio_story_settings_preset_save_button": {
            "execution": "ui",
            "inputPrompt": True,
            "dialogTitle": "Save Audio Story settings preset",
            "inputLabel": "Preset name",
        },
        "audio_story_transcription_console_copy_button": {"execution": "ui"},
        "audio_story_cast_install_button": {"destructive": True},
        "unnamed_qpushbutton_approve_and_generate": {"destructive": True},
    }
)


def _build_controls() -> tuple[NativeControl, ...]:
    rendered: list[NativeControl] = []
    for control in controls_from_specs(NATIVE_CONTROL_SPECS):
        if control.id in _ACTION_METADATA:
            rendered.append(replace(control, metadata=dict(_ACTION_METADATA[control.id])))
        else:
            rendered.append(control)
    return apply_card_layout(rendered)


class AudioStoryModeNativeAdapter(NativeSurfaceAdapter):
    """Expose all 158 reviewed Audio Story controls through one typed surface."""

    def __init__(
        self,
        application_facade: Any,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__("audio_story_mode_runtime", "nc.audio_story_mode", parent)
        self._application = application_facade
        self._persist = persist
        self._revision = 0
        self._surface = NativeSurface(
            id=self.surface_id,
            title="Audio Story Mode",
            addon_id=self.addon_id,
            sections=sections_from_specs(NATIVE_CONTROL_SPECS),
            description=(
                "Audio projects, source transcription, story planning, scene review, "
                "synchronized images, Novel Workshop, playback, and casting."
            ),
            controls=_build_controls(),
        )

    def _invoke(self, capability: str, payload: dict[str, Any] | None = None) -> Any:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Audio Story Mode is unavailable."))
            )
        return result.value

    def snapshot(self) -> NativeSurface:
        state = dict(self._invoke("runtime.audio_story.native_snapshot") or {})
        controls_state = dict(state.get("controls") or {})
        values = dict(controls_state.get("values") or {})
        option_overrides = dict(controls_state.get("options") or {})
        enabled_overrides = dict(controls_state.get("enabled") or {})
        rendered: list[NativeControl] = []
        for control in self._surface.controls:
            dynamic = option_overrides.get(control.id)
            replacement_choices = (
                choices(tuple(tuple(item) for item in dynamic))
                if isinstance(dynamic, (list, tuple)) and dynamic
                else control.choices
            )
            rendered.append(
                replace(
                    control,
                    value=values.get(control.id, control.default_value),
                    choices=replacement_choices,
                    enabled=bool(enabled_overrides.get(control.id, control.enabled)),
                )
            )
        return replace(
            self._surface,
            controls=tuple(rendered),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        self._invoke(
            "runtime.audio_story.native_update_control",
            {"control_id": str(control_id or "").strip(), "value": value},
        )
        if callable(self._persist):
            self._persist()
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        key = str(control_id or "").strip()
        if key not in _ACTION_IDS:
            raise KeyError(f"Unknown Audio Story action {control_id!r}.")
        metadata = _ACTION_METADATA[key]
        request: dict[str, Any] = {"payload": payload}
        if bool(metadata.get("destructive")):
            request["confirmed"] = True
        result = self._invoke(
            "runtime.audio_story.native_control_action",
            {"control_id": key, "payload": request},
        )
        if key == "audio_story_transcription_console_copy_button":
            presentation = dict((result or {}).get("presentation") or {})
            clipboard = QtGui.QGuiApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("The system clipboard is unavailable.")
            clipboard.setText(str(presentation.get("clipboard_suggestion") or ""))
        self._revision += 1
        self.changed.emit()


def build_audio_story_mode_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> AudioStoryModeNativeAdapter:
    """Register UI without requiring the optional addon to be loaded."""
    return AudioStoryModeNativeAdapter(application_facade, persist=persist)


__all__ = ["AudioStoryModeNativeAdapter", "build_audio_story_mode_adapter"]
