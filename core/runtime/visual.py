"""Lease-bound Visual Reply generation, publication, and history ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
import re
import threading
import uuid

from core.runtime.contracts import (
    CancellationToken,
    CommandResult,
    RuntimeFailure,
)
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerHandle, WorkerSupervisor


LeaseCheck = Callable[[WorkLease], bool]
RequestIdFactory = Callable[[], str]
CompletionCommit = Callable[
    [WorkLease, Callable[[], object]],
    CommandResult[object],
]
ImageReviewCallback = Callable[[Mapping[str, object]], object]

PERSONA_VISUAL_REPLY_POLICIES = frozenset(
    {"inherit", "off", "requested", "spontaneous"}
)
PERSONA_SELF_IMAGE_MODES = frozenset({"hybrid", "prompt", "reference"})
PERSONA_SELF_VISUAL_PREFIX = "@self"
USER_VISUAL_PREFIX = "@user"
USER_VISUAL_POLICIES = frozenset({"requested", "allowed", "never"})
VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY = "_visual_reply_user_request_text"
VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY = "_visual_reply_source_image_path"


def normalize_persona_visual_reply_policy(value: object) -> str:
    """Return the persisted per-persona Visual Reply policy."""

    policy = str(value or "inherit").strip().lower()
    return policy if policy in PERSONA_VISUAL_REPLY_POLICIES else "inherit"


def resolve_persona_visual_reply_policy(config: Mapping[str, object]) -> str:
    """Resolve old sessions without a persona policy from Visual Reply state."""

    policy = normalize_persona_visual_reply_policy(
        config.get("persona_visual_reply_policy", "inherit")
    )
    if policy != "inherit":
        return policy
    enabled = bool(config.get("visual_replies_enabled", True))
    mode = str(config.get("visual_reply_mode", "off") or "off").strip().lower()
    return "requested" if enabled and mode != "off" else "off"


def normalize_persona_self_image_mode(value: object) -> str:
    mode = str(value or "hybrid").strip().lower()
    return mode if mode in PERSONA_SELF_IMAGE_MODES else "hybrid"


def normalize_persona_appearance_freedom(value: object) -> str:
    return "flexible" if str(value or "").strip().lower() == "flexible" else "strict"


def persona_visual_identity_available(config: Mapping[str, object]) -> bool:
    return bool(
        str(config.get("persona_visual_identity_prompt", "") or "").strip()
        or str(config.get("persona_visual_reference_path", "") or "").strip()
    )


def normalize_user_visual_policy(value: object) -> str:
    policy = str(value or "requested").strip().lower()
    return policy if policy in USER_VISUAL_POLICIES else "requested"


def user_visual_identity_available(config: Mapping[str, object]) -> bool:
    if not bool(config.get("user_identity_enabled", False)):
        return False
    if normalize_user_visual_policy(
        config.get("user_identity_visual_policy", "requested")
    ) == "never":
        return False
    return bool(
        str(config.get("user_identity_visual_identity_prompt", "") or "").strip()
        or str(config.get("user_identity_visual_reference_path", "") or "").strip()
    )


def visual_generation_instruction(
    *,
    enabled: bool,
    automatic_allowed: bool,
    persona_identity_available: bool = False,
    user_identity_available: bool = False,
    user_visual_policy: str = "requested",
    comfyui_rules: str = "",
) -> str:
    """Build the single hidden instruction understood by the Visual Reply parser."""

    if not enabled:
        return ""
    instruction = (
        "Visual reply capability is available. If the user explicitly asks you "
        "to generate, draw, create, show, or make an image or picture, append "
        "exactly one tag at the end of your reply in this form: [visualize: "
        "concise image prompt]. Keep the prompt concrete and under 180 "
        "characters. For image-only requests, keep the visible text reply to a "
        "brief acknowledgement. If the user also asks for text, answer that text "
        "request normally."
    )
    if comfyui_rules:
        from addons.visual_reply.comfyui_prompting import model_instruction

        instruction = instruction.replace(
            "concise image prompt]. Keep the prompt concrete and under 180 characters.",
            "English image prompt]. Keep the prompt concrete and visually coherent.",
        )
        instruction += " " + model_instruction(comfyui_rules)
    if automatic_allowed:
        instruction += (
            " You may also use this sparingly and spontaneously when a generated "
            "image would meaningfully strengthen the response. Do not generate an "
            "image for every turn."
        )
    if persona_identity_available:
        instruction += (
            " When the requested image depicts you, your body, your face, or "
            "yourself as the active persona, begin the concise image prompt with "
            f"the exact marker {PERSONA_SELF_VISUAL_PREFIX} followed by the scene. "
            "Keep that marker inside the [visualize: ...] tag; never show it as "
            "visible reply text. Use the form [visualize: @self scene from the "
            "current user request]. The text after the marker must restate the "
            "current request's subject, action, named objects, and setting; never "
            "reuse a scene from these instructions. "
            "Use this marker only when the user's current request explicitly asks "
            "for the active persona to appear in the image. Do not infer persona "
            "inclusion merely because you are describing the image, because a saved "
            "persona portrait exists, or because the request depicts another person. "
            "Do not use that marker for other people or ordinary subjects."
        )
    if user_identity_available:
        instruction += (
            " When the requested image depicts the human user, begin the concise "
            f"image prompt with the exact marker {USER_VISUAL_PREFIX}. When it depicts "
            "both the active persona and the human user, begin it with the exact markers "
            f"{PERSONA_SELF_VISUAL_PREFIX} {USER_VISUAL_PREFIX}, in that order. Keep "
            "these markers inside the [visualize: ...] tag and never expose them as "
            "visible reply text. Do not use the user marker for the AI persona or for "
            "unrelated people."
        )
        if normalize_user_visual_policy(user_visual_policy) == "requested":
            instruction += (
                " Use the user marker only when the user explicitly asks to appear in "
                "the generated image."
            )
        else:
            instruction += (
                " You may include the user sparingly when doing so clearly improves an "
                "otherwise appropriate spontaneous Visual Reply."
            )
    return instruction


@dataclass(frozen=True, slots=True)
class PersonaVisualPlan:
    prompt: str
    inputs: tuple[Path, ...] = ()
    reference_strength: float | None = None
    uses_persona_identity: bool = False
    uses_user_identity: bool = False
    edits_source_image: bool = False
    source_edit_error: str = ""


def _attached_photo_edit_plan(runtime_config: Mapping[str, object]) -> PersonaVisualPlan | None:
    """Use only the accepted turn's photo, never a global/latest image."""
    source = str(runtime_config.get(VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY, "") or "").strip()
    request = str(runtime_config.get(VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY, "") or "").strip()
    if not source or not request:
        return None
    # Deliberately narrow imperative/request clauses: descriptions, hypotheticals
    # and negated requests must not start a paid edit.
    edit = re.search(
        r"(?:^|[.!?]\s+)(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
        r"(?:(?:edit|modify|change|add|put|place|insert|include|remove|replace|erase|"
        r"transform|recolor|retouch)\b|(?:make|turn)\s+(?:(?:the|this|that|attached|uploaded|my)\s+)*"
        r"(?:photo|picture|image)\b)[^.!?]*", request, re.IGNORECASE,
    )
    if edit is None or not re.search(r"\b(?:photo|picture|image|photograph)\b", request, re.IGNORECASE):
        return None
    if re.search(r"\b(?:do\s+not|don't|never)\s+(?:edit|modify|change|add|put|place|insert|include|remove|replace)\b", request, re.IGNORECASE):
        return None
    name = runtime_config.get("active_quick_persona_name", "")
    persona = _user_explicitly_requested_persona(request, name)
    inputs = [Path(source).expanduser()]
    error = ""
    prompt = (
        "Edit image 1, the user's source photo. Preserve its existing people, objects, "
        "background, composition and framing except for the requested changes. "
        f"Requested edit: {request.rstrip('.!?')}. "
    )
    if persona:
        portrait = str(runtime_config.get("persona_visual_reference_path", "") or "").strip()
        if portrait:
            inputs.append(Path(portrait).expanduser())
        else:
            error = "The active persona has no reference portrait. Set a persona portrait and retry."
        identity = _compact_persona_identity(runtime_config.get("persona_visual_identity_prompt", ""))
        prompt += (
            f"Image 2 is the identity reference for {name or 'the active persona'}. "
            f"Preserve that character's recognizable face and identity. {identity}. "
            "Use image 2 only for the character; do not copy its background or framing. "
            "Add the character naturally into image 1 with matching scale, perspective, "
            "lighting and shadows. Keep existing people distinct; do not replace or merge them."
        )
    return PersonaVisualPlan(
        prompt=prompt.strip(), inputs=tuple(inputs), reference_strength=0.75,
        uses_persona_identity=persona, edits_source_image=True, source_edit_error=error,
    )


