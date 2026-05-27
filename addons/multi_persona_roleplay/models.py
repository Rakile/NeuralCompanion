from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


MEMORY_SCOPES = ("shared", "persona-only", "session-only", "disabled")
BEHAVIOR_MODES = ("normal companion", "RPG character", "narrator", "game master", "group participant")
AR_MODE = "AlternativeReality"
SESSION_MODES = ("Single active persona", "Multi-character group chat", "Narrator + characters", "RPG / Game Master mode", AR_MODE)
AR_PACING_MODES = ("Slow / Audiobook", "Balanced", "Fast / Game-like")
AR_INTERACTION_FREQUENCIES = ("Ask often", "Ask sometimes", "Continue until important choice")
VOICE_BACKENDS = ("inherit", "chatterbox", "chatterbox_multilingual", "pockettts", "pockettts_multilingual", "gemini_tts_preview")
VISUAL_MODES = (
    "off",
    "manual",
    "auto_every_reply",
    "auto_scene_change",
    "auto_new_location",
    "auto_character_change",
    "auto_choices",
    "auto_important_moment",
    "auto_story_beat",
    "auto_every_n_replies",
    "auto_user_asks",
)
VISUAL_MODE_LABELS = {
    "off": "Off",
    "manual": "Manual only",
    "auto_every_reply": "Every assistant reply",
    "auto_scene_change": "Scene changes",
    "auto_new_location": "New location",
    "auto_character_change": "Speaker / character changes",
    "auto_choices": "When choices appear",
    "auto_important_moment": "Important story moments",
    "auto_story_beat": "AR story beats",
    "auto_every_n_replies": "Every N replies",
    "auto_user_asks": "When user asks for image",
}
VISUAL_MODE_DESCRIPTIONS = {
    "off": "This persona will not request story images.",
    "manual": "Only the Generate Visual Reply button sends an image request.",
    "auto_every_reply": "Request an image after each assistant/story reply, subject to cooldown and session limits.",
    "auto_scene_change": "Request an image when the scene state changes or scene updates are enabled.",
    "auto_new_location": "Request an image when the story moves to a different location.",
    "auto_character_change": "Request an image when the active speaker or character changes.",
    "auto_choices": "Request an image when the reply presents player choices.",
    "auto_important_moment": "Request an image for action, reveals, danger, discoveries, or high-tension beats.",
    "auto_story_beat": "Request images for AR story beats: first beat, important moments, choices, or interval beats.",
    "auto_every_n_replies": "Request an image after the configured number of assistant replies.",
    "auto_user_asks": "Request an image only when the user asks to see or generate one.",
}
VISUAL_PROVIDERS = ("inherit", "openai", "xai", "runware", "comfyui")
VISUAL_SIZES = ("inherit", "auto", "1024x1024", "1024x1536", "1536x1024")


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return bool(default)
    return bool(value)


