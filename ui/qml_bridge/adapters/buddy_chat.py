"""Native QML presentation for Buddy Chat.

The existing Buddy Chat controller remains the single owner of settings,
provider execution, avatar generation, setup refinement, voice routing, and
persistence.  This adapter only translates its typed state into generic QML
controls and routes edits back through finite addon capabilities.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from PySide6 import QtCore

from addons.buddy_chat.models import (
    AVATAR_PROMPT_PRESETS,
    BEHAVIOR_REPLY_LENGTHS,
    PROVIDER_IDS,
)
from ui.qml_bridge.adapters.buddy_chat_layout import apply_buddy_chat_layout
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter

_PROVIDER_LABELS = {
    "inherit": "Inherit",
    "main": "Main LLM Runtime",
    "lmstudio": "LM Studio",
    "ollama": "Ollama",
    "openai": "OpenAI",
    "xai": "xAI / Grok",
    "deepseek": "DeepSeek",
    "claude": "Claude",
}
_BEHAVIOR_FIELDS = (
    ("helpfulness", "Helpfulness"),
    ("warmth", "Warmth"),
    ("humor", "Humor"),
    ("expressiveness", "Expressiveness"),
    ("initiative", "Initiative"),
    ("directness", "Directness"),
    ("disagreement", "Willingness to disagree"),
    ("flirtation", "Flirtation"),
    ("participation_weight", "Participation weight"),
)
_REFINE_FIELDS = (
    ("display_name", "Name"),
    ("role", "Role"),
    ("description", "Detailed description"),
    ("system_prompt", "Complete system prompt"),
    ("speaking_style", "Speaking style"),
    *tuple((f"behavior.{key}", label) for key, label in _BEHAVIOR_FIELDS),
    ("behavior.reply_length", "Typical reply length"),
)


def _provider_choices() -> tuple[NativeChoice, ...]:
    return choices((value, _PROVIDER_LABELS[value]) for value in PROVIDER_IDS)


def _action(
    control_id: str,
    label: str,
    section: str,
    *,
    destructive: bool = False,
    metadata: Mapping[str, object] | None = None,
) -> NativeControl:
    options = {"execution": "ui", "destructive": destructive}
    options.update(dict(metadata or {}))
    return NativeControl(
        control_id,
        label,
        NativeControlKind.ACTION,
        section,
        metadata=options,
    )


def _display(control_id: str, label: str, section: str, value: Any) -> NativeControl:
    return NativeControl(
        control_id,
        label,
        NativeControlKind.DISPLAY,
        section,
        value=value,
    )


def _text(
    control_id: str,
    label: str,
    section: str,
    value: Any,
    *,
    multiline: bool = False,
    secret: bool = False,
    read_only: bool = False,
    description: str = "",
) -> NativeControl:
    return NativeControl(
        control_id,
        label,
        NativeControlKind.MULTILINE if multiline else NativeControlKind.TEXT,
        section,
        value=str(value or ""),
        secret=secret,
        description=description,
        metadata={"readOnly": read_only},
    )


def _boolean(
    control_id: str,
    label: str,
    section: str,
    value: Any,
    *,
    description: str = "",
    metadata: Mapping[str, object] | None = None,
) -> NativeControl:
    return NativeControl(
        control_id,
        label,
        NativeControlKind.BOOLEAN,
        section,
        value=bool(value),
        description=description,
        metadata=dict(metadata or {}),
    )


def _integer(
    control_id: str,
    label: str,
    section: str,
    value: Any,
    minimum: int,
    maximum: int,
) -> NativeControl:
    return NativeControl(
        control_id,
        label,
        NativeControlKind.INTEGER,
        section,
        value=int(value or 0),
        minimum=minimum,
        maximum=maximum,
        step=1,
    )


def _choice(
    control_id: str,
    label: str,
    section: str,
    value: Any,
    options: tuple[NativeChoice, ...],
    *,
    enabled: bool = True,
) -> NativeControl:
    return NativeControl(
        control_id,
        label,
        NativeControlKind.CHOICE,
        section,
        value=value,
        choices=options,
        enabled=enabled,
    )


class BuddyChatNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__("buddy_chat_tab", "nc.buddy_chat", parent)
        self._application = application_facade
        self._persist = persist
        self._paths: dict[str, str] = {}
        self._actions: dict[str, tuple[str, dict[str, object]]] = {}
        self._revision = 0
        self._poll_remaining = 0
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll)

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id, capability, dict(payload or {})
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Buddy Chat is unavailable."))
            )
        return result.value

    def _payload(self) -> dict[str, object]:
        value = self._invoke("runtime.buddy.native_snapshot")
        if not isinstance(value, Mapping):
            raise RuntimeError("Buddy Chat snapshot is not a mapping.")
        return dict(value)

    def _bind(self, control: NativeControl, path: str) -> NativeControl:
        self._paths[control.id] = path
        return control

    def _run(
        self,
        control: NativeControl,
        action: str,
        payload: Mapping[str, object] | None = None,
    ) -> NativeControl:
        self._actions[control.id] = (action, dict(payload or {}))
        return control

    def _poll(self) -> None:
        self._poll_remaining -= 1
        self._revision += 1
        self.changed.emit()
        if self._poll_remaining <= 0:
            try:
                busy = bool(self._payload().get("refinement_busy"))
            except Exception:
                busy = False
            if busy:
                self._poll_remaining = 2
            else:
                self._poll_timer.stop()

    def _start_polling(self, seconds: int = 60) -> None:
        self._poll_remaining = max(self._poll_remaining, int(seconds * 2))
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def snapshot(self) -> NativeSurface:
        payload = self._payload()
        settings = dict(payload.get("settings") or {})
        personas = [
            dict(item)
            for item in list(settings.get("personas") or [])
            if isinstance(item, Mapping)
        ]
        setup_choices = dict(payload.get("setup_choices") or {})
        setup_traits = dict(setup_choices.get("traits") or {})
        preview = dict(payload.get("setup_preview") or {})
        preview_personas = [
            dict(item)
            for item in list(preview.get("personas") or [])
            if isinstance(item, Mapping)
        ]
        group = dict(preview.get("group_behavior") or {})
        catalogs = {
            str(key): [str(item) for item in list(value or [])]
            for key, value in dict(payload.get("model_catalogs") or {}).items()
        }
        self._paths.clear()
        self._actions.clear()
        controls: list[NativeControl] = []

        controls.extend(
            [
                _display(
                    "buddy_chat_subtitle",
                    "Buddy Chat",
                    "Setup",
                    "Natural buddy participation, routed voices, avatars, and optional per-buddy models.",
                ),
                _display(
                    "buddy_setup_guide",
                    "Guided setup",
                    "Setup",
                    "Use three guided choices or preview one of four complete groups. Nothing is saved until Apply Group.",
                ),
                self._bind(
                    _boolean(
                        "buddy_adult_nsfw_toggle",
                        "Adult / NSFW",
                        "Setup",
                        settings.get("adult_nsfw_enabled", False),
                        description="Enable explicit conversation only for adult personas and participants.",
                        metadata={
                            "confirmOnEnable": True,
                            "confirmationTitle": "Enable Adult / NSFW Buddy Chat",
                            "confirmationText": "This enables explicit conversation for adult personas. The selected model or provider may still impose restrictions.",
                        },
                    ),
                    "adult_nsfw_enabled",
                ),
                self._bind(
                    _choice(
                        "buddy_setup_buddy_count",
                        "Buddies",
                        "Setup",
                        int(setup_choices.get("buddy_count", 2) or 2),
                        choices(((1, "1 - Focused"), (2, "2 - Balanced"), (3, "3 - Lively"))),
                    ),
                    "setup_choices.buddy_count",
                ),
                self._bind(
                    _choice(
                        "buddy_setup_participation",
                        "Participation",
                        "Setup",
                        str(setup_choices.get("participation") or "balanced"),
                        choices((("focused", "Focused"), ("balanced", "Balanced"), ("lively", "Lively"))),
                    ),
                    "setup_choices.participation",
                ),
            ]
        )
        for trait, label in (
            ("practical", "Practical help"),
            ("warm", "Emotional warmth"),
            ("playful", "Playful energy"),
            ("expressive", "Expressiveness"),
            ("honest", "Honest disagreement"),
            ("creative", "Creativity"),
            ("flirtatious", "Flirtation"),
        ):
            controls.append(
                self._bind(
                    _boolean(
                        f"buddy_setup_trait_{trait}",
                        label,
                        "Setup",
                        setup_traits.get(trait, False),
                    ),
                    f"setup_choices.traits.{trait}",
                )
            )
        controls.append(
            self._run(
                _action("buddy_setup_build_preview", "Preview guided group", "Setup"),
                "stage_setup",
            )
        )
        for preset_id, label in (
            ("reliable_guide", "Reliable Guide - 1 buddy"),
            ("supportive_duo", "Supportive Duo - 2 buddies"),
            ("expressive_circle", "Expressive Circle - 3 buddies"),
            ("magnetic_company", "Magnetic Company - 2 buddies"),
        ):
            controls.append(
                self._run(
                    _action(
                        f"buddy_preset_{preset_id}",
                        label,
                        "Setup",
                        destructive=True,
                    ),
                    "stage_setup",
                    {"preset_id": preset_id},
                )
            )
        preview_summary = str(preview.get("summary") or "")
        if preview_personas:
            preview_summary += "\n\n" + "\n".join(
                f"{item.get('display_name') or 'Buddy'} - {item.get('role') or ''}"
                for item in preview_personas
            )
        controls.append(
            _text(
                "buddy_setup_preview_text",
                str(preview.get("title") or "Buddy Setup Preview"),
                "Setup",
                preview_summary,
                multiline=True,
                read_only=True,
            )
        )
        controls.extend(
            [
                self._bind(
                    _integer(
                        "buddy_group_max_speakers",
                        "Group max speakers",
                        "Setup",
                        group.get("max_speakers", 1),
                        1,
                        max(1, len(preview_personas)),
                    ),
                    "setup_preview.group_behavior.max_speakers",
                ),
                self._bind(
                    _boolean(
                        "buddy_group_allow_buddy_to_buddy",
                        "Allow buddies to react to each other",
                        "Setup",
                        group.get("allow_buddy_to_buddy", False),
                    ),
                    "setup_preview.group_behavior.allow_buddy_to_buddy",
                ),
                self._bind(
                    _integer(
                        "buddy_group_natural_second_speaker",
                        "Natural second speaker every N replies",
                        "Setup",
                        group.get("natural_second_speaker_every", 0),
                        0,
                        100,
                    ),
                    "setup_preview.group_behavior.natural_second_speaker_every",
                ),
                self._bind(
                    _integer(
                        "buddy_group_forced_buddy",
                        "Force buddy every N replies",
                        "Setup",
                        group.get("forced_buddy_every", 0),
                        0,
                        100,
                    ),
                    "setup_preview.group_behavior.forced_buddy_every",
                ),
                self._bind(
                    _text(
                        "buddy_setup_shared_prompt",
                        "Shared Buddy Chat override",
                        "Setup",
                        preview.get("system_override_prompt")
                        or settings.get("system_override_prompt"),
                        multiline=True,
                    ),
                    "setup_preview.system_override_prompt",
                ),
                self._bind(
                    _text(
                        "buddy_setup_normal_prompt",
                        "Normal intimacy layer",
                        "Setup",
                        preview.get("normal_intimacy_prompt")
                        or settings.get("normal_intimacy_prompt"),
                        multiline=True,
                    ),
                    "setup_preview.normal_intimacy_prompt",
                ),
                self._bind(
                    _text(
                        "buddy_setup_adult_prompt",
                        "Adult / NSFW layer",
                        "Setup",
                        preview.get("adult_nsfw_prompt")
                        or settings.get("adult_nsfw_prompt"),
                        multiline=True,
                    ),
                    "setup_preview.adult_nsfw_prompt",
                ),
            ]
        )
        for index, persona in enumerate(preview_personas):
            behavior = dict(persona.get("behavior") or {})
            prefix = f"buddy_setup_persona_{index}"
            path = f"setup_preview.personas.{index}"
            name = str(persona.get("display_name") or f"Buddy {index + 1}")
            controls.extend(
                [
                    self._bind(_text(f"{prefix}_name", f"{name}: name", "Setup", name), f"{path}.display_name"),
                    self._bind(_text(f"{prefix}_role", f"{name}: role", "Setup", persona.get("role")), f"{path}.role"),
                    self._bind(_text(f"{prefix}_description", f"{name}: description", "Setup", persona.get("description"), multiline=True), f"{path}.description"),
                    self._bind(_text(f"{prefix}_system_prompt", f"{name}: system prompt", "Setup", persona.get("system_prompt"), multiline=True), f"{path}.system_prompt"),
                    self._bind(_text(f"{prefix}_style", f"{name}: speaking style", "Setup", persona.get("speaking_style")), f"{path}.speaking_style"),
                ]
            )
            for field, label in _BEHAVIOR_FIELDS:
                controls.append(
                    self._bind(
                        _integer(f"{prefix}_{field}", f"{name}: {label}", "Setup", behavior.get(field, 50), 0, 100),
                        f"{path}.behavior.{field}",
                    )
                )
            controls.append(
                self._bind(
                    _choice(
                        f"{prefix}_reply_length",
                        f"{name}: reply length",
                        "Setup",
                        str(behavior.get("reply_length") or "balanced"),
                        choices((value, value.title()) for value in BEHAVIOR_REPLY_LENGTHS),
                    ),
                    f"{path}.behavior.reply_length",
                )
            )
        refine_personas = tuple(
            NativeChoice(str(item.get("id") or ""), str(item.get("display_name") or "Buddy"))
            for item in preview_personas
            if str(item.get("id") or "")
        ) or (NativeChoice("", "No staged buddy"),)
        refine_persona_value = str(setup_choices.get("refine_persona") or "")
        if refine_persona_value not in {str(item.value) for item in refine_personas} and preview_personas:
            refine_persona_value = str(preview_personas[0].get("id") or "")
        refine_scope = str(setup_choices.get("refine_scope") or "group")
        controls.extend(
            [
                self._bind(_choice("buddy_refine_scope", "Refine scope", "Setup", str(setup_choices.get("refine_scope") or "group"), choices((("group", "Entire group"), ("persona", "One buddy"), ("field", "One field")))), "setup_choices.refine_scope"),
                self._bind(_choice("buddy_refine_persona", "Refine persona", "Setup", refine_persona_value, refine_personas, enabled=refine_scope in {"persona", "field"}), "setup_choices.refine_persona"),
                self._bind(_choice("buddy_refine_field", "Refine field", "Setup", str(setup_choices.get("refine_field") or "display_name"), choices(_REFINE_FIELDS), enabled=refine_scope == "field"), "setup_choices.refine_field"),
                self._bind(_text("buddy_refine_instruction", "Refinement instruction", "Setup", setup_choices.get("refine_instruction")), "setup_choices.refine_instruction"),
                self._run(_action("buddy_setup_refine", "Refine with LLM", "Setup"), "refine_setup"),
                self._run(_action("buddy_setup_refine_cancel", "Cancel refinement", "Setup"), "cancel_refinement"),
                _display("buddy_setup_refinement_status", "Refinement result", "Setup", str(payload.get("status") or "")),
                self._run(_action("buddy_setup_undo", "Undo last setup", "Setup"), "undo_setup"),
                self._run(_action("buddy_setup_cancel", "Cancel preview", "Setup"), "cancel_setup"),
                self._run(_action("buddy_setup_apply", "Apply group", "Setup", destructive=True), "apply_setup"),
            ]
        )

        controls.extend(
            [
                self._bind(_boolean("buddy_enabled", "Enable Buddy Chat", "Overview", settings.get("enabled", False)), "enabled"),
                self._bind(_choice("buddy_reply_mode", "Reply mode", "Overview", str(settings.get("reply_mode") or "context_only"), choices((("context_only", "Natural main conversation - recommended"), ("main_answer", "Direct Buddy-generated replies - advanced")))), "reply_mode"),
                self._bind(_choice("buddy_llm_mode", "LLM provider mode", "Overview", str(settings.get("llm_mode") or "main"), choices((("main", "Use Main LLM Runtime"), ("buddy", "Use Buddy Provider"), ("per_persona", "Use Per-Persona Providers")))), "llm_mode"),
                self._bind(_integer("buddy_max_speakers", "Max buddies per reply", "Overview", settings.get("max_speakers", 1), 1, 4), "max_speakers"),
                self._bind(_integer("buddy_forced_every", "Force buddy every N replies", "Overview", settings.get("forced_buddy_every", 0), 0, 100), "forced_buddy_every"),
                self._bind(_boolean("buddy_structured_outputs", "Use Instructor structured Buddy replies", "Overview", settings.get("buddy_chat_instructor_structured_outputs_enabled", False)), "instructor_structured_outputs_enabled"),
                self._bind(_boolean("buddy_persona_window", "Show active persona window", "Overview", settings.get("active_persona_window_enabled", False), description="The active persona is already represented natively in the Conversation workspace."), "active_persona_window_enabled"),
                self._bind(_boolean("buddy_persona_window_top", "Keep persona window on top", "Overview", settings.get("active_persona_window_on_top", True)), "active_persona_window_on_top"),
                self._run(_action("buddy_add", "Add Buddy", "Overview"), "add_persona"),
                self._run(_action("buddy_import_mprc", "Load MPRC personas", "Overview"), "import_mprc"),
                self._run(_action("buddy_save", "Save", "Overview"), "save"),
                _display("buddy_status", "Status", "Overview", str(payload.get("status") or "")),
            ]
        )

        for index, persona in enumerate(personas):
            name = str(persona.get("display_name") or f"Buddy {index + 1}")
            prefix = f"buddy_persona_{index}"
            path = f"personas.{index}"
            behavior = dict(persona.get("behavior") or {})
            controls.extend(
                [
                    self._bind(_boolean(f"{prefix}_enabled", f"{name}: active", "Buddies", persona.get("enabled", True)), f"{path}.enabled"),
                    self._bind(_text(f"{prefix}_name", f"{name}: name", "Buddies", name), f"{path}.display_name"),
                    self._bind(_text(f"{prefix}_role", f"{name}: role", "Buddies", persona.get("role")), f"{path}.role"),
                    self._bind(_text(f"{prefix}_style", f"{name}: speaking style", "Buddies", persona.get("speaking_style")), f"{path}.speaking_style"),
                    self._bind(_text(f"{prefix}_description", f"{name}: description", "Buddies", persona.get("description"), multiline=True), f"{path}.description"),
                    self._bind(_text(f"{prefix}_system_prompt", f"{name}: system prompt", "Buddies", persona.get("system_prompt"), multiline=True), f"{path}.system_prompt"),
                ]
            )
            for field, label in _BEHAVIOR_FIELDS:
                controls.append(
                    self._bind(
                        _integer(f"{prefix}_{field}", f"{name}: {label}", "Buddies", behavior.get(field, 50), 0, 100),
                        f"{path}.behavior.{field}",
                    )
                )
            controls.append(
                self._bind(
                    _choice(f"{prefix}_reply_length", f"{name}: reply length", "Buddies", str(behavior.get("reply_length") or "balanced"), choices((value, value.title()) for value in BEHAVIOR_REPLY_LENGTHS)),
                    f"{path}.behavior.reply_length",
                )
            )
            controls.append(
                self._run(_action(f"{prefix}_remove", f"Remove {name}", "Buddies", destructive=True), "remove_persona", {"index": index})
            )

            voice = dict(persona.get("voice") or {})
            controls.extend(
                [
                    self._bind(_boolean(f"{prefix}_voice_enabled", f"{name}: use voice sample", "Voices", voice.get("enabled", False)), f"{path}.voice.enabled"),
                    self._bind(_text(f"{prefix}_voice_path", f"{name}: voice sample", "Voices", voice.get("sample_path")), f"{path}.voice.sample_path"),
                    self._run(_action(f"{prefix}_voice_choose", f"Choose voice sample for {name}", "Voices", metadata={"filePicker": True, "nameFilters": ["Audio files (*.wav *.mp3 *.flac *.ogg *.m4a)", "All files (*)"]}), "choose_voice", {"index": index}),
                ]
            )

            avatar = dict(persona.get("avatar") or {})
            controls.extend(
                [
                    self._bind(_choice(f"{prefix}_avatar_preset", f"{name}: avatar prompt preset", "Avatars", str(avatar.get("preset") or next(iter(AVATAR_PROMPT_PRESETS))), choices((value, value) for value in AVATAR_PROMPT_PRESETS)), f"{path}.avatar.preset"),
                    self._run(_action(f"{prefix}_avatar_use_preset", f"Use prompt preset for {name}", "Avatars", destructive=True), "use_avatar_preset", {"index": index}),
                    self._bind(_text(f"{prefix}_avatar_prompt", f"{name}: avatar prompt", "Avatars", avatar.get("prompt"), multiline=True), f"{path}.avatar.prompt"),
                    self._bind(_text(f"{prefix}_avatar_path", f"{name}: generated image", "Avatars", avatar.get("image_path")), f"{path}.avatar.image_path"),
                    NativeControl(f"{prefix}_avatar_preview", f"{name}: avatar preview", NativeControlKind.IMAGE, "Avatars", value=str(avatar.get("image_path") or "")),
                    self._run(_action(f"{prefix}_avatar_generate", f"Generate avatar for {name}", "Avatars"), "generate_avatar", {"index": index}),
                ]
            )

        shared = dict(settings.get("buddy_provider") or {})
        shared_models = [str(shared.get("model") or "")] + catalogs.get("shared", [])
        shared_model_choices = tuple(
            NativeChoice(value, value)
            for value in dict.fromkeys(item for item in shared_models if item)
        ) or (NativeChoice("", "Enter model below"),)
        controls.extend(
            [
                self._bind(_choice("buddy_provider", "Shared provider", "Providers", str(shared.get("provider_id") or "inherit"), _provider_choices()), "buddy_provider.provider_id"),
                self._bind(_text("buddy_model", "Shared model", "Providers", shared.get("model"), description=f"Available LM Studio models: {', '.join(item.value for item in shared_model_choices if item.value) or 'refresh to discover'}"), "buddy_provider.model"),
                self._bind(_text("buddy_base_url", "Shared base URL", "Providers", shared.get("base_url")), "buddy_provider.base_url"),
                self._bind(_text("buddy_api_key", "Shared API key", "Providers", shared.get("api_key"), secret=True), "buddy_provider.api_key"),
                self._run(_action("buddy_refresh_models", "Refresh shared models", "Providers"), "refresh_models", {"target": "shared"}),
                self._run(_action("buddy_test_provider", "Test Buddy provider", "Providers"), "test_provider"),
            ]
        )
        for index, persona in enumerate(personas):
            name = str(persona.get("display_name") or f"Buddy {index + 1}")
            provider = dict(persona.get("provider") or {})
            prefix = f"buddy_persona_{index}"
            path = f"personas.{index}.provider"
            target = f"persona:{index}"
            model_values = [str(provider.get("model") or "")] + catalogs.get(target, [])
            model_choices = tuple(
                NativeChoice(value, value)
                for value in dict.fromkeys(item for item in model_values if item)
            ) or (NativeChoice("", "Enter model below"),)
            controls.extend(
                [
                    self._bind(_choice(f"{prefix}_provider", f"{name}: provider", "Providers", str(provider.get("provider_id") or "inherit"), _provider_choices()), f"{path}.provider_id"),
                    self._bind(_text(f"{prefix}_model", f"{name}: model", "Providers", provider.get("model"), description=f"Available LM Studio models: {', '.join(item.value for item in model_choices if item.value) or 'refresh to discover'}"), f"{path}.model"),
                    self._bind(_text(f"{prefix}_base_url", f"{name}: base URL", "Providers", provider.get("base_url")), f"{path}.base_url"),
                    self._bind(_text(f"{prefix}_api_key", f"{name}: API key", "Providers", provider.get("api_key"), secret=True), f"{path}.api_key"),
                    self._run(_action(f"{prefix}_refresh_models", f"Refresh models for {name}", "Providers"), "refresh_models", {"target": target}),
                ]
            )

        controls.extend(
            [
                self._bind(_boolean("buddy_system_override_enabled", "Override main persona instructions while Buddy Chat is enabled", "Advanced", settings.get("system_override_enabled", True)), "system_override_enabled"),
                self._run(_action("buddy_system_override_reset", "Use recommended override", "Advanced"), "reset_system_prompt"),
                self._bind(_text("buddy_system_override_prompt", "Buddy system override", "Advanced", settings.get("system_override_prompt"), multiline=True), "system_override_prompt"),
            ]
        )
        return NativeSurface(
            id=self.surface_id,
            title="Buddy Chat",
            addon_id=self.addon_id,
            sections=("Setup", "Overview", "Buddies", "Voices", "Avatars", "Providers", "Advanced"),
            description="Natural multi-buddy chat with guided groups, routed voices, avatars, and provider overrides.",
            controls=apply_buddy_chat_layout(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        path = self._paths.get(key)
        if path is None:
            self.snapshot()
            path = self._paths.get(key)
        if path is None:
            raise KeyError(f"Unknown Buddy Chat setting '{control_id}'.")
        self._invoke(
            "runtime.buddy.native_update", {"key": path, "value": value}
        )
        if callable(self._persist):
            self._persist()
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        key = str(control_id or "").strip()
        action = self._actions.get(key)
        if action is None:
            self.snapshot()
            action = self._actions.get(key)
        if action is None:
            raise KeyError(f"Unknown Buddy Chat action '{control_id}'.")
        name, request = action
        if name == "choose_voice":
            values = list(payload or []) if isinstance(payload, (list, tuple)) else []
            if not values:
                return
            index = int(request["index"])
            value = str(values[0] or "").removeprefix("file:///")
            self._invoke(
                "runtime.buddy.native_update",
                {"key": f"personas.{index}.voice.sample_path", "value": value},
            )
            self._invoke(
                "runtime.buddy.native_update",
                {"key": f"personas.{index}.voice.enabled", "value": True},
            )
        else:
            self._invoke(
                "runtime.buddy.native_action",
                {"action": name, "payload": request},
            )
        if name in {"generate_avatar", "test_provider", "refresh_models", "refine_setup"}:
            self._start_polling()
        if callable(self._persist) and name not in {
            "test_provider",
            "refresh_models",
            "refine_setup",
            "cancel_refinement",
        }:
            self._persist()
        self._revision += 1
        self.changed.emit()


def build_buddy_chat_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> BuddyChatNativeAdapter:
    return BuddyChatNativeAdapter(application_facade, persist=persist)


__all__ = ["BuddyChatNativeAdapter", "build_buddy_chat_adapter"]