def _bounded_prompt_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return shortened or text[:limit].rstrip(" ,;:.-")


def _authoritative_visual_request(value: object) -> str:
    """Keep the user's requested scene ahead of any assistant-authored scene draft."""

    text = " ".join(str(value or "").split())
    if not text:
        return ""
    request = re.search(
        r"\b(?:please\s+)?(?:generate|create|draw|make|show)\b",
        text,
        flags=re.IGNORECASE,
    )
    if request is not None:
        text = text[request.start() :]
    return _bounded_prompt_text(text, 260).rstrip(" .")


def _compact_persona_identity(value: object) -> str:
    """Reduce generic continuity prose to a visual identity anchor."""

    identity = _bounded_prompt_text(value, 260).rstrip(" .")
    lowered = identity.lower()
    if (
        "consistent recurring character" in lowered
        and "match the saved reference portrait" in lowered
    ):
        return (
            "recognizable face, adult age, core hair and eye identity, color palette, "
            "and established art style"
        )
    return identity


def _compact_user_identity(value: object) -> str:
    """Keep stable human traits while dropping saved scene and camera directions."""

    identity = " ".join(str(value or "").split())
    if not identity:
        return ""
    stable_cues = (
        "adult", "age", "man", "woman", "male", "female", "person", "human",
        "face", "facial", "hair", "eyes", "eye", "beard", "skin", "freckles",
        "jaw", "nose", "mouth", "android", "cyborg",
    )
    scene_cues = (
        "background", "corridor", "room", "street", "landscape", "lighting",
        "illuminated", "camera", "framing", "composition", "depth of field",
        "photorealistic", "cinematic", "color grading", "portrait image",
        "centered", "wearing", "dressed", "positioned",
    )
    sentences = re.split(r"(?<=[.!?])\s+", identity)
    kept: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        has_stable_traits = any(cue in lowered for cue in stable_cues)
        has_scene_direction = any(cue in lowered for cue in scene_cues)
        if has_stable_traits or not has_scene_direction:
            kept.append(sentence)
    compact = " ".join(kept).strip()
    compact = re.sub(
        r"\b(?:a\s+)?(?:cinematic\s+)?(?:close-up\s+)?portrait\s+of\s+",
        "",
        compact,
        flags=re.IGNORECASE,
    )
    compact = re.sub(
        r"\b(?:photorealistic|cinematic|AAA\s+science-fiction)\b[ ,;-]*",
        "",
        compact,
        flags=re.IGNORECASE,
    )
    return _bounded_prompt_text(compact, 220).rstrip(" .")


def _explicit_joint_identity_request(value: object) -> bool:
    """Recognize direct two-person requests, including the common both/booth typo."""

    request = " ".join(str(value or "").lower().split())
    if not request:
        return False
    request = re.sub(r"\bbooth\s+of\s+us\b", "both of us", request)
    return bool(
        re.search(
            r"\b(?:both\s+of\s+us|the\s+two\s+of\s+us|you\s+and\s+me|"
            r"me\s+and\s+you|us\s+together)\b",
            request,
        )
    )


def _normalize_joint_request_text(value: object) -> str:
    return re.sub(
        r"\bbooth\s+of\s+us\b",
        "both of us",
        str(value or ""),
        flags=re.IGNORECASE,
    )