def _int(value: Any, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = int(default)
    if minimum is not None:
        parsed = max(int(minimum), parsed)
    if maximum is not None:
        parsed = min(int(maximum), parsed)
    return parsed


def _choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    text = _text(value, default)
    if choices is SESSION_MODES and text.strip().lower() in {"ar", "alternative reality", "alternative_reality"}:
        return AR_MODE
    lowered = {item.lower(): item for item in choices}
    return lowered.get(text.lower(), default)


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    tags = []
    seen = set()
    for raw in raw_items:
        tag = _text(raw).lower()
        if not tag or tag in seen:
            continue
        tags.append(tag)
        seen.add(tag)
    return tags


def _list_values(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


@dataclass
class VoiceConfig:
    enabled: bool = False
    backend: str = "inherit"
    sample_path: str = ""
    preset_name: str = ""
    language: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "VoiceConfig":
        data = dict(payload or {})
        return cls(
            enabled=_bool(data.get("enabled"), False),
            backend=_choice(data.get("backend"), VOICE_BACKENDS, "inherit"),
            sample_path=_text(data.get("sample_path")),
            preset_name=_text(data.get("preset_name")),
            language=_text(data.get("language")).lower(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VisualProfile:
    enabled: bool = False
    mode: str = "off"
    provider: str = "inherit"
    model: str = ""
    size: str = "inherit"
    style_preset: str = ""
    character_description: str = ""
    clothing_props: str = ""
    environment_style: str = ""
    negative_prompt: str = ""
    keep_continuity: bool = True
    include_scene_summary: bool = True
    include_active_speaker: bool = True
    auto_reply_interval: int = 1
    cooldown_seconds: int = 60
    max_auto_images_per_session: int = 3
    auto_show_dock: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "VisualProfile":
        data = dict(payload or {})
        return cls(
            enabled=_bool(data.get("enabled"), False),
            mode=_choice(data.get("mode"), VISUAL_MODES, "off"),
            provider=_choice(data.get("provider"), VISUAL_PROVIDERS, "inherit"),
            model=_text(data.get("model")),
            size=_choice(data.get("size"), VISUAL_SIZES, "inherit"),
            style_preset=_text(data.get("style_preset")),
            character_description=_text(data.get("character_description")),
            clothing_props=_text(data.get("clothing_props")),
            environment_style=_text(data.get("environment_style")),
            negative_prompt=_text(data.get("negative_prompt")),
            keep_continuity=_bool(data.get("keep_continuity"), True),
            include_scene_summary=_bool(data.get("include_scene_summary"), True),
            include_active_speaker=_bool(data.get("include_active_speaker"), True),
            auto_reply_interval=_int(data.get("auto_reply_interval"), 1, 1, 100),
            cooldown_seconds=_int(data.get("cooldown_seconds"), 60, 0, 86400),
            max_auto_images_per_session=_int(data.get("max_auto_images_per_session"), 3, 0, 100),
            auto_show_dock=_bool(data.get("auto_show_dock"), True),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonaSafetyConfig:
    allow_adult_only: bool = False
    avoid_real_person_impersonation: bool = True
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PersonaSafetyConfig":
        data = dict(payload or {})
        return cls(
            allow_adult_only=_bool(data.get("allow_adult_only"), False),
            avoid_real_person_impersonation=_bool(data.get("avoid_real_person_impersonation"), True),
            notes=_text(data.get("notes")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonaConfig:
    id: str
    enabled: bool = True
    display_name: str = "Persona"
    role: str = ""
    description: str = ""
    character_image_path: str = ""
    system_prompt: str = ""
    ar_profile_enabled: bool = True
    ar_description: str = ""
    ar_system_prompt: str = ""
    speaking_style: str = ""
    allowed_tone: str = ""
    response_length: str = "balanced"
    temperature_hint: str = ""
    memory_scope: str = "persona-only"
    behavior_mode: str = "normal companion"
    tags: list[str] = field(default_factory=list)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    visual: VisualProfile = field(default_factory=VisualProfile)
    safety: PersonaSafetyConfig = field(default_factory=PersonaSafetyConfig)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PersonaConfig":
        data = dict(payload or {})
        persona_id = normalize_persona_id(data.get("id") or data.get("display_name") or "persona")
        return cls(
            id=persona_id,
            enabled=_bool(data.get("enabled"), True),
            display_name=_text(data.get("display_name"), persona_id.replace("_", " ").title()) or "Persona",
            role=_text(data.get("role")),
            description=_text(data.get("description")),
            character_image_path=_text(data.get("character_image_path")),
            system_prompt=_text(data.get("system_prompt")),
            ar_profile_enabled=_bool(data.get("ar_profile_enabled"), True),
            ar_description=_text(data.get("ar_description")),
            ar_system_prompt=_text(data.get("ar_system_prompt")),
            speaking_style=_text(data.get("speaking_style")),
            allowed_tone=_text(data.get("allowed_tone")),
            response_length=_text(data.get("response_length"), "balanced") or "balanced",
            temperature_hint=_text(data.get("temperature_hint")),
            memory_scope=_choice(data.get("memory_scope"), MEMORY_SCOPES, "persona-only"),
            behavior_mode=_choice(data.get("behavior_mode"), BEHAVIOR_MODES, "normal companion"),
            tags=_tags(data.get("tags")),
            voice=VoiceConfig.from_dict(data.get("voice") if isinstance(data.get("voice"), dict) else {}),
            visual=VisualProfile.from_dict(data.get("visual") if isinstance(data.get("visual"), dict) else {}),
            safety=PersonaSafetyConfig.from_dict(data.get("safety") if isinstance(data.get("safety"), dict) else {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = normalize_persona_id(payload.get("id"))
        payload["memory_scope"] = _choice(payload.get("memory_scope"), MEMORY_SCOPES, "persona-only")
        payload["behavior_mode"] = _choice(payload.get("behavior_mode"), BEHAVIOR_MODES, "normal companion")
        payload["tags"] = _tags(payload.get("tags"))
        return payload


# Compact per-session AR state. Keep this small because it is injected into prompts.
@dataclass
class AlternativeRealityState:
    current_scene: str = ""
    location: str = ""
    active_characters: list[str] = field(default_factory=list)
    tension_level: int = 2
    story_goal: str = ""
    recent_events: list[str] = field(default_factory=list)
    player_intent: str = ""
    pending_choices: list[str] = field(default_factory=list)
    mood: str = ""
    time_of_day: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AlternativeRealityState":
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        events = data.get("recent_events")
        choices = data.get("pending_choices")
        characters = data.get("active_characters")
        return cls(
            current_scene=_text(data.get("current_scene")),
            location=_text(data.get("location")),
            active_characters=[normalize_persona_id(item) for item in _list_values(characters) if _text(item)][:8],
            tension_level=_int(data.get("tension_level"), 2, 0, 10),
            story_goal=_text(data.get("story_goal")),
            recent_events=[_text(item) for item in _list_values(events) if _text(item)][:12],
            player_intent=_text(data.get("player_intent")),
            pending_choices=[_text(item) for item in _list_values(choices) if _text(item)][:6],
            mood=_text(data.get("mood")),
            time_of_day=_text(data.get("time_of_day")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["active_characters"] = [normalize_persona_id(item) for item in list(payload.get("active_characters") or []) if _text(item)][:8]
        payload["recent_events"] = [str(item)[:260] for item in list(payload.get("recent_events") or []) if _text(item)][-12:]
        payload["pending_choices"] = [str(item)[:180] for item in list(payload.get("pending_choices") or []) if _text(item)][:6]
        payload["tension_level"] = _int(payload.get("tension_level"), 2, 0, 10)
        return payload


@dataclass
class RoleplaySessionState:
    enabled: bool = False
    mode: str = "Single active persona"
    active_persona_id: str = "mentor"
    current_speaker_id: str = "mentor"
    scene_title: str = ""
    location: str = ""
    time_of_day: str = ""
    mood: str = ""
    objective: str = ""
    scene_summary: str = ""
    turn_index: int = 0
    character_state_summaries: dict[str, str] = field(default_factory=dict)
    recent_events: list[str] = field(default_factory=list)
    last_visual_reply_at: float = 0.0
    auto_image_count: int = 0
    auto_select_speaker: bool = False
    keep_scene_continuity: bool = True
    update_scene_after_reply: bool = False
    ar_state: AlternativeRealityState = field(default_factory=AlternativeRealityState)
    ar_pacing: str = "Balanced"
    ar_interaction_frequency: str = "Ask sometimes"
    ar_use_persona_profiles: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RoleplaySessionState":
        data = dict(payload or {})
        summaries = data.get("character_state_summaries")
        if not isinstance(summaries, dict):
            summaries = {}
        events = data.get("recent_events")
        if not isinstance(events, list):
            events = []
        return cls(
            enabled=_bool(data.get("enabled"), False),
            mode=_choice(data.get("mode"), SESSION_MODES, "Single active persona"),
            active_persona_id=normalize_persona_id(data.get("active_persona_id") or "mentor"),
            current_speaker_id=normalize_persona_id(data.get("current_speaker_id") or data.get("active_persona_id") or "mentor"),
            scene_title=_text(data.get("scene_title")),
            location=_text(data.get("location")),
            time_of_day=_text(data.get("time_of_day")),
            mood=_text(data.get("mood")),
            objective=_text(data.get("objective")),
            scene_summary=_text(data.get("scene_summary")),
            turn_index=_int(data.get("turn_index"), 0, 0),
            character_state_summaries={normalize_persona_id(key): _text(value) for key, value in summaries.items()},
            recent_events=[_text(item) for item in events if _text(item)][:20],
            last_visual_reply_at=float(data.get("last_visual_reply_at", 0.0) or 0.0),
            auto_image_count=_int(data.get("auto_image_count"), 0, 0),
            auto_select_speaker=_bool(data.get("auto_select_speaker"), False),
            keep_scene_continuity=_bool(data.get("keep_scene_continuity"), True),
            update_scene_after_reply=_bool(data.get("update_scene_after_reply"), False),
            ar_state=AlternativeRealityState.from_dict(data.get("ar_state") if isinstance(data.get("ar_state"), dict) else {}),
            ar_pacing=_choice(data.get("ar_pacing"), AR_PACING_MODES, "Balanced"),
            ar_interaction_frequency=_choice(data.get("ar_interaction_frequency"), AR_INTERACTION_FREQUENCIES, "Ask sometimes"),
            ar_use_persona_profiles=_bool(data.get("ar_use_persona_profiles"), True),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["active_persona_id"] = normalize_persona_id(payload.get("active_persona_id"))
        payload["current_speaker_id"] = normalize_persona_id(payload.get("current_speaker_id"))
        payload["recent_events"] = [str(item)[:300] for item in list(payload.get("recent_events") or [])][-20:]
        if isinstance(self.ar_state, AlternativeRealityState):
            payload["ar_state"] = self.ar_state.to_dict()
        else:
            payload["ar_state"] = AlternativeRealityState.from_dict(payload.get("ar_state")).to_dict()
        payload["ar_pacing"] = _choice(payload.get("ar_pacing"), AR_PACING_MODES, "Balanced")
        payload["ar_interaction_frequency"] = _choice(payload.get("ar_interaction_frequency"), AR_INTERACTION_FREQUENCIES, "Ask sometimes")
        return payload


def normalize_persona_id(value: Any) -> str:
    raw = _text(value).lower()
    if not raw:
        raw = "persona"
    result = []
    previous_underscore = False
    for char in raw:
        if char.isalnum():
            result.append(char)
            previous_underscore = False
        elif not previous_underscore:
            result.append("_")
            previous_underscore = True
    text = "".join(result).strip("_")
    return text or "persona"


def unique_persona_id(base: str, existing_ids: set[str]) -> str:
    root = normalize_persona_id(base)
    if root not in existing_ids:
        return root
    index = 2
    while f"{root}_{index}" in existing_ids:
        index += 1
    return f"{root}_{index}"


def personas_from_payload(payload: Any) -> list[PersonaConfig]:
    raw_items = payload if isinstance(payload, list) else []
    personas: list[PersonaConfig] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        persona = PersonaConfig.from_dict(raw)
        persona.id = unique_persona_id(persona.id, seen)
        seen.add(persona.id)
        personas.append(persona)
    return personas
