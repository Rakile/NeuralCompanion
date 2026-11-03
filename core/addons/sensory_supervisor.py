"""Presentation-neutral sensory supervisor profile and prompt runtime."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from core.addons.base import BaseAddon
from core.sensory_prompt_defaults import resolve_prompt


STRICTNESS_OPTIONS = ("Interpret freely", "Follow closely", "Say almost exactly")
EMOTION_OPTIONS = (
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
REPEAT_MODE_OPTIONS = ("One-off", "Every Nth match", "Meaningful change only")

# Only exact previously shipped defaults are upgraded; user edits remain intact.
_LEGACY_PROMPT_HASHES = {
    "screen": (
        "bfd1bbf3136a9674d5974a53e83da7226ef7c55e75b4515e0987fbaf0343fc33",
        "960849f8804da838806a0173931ad0a68ef359c1591924ec81e8ab1a8a18c5c7",
        "7c7c8d0b5e754afc31ba966ec81d7441f315ef6be05fd552b2cc2225d1c4785c",
        "b004f1c68e4aecc0cc20093e90bb8e7f165e7bf4e908f7b8be4f73d803d52699",
        "2db1d20b1f5cd6cccf33d535c3dc533fd569b3e976c9689a9f6c7bc4ff051efc",
        "e1d65c01fe4b68a1a69ef7ea2c21099bac40b96f181af1c938a5e1d0fce5fc61",
        "bff3815485ad045645a8e40001962ecf4bc78d1b15e2e8eff54d5c88a436435f",
    ),
    "webcam": (
        "1ed012e277c2409f5d08773615f766ee997bf1bb3a1e2c1ef6242430c887e8e2",
        "e815d02268e6284263790e3f7dc7f64d9ff6e46eae591b6e83ab3cd2f4b12a83",
    ),
    "clipboard": (
        "0c4b2f5a2ceb4a836e7958b23f0a605b71587e5d0bd9f27e5e6c38e58cba32d0",
        "f3b797f0c9e4793f5b0e743e0b44eabe9bf2cb207b1f1f28c09e0f89ab551cd4",
        "a75b736028a440acdae47a85ee1e0f5a208346ae991410248a84cd30534cd69b",
    ),
    "heart_rate": (
        "a22196d961034b7b9a7cd9b8f198b967a2bdf18eec9d14878360e4c332902994",
        "54934d155de2db9d8f84ab9942d9ac16ae7c43074ac955551e9c5694d5a6e2cc",
    ),
}


@dataclass(frozen=True, slots=True)
class SensorySupervisorSpec:
    prefix: str
    source_id: str
    label: str
    tab_id: str
    contributor_id: str
    order: int
    default_personas: tuple[Mapping[str, Any], ...]
    legacy_enabled_key: str = ""


class SensorySupervisorRuntime:
    """Owns supervisor state and sensory prompt publication without widgets."""

    def __init__(self, context, spec: SensorySupervisorSpec) -> None:
        self.context = context
        self.spec = spec
        self.enabled = True
        self.recommended_prompt_template = self._load_prompt_template()
        self.prompt_template = self.recommended_prompt_template
        self.personas = self._normalize_personas(spec.default_personas)
        self.selected_persona_id = self.personas[0]["id"] if self.personas else ""
        self._suppress_notify = False
        self._register_prompt_contributor()

    @property
    def enabled_key(self) -> str:
        return f"{self.spec.prefix}_enabled"

    @property
    def prompt_key(self) -> str:
        return f"{self.spec.prefix}_prompt_template"

    @property
    def personas_key(self) -> str:
        return f"{self.spec.prefix}_personas"

    @property
    def selected_key(self) -> str:
        return f"{self.spec.prefix}_selected_persona_id"

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        if name == "runtime.supervisor.snapshot":
            result = self.export_session_state()
            result["preview"] = self.render_prompt()
            result["recommended_prompt_template"] = self.recommended_prompt_template
            return result
        if name == "runtime.supervisor.reset_prompt":
            self.prompt_template = self.recommended_prompt_template
            self._publish_state()
            return self.invoke_capability("runtime.supervisor.snapshot")
        if name == "ui.tab_enabled":
            addon_id = str(request.get("addon_id") or "").strip()
            tab_id = str(request.get("tab_id") or "").strip()
            if addon_id and addon_id != str(self.context.manifest.id):
                return None
            if tab_id and tab_id != self.spec.tab_id:
                return None
            if str(request.get("action") or "get").strip().lower() == "set":
                self.enabled = bool(request.get("enabled", True))
                self._publish_state()
            return {"enabled": bool(self.enabled)}
        return None

    def export_session_state(self) -> dict[str, Any]:
        return {
            self.enabled_key: bool(self.enabled),
            self.prompt_key: str(self.prompt_template or self.recommended_prompt_template),
            self.personas_key: self._normalize_personas(self.personas),
            self.selected_key: str(self.selected_persona_id or ""),
        }

    def import_session_state(self, session) -> None:
        payload = dict(session or {})
        previous = self._suppress_notify
        self._suppress_notify = True
        try:
            if self.enabled_key in payload:
                self.enabled = bool(payload[self.enabled_key])
            elif self.spec.legacy_enabled_key and self.spec.legacy_enabled_key in payload:
                self.enabled = bool(payload[self.spec.legacy_enabled_key])
            if self.prompt_key in payload:
                self.prompt_template = self._normalize_prompt(payload[self.prompt_key])
            if self.personas_key in payload:
                self.personas = self._normalize_personas(payload[self.personas_key])
                self.selected_persona_id = str(payload.get(self.selected_key) or "").strip()
            self._ensure_selected_persona()
            self._publish_state()
        finally:
            self._suppress_notify = previous

    def render_prompt(self) -> str:
        active = self._selected_persona()
        rendered = self._normalize_prompt(self.prompt_template)
        rendered = rendered.replace("__PERSONA_NAME__", str(active.get("name") or "Supervisor"))
        rendered = rendered.replace("__PERSONA_STYLE__", str(active.get("style") or "observant companion"))
        rules = (
            self._render_detector_rules(active)
            if self._uses_managed_prompt()
            else self._render_behavior_rules(active)
        )
        rendered = rendered.replace("__BEHAVIOR_RULES__", rules)
        if self.spec.source_id in ('screen', 'clipboard'):
            rendered = rendered.replace(f'__{self.spec.source_id.upper()}_MATCHES_RULES__', rules)
        return rendered

    def shutdown(self) -> None:
        self._unregister_prompt_contributor()

    def _load_prompt_template(self) -> str:
        try:
            path = self.context.manifest.root_dir / "prompt_template.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            text = str(dict(payload or {}).get("template") or "").strip()
            if text:
                return text
        except (OSError, ValueError, TypeError):
            pass
        return (
            f"This behavior applies only to {self.spec.source_id} input.\n\n"
            "Active supervisor persona: __PERSONA_NAME__.\n"
            "Persona style: __PERSONA_STYLE__.\n\n"
            "Configured behaviors:\n__BEHAVIOR_RULES__"
        )

    def _normalize_prompt(self, value) -> str:
        return resolve_prompt(
            value, self.recommended_prompt_template,
            legacy_hashes=_LEGACY_PROMPT_HASHES.get(self.spec.source_id, ()),
        )

    def _uses_managed_prompt(self) -> bool:
        effective = self._normalize_prompt(self.prompt_template).strip().replace("\r\n", "\n")
        recommended = self.recommended_prompt_template.strip().replace("\r\n", "\n")
        if (self.spec.source_id in ('screen', 'clipboard')
                and f'__{self.spec.source_id.upper()}_MATCHES_RULES__' in effective):
            return True  # Explicit opt-in survives edits to the surrounding wording.
        return effective == recommended

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:8]}"

    def _normalize_personas(self, personas) -> list[dict[str, Any]]:
        normalized = []
        for raw_persona in list(personas or []):
            if not isinstance(raw_persona, Mapping):
                continue
            name = str(raw_persona.get("name") or "Unnamed Persona").strip()
            behaviors = []
            for raw_behavior in list(raw_persona.get("behaviors") or []):
                if not isinstance(raw_behavior, Mapping):
                    continue
                strictness = str(raw_behavior.get("strictness") or STRICTNESS_OPTIONS[0])
                emotion = str(raw_behavior.get("emotion") or EMOTION_OPTIONS[0])
                repeat_mode = raw_behavior.get("repeat_mode")
                if repeat_mode is None:
                    repeat_mode = "Every Nth match" if raw_behavior.get("allow_repeat") else REPEAT_MODE_OPTIONS[0]
                repeat_mode = str(repeat_mode or REPEAT_MODE_OPTIONS[0])
                try:
                    repeat_interval = max(1, min(999, int(raw_behavior.get("repeat_interval", 3))))
                except (TypeError, ValueError):
                    repeat_interval = 3
                behaviors.append(
                    {
                        "id": str(raw_behavior.get("id") or "").strip() or self._new_id("behavior"),
                        "enabled": bool(raw_behavior.get("enabled", True)),
                        "trigger": str(raw_behavior.get("trigger") or "").strip(),
                        "action": str(raw_behavior.get("action") or "").strip(),
                        "strictness": strictness if strictness in STRICTNESS_OPTIONS else STRICTNESS_OPTIONS[0],
                        "emotion": emotion if emotion in EMOTION_OPTIONS else EMOTION_OPTIONS[0],
                        "repeat_mode": repeat_mode if repeat_mode in REPEAT_MODE_OPTIONS else REPEAT_MODE_OPTIONS[0],
                        "repeat_interval": repeat_interval,
                    }
                )
            normalized.append(
                {
                    "id": str(raw_persona.get("id") or "").strip() or self._new_id("persona"),
                    "name": name,
                    "style": str(raw_persona.get("style") or "").strip() or f"{name} companion style",
                    "behaviors": behaviors,
                }
            )
        if not normalized:
            return self._normalize_personas(copy.deepcopy(self.spec.default_personas))
        return normalized

    def _ensure_selected_persona(self) -> None:
        if not self.personas:
            self.personas = self._normalize_personas(self.spec.default_personas)
        known = {str(item.get("id") or "") for item in self.personas}
        if self.selected_persona_id not in known:
            self.selected_persona_id = str(self.personas[0].get("id") or "")

    def _selected_persona(self) -> dict[str, Any]:
        self._ensure_selected_persona()
        return next(
            (
                item
                for item in self.personas
                if str(item.get("id") or "") == self.selected_persona_id
            ),
            self.personas[0],
        )

    @staticmethod
    def _strictness_instruction(value: object) -> str:
        if value == "Follow closely":
            return "Final assistant: follow the Action closely and preserve its requested content."
        if value == "Say almost exactly":
            return "Final assistant: fulfill the Action with minimal interpretation; preserve any explicitly requested wording."
        return "Final assistant: interpret delivery freely while fulfilling the Action's intent."

    @staticmethod
    def _repeat_instruction(mode: object, interval: object) -> str:
        if mode == "Every Nth match":
            return f"Repeat on every {max(1, int(interval or 3))}th matching refresh."
        if mode == "Meaningful change only":
            return "Repeat only after a clearly meaningful change."
        return "One-off only for the same ongoing pattern."

    @staticmethod
    def _active_behaviors(persona: Mapping[str, Any]) -> list[dict[str, Any]]:
        fields = ("id", "trigger", "action", "strictness", "emotion", "repeat_mode", "repeat_interval")
        result = []
        for behavior in list(persona.get("behaviors") or []):
            item = dict(behavior or {})
            if not item.get("enabled", True) or not item.get("trigger") or not item.get("action"):
                continue
            result.append({field: item.get(field) for field in fields})
        return result

    def _render_behavior_rules(self, persona: Mapping[str, Any]) -> str:
        lines = []
        for item in self._active_behaviors(persona):
            emotion = str(item.get("emotion") or EMOTION_OPTIONS[0])
            lines.append(
                f"{len(lines) + 1}. Rule tag: [supervisor_rule:{self.spec.source_id}:{item['id']}]\n"
                f"   Trigger (condition): {item['trigger']}\n"
                f"   Action: {item['action']}\n"
                f"   Strictness: {self._strictness_instruction(item.get('strictness'))}\n"
                f"   Emotion override: {'Auto.' if emotion == 'Auto' else f'Prefer emotion={emotion}.'}\n"
                f"   Repeat policy: {self._repeat_instruction(item.get('repeat_mode'), item.get('repeat_interval'))}"
            )
        return "\n".join(lines) or (
            "No behaviors are configured for this persona yet. Set should_speak=false."
        )

    def _render_detector_rules(self, persona: Mapping[str, Any]) -> str:
        if self.spec.source_id in ('screen', 'clipboard'):
            from core.screen_review import rule_tags
            rules = self._active_behaviors(persona)
            return '\n'.join(json.dumps(
                {'tag': tag, 'statement': rule['trigger'], 'action': rule['action']},
                ensure_ascii=False, separators=(',', ':'))
                for tag, rule in zip(rule_tags(rules), rules))
        lines = []
        for item in self._active_behaviors(persona):
            lines.append(
                f"{len(lines) + 1}. Rule tag: [supervisor_rule:{self.spec.source_id}:{item['id']}]\n"
                f"   Trigger: {item['trigger']}"
            )
        return "\n".join(lines) or "No Triggers are configured. Set should_speak=false."

    def _register_prompt_contributor(self) -> None:
        service = self.context.capabilities.sensory_targets
        if service is None:
            return
        if not self.enabled:
            self._unregister_prompt_contributor()
            return
        active = self._selected_persona()
        metadata = {
            "type": "behavior_rule",
            "persona_name": str(active.get("name") or "Supervisor"),
            "persona_style": str(active.get("style") or "observant companion"),
            "behavior_count": len(list(active.get("behaviors") or [])),
            "active_behaviors": self._active_behaviors(active),
        }
        if self._uses_managed_prompt():
            metadata["action_contract"] = 1
            if self.spec.source_id in ('screen', 'clipboard'):
                metadata['review_contract'] = f'{self.spec.source_id}_matches'
                # Mixed-source reviews retain the shared schema, with rule data
                # rather than a second, conflicting JSON output instruction.
                metadata['legacy_prompt'] = '\n'.join(
                    f'[supervisor_rule:{self.spec.source_id}:{rule["id"]}] {rule["trigger"]}'
                    for rule in self._active_behaviors(active))
                if self.spec.source_id == 'clipboard':
                    metadata['legacy_prompt'] = (
                        'Match clipboard rules only when the image prefix says NEW since the last clipboard image. '
                        'Absent or unchanged images do not match.\n' + metadata['legacy_prompt'])
        service.register_prompt_contributor(
            contributor_id=self.spec.contributor_id,
            source_id=self.spec.source_id,
            label=self.spec.label,
            prompt=self.render_prompt(),
            order=int(self.spec.order),
            metadata=metadata,
        )

    def _unregister_prompt_contributor(self) -> None:
        service = self.context.capabilities.sensory_targets
        if service is not None:
            service.unregister_prompt_contributor(self.spec.contributor_id)

    def _publish_state(self) -> None:
        self._ensure_selected_persona()
        self._register_prompt_contributor()
        if self._suppress_notify:
            return
        notifier = getattr(self.context.capabilities.shell_session, "notify_settings_changed", None)
        if callable(notifier):
            notifier()


class SensorySupervisorAddon(BaseAddon):
    """Small addon entry point shared by the four supervisor providers."""

    SPEC: SensorySupervisorSpec

    def initialize(self, context) -> None:
        super().initialize(context)
        self.runtime = SensorySupervisorRuntime(context, self.SPEC)
        context.logger.info("%s native service initialized.", self.SPEC.label)

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        if name == "runtime.session.export":
            return self.export_session_state()
        if name == "runtime.session.import":
            self.import_session_state(request.get("state") or {})
            return {"accepted": True}
        return self.runtime.invoke_capability(name, request)

    def export_session_state(self):
        return self.runtime.export_session_state()

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, payload):
        self.runtime.import_session_state(payload)

    def import_preset_state(self, payload):
        self.import_session_state(payload)

    def shutdown(self):
        runtime = getattr(self, "runtime", None)
        self.runtime = None
        if runtime is not None:
            runtime.shutdown()