def plan_persona_visual_request(
    prompt: str,
    runtime_config: Mapping[str, object],
) -> PersonaVisualPlan:
    """Resolve opt-in ``@self``/``@user`` markers without changing other prompts."""

    original = str(prompt or "").strip()
    photo_edit = _attached_photo_edit_plan(runtime_config)
    if photo_edit is not None:
        return photo_edit
    if not original and runtime_config.get(VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY):
        return PersonaVisualPlan(prompt="")
    uses_persona, uses_user, scene = _visual_identity_markers(original)
    authoritative_scene = ""
    if VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY in runtime_config:
        request_text = str(
            runtime_config.get(VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY, "") or ""
        )
        joint_request = _explicit_joint_identity_request(request_text)
        uses_persona = bool(
            persona_visual_identity_available(runtime_config)
            and (
                joint_request
                or _user_explicitly_requested_persona(
                    request_text,
                    runtime_config.get("active_quick_persona_name", ""),
                )
            )
        )
        uses_user = bool(uses_user or joint_request)
        if uses_persona:
            authoritative_scene = _authoritative_visual_request(
                _normalize_joint_request_text(request_text)
            )
    if not uses_persona and not uses_user:
        return PersonaVisualPlan(prompt=scene or original)

    user_policy = normalize_user_visual_policy(
        runtime_config.get("user_identity_visual_policy", "requested")
    )
    uses_user = bool(
        uses_user
        and bool(runtime_config.get("user_identity_enabled", False))
        and user_policy != "never"
    )
    if not uses_persona and not uses_user:
        return PersonaVisualPlan(prompt=scene or original)
    persona_scene = (authoritative_scene or scene).rstrip(" .")
    if not persona_scene:
        if uses_persona and uses_user:
            persona_scene = "a natural portrait of the active persona together with the user"
        elif uses_user:
            persona_scene = "a natural portrait of the user"
        else:
            persona_scene = "a natural portrait of the active persona"
    scene = persona_scene
    persona_identity = _compact_persona_identity(
        runtime_config.get("persona_visual_identity_prompt", "")
    )
    persona_name = str(
        runtime_config.get("active_quick_persona_name", "") or "the active persona"
    ).strip()
    user_identity = _compact_user_identity(
        runtime_config.get("user_identity_visual_identity_prompt", "")
    )
    user_name = str(
        runtime_config.get("user_identity_name", "") or "the human user"
    ).strip() or "the human user"
    flexible = uses_persona and normalize_persona_appearance_freedom(
        runtime_config.get("persona_appearance_freedom")
    ) == "flexible"
    if flexible:
        # Keep the requested scene first while preserving the persona's stable
        # identity. Flexible appearance changes scene styling, not who appears.
        resolved_prompt = (
            f"Requested scene (highest priority): {persona_scene}. Character: "
            f"{persona_name}. Identity (must preserve): "
            f"{persona_identity or 'the established recurring persona identity'}. "
            "Keep the recognizable face, apparent age, gender presentation, core hair "
            "and eyes, species, palette, and art style. Flexible appearance: the scene "
            "may change pose, expression, clothing, props, background, composition, "
            "and framing. Show every requested action and named object. Frame wide "
            "enough to clearly show them; never return a standalone portrait for an "
            "action or prop. "
        )
        if uses_user:
            resolved_prompt = (
                "Required composition (highest priority): two distinct people, "
                f"{persona_name[:24]} and {user_name[:24]}, together. "
                f"Requested scene: {persona_scene[:220]}. Medium-wide two-shot; show "
                "both, all actions, objects, and the setting. AI persona: "
                f"{persona_identity[:120] or 'established persona identity'}. "
                f"Human: {user_identity[:120] or 'established human user identity'}. "
                "Shared art style: the persona's established style. Keep both identities "
                "recognizable and distinct; do not merge them. The scene overrides saved "
                "pose, clothing, background, lighting, camera, and framing. No "
                "single-person portrait or isolated headshot."
            )
    elif uses_persona and uses_user:
        resolved_prompt = (
            "Create a scene containing two distinct recurring identities. "
            f"Requested scene (highest priority): {persona_scene}. "
            f"Active AI persona, {persona_name}: "
            f"{persona_identity or 'preserve the established active persona identity'}. "
            f"Human user, {user_name}: "
            f"{user_identity or 'preserve the established human user identity'}. "
            "Preserve each face, age, hair, body traits, "
            "signature clothing, and art style. Do not merge, swap, average, or clone "
            "the two identities. The first reference panel is the AI persona and the "
            "second reference panel is the human user. Use identity traits without "
            "copying either reference background or framing."
        )
    elif uses_user:
        if user_identity:
            resolved_prompt = (
                f"Create the same recognizable human user, {user_name}. Stable visual "
                f"identity: {user_identity}. Requested scene: {scene}. Preserve face, "
                "age, hair, body traits, and signature clothing unless the scene "
                "explicitly changes clothing. Do not copy the reference background or framing."
            )
        else:
            resolved_prompt = f"Create the same recognizable human user, {user_name}. {scene}."
    elif uses_persona and persona_identity:
        resolved_prompt = (
            f"Requested scene (highest priority): {persona_scene}. Preserve every "
            "specifically requested subject, action, named object, pose, and setting. "
            f"Character: {persona_name}. Visual identity anchor: {persona_identity}. "
            "Preserve that identity and its established art direction. The scene "
            "controls pose, expression, "
            "clothing, props, background, composition, and framing. Use any saved "
            "portrait only for identity and style; do not copy its pose or background "
            "and do not introduce unrelated objects or actions."
        )
    else:
        resolved_prompt = (
            f"Requested scene (highest priority): {persona_scene}. Create {persona_name} "
            "as the same recurring character. The scene controls pose, expression, "
            "clothing, props, background, composition, and framing."
        )

    mode = normalize_persona_self_image_mode(
        runtime_config.get("persona_self_image_mode", "hybrid")
    )
    persona_reference_path = str(
        runtime_config.get("persona_visual_reference_path", "") or ""
    ).strip()
    persona_reference = (
        Path(persona_reference_path).expanduser() if persona_reference_path else None
    )
    user_reference_path = str(
        runtime_config.get("user_identity_visual_reference_path", "") or ""
    ).strip()
    user_reference = (
        Path(user_reference_path).expanduser() if user_reference_path else None
    )
    inputs_list: list[Path] = []
    strengths: list[float] = []
    try:
        persona_strength = float(
            runtime_config.get("persona_visual_reference_strength", 0.75)
        )
    except (TypeError, ValueError):
        persona_strength = 0.75
    try:
        user_strength = float(
            runtime_config.get("user_identity_visual_reference_strength", 0.52)
        )
    except (TypeError, ValueError):
        user_strength = 0.52
    if (
        uses_persona
        and mode != "prompt"
        and persona_reference is not None
        and persona_reference.is_file()
    ):
        inputs_list.append(persona_reference.resolve())
        bounded_persona_strength = max(0.0, min(1.0, persona_strength))
        # Runware calls this transformation strength: higher values give the
        # requested scene more control and preserve less source composition.
        # Hybrid exposes that balance directly. Reference-preferred keeps a
        # portrait-focused fixed value for subtle changes and mood-like scenes.
        strengths.append(
            0.35 if mode == "reference" else bounded_persona_strength
        )
    if uses_user and user_reference is not None and user_reference.is_file():
        resolved_user = user_reference.resolve()
        if resolved_user not in inputs_list:
            inputs_list.append(resolved_user)
            strengths.append(max(0.0, min(1.0, user_strength)))
    inputs = tuple(inputs_list)
    if uses_persona and uses_user and len(inputs) >= 2:
        resolved_prompt += (
            " The first reference panel is the AI persona and the second reference "
            "panel is the human user; ignore both backgrounds and framing."
        )
    elif uses_user and inputs:
        resolved_prompt += " The reference panel is the human user; ignore background/framing."
    elif uses_persona and inputs:
        resolved_prompt += " The reference panel is the AI persona; ignore background/framing."
    strength = sum(strengths) / len(strengths) if strengths else None
    if uses_persona and uses_user and len(inputs) >= 2 and strength is not None:
        strength = max(0.70, min(0.80, strength))
    return PersonaVisualPlan(
        prompt=resolved_prompt.strip(),
        inputs=inputs,
        reference_strength=strength,
        uses_persona_identity=uses_persona,
        uses_user_identity=uses_user,
    )


def _visual_identity_markers(prompt: str) -> tuple[bool, bool, str]:
    remaining = str(prompt or "").strip()
    uses_persona = False
    uses_user = False
    while remaining:
        lowered = remaining.lower()
        matched = ""
        for marker in (PERSONA_SELF_VISUAL_PREFIX, USER_VISUAL_PREFIX):
            following = lowered[len(marker) : len(marker) + 1]
            if lowered == marker or (
                lowered.startswith(marker) and following in {" ", ":", "-", "\t"}
            ):
                matched = marker
                break
        if not matched:
            break
        uses_persona = uses_persona or matched == PERSONA_SELF_VISUAL_PREFIX
        uses_user = uses_user or matched == USER_VISUAL_PREFIX
        remaining = remaining[len(matched) :].lstrip(" :-\t")
    return uses_persona, uses_user, remaining


def _user_explicitly_requested_persona(
    request_text: object,
    persona_name: object,
) -> bool:
    """Return whether the accepted user turn explicitly puts the persona on screen."""

    request = " ".join(str(request_text or "").lower().split())
    if not request:
        return False
    if re.search(r"(?<!\w)@self(?!\w)", request):
        return True

    name = " ".join(str(persona_name or "").lower().split())
    if name:
        escaped_name = rf"(?<!\w){re.escape(name)}(?!\w)"
        name_patterns = (
            rf"\b(?:image|picture|photo|portrait|drawing|artwork|scene|visual)\s+"
            rf"(?:of|with|including|featuring)\s+{escaped_name}",
            rf"\b(?:include|feature|show|depict|draw|render|paint|add|put)\s+"
            rf"{escaped_name}",
            rf"{escaped_name}\s+(?:in|inside|at|beside|next\s+to|with|as|wearing|"
            rf"holding|standing|sitting|posing)\b",
        )
        if any(re.search(pattern, request) for pattern in name_patterns):
            return True

    explicit_patterns = (
        r"\b(?:image|picture|photo|portrait|drawing|artwork|scene|visual)\s+"
        r"(?:of|with|including|featuring)\s+(?:you|yourself|himself|herself|themselves)\b",
        r"\b(?:include|feature|depict|draw|render|paint|add|put)\s+"
        r"(?:you|yourself|himself|herself|themselves|your\s+(?:avatar|character|persona))\b",
        r"\bshow\s+me\s+(?:you|yourself|your\s+(?:avatar|character|persona))\b",
        r"\b(?:show|generate|create|make)\s+(?:an?\s+(?:image|picture|photo|portrait)\s+"
        r"of\s+)?(?:yourself|your\s+(?:avatar|character|persona))\b",
        r"\b(?:image|picture|photo|portrait|drawing|artwork|scene|visual)\s+"
        r"(?:where|in\s+which)\s+you\b",
        r"\b(?:you|yourself)\s+(?:in|inside|at|beside|next\s+to|with|as|wearing|"
        r"holding|standing|sitting|posing)\b",
        r"\byour\s+(?:face|body|avatar|appearance|portrait|image|photo|picture|"
        r"character|persona)\b",
        r"\b(?:both\s+of\s+us|the\s+two\s+of\s+us|you\s+and\s+me|me\s+and\s+you|"
        r"us\s+together)\b",
    )
    return any(re.search(pattern, request) for pattern in explicit_patterns)


