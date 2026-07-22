from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


PROVIDER_IDS = ("inherit", "main", "lmstudio", "ollama", "openai", "xai", "deepseek", "claude")
LLM_MODES = ("main", "buddy", "per_persona")
REPLY_MODES = ("context_only", "main_answer")
DEFAULT_AVATAR_PROMPT_PRESET = "Cinematic Buddy Portrait"
AVATAR_PROMPT_PRESETS = {
    "Cinematic Buddy Portrait": (
        "polished AAA-quality companion avatar portrait of {name}, {role}. "
        "Natural confident expression, clear face, detailed eyes, tasteful outfit that fits the personality, "
        "soft cinematic key light, subtle rim light, clean dark neutral background, high-end character design, "
        "sharp but warm, no text, no watermark."
    ),
    "Warm Realistic Companion": (
        "realistic friendly portrait of {name}, {role}. "
        "Approachable human warmth, relaxed posture, expressive eyes, believable skin and hair detail, "
        "modern casual clothing, soft studio lighting, shallow depth of field, natural colors, no text, no watermark."
    ),
    "Stylized Story Character": (
        "stylized story-character avatar of {name}, {role}. "
        "Distinct silhouette, expressive face, memorable clothing and small personal details, painterly premium game art, "
        "rich lighting, readable head-and-shoulders composition, no text, no watermark."
    ),
    "Neon AI Friend": (
        "futuristic AI companion avatar of {name}, {role}. "
        "Elegant neural-light accents, luminous eyes, glossy post-production finish, controlled neon cyan and magenta highlights, "
        "dark clean background, cinematic sci-fi portrait, no text, no watermark."
    ),
    "Soft Animated Avatar": (
        "soft animated companion avatar of {name}, {role}. "
        "Appealing expressive face, clean readable features, gentle smile, premium animated-film lighting, "
        "cozy color palette, polished character portrait, no text, no watermark."
    ),
}
DEFAULT_SYSTEM_OVERRIDE_PROMPT = """Buddy Chat main-chat override:
When Buddy Chat is enabled, treat the buddy roster as an active conversation layer that can temporarily override conflicting single-persona instructions.
Do not suppress buddy personas because the main persona prompt says to answer as one character. The main assistant may still narrate, but buddy dialogue is allowed when it feels natural.
Use the active buddies like people in the room, not a staged panel. Usually one buddy speaks; a second buddy may join only when it adds a real contrast, question, correction, or emotional reaction.
The user is not one of the buddies. Do not address the user by a buddy name unless the user explicitly asks for that.
Do not turn ordinary main chat into story mode, scene prose, or stage directions unless the user asks for roleplay or story.
Every spoken buddy line must start with [Exact Buddy Name], followed by the spoken words. This is required for TTS voice routing.
Best format:
[Mira] Short natural reply.
[Alex] Optional short second angle.
Do not write buddy speech only as narration such as "Mira says..." or "Elara whispers..." unless the quoted dialogue is also clearly spoken by that buddy.
Avoid theatrical stage directions, long inner monologues, and repeated sensory boilerplate in normal chat.
Keep non-buddy narration in the main assistant voice. Do not force all buddies to speak every turn.
Use hidden sensory, music, visual, and memory context as quiet background awareness; do not repeat track-change or screen-observation boilerplate.
If the user asks for a normal direct answer, answer directly and let a buddy add at most one short natural aside."""


def normalize_persona_id(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9_ -]+", "", str(value or "").strip().lower())
    text = re.sub(r"[\s-]+", "_", text).strip("_")
    return text or "buddy"


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
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


def _float(value: Any, default: float = 1.0, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    if minimum is not None:
        parsed = max(float(minimum), parsed)
    if maximum is not None:
        parsed = min(float(maximum), parsed)
    return parsed


def _choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    text = _text(value, default).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "same_as_main": "main",
        "main_runtime": "main",
        "buddy_provider": "buddy",
        "per_persona_providers": "per_persona",
        "lm_studio": "lmstudio",
        "lm-studio": "lmstudio",
        "xai_grok": "xai",
        "grok": "xai",
    }
    text = aliases.get(text, text)
    lowered = {item.lower(): item for item in choices}
    return lowered.get(text, default)


