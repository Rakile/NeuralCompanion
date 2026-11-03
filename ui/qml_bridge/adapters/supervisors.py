"""Shared native QML editor for sensory supervisor profiles and rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping
from uuid import uuid4

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


STRICTNESS = ("Interpret freely", "Follow closely", "Say almost exactly")
EMOTIONS = (
    "Auto",
    "neutral",
    "happy",
    "angry",
    "calculating",
    "condescending",
    "sad",
    "shy",
    "surprised",
)
REPEAT_MODES = ("One-off", "Every Nth match", "Meaningful change only")


@dataclass(frozen=True, slots=True)
class SupervisorSpec:
    surface_id: str
    addon_id: str
    title: str
    prefix: str
    trigger_label: str
    description: str

    @property
    def enabled_key(self) -> str:
        return f"{self.prefix}_enabled"

    @property
    def prompt_key(self) -> str:
        return f"{self.prefix}_prompt_template"

    @property
    def personas_key(self) -> str:
        return f"{self.prefix}_personas"

    @property
    def selected_key(self) -> str:
        return f"{self.prefix}_selected_persona_id"


class SupervisorNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        spec: SupervisorSpec,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._spec = spec
        self._persist = persist
        self._revision = 0
        self._selected_behavior = ""

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", f"{self._spec.title} is unavailable."))
            )
        return result.value

    def _snapshot(self) -> dict[str, object]:
        value = self._invoke("runtime.supervisor.snapshot")
        if not isinstance(value, Mapping):
            raise RuntimeError(f"{self._spec.title} snapshot is not a mapping.")
        return dict(value)

    def _state_only(self, payload: Mapping[str, object]) -> dict[str, object]:
        return {
            self._spec.enabled_key: bool(payload.get(self._spec.enabled_key, True)),
            self._spec.prompt_key: str(payload.get(self._spec.prompt_key) or ""),
            self._spec.personas_key: [
                dict(item) for item in list(payload.get(self._spec.personas_key) or [])
            ],
            self._spec.selected_key: str(payload.get(self._spec.selected_key) or ""),
        }

    @staticmethod
    def _active_persona(state: Mapping[str, object], spec: SupervisorSpec) -> dict[str, object]:
        personas = list(state.get(spec.personas_key) or [])
        selected = str(state.get(spec.selected_key) or "")
        for item in personas:
            if str(dict(item).get("id") or "") == selected:
                return dict(item)
        return dict(personas[0]) if personas else {}

    def _active_behavior(self, persona: Mapping[str, object]) -> dict[str, object]:
        behaviors = [dict(item) for item in list(persona.get("behaviors") or [])]
        known = {str(item.get("id") or "") for item in behaviors}
        if self._selected_behavior not in known:
            self._selected_behavior = str(behaviors[0].get("id") or "") if behaviors else ""
        return next(
            (item for item in behaviors if str(item.get("id") or "") == self._selected_behavior),
            {},
        )

    def snapshot(self) -> NativeSurface:
        payload = self._snapshot()
        state = self._state_only(payload)
        personas = [dict(item) for item in list(state.get(self._spec.personas_key) or [])]
        active = self._active_persona(state, self._spec)
        behavior = self._active_behavior(active)
        persona_options = tuple(
            NativeChoice(str(item.get("id") or ""), str(item.get("name") or "Unnamed Profile"))
            for item in personas
            if str(item.get("id") or "")
        )
        behavior_options = tuple(
            NativeChoice(
                str(item.get("id") or ""),
                str(item.get("trigger") or "New reaction rule")[:90],
            )
            for item in list(active.get("behaviors") or [])
            if str(item.get("id") or "")
        )
        values: dict[str, object] = {
            "supervisor_enabled": bool(state.get(self._spec.enabled_key, True)),
            "supervisor_status": (
                f"{self._spec.title} is active with {len(personas)} reaction profile(s)."
                if state.get(self._spec.enabled_key, True)
                else f"{self._spec.title} is disabled."
            ),
            "supervisor_persona": str(active.get("id") or ""),
            "supervisor_style": str(active.get("style") or ""),
            "supervisor_behavior": self._selected_behavior,
            "supervisor_behavior_enabled": bool(behavior.get("enabled", False)),
            "supervisor_trigger": str(behavior.get("trigger") or ""),
            "supervisor_action": str(behavior.get("action") or ""),
            "supervisor_strictness": str(behavior.get("strictness") or STRICTNESS[0]),
            "supervisor_emotion": str(behavior.get("emotion") or EMOTIONS[0]),
            "supervisor_repeat_mode": str(behavior.get("repeat_mode") or REPEAT_MODES[0]),
            "supervisor_repeat_interval": int(behavior.get("repeat_interval") or 3),
            "supervisor_prompt_template": str(state.get(self._spec.prompt_key) or ""),
            "supervisor_preview": str(payload.get("preview") or ""),
        }
        has_persona = bool(active)
        has_behavior = bool(behavior)
        controls = []
        for control in self._surface.controls:
            updates: dict[str, object] = {"value": values.get(control.id, control.default_value)}
            if control.id == "supervisor_persona":
                updates["choices"] = persona_options or (NativeChoice("", "No profiles"),)
            elif control.id == "supervisor_behavior":
                updates["choices"] = behavior_options or (NativeChoice("", "No rules"),)
            if control.id in {
                "supervisor_rename_persona",
                "supervisor_delete_persona",
                "supervisor_style",
                "supervisor_add_behavior",
            }:
                updates["enabled"] = has_persona
            elif control.id in {
                "supervisor_delete_behavior",
                "supervisor_behavior_enabled",
                "supervisor_trigger",
                "supervisor_action",
                "supervisor_strictness",
                "supervisor_emotion",
                "supervisor_repeat_mode",
                "supervisor_repeat_interval",
            }:
                updates["enabled"] = has_behavior
            controls.append(replace(control, **updates))
        return replace(self._surface, controls=tuple(controls), revision=self._revision)

    def _mutate(self, callback: Callable[[dict[str, object]], None]) -> None:
        state = self._state_only(self._snapshot())
        callback(state)
        self._invoke("runtime.session.import", {"state": state})
        if callable(self._persist):
            self._persist()
        self._revision += 1
        self.changed.emit()

    def _edit_active(self, state: dict[str, object], callback: Callable[[dict[str, object]], None]) -> None:
        personas = [dict(item) for item in list(state.get(self._spec.personas_key) or [])]
        selected = str(state.get(self._spec.selected_key) or "")
        for index, item in enumerate(personas):
            if str(item.get("id") or "") == selected:
                callback(item)
                personas[index] = item
                state[self._spec.personas_key] = personas
                return
        raise RuntimeError("Select a reaction profile first.")

    def _edit_behavior(self, state: dict[str, object], callback: Callable[[dict[str, object]], None]) -> None:
        def edit_persona(persona: dict[str, object]) -> None:
            behaviors = [dict(item) for item in list(persona.get("behaviors") or [])]
            for index, item in enumerate(behaviors):
                if str(item.get("id") or "") == self._selected_behavior:
                    callback(item)
                    behaviors[index] = item
                    persona["behaviors"] = behaviors
                    return
            raise RuntimeError("Select a reaction rule first.")

        self._edit_active(state, edit_persona)

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key == "supervisor_persona":
            def select(state: dict[str, object]) -> None:
                state[self._spec.selected_key] = str(value or "")
            self._selected_behavior = ""
            self._mutate(select)
            return
        if key == "supervisor_behavior":
            self._selected_behavior = str(value or "")
            self._revision += 1
            self.changed.emit()
            return
        if key == "supervisor_enabled":
            self._mutate(lambda state: state.__setitem__(self._spec.enabled_key, bool(value)))
            return
        if key == "supervisor_prompt_template":
            self._mutate(lambda state: state.__setitem__(self._spec.prompt_key, str(value or "")))
            return
        if key == "supervisor_style":
            self._mutate(lambda state: self._edit_active(state, lambda item: item.__setitem__("style", str(value or "").strip())))
            return
        behavior_names = {
            "supervisor_behavior_enabled": "enabled",
            "supervisor_trigger": "trigger",
            "supervisor_action": "action",
            "supervisor_strictness": "strictness",
            "supervisor_emotion": "emotion",
            "supervisor_repeat_mode": "repeat_mode",
            "supervisor_repeat_interval": "repeat_interval",
        }
        name = behavior_names.get(key)
        if name is None:
            raise KeyError(f"Unknown supervisor setting '{control_id}'.")
        if key == "supervisor_behavior_enabled":
            normalized = bool(value)
        elif key in {"supervisor_trigger", "supervisor_action"}:
            normalized = str(value or "").strip()
        elif key == "supervisor_strictness":
            normalized = str(value or STRICTNESS[0])
        elif key == "supervisor_emotion":
            normalized = str(value or EMOTIONS[0])
        elif key == "supervisor_repeat_mode":
            normalized = str(value or REPEAT_MODES[0])
        else:
            normalized = max(1, min(999, int(value)))
        self._mutate(
            lambda state: self._edit_behavior(
                state,
                lambda item: item.__setitem__(name, normalized),
            )
        )

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        action = str(control_id or "").strip()
        if action == "supervisor_add_persona":
            name = str(payload or "").strip()
            if not name:
                raise ValueError("Enter a reaction profile name.")
            def add(state: dict[str, object]) -> None:
                personas = [dict(item) for item in list(state.get(self._spec.personas_key) or [])]
                persona_id = f"persona_{uuid4().hex[:8]}"
                personas.append({"id": persona_id, "name": name, "style": f"{name} energy, playful and strongly in-character", "behaviors": []})
                state[self._spec.personas_key] = personas
                state[self._spec.selected_key] = persona_id
            self._selected_behavior = ""
            self._mutate(add)
        elif action == "supervisor_rename_persona":
            name = str(payload or "").strip()
            if not name:
                raise ValueError("Enter a reaction profile name.")
            self._mutate(lambda state: self._edit_active(state, lambda item: item.__setitem__("name", name)))
        elif action == "supervisor_delete_persona":
            def delete(state: dict[str, object]) -> None:
                personas = [dict(item) for item in list(state.get(self._spec.personas_key) or [])]
                if len(personas) <= 1:
                    raise RuntimeError("At least one reaction profile must remain.")
                selected = str(state.get(self._spec.selected_key) or "")
                personas = [item for item in personas if str(item.get("id") or "") != selected]
                state[self._spec.personas_key] = personas
                state[self._spec.selected_key] = str(personas[0].get("id") or "")
            self._selected_behavior = ""
            self._mutate(delete)
        elif action == "supervisor_add_behavior":
            behavior_id = f"behavior_{uuid4().hex[:8]}"
            def add_rule(state: dict[str, object]) -> None:
                def edit(persona: dict[str, object]) -> None:
                    behaviors = [dict(item) for item in list(persona.get("behaviors") or [])]
                    behaviors.append({"id": behavior_id, "enabled": False, "trigger": "", "action": "", "strictness": STRICTNESS[0], "emotion": EMOTIONS[0], "repeat_mode": REPEAT_MODES[0], "repeat_interval": 3})
                    persona["behaviors"] = behaviors
                self._edit_active(state, edit)
            self._selected_behavior = behavior_id
            self._mutate(add_rule)
        elif action == "supervisor_delete_behavior":
            def delete_rule(state: dict[str, object]) -> None:
                def edit(persona: dict[str, object]) -> None:
                    persona["behaviors"] = [
                        dict(item) for item in list(persona.get("behaviors") or [])
                        if str(dict(item).get("id") or "") != self._selected_behavior
                    ]
                self._edit_active(state, edit)
            self._mutate(delete_rule)
            self._selected_behavior = ""
        elif action == "supervisor_restore_prompt":
            self._invoke("runtime.supervisor.reset_prompt")
            if callable(self._persist):
                self._persist()
            self._revision += 1
            self.changed.emit()
        else:
            raise KeyError(f"Unknown supervisor action '{control_id}'.")


def _surface(spec: SupervisorSpec) -> NativeSurface:
    controls = (
        NativeControl("supervisor_enabled", f"Enable {spec.title}", NativeControlKind.BOOLEAN, "Overview", default_value=True),
        NativeControl("supervisor_status", "Status", NativeControlKind.DISPLAY, "Overview"),
        NativeControl("supervisor_persona", "Active Reaction Profile", NativeControlKind.CHOICE, "Reaction Profiles", choices=(NativeChoice("", "No profiles"),)),
        NativeControl("supervisor_add_persona", "Add Profile", NativeControlKind.ACTION, "Reaction Profiles", metadata={"execution": "ui", "inputPrompt": True, "dialogTitle": "Add Reaction Profile", "inputLabel": "Profile name"}),
        NativeControl("supervisor_rename_persona", "Rename Profile", NativeControlKind.ACTION, "Reaction Profiles", metadata={"execution": "ui", "inputPrompt": True, "dialogTitle": "Rename Reaction Profile", "inputLabel": "New profile name"}),
        NativeControl("supervisor_delete_persona", "Delete Profile", NativeControlKind.ACTION, "Reaction Profiles", metadata={"destructive": True, "execution": "ui"}),
        NativeControl("supervisor_style", "Speaking style", NativeControlKind.TEXT, "Reaction Profiles"),
        NativeControl("supervisor_behavior", "Reaction rule", NativeControlKind.CHOICE, "Reaction Rules", choices=(NativeChoice("", "No rules"),)),
        NativeControl("supervisor_add_behavior", "Add Rule", NativeControlKind.ACTION, "Reaction Rules", metadata={"execution": "ui"}),
        NativeControl("supervisor_delete_behavior", "Remove Rule", NativeControlKind.ACTION, "Reaction Rules", metadata={"destructive": True, "execution": "ui"}),
        NativeControl("supervisor_behavior_enabled", "Enabled", NativeControlKind.BOOLEAN, "Reaction Rules", default_value=False),
        NativeControl("supervisor_trigger", spec.trigger_label, NativeControlKind.MULTILINE, "Reaction Rules"),
        NativeControl("supervisor_action", "Action", NativeControlKind.MULTILINE, "Reaction Rules"),
        NativeControl("supervisor_strictness", "Strictness", NativeControlKind.CHOICE, "Reaction Rules", default_value=STRICTNESS[0], choices=choices(tuple((item, item) for item in STRICTNESS))),
        NativeControl("supervisor_emotion", "Emotion override", NativeControlKind.CHOICE, "Reaction Rules", default_value=EMOTIONS[0], choices=choices(tuple((item, item) for item in EMOTIONS))),
        NativeControl("supervisor_repeat_mode", "Repeat mode", NativeControlKind.CHOICE, "Reaction Rules", default_value=REPEAT_MODES[0], choices=choices(tuple((item, item) for item in REPEAT_MODES))),
        NativeControl("supervisor_repeat_interval", "Nth match interval", NativeControlKind.INTEGER, "Reaction Rules", default_value=3, minimum=1, maximum=999),
        NativeControl("supervisor_prompt_template", "Advanced Prompt Rules", NativeControlKind.MULTILINE, "Advanced Prompt"),
        NativeControl("supervisor_restore_prompt", "Restore recommended prompt", NativeControlKind.ACTION, "Advanced Prompt", metadata={"execution": "ui"}),
        NativeControl("supervisor_preview", "Review Prompt Preview", NativeControlKind.MULTILINE, "Advanced Prompt", metadata={"readOnly": True}),
    )
    controls = apply_card_layout(tuple(
        replace(control, metadata={**control.metadata, "scrollable": True})
        if control.kind is NativeControlKind.MULTILINE else control
        for control in controls
    ))
    return NativeSurface(
        id=spec.surface_id,
        title=spec.title,
        addon_id=spec.addon_id,
        sections=("Overview", "Reaction Profiles", "Reaction Rules", "Advanced Prompt"),
        description=spec.description,
        controls=controls,
    )


SPECS = (
    SupervisorSpec("clipboard_supervisor_tab", "nc.clipboard_supervisor", "Clipboard Supervisor", "clipboard_supervisor", "Clipboard Image Trigger", "Configure persona-driven reactions to newly copied images."),
    SupervisorSpec("screen_supervisor_tab", "nc.screen_supervisor", "Screen Supervisor", "screen_supervisor", "Visual Trigger", "Configure persona-driven reactions to noteworthy screen content."),
    SupervisorSpec("webcam_supervisor_tab", "nc.webcam_supervisor", "Webcam Supervisor", "webcam_supervisor", "Webcam Trigger", "Configure persona-driven reactions to posture, expression, and attention cues."),
    SupervisorSpec("heart_rate_behavior_tab", "nc.heart_rate_behavior", "Heart Rate Behavior", "heart_rate_behavior", "Signal Trigger", "Configure persona-driven reactions to heart-rate states."),
)


def build_supervisor_adapters(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> tuple[SupervisorNativeAdapter, ...]:
    return tuple(
        SupervisorNativeAdapter(
            application_facade,
            _surface(spec),
            spec,
            persist=persist,
        )
        for spec in SPECS
    )


__all__ = ["SupervisorNativeAdapter", "build_supervisor_adapters"]