def persona_visual_request_config(
    runtime_config: Mapping[str, object],
    *,
    reference_strength: float | None,
    reference_count: int = 0,
    edits_source_image: bool = False,
    source_edit_error: str = "",
) -> dict[str, object]:
    """Enable provider I2I only for one identity-reference request."""

    resolved = dict(runtime_config or {})
    if edits_source_image:
        resolved["_visual_reply_source_edit"] = True
        resolved["_visual_reply_source_edit_error"] = source_edit_error
    if reference_strength is None:
        return resolved
    provider = str(resolved.get("visual_reply_provider", "") or "").strip().lower()
    if provider not in {"runware", "xai"}:
        return resolved
    raw_settings = resolved.get("visual_reply_provider_settings", {})
    if not isinstance(raw_settings, Mapping):
        raw_settings = {}
    provider_settings = {
        str(key): dict(value) if isinstance(value, Mapping) else value
        for key, value in dict(raw_settings or {}).items()
    }
    selected = dict(provider_settings.get(provider) or {})
    selected["image_to_image_enabled"] = True
    if provider == "runware":
        selected["image_to_image_strength"] = max(
            0.0, min(1.0, float(reference_strength))
        )
        if int(reference_count or 0) > 1:
            selected["request_scoped_reference_board"] = True
    provider_settings[provider] = selected
    resolved["visual_reply_provider_settings"] = provider_settings
    return resolved


@dataclass(frozen=True, slots=True)
class VisualRequest:
    request_id: str
    binding_id: str
    lease: WorkLease
    prompt: str
    inputs: tuple[Path, ...] = ()
    source_text: str = ""
    keep_current_image: bool = False
    runtime_config: Mapping[str, object] | None = None
    story_session_id: int | None = None
    asset_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class VisualResult:
    request_id: str
    binding_id: str
    lease: WorkLease
    prompt: str
    output: Path
    source_text: str = ""
    keep_current_image: bool = False
    asset_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    inputs: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class VisualHistoryLink:
    request_id: str
    binding_id: str
    session_lease: WorkLease
    turn_lease: WorkLease
    prompt: str
    output: Path
    source_text: str = ""
    asset_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    inputs: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class VisualGeneratedAsset:
    output: Path
    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class VisualStorySession:
    session_id: int
    lease: WorkLease | None
    max_images: int
    requested_images: int
    style_guide: str


@dataclass(frozen=True, slots=True)
class VisualSnapshot:
    running: bool
    active_requests: tuple[VisualRequest, ...]
    pending_history_links: tuple[VisualHistoryLink, ...]
    active_story_session: int
    story: VisualStorySession | None = None


@dataclass(frozen=True, slots=True)
class VisualPolicyCapabilities:
    """Finite Visual Reply policy surface supplied by the owning addon."""

    mode: Callable[[], str] | None = None
    enabled: Callable[[], bool] | None = None
    enabled_for: Callable[[Mapping[str, object]], bool] | None = None
    generation_available: Callable[[], bool] | None = None
    generation_available_for: Callable[[Mapping[str, object]], bool] | None = None
    story_mode_enabled: Callable[[], bool] | None = None
    story_max_images: Callable[[], int] | None = None
    story_continuity_strength: Callable[[], float] | None = None
    story_theme_prompts: Callable[[], Mapping[str, str]] | None = None
    story_theme_enabled: Callable[[], tuple[str, ...] | list[str]] | None = None
    story_theme_suffix: Callable[[], str] | None = None
    master_style_prompt: Callable[[], str] | None = None
    master_style_suffix: Callable[[], str] | None = None
    master_prompt_safety_suffix: Callable[[], str] | None = None
    no_speech_bubbles_suffix: Callable[[], str] | None = None
    apply_style_anchor: Callable[[str], str] | None = None
    story_style_guide: Callable[[str, float], str] | None = None
    story_prompt: Callable[[str, str, str], str] | None = None
    normalize_prompt: Callable[[str], str] | None = None
    strip_visual_tail: Callable[[str], tuple[str, str]] | None = None
    looks_like_tag_prefix: Callable[[str], bool] | None = None
    extract_prompt: Callable[[str], tuple[str, str]] | None = None


@dataclass(frozen=True, slots=True)
class VisualCapabilities:
    """Narrow addon adapters used without exposing engine or Qt host objects."""

    generate: Callable[
        [VisualRequest, CancellationToken],
        VisualGeneratedAsset | Path | str | None,
    ] | None = None
    publish_requested: Callable[[VisualRequest], object] | None = None
    publish_result: Callable[[VisualResult], object] | None = None
    publish_failure: Callable[[VisualRequest, RuntimeFailure], object] | None = None
    attach_history: Callable[[VisualHistoryLink], object] | None = None
    refresh_history: Callable[[WorkLease], object] | None = None
    preview_asset: Callable[[str], object] | None = None
    policy: VisualPolicyCapabilities | None = None
    retire_request: Callable[[VisualRequest, str], object] | None = None


@dataclass(slots=True)
class _VisualBinding:
    request: VisualRequest
    handle: WorkerHandle | None = None
    completing: bool = False
    spawn_started: bool = False
    cancel_reason: str = ""
    run_gate: threading.Event = field(default_factory=threading.Event)
    startup_complete: threading.Event = field(default_factory=threading.Event)
    history_link: VisualHistoryLink | None = None


@dataclass(slots=True)
class _PendingHistoryBinding:
    link: VisualHistoryLink
    reconciling: bool = False
    cancelled: bool = False
    claim_complete: threading.Event | None = None


@dataclass(slots=True)
class _StoryBinding:
    session_id: int
    lease: WorkLease | None
    max_images: int
    requested_images: int = 0
    style_guide: str = ""