@dataclass
class ProviderOverride:
    provider_id: str = "inherit"
    model: str = ""
    base_url: str = ""
    api_key: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ProviderOverride":
        data = dict(payload or {})
        return cls(
            provider_id=_choice(data.get("provider_id") or data.get("provider"), PROVIDER_IDS, "inherit"),
            model=_text(data.get("model")),
            base_url=_text(data.get("base_url")),
            api_key=_text(data.get("api_key")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_id"] = _choice(payload.get("provider_id"), PROVIDER_IDS, "inherit")
        return payload


@dataclass
class VoiceProfile:
    enabled: bool = False
    sample_path: str = ""
    volume: float = 1.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "VoiceProfile":
        data = dict(payload or {})
        return cls(
            enabled=_bool(data.get("enabled"), False),
            sample_path=_text(data.get("sample_path")),
            volume=_float(data.get("volume"), 1.0, 0.0, 1.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AvatarProfile:
    prompt: str = ""
    image_path: str = ""
    preset: str = DEFAULT_AVATAR_PROMPT_PRESET

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AvatarProfile":
        data = dict(payload or {})
        preset = _text(data.get("preset"), DEFAULT_AVATAR_PROMPT_PRESET) or DEFAULT_AVATAR_PROMPT_PRESET
        if preset not in AVATAR_PROMPT_PRESETS:
            preset = DEFAULT_AVATAR_PROMPT_PRESET
        return cls(
            prompt=_text(data.get("prompt") or data.get("avatar_prompt")),
            image_path=_text(data.get("image_path") or data.get("character_image_path")),
            preset=preset,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("preset") not in AVATAR_PROMPT_PRESETS:
            payload["preset"] = DEFAULT_AVATAR_PROMPT_PRESET
        return payload


def default_avatar_prompt(display_name: str, role: str = "", speaking_style: str = "", preset: str = DEFAULT_AVATAR_PROMPT_PRESET) -> str:
    preset_name = preset if preset in AVATAR_PROMPT_PRESETS else DEFAULT_AVATAR_PROMPT_PRESET
    name = _text(display_name, "Buddy") or "Buddy"
    role_text = _text(role) or _text(speaking_style) or "natural buddy companion"
    style_text = _text(speaking_style) or "natural friendly presence"
    return AVATAR_PROMPT_PRESETS[preset_name].format(name=name, role=role_text, style=style_text)


@dataclass
class BuddyPersona:
    id: str = "buddy"
    enabled: bool = True
    display_name: str = "Buddy"
    role: str = ""
    description: str = ""
    system_prompt: str = ""
    speaking_style: str = ""
    provider: ProviderOverride = field(default_factory=ProviderOverride)
    voice: VoiceProfile = field(default_factory=VoiceProfile)
    avatar: AvatarProfile = field(default_factory=AvatarProfile)
    source: str = "buddy_chat"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "BuddyPersona":
        data = dict(payload or {})
        display_name = _text(data.get("display_name") or data.get("name"), "Buddy") or "Buddy"
        persona_id = normalize_persona_id(data.get("id") or display_name)
        return cls(
            id=persona_id,
            enabled=_bool(data.get("enabled"), True),
            display_name=display_name,
            role=_text(data.get("role")),
            description=_text(data.get("description") or data.get("ar_description")),
            system_prompt=_text(data.get("system_prompt") or data.get("ar_system_prompt")),
            speaking_style=_text(data.get("speaking_style") or data.get("allowed_tone")),
            provider=ProviderOverride.from_dict(data.get("provider") if isinstance(data.get("provider"), dict) else {}),
            voice=VoiceProfile.from_dict(data.get("voice") if isinstance(data.get("voice"), dict) else {}),
            avatar=AvatarProfile.from_dict(data.get("avatar") if isinstance(data.get("avatar"), dict) else data),
            source=_text(data.get("source"), "buddy_chat") or "buddy_chat",
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = normalize_persona_id(payload.get("id") or payload.get("display_name"))
        payload["provider"] = self.provider.to_dict()
        payload["voice"] = self.voice.to_dict()
        payload["avatar"] = self.avatar.to_dict()
        return payload


@dataclass
class BuddySettings:
    version: int = 1
    settings_epoch: int = 0
    enabled: bool = False
    reply_mode: str = "context_only"
    llm_mode: str = "main"
    instructor_structured_outputs_enabled: bool = False
    system_override_enabled: bool = True
    system_override_prompt: str = DEFAULT_SYSTEM_OVERRIDE_PROMPT
    active_persona_window_enabled: bool = False
    active_persona_window_on_top: bool = True
    allow_buddy_to_buddy: bool = True
    max_speakers: int = 1
    natural_second_speaker_every: int = 4
    forced_buddy_every: int = 0
    completed_reply_count: int = 0
    buddy_provider: ProviderOverride = field(default_factory=lambda: ProviderOverride(provider_id="inherit"))
    personas: list[BuddyPersona] = field(default_factory=list)
    turn_index: int = 0

    @classmethod
    def default(cls) -> "BuddySettings":
        return cls(
            personas=[
                BuddyPersona(
                    id="alex",
                    display_name="Alex",
                    role="steady practical buddy",
                    description="Grounded, concise, and useful. Usually answers when the user needs clarity.",
                    speaking_style="direct, calm, lightly warm",
                    avatar=AvatarProfile(
                        prompt=default_avatar_prompt("Alex", "steady practical buddy", "direct, calm, lightly warm"),
                    ),
                ),
                BuddyPersona(
                    id="mira",
                    display_name="Mira",
                    role="observant expressive buddy",
                    description="Notices mood and context. Speaks naturally without forcing a response every turn.",
                    speaking_style="warm, casual, observant",
                    avatar=AvatarProfile(
                        prompt=default_avatar_prompt("Mira", "observant expressive buddy", "warm, casual, observant"),
                    ),
                ),
            ]
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "BuddySettings":
        data = dict(payload or {})
        personas = [
            BuddyPersona.from_dict(item)
            for item in list(data.get("personas") or [])
            if isinstance(item, dict)
        ]
        settings = cls(
            version=_int(data.get("version"), 1, 1, 100),
            settings_epoch=_int(data.get("settings_epoch"), 0, 0, 100),
            enabled=_bool(data.get("enabled"), False),
            reply_mode=_choice(data.get("reply_mode"), REPLY_MODES, "context_only"),
            llm_mode=_choice(data.get("llm_mode"), LLM_MODES, "main"),
            instructor_structured_outputs_enabled=_bool(
                data.get("buddy_chat_instructor_structured_outputs_enabled")
                if "buddy_chat_instructor_structured_outputs_enabled" in data
                else data.get("instructor_structured_outputs_enabled"),
                False,
            ),
            system_override_enabled=_bool(data.get("system_override_enabled"), True),
            system_override_prompt=_text(data.get("system_override_prompt"), DEFAULT_SYSTEM_OVERRIDE_PROMPT) or DEFAULT_SYSTEM_OVERRIDE_PROMPT,
            active_persona_window_enabled=_bool(data.get("active_persona_window_enabled"), False),
            active_persona_window_on_top=_bool(data.get("active_persona_window_on_top"), True),
            allow_buddy_to_buddy=_bool(data.get("allow_buddy_to_buddy"), True),
            max_speakers=_int(data.get("max_speakers"), 1, 1, 4),
            natural_second_speaker_every=_int(data.get("natural_second_speaker_every"), 4, 0, 100),
            forced_buddy_every=_int(data.get("forced_buddy_every"), 0, 0, 100),
            completed_reply_count=_int(data.get("completed_reply_count"), 0, 0, 10_000_000),
            buddy_provider=ProviderOverride.from_dict(data.get("buddy_provider") if isinstance(data.get("buddy_provider"), dict) else {}),
            personas=personas,
            turn_index=_int(data.get("turn_index"), 0, 0, 10_000_000),
        )
        if not settings.personas:
            settings.personas = cls.default().personas
        return settings

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "settings_epoch": max(0, int(self.settings_epoch or 0)),
            "enabled": bool(self.enabled),
            "reply_mode": _choice(self.reply_mode, REPLY_MODES, "context_only"),
            "llm_mode": _choice(self.llm_mode, LLM_MODES, "main"),
            "buddy_chat_instructor_structured_outputs_enabled": bool(self.instructor_structured_outputs_enabled),
            "system_override_enabled": bool(self.system_override_enabled),
            "system_override_prompt": _text(self.system_override_prompt, DEFAULT_SYSTEM_OVERRIDE_PROMPT) or DEFAULT_SYSTEM_OVERRIDE_PROMPT,
            "active_persona_window_enabled": bool(self.active_persona_window_enabled),
            "active_persona_window_on_top": bool(self.active_persona_window_on_top),
            "allow_buddy_to_buddy": bool(self.allow_buddy_to_buddy),
            "max_speakers": max(1, min(4, int(self.max_speakers or 1))),
            "natural_second_speaker_every": max(0, min(100, int(self.natural_second_speaker_every or 0))),
            "forced_buddy_every": max(0, min(100, int(self.forced_buddy_every or 0))),
            "completed_reply_count": max(0, int(self.completed_reply_count or 0)),
            "buddy_provider": self.buddy_provider.to_dict(),
            "personas": [persona.to_dict() for persona in list(self.personas or [])],
            "turn_index": max(0, int(self.turn_index or 0)),
        }

    def enabled_personas(self) -> list[BuddyPersona]:
        return [persona for persona in list(self.personas or []) if bool(persona.enabled)]
