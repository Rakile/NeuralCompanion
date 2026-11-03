"""Presentation-only layout policy for the Buddy Chat native surface.

Buddy Chat's controller remains authoritative for settings, actions, provider
work, voice routing, avatar generation, and persistence.  This module only
adds stable task-oriented card metadata understood by ``NCLiveControlsGroup``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind


@dataclass(frozen=True, slots=True)
class _Card:
    key: str
    title: str
    order: int
    span: int = 1
    description: str = ""


def _card(
    key: str,
    title: str,
    order: int,
    *,
    span: int = 1,
    description: str = "",
) -> _Card:
    return _Card(key, title, order, span, description)


def _persona_names(
    controls: tuple[NativeControl, ...],
    *,
    staged: bool,
) -> dict[int, str]:
    prefix = "buddy_setup_persona_" if staged else "buddy_persona_"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)_name$")
    names: dict[int, str] = {}
    for control in controls:
        match = pattern.fullmatch(control.id)
        if match is None:
            continue
        index = int(match.group(1))
        value = str(control.value or "").strip()
        if not value:
            value = str(control.label or "").split(":", 1)[0].strip()
        names[index] = value or f"Buddy {index + 1}"
    return names


def _setup_card(
    control: NativeControl,
    staged_names: dict[int, str],
) -> _Card:
    control_id = control.id
    if control_id in {"buddy_chat_subtitle", "buddy_setup_guide"}:
        return _card(
            "setup_intro",
            "How setup works",
            10,
            span=2,
            description="Build and review a complete group before saving it.",
        )
    if (
        control_id in {"buddy_setup_buddy_count", "buddy_setup_participation"}
        or control_id.startswith("buddy_setup_trait_")
        or control_id == "buddy_setup_build_preview"
    ):
        return _card(
            "setup_builder",
            "Build my group",
            20,
            description="Choose the group shape and desired personality mix.",
        )
    if control_id == "buddy_adult_nsfw_toggle" or control_id.startswith(
        "buddy_preset_"
    ):
        return _card(
            "setup_templates",
            "Complete quick starts",
            30,
            description="Load a complete editable group as a starting point.",
        )
    if control_id == "buddy_setup_preview_text":
        return _card(
            "setup_preview",
            "Staged group preview",
            40,
            span=2,
            description="Nothing is saved until Apply group is selected.",
        )
    if control_id.startswith("buddy_group_"):
        return _card(
            "setup_participation",
            "Group participation",
            50,
            description="Control how often buddies join and react to each other.",
        )
    if control_id in {
        "buddy_refine_scope",
        "buddy_refine_persona",
        "buddy_refine_field",
        "buddy_refine_instruction",
        "buddy_setup_refine",
        "buddy_setup_refine_cancel",
        "buddy_setup_refinement_status",
    }:
        return _card(
            "setup_refinement",
            "Optional LLM refinement",
            60,
            description="Ask the LLM to propose a focused change to the preview.",
        )
    if control_id in {
        "buddy_setup_shared_prompt",
        "buddy_setup_normal_prompt",
        "buddy_setup_adult_prompt",
    }:
        return _card(
            "setup_prompt_layers",
            "Shared prompt layers",
            70,
            span=2,
            description="Edit the shared conversation layers before applying.",
        )
    persona_match = re.fullmatch(r"buddy_setup_persona_(\d+)_(.+)", control_id)
    if persona_match is not None:
        index = int(persona_match.group(1))
        field = persona_match.group(2)
        name = staged_names.get(index, f"Buddy {index + 1}")
        order = 100 + index * 20
        if field in {"name", "role", "description", "system_prompt", "style"}:
            return _card(
                f"setup_persona_{index}_identity",
                f"{name} · identity",
                order,
                description="Identity, speaking style, and complete character prompt.",
            )
        return _card(
            f"setup_persona_{index}_behavior",
            f"{name} · response behavior",
            order + 10,
            description="Tune how this staged buddy participates and responds.",
        )
    if control_id in {
        "buddy_setup_undo",
        "buddy_setup_cancel",
        "buddy_setup_apply",
    }:
        return _card(
            "setup_finish",
            "Finish setup",
            1000,
            span=2,
        )
    return _card("setup_other", "Other setup controls", 1100, span=2)


def _overview_card(control_id: str) -> _Card:
    if control_id in {
        "buddy_enabled",
        "buddy_reply_mode",
        "buddy_llm_mode",
        "buddy_max_speakers",
        "buddy_forced_every",
        "buddy_structured_outputs",
    }:
        return _card(
            "overview_reply_flow",
            "Activation and reply routing",
            10,
            span=2,
            description="Choose when Buddy Chat participates and who writes replies.",
        )
    if control_id in {"buddy_persona_window", "buddy_persona_window_top"}:
        return _card(
            "overview_persona_display",
            "Active persona display",
            20,
            description="Control the window that follows the buddy currently speaking.",
        )
    if control_id in {"buddy_add", "buddy_import_mprc", "buddy_save"}:
        return _card(
            "overview_management",
            "Buddy management",
            30,
            description="Add or import buddies, then save the configuration.",
        )
    if control_id == "buddy_status":
        return _card("overview_status", "Current status", 40, span=2)
    return _card("overview_other", "Other settings", 100, span=2)


def _buddy_card(
    control_id: str,
    persona_names: dict[int, str],
) -> _Card:
    match = re.fullmatch(r"buddy_persona_(\d+)_(.+)", control_id)
    if match is None:
        return _card("buddies_other", "Other buddy settings", 1000, span=2)
    index = int(match.group(1))
    field = match.group(2)
    name = persona_names.get(index, f"Buddy {index + 1}")
    order = 10 + index * 30
    if field in {"enabled", "name", "role", "style", "remove"}:
        return _card(
            f"buddies_persona_{index}_identity",
            f"{name} · identity",
            order,
            description="Identity, speaking style, activation, and removal.",
        )
    if field in {"description", "system_prompt"}:
        return _card(
            f"buddies_persona_{index}_prompt",
            f"{name} · character prompt",
            order + 20,
            span=2,
            description="Long character fields use the full available width.",
        )
    return _card(
        f"buddies_persona_{index}_behavior",
        f"{name} · response behavior",
        order + 10,
        description="Tune how this buddy participates and responds.",
    )


def _voice_card(control_id: str, persona_names: dict[int, str]) -> _Card:
    match = re.fullmatch(r"buddy_persona_(\d+)_voice_.+", control_id)
    if match is None:
        return _card("voices_other", "Other voice settings", 1000, span=2)
    index = int(match.group(1))
    name = persona_names.get(index, f"Buddy {index + 1}")
    return _card(
        f"voices_persona_{index}",
        f"{name} · voice",
        10 + index * 10,
        description="Choose the reference sample used by supported TTS backends.",
    )


def _avatar_card(control_id: str, persona_names: dict[int, str]) -> _Card:
    match = re.fullmatch(r"buddy_persona_(\d+)_avatar_(.+)", control_id)
    if match is None:
        return _card("avatars_other", "Other avatar settings", 1000, span=2)
    index = int(match.group(1))
    field = match.group(2)
    name = persona_names.get(index, f"Buddy {index + 1}")
    order = 10 + index * 20
    if field == "preview":
        return _card(
            f"avatars_persona_{index}_preview",
            f"{name} · avatar preview",
            order,
        )
    return _card(
        f"avatars_persona_{index}_generator",
        f"{name} · avatar generator",
        order + 10,
        description="Edit the prompt and generate through Visual Reply.",
    )


_SHARED_PROVIDER_IDS = {
    "buddy_provider",
    "buddy_model",
    "buddy_base_url",
    "buddy_api_key",
    "buddy_refresh_models",
    "buddy_test_provider",
}


def _provider_card(control_id: str, persona_names: dict[int, str]) -> _Card:
    if control_id in _SHARED_PROVIDER_IDS:
        return _card(
            "providers_shared",
            "Shared Buddy provider",
            10,
            description="Used when provider mode is set to Use Buddy Provider.",
        )
    match = re.fullmatch(
        r"buddy_persona_(\d+)_(?:provider|model|base_url|api_key|refresh_models)",
        control_id,
    )
    if match is None:
        return _card("providers_other", "Other provider settings", 1000, span=2)
    index = int(match.group(1))
    name = persona_names.get(index, f"Buddy {index + 1}")
    return _card(
        f"providers_persona_{index}",
        f"{name} · provider override",
        20 + index * 10,
        description="Leave on Inherit unless this buddy needs another model.",
    )


def _advanced_card() -> _Card:
    return _card(
        "advanced_system_override",
        "Buddy system override",
        10,
        span=2,
        description="Advanced instructions used only while Buddy Chat is enabled.",
    )


def _resolve_card(
    control: NativeControl,
    *,
    staged_names: dict[int, str],
    persona_names: dict[int, str],
) -> _Card:
    if control.section == "Setup":
        return _setup_card(control, staged_names)
    if control.section == "Overview":
        return _overview_card(control.id)
    if control.section == "Buddies":
        return _buddy_card(control.id, persona_names)
    if control.section == "Voices":
        return _voice_card(control.id, persona_names)
    if control.section == "Avatars":
        return _avatar_card(control.id, persona_names)
    if control.section == "Providers":
        return _provider_card(control.id, persona_names)
    if control.section == "Advanced":
        return _advanced_card()
    key = re.sub(r"[^a-z0-9]+", "_", control.section.lower()).strip("_")
    return _card(f"{key or 'other'}_settings", "Other settings", 1000, span=2)


def _multiline_height(control: NativeControl) -> int:
    if bool(control.metadata.get("readOnly")):
        return 150
    if control.id.endswith("_description"):
        return 132
    if control.id in {
        "buddy_setup_normal_prompt",
        "buddy_setup_adult_prompt",
    }:
        return 144
    if control.id == "buddy_system_override_prompt":
        return 190
    return 176


def _action_width(control_id: str) -> int:
    if control_id.startswith("buddy_preset_"):
        return 184
    if control_id in {
        "buddy_import_mprc",
        "buddy_setup_build_preview",
    } or control_id.endswith("_voice_choose"):
        return 180
    if control_id.endswith("_avatar_generate"):
        return 170
    return 148


def apply_buddy_chat_layout(
    controls: Iterable[NativeControl],
) -> tuple[NativeControl, ...]:
    """Decorate Buddy Chat controls without changing runtime contracts."""

    source = tuple(controls)
    staged_names = _persona_names(source, staged=True)
    persona_names = _persona_names(source, staged=False)
    rendered: list[NativeControl] = []
    for control in source:
        card = _resolve_card(
            control,
            staged_names=staged_names,
            persona_names=persona_names,
        )
        metadata = dict(control.metadata)
        metadata.update(
            groupKey=card.key,
            groupTitle=card.title,
            groupDescription=card.description,
            groupOrder=card.order,
            groupColumnSpan=card.span,
        )
        if control.kind is NativeControlKind.ACTION:
            metadata.update(
                actionStrip=True,
                compactActionWidth=_action_width(control.id),
            )
        if control.kind is NativeControlKind.MULTILINE:
            metadata.update(
                stackedLayout=True,
                scrollable=True,
                editorPreferredHeight=_multiline_height(control),
            )
        if control.kind is NativeControlKind.IMAGE:
            metadata.update(
                imageMinimumWidth=180,
                imageMinimumHeight=180,
                editorPreferredWidth=220,
            )
        rendered.append(replace(control, metadata=metadata))
    return tuple(rendered)


__all__ = ["apply_buddy_chat_layout"]