class VisualService:
    """Own Visual Reply workers and exact request-to-turn publication admission."""

    name = "visual"

    def __init__(
        self,
        *,
        workers: WorkerSupervisor,
        lease_is_current: LeaseCheck,
        capabilities: VisualCapabilities | None = None,
        request_id_factory: RequestIdFactory | None = None,
        commit_completion: CompletionCommit | None = None,
    ) -> None:
        self._workers = workers
        self._lease_is_current = lease_is_current
        self._capabilities = capabilities or VisualCapabilities()
        self._request_id_factory = request_id_factory or (
            lambda: f"visual_{uuid.uuid4().hex}"
        )
        self._commit_completion = commit_completion or self._commit_if_current
        self._lock = threading.Lock()
        self._running = False
        self._bindings: dict[str, _VisualBinding] = {}
        self._pending_history: dict[tuple[str, str], _PendingHistoryBinding] = {}
        self._story_counter = 0
        self._active_story_session = 0
        self._story: _StoryBinding | None = None
        self._image_review_callback: ImageReviewCallback | None = None

    def start(self) -> CommandResult[None]:
        with self._lock:
            self._running = True
        return CommandResult(True)

    def mode(self) -> str:
        policy = self._capabilities.policy
        if policy is None or policy.mode is None:
            return "off"
        return str(policy.mode() or "off").strip().lower() or "off"

    def enabled(self, runtime_config: Mapping[str, object] | None = None) -> bool:
        policy = self._capabilities.policy
        if policy is None:
            return True
        if runtime_config is not None and policy.enabled_for is not None:
            return bool(policy.enabled_for(_freeze_mapping(runtime_config)))
        return bool(policy.enabled()) if policy.enabled is not None else True

    def generation_available(
        self,
        runtime_config: Mapping[str, object] | None = None,
    ) -> bool:
        policy = self._capabilities.policy
        if policy is None:
            return self._capabilities.generate is not None
        if runtime_config is not None and policy.generation_available_for is not None:
            return bool(
                policy.generation_available_for(_freeze_mapping(runtime_config))
            )
        if policy.generation_available is not None:
            return bool(policy.generation_available())
        return self._capabilities.generate is not None

    def story_mode_enabled(self) -> bool:
        policy = self._capabilities.policy
        return bool(
            policy is not None
            and policy.story_mode_enabled is not None
            and policy.story_mode_enabled()
        )

    def story_max_images(self) -> int:
        policy = self._capabilities.policy
        value = (
            policy.story_max_images()
            if policy is not None and policy.story_max_images is not None
            else 3
        )
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 3

    def story_continuity_strength(self) -> float:
        policy = self._capabilities.policy
        value = (
            policy.story_continuity_strength()
            if policy is not None and policy.story_continuity_strength is not None
            else 0.8
        )
        try:
            strength = float(value)
        except (TypeError, ValueError):
            strength = 0.8
        if strength > 1.0:
            strength /= 100.0
        return max(0.0, min(1.0, strength))

    def story_theme_prompts(self) -> Mapping[str, str]:
        policy = self._capabilities.policy
        values = (
            policy.story_theme_prompts()
            if policy is not None and policy.story_theme_prompts is not None
            else {}
        )
        return MappingProxyType(
            {str(key): str(value) for key, value in dict(values or {}).items()}
        )

    def story_theme_enabled(self) -> tuple[str, ...]:
        policy = self._capabilities.policy
        values = (
            policy.story_theme_enabled()
            if policy is not None and policy.story_theme_enabled is not None
            else ()
        )
        return tuple(str(value) for value in values or ())

    def story_theme_suffix(self) -> str:
        policy = self._capabilities.policy
        return str(
            policy.story_theme_suffix()
            if policy is not None and policy.story_theme_suffix is not None
            else ""
        ).strip()

    def master_style_prompt(self) -> str:
        policy = self._capabilities.policy
        return str(
            policy.master_style_prompt()
            if policy is not None and policy.master_style_prompt is not None
            else ""
        ).strip()

    def master_style_suffix(self) -> str:
        policy = self._capabilities.policy
        return str(
            policy.master_style_suffix()
            if policy is not None and policy.master_style_suffix is not None
            else ""
        ).strip()

    def master_prompt_safety_suffix(self) -> str:
        policy = self._capabilities.policy
        return str(
            policy.master_prompt_safety_suffix()
            if policy is not None
            and policy.master_prompt_safety_suffix is not None
            else ""
        ).strip()

    def no_speech_bubbles_suffix(self) -> str:
        policy = self._capabilities.policy
        return str(
            policy.no_speech_bubbles_suffix()
            if policy is not None and policy.no_speech_bubbles_suffix is not None
            else ""
        ).strip()

    def apply_style_anchor(self, prompt: str) -> str:
        text = str(prompt or "").strip()
        policy = self._capabilities.policy
        if policy is None or policy.apply_style_anchor is None:
            return text
        return str(policy.apply_style_anchor(text) or "").strip()

    def story_style_guide(
        self,
        story_text: str,
        continuity_strength: float | None = None,
    ) -> str:
        policy = self._capabilities.policy
        if policy is None or policy.story_style_guide is None:
            return ""
        strength = (
            self.story_continuity_strength()
            if continuity_strength is None
            else max(0.0, min(1.0, float(continuity_strength)))
        )
        return str(policy.story_style_guide(str(story_text or ""), strength) or "")

    def story_prompt(
        self,
        text: str,
        emotion: str = "",
        story_style_guide: str = "",
    ) -> str:
        policy = self._capabilities.policy
        if policy is None or policy.story_prompt is None:
            return ""
        return str(
            policy.story_prompt(
                str(text or ""),
                str(emotion or ""),
                str(story_style_guide or ""),
            )
            or ""
        ).strip()

    def normalize_prompt(self, prompt: str) -> str:
        text = str(prompt or "").strip()
        policy = self._capabilities.policy
        if policy is None or policy.normalize_prompt is None:
            return text
        return str(policy.normalize_prompt(text) or "").strip()

    def strip_visual_tail(self, text: str) -> tuple[str, str]:
        value = str(text or "")
        policy = self._capabilities.policy
        if policy is None or policy.strip_visual_tail is None:
            return value, ""
        cleaned, prompt = policy.strip_visual_tail(value)
        return str(cleaned or ""), str(prompt or "")

    def looks_like_tag_prefix(self, fragment: str) -> bool:
        policy = self._capabilities.policy
        return bool(
            policy is not None
            and policy.looks_like_tag_prefix is not None
            and policy.looks_like_tag_prefix(str(fragment or ""))
        )

    def extract_prompt(self, text: str) -> tuple[str, str]:
        value = str(text or "")
        policy = self._capabilities.policy
        if policy is None or policy.extract_prompt is None:
            return value, ""
        cleaned, prompt = policy.extract_prompt(value)
        return str(cleaned or ""), str(prompt or "")

    def generation_instruction(
        self,
        runtime_config: Mapping[str, object] | None = None,
        *,
        automatic_allowed: bool = False,
    ) -> str:
        from addons.visual_reply.comfyui_prompting import rules_for_config

        return visual_generation_instruction(
            enabled=self.generation_available(runtime_config),
            automatic_allowed=automatic_allowed,
            comfyui_rules=rules_for_config(runtime_config or {}),
        )

    def request_generation(
        self,
        lease: WorkLease,
        *,
        prompt: str,
        inputs: tuple[Path, ...] = (),
        source_text: str = "",
        keep_current_image: bool = False,
        request_id: str | None = None,
        runtime_config: Mapping[str, object] | None = None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[VisualRequest]:
        if not self.enabled(runtime_config):
            return _failure("visual_disabled", "Visual Reply is disabled")
        return self.request(
            lease,
            prompt=prompt,
            inputs=inputs,
            source_text=source_text,
            keep_current_image=keep_current_image,
            request_id=request_id,
            runtime_config=runtime_config,
            asset_metadata=asset_metadata,
        )

    def request(
        self,
        lease: WorkLease,
        *,
        prompt: str,
        inputs: tuple[Path, ...] = (),
        source_text: str = "",
        keep_current_image: bool = False,
        request_id: str | None = None,
        runtime_config: Mapping[str, object] | None = None,
        story_session_id: int | None = None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[VisualRequest]:
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            return _failure("visual_prompt_required", "Visual prompt is required")
        if not self._lease_is_current(lease):
            return _failure("visual_stale_lease", "Visual request lease is stale")
        normalized_inputs = tuple(Path(item) for item in inputs)
        request_text = str(request_id or self._request_id_factory() or "").strip()
        if not request_text:
            return _failure("visual_request_id_missing", "Visual request id is empty")
        request = VisualRequest(
            request_id=request_text,
            binding_id=uuid.uuid4().hex,
            lease=lease,
            prompt=prompt_text,
            inputs=normalized_inputs,
            source_text=str(source_text or ""),
            keep_current_image=bool(keep_current_image),
            runtime_config=(
                _freeze_mapping(runtime_config) if runtime_config is not None else None
            ),
            story_session_id=(
                int(story_session_id) if story_session_id is not None else None
            ),
            asset_metadata=_freeze_mapping(asset_metadata),
        )
        binding = _VisualBinding(request)
        with self._lock:
            if not self._running:
                return _failure("visual_stopped", "Visual service is not running")
            if request_text in self._bindings:
                return _failure(
                    "visual_request_conflict",
                    f"Visual request '{request_text}' is already active",
                )
            if (
                request.story_session_id is not None
                and (
                    request.story_session_id != self._active_story_session
                    or self._story is None
                    or self._story.session_id != request.story_session_id
                    or (
                        self._story.lease is not None
                        and self._story.lease != request.lease
                    )
                )
            ):
                return _failure(
                    "visual_story_session_stale",
                    "Visual story request no longer owns the active story session",
                )
            pending_for_request = tuple(
                (key, pending)
                for key, pending in self._pending_history.items()
                if key[0] == request_text
            )
            if any(pending.reconciling for _key, pending in pending_for_request):
                return _failure(
                    "visual_history_reconcile_in_progress",
                    f"Visual request '{request_text}' has an active history reconciliation",
                )
            for key, _pending in pending_for_request:
                self._pending_history.pop(key, None)
            self._bindings[request_text] = binding

        callback = self._capabilities.publish_requested
        if callback is not None:
            try:
                callback(request)
            except BaseException as exc:
                self._abandon_unstarted_binding(binding)
                return _failure(
                    "visual_request_publish_failed",
                    f"Could not publish Visual Reply request: {exc}",
                    exc,
                )

        generate = self._capabilities.generate
        if generate is None:
            with self._lock:
                active = (
                    self._bindings.get(request_text) is binding
                    and self._running
                    and not binding.cancel_reason
                )
            binding.run_gate.set()
            binding.startup_complete.set()
            if not active:
                return _failure(
                    "visual_request_cancelled",
                    "Visual request was cancelled before worker publication",
                )
            return CommandResult(True, request)
        with self._lock:
            active = (
                self._bindings.get(request_text) is binding
                and self._running
                and not binding.cancel_reason
            )
            if active:
                binding.spawn_started = True
        if not active:
            self._abandon_unstarted_binding(binding)
            return _failure(
                "visual_request_cancelled",
                "Visual request was cancelled before worker publication",
            )
        try:
            handle = self._workers.spawn(
                name=f"visual-reply-{request_text}",
                lease=lease,
                target=lambda token: self._run_generation(
                    binding,
                    generate,
                    token,
                ),
                identity=binding,
            )
        except BaseException as exc:
            self._finish_failed_spawn(binding)
            return _failure(
                "visual_worker_start_failed",
                f"Could not start Visual Reply worker: {exc}",
                exc,
            )
        with self._lock:
            current = self._bindings.get(request_text)
            binding.handle = handle
            cancelled = (
                current is not binding
                or not self._running
                or bool(binding.cancel_reason)
            )
            cancel_reason = binding.cancel_reason or "visual_request_cancelled"
        if cancelled:
            self._workers.cancel_handles((handle,), cancel_reason)
        binding.run_gate.set()
        binding.startup_complete.set()
        if cancelled:
            return _failure(
                "visual_request_cancelled",
                "Visual request was cancelled during worker publication",
            )
        return CommandResult(True, request)

    def cancel(self, request_id: str, reason: str) -> CommandResult[None]:
        request_text = str(request_id or "").strip()
        with self._lock:
            binding = self._bindings.get(request_text)
            if binding is None:
                return _failure(
                    "visual_request_missing",
                    f"Visual request '{request_text}' is not active",
                )
            if binding.completing:
                return _failure(
                    "visual_completion_in_progress",
                    f"Visual request '{request_text}' already owns completion admission",
                )
        self._cancel_binding(binding, str(reason or "visual_cancelled"))
        return CommandResult(True)

    def complete(
        self,
        request_id: str,
        output: Path,
        *,
        binding_id: str | None = None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[VisualResult]:
        output_path = Path(output).expanduser()
        if not output_path.exists() or not output_path.is_file():
            return _failure("visual_output_missing", "Visual Reply output does not exist")
        request_text = str(request_id or "").strip()
        with self._lock:
            binding = self._bindings.get(request_text)
            if (
                binding is None
                or binding.completing
                or binding_id is None
                or (
                    str(binding_id) != binding.request.binding_id
                )
            ):
                return _failure(
                    "visual_stale_binding",
                    "Visual completion no longer owns its exact request binding",
                )
            binding.completing = True
            request = binding.request
        if not self._lease_is_current(request.lease):
            self._discard_binding(binding)
            return _failure("visual_stale_lease", "Visual completion lease is stale")

        merged_metadata = dict(request.asset_metadata)
        merged_metadata.update(deepcopy(dict(asset_metadata or {})))
        frozen_metadata = _freeze_mapping(merged_metadata)
        result = VisualResult(
            request_id=request.request_id,
            binding_id=request.binding_id,
            lease=request.lease,
            prompt=request.prompt,
            output=output_path.resolve(),
            source_text=request.source_text,
            keep_current_image=request.keep_current_image,
            asset_metadata=frozen_metadata,
            inputs=request.inputs,
        )
        history_link = VisualHistoryLink(
            request_id=request.request_id,
            binding_id=request.binding_id,
            session_lease=_session_scope_lease(request.lease),
            turn_lease=request.lease,
            prompt=request.prompt,
            output=output_path.resolve(),
            source_text=request.source_text,
            asset_metadata=frozen_metadata,
            inputs=request.inputs,
        )

        def publish() -> VisualResult:
            if not self._lease_is_current(request.lease):
                raise _StaleVisualCompletion()
            publish_result = self._capabilities.publish_result
            if publish_result is not None:
                publish_result(result)
            attach_history = self._capabilities.attach_history
            if attach_history is not None:
                with self._lock:
                    current = self._bindings.get(request.request_id)
                    if current is not binding or not binding.completing:
                        raise _StaleVisualCompletion()
                    binding.history_link = history_link
                linked = attach_history(history_link) is not False
                if linked:
                    refresh_history = self._capabilities.refresh_history
                    if refresh_history is not None:
                        refresh_history(history_link.session_lease)
                else:
                    with self._lock:
                        current = self._bindings.get(request.request_id)
                        if (
                            current is binding
                            and binding.completing
                            and binding.history_link is history_link
                        ):
                            self._pending_history[
                                (history_link.request_id, history_link.binding_id)
                            ] = _PendingHistoryBinding(history_link)
            return result

        try:
            committed = self._commit_completion(request.lease, publish)
        except _StaleVisualCompletion:
            committed = _failure(
                "visual_stale_lease",
                "Visual completion lease became stale before publication",
            )
        except BaseException as exc:
            committed = _failure(
                "visual_completion_failed",
                f"Could not publish Visual Reply completion: {exc}",
                exc,
            )
        self._discard_binding(binding)
        if not committed.accepted:
            return CommandResult(False, failure=committed.failure)
        return CommandResult(True, committed.value or result)

    def preview(self, asset_id: str) -> CommandResult[None]:
        asset_text = str(asset_id or "").strip()
        if not asset_text:
            return _failure("visual_asset_required", "Visual asset id is required")
        with self._lock:
            if not self._running:
                return _failure("visual_stopped", "Visual service is not running")
            callback = self._capabilities.preview_asset
        if callback is None:
            return _failure("visual_preview_unavailable", "Visual preview is unavailable")
        try:
            callback(asset_text)
        except BaseException as exc:
            return _failure(
                "visual_preview_failed",
                f"Could not preview Visual Reply asset: {exc}",
                exc,
            )
        return CommandResult(True)

    def register_image_review(
        self,
        callback: ImageReviewCallback | None,
    ) -> ImageReviewCallback | None:
        """Replace the single review endpoint without retaining a UI object."""

        normalized = callback if callable(callback) else None
        with self._lock:
            self._image_review_callback = normalized
        return callback

    def unregister_image_review(
        self,
        callback: ImageReviewCallback | None = None,
    ) -> None:
        with self._lock:
            if callback is None or self._image_review_callback == callback:
                self._image_review_callback = None

    def bind_image_review(
        self,
        callback: ImageReviewCallback,
    ) -> Callable[[], None]:
        self.register_image_review(callback)
        return lambda: self.unregister_image_review(callback)

    def image_review_callback(self) -> ImageReviewCallback | None:
        with self._lock:
            return self._image_review_callback

    def snapshot(self) -> VisualSnapshot:
        with self._lock:
            story = self._story
            return VisualSnapshot(
                running=self._running,
                active_requests=tuple(
                    binding.request for binding in self._bindings.values()
                ),
                pending_history_links=tuple(
                    pending.link for pending in self._pending_history.values()
                ),
                active_story_session=self._active_story_session,
                story=(
                    VisualStorySession(
                        session_id=story.session_id,
                        lease=story.lease,
                        max_images=story.max_images,
                        requested_images=story.requested_images,
                        style_guide=story.style_guide,
                    )
                    if story is not None
                    else None
                ),
            )

    def lease_is_current(self, lease: WorkLease) -> bool:
        return bool(self._lease_is_current(lease))

    def history_link_is_current(
        self,
        session_lease: WorkLease,
        turn_lease: WorkLease,
        request_id: str,
        binding_id: str,
    ) -> bool:
        request_text = str(request_id or "").strip()
        binding_text = str(binding_id or "").strip()
        with self._lock:
            binding = self._bindings.get(request_text)
            active_link = binding.history_link if binding is not None else None
            if (
                binding is not None
                and binding.completing
                and active_link is not None
                and active_link.request_id == request_text
                and active_link.binding_id == binding_text
                and active_link.session_lease == session_lease
                and active_link.turn_lease == turn_lease
            ):
                return True
            pending = self._pending_history.get((request_text, binding_text))
            return bool(
                pending is not None
                and pending.reconciling
                and not pending.cancelled
                and pending.link.session_lease == session_lease
                and pending.link.turn_lease == turn_lease
            )

    def reconcile_history(self, session_lease: WorkLease | None = None) -> int:
        with self._lock:
            candidates = tuple(self._pending_history.values())
        linked_count = 0
        refreshed_lease = None
        for candidate in candidates:
            link = candidate.link
            if session_lease is not None and link.session_lease != session_lease:
                continue
            if not self._lease_is_current(link.turn_lease):
                self._discard_pending_history(candidate)
                continue

            def attach_pending() -> bool:
                if not self._lease_is_current(link.turn_lease):
                    raise _StaleVisualCompletion()
                claim_complete = threading.Event()
                with self._lock:
                    current = self._pending_history.get(
                        (link.request_id, link.binding_id)
                    )
                    if (
                        current is not candidate
                        or current.reconciling
                        or current.cancelled
                        or not self._running
                    ):
                        return False
                    current.reconciling = True
                    current.claim_complete = claim_complete
                linked = False
                try:
                    callback = self._capabilities.attach_history
                    linked = callback is None or callback(link) is not False
                    return linked
                finally:
                    with self._lock:
                        current = self._pending_history.get(
                            (link.request_id, link.binding_id)
                        )
                        if current is candidate:
                            current.reconciling = False
                            current.claim_complete = None
                            if linked or current.cancelled:
                                self._pending_history.pop(
                                    (link.request_id, link.binding_id),
                                    None,
                                )
                    claim_complete.set()

            try:
                committed = self._commit_completion(link.turn_lease, attach_pending)
            except _StaleVisualCompletion:
                committed = CommandResult(False)
            if committed.accepted and bool(committed.value):
                linked_count += 1
                refreshed_lease = link.session_lease
            elif not committed.accepted:
                self._discard_pending_history(candidate)
        refresh_history = self._capabilities.refresh_history
        if linked_count and refresh_history is not None and refreshed_lease is not None:
            refresh_history(refreshed_lease)
        return linked_count

    def clear_history(self) -> None:
        self._cancel_pending_history(lambda _pending: True)

    def cancel_session(self, session_generation: object, reason: str) -> None:
        with self._lock:
            bindings = tuple(
                binding
                for binding in self._bindings.values()
                if binding.request.lease.session_generation == session_generation
            )
            story = self._story
            clear_story = bool(
                story is not None
                and story.lease is not None
                and story.lease.session_generation == session_generation
            )
            if clear_story:
                self._story = None
                self._active_story_session = 0
        for binding in reversed(bindings):
            self._cancel_binding(
                binding,
                str(reason or "visual_session_cancelled"),
                allow_completing=True,
            )
        self._cancel_pending_history(
            lambda pending: (
                pending.link.session_lease.session_generation == session_generation
            )
        )

    def begin_story_session(
        self,
        lease: WorkLease | None = None,
        *,
        story_text: str = "",
        max_images: int | None = None,
    ) -> int:
        if lease is not None and not self._lease_is_current(lease):
            return 0
        image_limit = self.story_max_images() if max_images is None else max(1, int(max_images))
        style_guide = self.story_style_guide(story_text) if story_text else ""
        with self._lock:
            self._story_counter += 1
            self._active_story_session = self._story_counter
            active_story = self._active_story_session
            self._story = _StoryBinding(
                session_id=active_story,
                lease=lease,
                max_images=image_limit,
                style_guide=style_guide,
            )
            stale_bindings = tuple(
                binding
                for binding in self._bindings.values()
                if binding.request.story_session_id is not None
                and binding.request.story_session_id != active_story
            )
        for binding in reversed(stale_bindings):
            self._cancel_binding(
                binding,
                "visual_story_superseded",
                allow_completing=True,
            )
        return active_story

    def request_story_frame(
        self,
        story_session_id: int,
        lease: WorkLease,
        *,
        text: str,
        emotion: str = "",
        request_id: str | None = None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[VisualRequest]:
        if not self.generation_available():
            return _failure(
                "visual_story_generation_unavailable",
                "Visual Reply story generation is unavailable",
            )
        with self._lock:
            story = self._story
            if (
                story is None
                or story.session_id != int(story_session_id)
                or self._active_story_session != story.session_id
                or (story.lease is not None and story.lease != lease)
            ):
                return _failure(
                    "visual_story_session_stale",
                    "Visual story request no longer owns the active story session",
                )
            if story.requested_images >= story.max_images:
                return _failure(
                    "visual_story_limit_reached",
                    "Visual story image limit has been reached",
                )
            style_guide = story.style_guide
        prompt = self.story_prompt(text, emotion, style_guide)
        if not prompt:
            return _failure(
                "visual_story_prompt_empty",
                "Visual story frame did not produce an image prompt",
            )
        with self._lock:
            current = self._story
            if current is not story or current.requested_images >= current.max_images:
                return _failure(
                    "visual_story_session_stale",
                    "Visual story request lost its active story reservation",
                )
            story.requested_images += 1
        requested = self.request(
            lease,
            prompt=prompt,
            source_text=str(text or ""),
            keep_current_image=True,
            request_id=request_id,
            story_session_id=int(story_session_id),
            asset_metadata=asset_metadata,
        )
        if not requested.accepted:
            with self._lock:
                current = self._story
                if current is story and current.requested_images > 0:
                    current.requested_images -= 1
        return requested

    def clear_story(self) -> None:
        with self._lock:
            self._active_story_session = 0
            self._story = None
            bindings = tuple(
                binding
                for binding in self._bindings.values()
                if binding.request.story_session_id is not None
            )
        for binding in reversed(bindings):
            self._cancel_binding(
                binding,
                "visual_story_cleared",
                allow_completing=True,
            )

    def stop(self) -> CommandResult[None]:
        with self._lock:
            self._running = False
            self._active_story_session = 0
            self._story = None
            self._image_review_callback = None
            bindings = tuple(self._bindings.values())
        self.clear_history()
        for binding in reversed(bindings):
            self._cancel_binding(
                binding,
                "visual_runtime_stop",
                allow_completing=True,
            )
        return CommandResult(True)

    def _run_generation(
        self,
        binding: _VisualBinding,
        generate: Callable[
            [VisualRequest, CancellationToken],
            VisualGeneratedAsset | Path | str | None,
        ],
        token: CancellationToken,
    ) -> None:
        binding.run_gate.wait()
        if token.cancelled:
            self._discard_binding(binding)
            return
        self._generate(binding, generate, token)

    def _generate(
        self,
        binding: _VisualBinding,
        generate: Callable[
            [VisualRequest, CancellationToken],
            VisualGeneratedAsset | Path | str | None,
        ],
        token: CancellationToken,
    ) -> None:
        request = binding.request
        try:
            generated = generate(request, token)
            if generated is None or token.cancelled:
                self._discard_binding(binding)
                return
            if isinstance(generated, VisualGeneratedAsset):
                output = generated.output
                asset_metadata = generated.metadata
            else:
                output = Path(generated)
                asset_metadata = None
            completed = self.complete(
                request.request_id,
                Path(output),
                binding_id=request.binding_id,
                asset_metadata=asset_metadata,
            )
            if not completed.accepted:
                self._fail_binding(
                    binding,
                    completed.failure
                    or RuntimeFailure(
                        "visual_generation_failed",
                        "Visual Reply completion was rejected",
                    ),
                )
        except BaseException as exc:
            failure = RuntimeFailure(
                "visual_generation_failed",
                f"Visual Reply generation failed: {exc}",
                exc,
            )
            self._fail_binding(binding, failure)

    def _fail_binding(
        self,
        binding: _VisualBinding,
        failure: RuntimeFailure,
    ) -> None:
        with self._lock:
            current = self._bindings.get(binding.request.request_id)
            if current is not binding or binding.completing:
                return
            binding.completing = True
        if not self._lease_is_current(binding.request.lease):
            self._discard_binding(binding)
            return

        def publish_failure() -> VisualResult:
            if not self._lease_is_current(binding.request.lease):
                raise _StaleVisualCompletion()
            callback = self._capabilities.publish_failure
            if callback is not None:
                callback(binding.request, failure)
            return VisualResult(
                binding.request.request_id,
                binding.request.binding_id,
                binding.request.lease,
                binding.request.prompt,
                Path(),
                binding.request.source_text,
                binding.request.keep_current_image,
            )

        try:
            self._commit_completion(binding.request.lease, publish_failure)
        except BaseException:
            pass
        self._discard_binding(binding)

    def _discard_binding(self, binding: _VisualBinding) -> None:
        retired = False
        with self._lock:
            current = self._bindings.get(binding.request.request_id)
            if current is binding:
                self._bindings.pop(binding.request.request_id, None)
                retired = True
        if retired:
            self._notify_request_retired(binding)

    def _notify_request_retired(self, binding: _VisualBinding) -> None:
        callback = self._capabilities.retire_request
        if callback is not None:
            try:
                callback(binding.request, binding.cancel_reason or "visual_request_retired")
            except BaseException:
                # Status observers must not change cancellation/completion outcomes.
                pass

    def _abandon_unstarted_binding(self, binding: _VisualBinding) -> None:
        self._discard_binding(binding)
        binding.run_gate.set()
        binding.startup_complete.set()

    def _finish_failed_spawn(self, binding: _VisualBinding) -> None:
        self._discard_binding(binding)
        binding.run_gate.set()
        binding.startup_complete.set()

    def _cancel_binding(
        self,
        binding: _VisualBinding,
        reason: str,
        *,
        allow_completing: bool = False,
    ) -> None:
        retired = False
        with self._lock:
            current = self._bindings.get(binding.request.request_id)
            if current is not binding:
                return
            if binding.completing and not allow_completing:
                return
            binding.cancel_reason = str(reason or "visual_cancelled")
            wait_for_startup = binding.spawn_started and not binding.startup_complete.is_set()
            if not binding.spawn_started:
                self._bindings.pop(binding.request.request_id, None)
                retired = True
            handle = binding.handle
        if not binding.spawn_started:
            binding.run_gate.set()
            binding.startup_complete.set()
        elif wait_for_startup:
            binding.startup_complete.wait()
            with self._lock:
                current = self._bindings.get(binding.request.request_id)
                if current is binding:
                    self._bindings.pop(binding.request.request_id, None)
                    retired = True
                handle = binding.handle
        else:
            with self._lock:
                current = self._bindings.get(binding.request.request_id)
                if current is binding:
                    self._bindings.pop(binding.request.request_id, None)
                    retired = True
                handle = binding.handle
        if retired:
            self._notify_request_retired(binding)
        if handle is not None:
            self._workers.cancel_handles((handle,), binding.cancel_reason)
            self._workers.join_handles((handle,))

    def _discard_pending_history(self, pending: _PendingHistoryBinding) -> None:
        link = pending.link
        with self._lock:
            current = self._pending_history.get((link.request_id, link.binding_id))
            if current is pending and not current.reconciling:
                self._pending_history.pop((link.request_id, link.binding_id), None)

    def _cancel_pending_history(
        self,
        predicate: Callable[[_PendingHistoryBinding], bool],
    ) -> None:
        waits = []
        with self._lock:
            for key, pending in tuple(self._pending_history.items()):
                if not predicate(pending):
                    continue
                if pending.reconciling:
                    pending.cancelled = True
                    if pending.claim_complete is not None:
                        waits.append(pending.claim_complete)
                else:
                    self._pending_history.pop(key, None)
        for claim_complete in waits:
            claim_complete.wait()

    def _commit_if_current(
        self,
        lease: WorkLease,
        effect: Callable[[], VisualResult],
    ) -> CommandResult[VisualResult]:
        if not self._lease_is_current(lease):
            return _failure("visual_stale_lease", "Visual completion lease is stale")
        return CommandResult(True, effect())


class _StaleVisualCompletion(RuntimeError):
    pass


def _session_scope_lease(lease: WorkLease) -> WorkLease:
    return WorkLease(
        run_id=lease.run_id,
        session_generation=lease.session_generation,
    )


def _freeze_mapping(
    value: Mapping[str, object] | None,
) -> Mapping[str, object]:
    return MappingProxyType(
        {
            str(key): _freeze_value(item)
            for key, item in dict(value or {}).items()
        }
    )


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    try:
        return deepcopy(value)
    except BaseException:
        return value


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = [
    "PERSONA_SELF_IMAGE_MODES",
    "PERSONA_SELF_VISUAL_PREFIX",
    "PERSONA_VISUAL_REPLY_POLICIES",
    "USER_VISUAL_POLICIES",
    "USER_VISUAL_PREFIX",
    "VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY",
    "PersonaVisualPlan",
    "VisualCapabilities",
    "VisualGeneratedAsset",
    "VisualHistoryLink",
    "VisualPolicyCapabilities",
    "VisualRequest",
    "VisualResult",
    "VisualService",
    "VisualSnapshot",
    "VisualStorySession",
    "normalize_persona_self_image_mode",
    "normalize_persona_appearance_freedom",
    "normalize_persona_visual_reply_policy",
    "normalize_user_visual_policy",
    "persona_visual_identity_available",
    "persona_visual_request_config",
    "plan_persona_visual_request",
    "resolve_persona_visual_reply_policy",
    "visual_generation_instruction",
    "user_visual_identity_available",
]
