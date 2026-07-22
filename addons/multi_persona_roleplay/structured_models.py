from __future__ import annotations

import re
from typing import Any

from .models import normalize_persona_id


INSTRUCTOR_SETTING_DEFAULTS: dict[str, bool] = {
    "mprc_instructor_structured_outputs_enabled": False,
    "mprc_instructor_master_story_validation_enabled": True,
    "mprc_instructor_scene_patch_enabled": True,
    "mprc_instructor_visual_beat_enabled": True,
    "mprc_instructor_audio_cue_selection_enabled": True,
    "mprc_instructor_ar_turn_enabled": False,
}


try:
    from pydantic import BaseModel, Field

    try:
        from pydantic import ConfigDict
    except Exception:  # pragma: no cover - pydantic v1 compatibility
        ConfigDict = None  # type: ignore[assignment]

    PYDANTIC_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency fallback
    BaseModel = object  # type: ignore[assignment,misc]
    Field = None  # type: ignore[assignment]
    ConfigDict = None  # type: ignore[assignment]
    PYDANTIC_AVAILABLE = False


if PYDANTIC_AVAILABLE:

    if ConfigDict is not None:

        class _MprcStructuredModel(BaseModel):  # type: ignore[misc]
            model_config = ConfigDict(extra="ignore")

    else:

        class _MprcStructuredModel(BaseModel):  # type: ignore[misc]
            class Config:
                extra = "ignore"


    class MasterStoryPersona(_MprcStructuredModel):
        id: str = ""
        enabled: bool = True
        display_name: str = ""
        role: str = ""
        description: str = ""
        system_prompt: str = ""
        ar_profile_enabled: bool = True
        ar_description: str = ""
        ar_system_prompt: str = ""
        speaking_style: str = ""
        allowed_tone: str = ""
        response_length: str = "balanced"
        temperature_hint: str = ""
        memory_scope: str = "persona-only"
        behavior_mode: str = "group participant"
        master_narrator: bool = False
        tags: list[str] = Field(default_factory=list)  # type: ignore[misc]
        visual: dict[str, Any] = Field(default_factory=dict)  # type: ignore[misc]
        safety: dict[str, Any] = Field(default_factory=dict)  # type: ignore[misc]


    class MasterStorySession(_MprcStructuredModel):
        enabled: bool = True
        mode: str = ""
        active_persona_id: str = ""
        current_speaker_id: str = ""
        scene_title: str = ""
        location: str = ""
        time_of_day: str = ""
        mood: str = ""
        objective: str = ""
        scene_summary: str = ""
        turn_index: int = 0
        character_state_summaries: dict[str, str] = Field(default_factory=dict)  # type: ignore[misc]
        recent_events: list[str] = Field(default_factory=list)  # type: ignore[misc]
        auto_select_speaker: bool = False
        keep_scene_continuity: bool = True
        update_scene_after_reply: bool = False
        ar_state: dict[str, Any] = Field(default_factory=dict)  # type: ignore[misc]
        ar_pacing: str = "Balanced"
        ar_interaction_frequency: str = "Ask sometimes"
        ar_dialogue_density: str = "Balanced narrator + character dialogue"
        ar_use_persona_profiles: bool = True


    class MasterStoryDraft(_MprcStructuredModel):
        id: str = ""
        title: str = ""
        summary: str = ""
        mode: str = ""
        active_persona_id: str = ""
        current_speaker_id: str = ""
        narrator_persona_id: str = ""
        selected_narrator_id: str = ""
        session: MasterStorySession = Field(default_factory=MasterStorySession)  # type: ignore[misc]
        personas: list[MasterStoryPersona] = Field(default_factory=list)  # type: ignore[misc]
        persona_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)  # type: ignore[misc]
        content_safety: dict[str, Any] = Field(default_factory=dict)  # type: ignore[misc]
        avatar_visual_direction: str = ""
        generation: dict[str, Any] = Field(default_factory=dict)  # type: ignore[misc]
        updated_at: str = ""


    class ARSceneStatePatch(_MprcStructuredModel):
        scene_summary: str = ""
        current_scene: str = ""
        location: str = ""
        time_of_day: str = ""
        mood: str = ""
        story_goal: str = ""
        current_objective: str = ""
        tension_level: int | None = None
        recent_event: str = ""
        pending_choices: list[str] = Field(default_factory=list)  # type: ignore[misc]
        active_characters: list[str] = Field(default_factory=list)  # type: ignore[misc]
        character_state_summaries: dict[str, str] = Field(default_factory=dict)  # type: ignore[misc]


    class VisualBeat(_MprcStructuredModel):
        subject: str = ""
        action: str = ""
        setting: str = ""
        mood: str = ""
        response_style_hint: str = ""
        source_excerpt: str = ""
        what_to_avoid: str = ""


    class AudioCue(_MprcStructuredModel):
        cue_id: str = ""
        tag: str = ""
        reason: str = ""


    class AudioCueSelection(_MprcStructuredModel):
        cues: list[AudioCue] = Field(default_factory=list)  # type: ignore[misc]


    class StorySegment(_MprcStructuredModel):
        role: str = "narrator"
        kind: str = ""
        speaker_id: str = "narrator"
        text: str = ""
        sfx_tags: list[str] = Field(default_factory=list)  # type: ignore[misc]


    class StructuredStoryTurn(_MprcStructuredModel):
        schema_version: str = "mprc.story_output.v1"
        segments: list[StorySegment] = Field(default_factory=list)  # type: ignore[misc]
        choices: list[Any] = Field(default_factory=list)  # type: ignore[misc]

else:
    MasterStoryDraft = None  # type: ignore[assignment]
    ARSceneStatePatch = None  # type: ignore[assignment]
    VisualBeat = None  # type: ignore[assignment]
    AudioCueSelection = None  # type: ignore[assignment]
    StructuredStoryTurn = None  # type: ignore[assignment]


def structured_feature_enabled(settings: dict[str, Any] | None, feature_key: str) -> bool:
    values = dict(settings or {})
    if not bool(values.get("mprc_instructor_structured_outputs_enabled", INSTRUCTOR_SETTING_DEFAULTS["mprc_instructor_structured_outputs_enabled"])):
        return False
    key = str(feature_key or "").strip()
    if not key:
        return False
    return bool(values.get(key, INSTRUCTOR_SETTING_DEFAULTS.get(key, False)))


def model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper(exclude_none=True)
        return dict(dumped or {}) if isinstance(dumped, dict) else {}
    dumper = getattr(value, "dict", None)
    if callable(dumper):
        dumped = dumper(exclude_none=True)
        return dict(dumped or {}) if isinstance(dumped, dict) else {}
    return {}


def validate_master_story_draft(payload: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        return {}, ["Master Story draft must be a JSON object."]
    source = dict(payload.get("draft") or {}) if isinstance(payload.get("draft"), dict) else dict(payload)
    if PYDANTIC_AVAILABLE and MasterStoryDraft is not None:
        try:
            source = model_to_dict(MasterStoryDraft(**source))
        except Exception as exc:
            return {}, [f"Master Story draft failed structured validation: {exc}"]

    clean: dict[str, Any] = {}
    text_fields = {
        "id": 120,
        "title": 140,
        "summary": 1600,
        "mode": 80,
        "active_persona_id": 120,
        "current_speaker_id": 120,
        "narrator_persona_id": 120,
        "selected_narrator_id": 120,
        "avatar_visual_direction": 1800,
        "updated_at": 80,
    }
    for key, limit in text_fields.items():
        text = _compact(source.get(key), limit)
        if text:
            clean[key] = text

    session = _sanitize_master_story_session(source.get("session"))
    clean["session"] = session
    personas = _sanitize_master_story_personas(source.get("personas"))
    clean["personas"] = personas
    clean["content_safety"] = _sanitize_content_safety(source.get("content_safety"))
    generation = _sanitize_generation(source.get("generation"))
    if generation:
        clean["generation"] = generation
    overrides = _sanitize_persona_overrides(source.get("persona_overrides"), {persona["id"] for persona in personas})
    if overrides:
        clean["persona_overrides"] = overrides

    known_ids = {persona["id"] for persona in personas if str(persona.get("id") or "").strip()}
    if session.get("ar_state"):
        session["ar_state"] = _sanitize_ar_state_payload(session.get("ar_state"), known_persona_ids=known_ids)
    errors = _master_story_errors(clean)
    return clean, errors


def sanitize_scene_patch(payload: dict[str, Any] | None, *, known_persona_ids: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    known_ids = {normalize_persona_id(item) for item in set(known_persona_ids or set()) if str(item or "").strip()}
    clean: dict[str, Any] = {}
    for key, limit in (
        ("scene_summary", 1400),
        ("current_scene", 360),
        ("location", 180),
        ("time_of_day", 120),
        ("mood", 180),
        ("story_goal", 300),
        ("current_objective", 300),
        ("recent_event", 260),
    ):
        text = _compact(payload.get(key), limit)
        if text:
            clean[key] = text
    if "tension_level" in payload:
        clean["tension_level"] = _clamp_int(payload.get("tension_level"), 0, 10)
    choices = [_compact(item, 180) for item in _list_values(payload.get("pending_choices")) if _compact(item, 180)]
    if choices:
        clean["pending_choices"] = choices[:6]
    active = []
    seen: set[str] = set()
    for item in _list_values(payload.get("active_characters")):
        persona_id = normalize_persona_id(item)
        if persona_id and (not known_ids or persona_id in known_ids) and persona_id not in seen:
            active.append(persona_id)
            seen.add(persona_id)
    if active:
        clean["active_characters"] = active[:8]
    summaries = payload.get("character_state_summaries")
    if isinstance(summaries, dict):
        clean_summaries: dict[str, str] = {}
        for key, value in summaries.items():
            persona_id = normalize_persona_id(key)
            if persona_id and (not known_ids or persona_id in known_ids):
                text = _compact(value, 360)
                if text:
                    clean_summaries[persona_id] = text
        if clean_summaries:
            clean["character_state_summaries"] = clean_summaries
    return clean


def sanitize_visual_beat(payload: dict[str, Any] | None, *, latest_turn_text: str = "") -> dict[str, str]:
    source = dict(payload or {}) if isinstance(payload, dict) else {}
    latest_visible = _latest_visible_story_action(latest_turn_text)
    excerpt = _compact(source.get("source_excerpt"), 700)
    if latest_visible and (not excerpt or _disallowed_visual_excerpt(excerpt)):
        excerpt = latest_visible
    action = _compact(source.get("action"), 500)
    if latest_visible and (not action or _disallowed_visual_excerpt(action)):
        action = latest_visible
    clean = {
        "subject": _compact(source.get("subject") or source.get("main_subject"), 180),
        "action": action,
        "setting": _compact(source.get("setting") or source.get("location"), 220),
        "mood": _compact(source.get("mood"), 160),
        "response_style_hint": _compact(source.get("response_style_hint"), 220),
        "source_excerpt": excerpt or latest_visible,
        "what_to_avoid": _compact(source.get("what_to_avoid"), 260),
    }
    return {key: value for key, value in clean.items() if value}


def sanitize_audio_cue_selection(payload: dict[str, Any] | None, *, available_cues: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, str]]]:
    allowed = _available_audio_cue_map(available_cues)
    if not allowed:
        return {"cues": []}
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    raw_cues = []
    if isinstance(payload, dict):
        raw_cues = _list_values(payload.get("cues") or payload.get("audio_cues") or payload.get("selected_cues"))
    for item in raw_cues:
        candidate_id = ""
        candidate_tag = ""
        if isinstance(item, dict):
            candidate_id = _audio_key(item.get("cue_id") or item.get("id") or item.get("name"))
            candidate_tag = _normalize_audio_tag(item.get("tag") or item.get("audio_tag") or item.get("activate"))
        else:
            candidate_tag = _normalize_audio_tag(item)
            candidate_id = _audio_key(item)
        resolved = _resolve_audio_cue(candidate_id, candidate_tag, allowed)
        if not resolved:
            continue
        cue_id, tag = resolved
        if cue_id in seen:
            continue
        selected.append({"cue_id": cue_id, "tag": tag})
        seen.add(cue_id)
    return {"cues": selected[:4]}


def sanitize_structured_story_turn(
    payload: dict[str, Any] | None,
    *,
    cast: dict[str, dict[str, str]] | None = None,
    require_choices: bool = False,
    available_cues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"segments": [], "choices": []}
    source = payload.get("story") if isinstance(payload.get("story"), dict) else payload
    cast_ids = {"narrator", "unknown_speaker"}
    cast_ids.update(normalize_persona_id(key) for key in dict(cast or {}).keys() if str(key or "").strip())
    clean_segments: list[dict[str, Any]] = []
    for item in _list_values(source.get("segments")):
        if not isinstance(item, dict):
            continue
        role = _compact(item.get("role") or item.get("kind") or item.get("type") or "narrator", 60).lower()
        text = _compact(item.get("text") or item.get("content") or item.get("body"), 1400)
        if not text:
            continue
        speaker_id = normalize_persona_id(item.get("speaker_id") or "")
        if role in {"narrator", "choice", "choices", "music", "ambience", "ambient", "fx", "sfx", "stinger", "audio", "sound"}:
            speaker_id = "narrator"
        elif speaker_id not in cast_ids:
            speaker_id = "unknown_speaker"
        segment = {
            "role": role or "narrator",
            "speaker_id": speaker_id,
            "text": text,
        }
        if role in {"music", "ambience", "ambient", "fx", "sfx", "stinger", "audio", "sound"}:
            audio = sanitize_audio_cue_selection({"cues": [{"tag": f"[{role.upper()}: {text}]"}]}, available_cues=available_cues)
            if not audio["cues"]:
                continue
            tag = audio["cues"][0]["tag"]
            segment["role"] = tag.strip("[]").split(":", 1)[0].lower()
            segment["text"] = tag.strip("[]").split(":", 1)[1].strip()
        tags = [
            _compact(tag, 120)
            for tag in _list_values(item.get("sfx_tags"))
            if _compact(tag, 120)
        ]
        if tags:
            segment["sfx_tags"] = tags[:4]
        clean_segments.append(segment)
        if len(clean_segments) >= 8:
            break
    choices = []
    for item in _list_values(source.get("choices") or payload.get("choices")):
        choice = _choice_text(item)
        if choice:
            choices.append(choice)
        if len(choices) >= 4:
            break
    if require_choices and not choices:
        choices = []
    return {
        "schema_version": str(payload.get("schema_version") or "mprc.story_output.v1"),
        "segments": clean_segments,
        "choices": choices,
    }


def _sanitize_master_story_session(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_text = {
        "mode": 80,
        "active_persona_id": 120,
        "current_speaker_id": 120,
        "narrator_persona_id": 120,
        "selected_narrator_id": 120,
        "scene_title": 180,
        "location": 180,
        "time_of_day": 120,
        "mood": 180,
        "objective": 300,
        "scene_summary": 2200,
        "ar_pacing": 80,
        "ar_interaction_frequency": 80,
        "ar_dialogue_density": 120,
    }
    clean: dict[str, Any] = {}
    for key, limit in allowed_text.items():
        text = _compact(value.get(key), limit)
        if text:
            clean[key] = text
    for key in ("enabled", "auto_select_speaker", "keep_scene_continuity", "update_scene_after_reply", "ar_use_persona_profiles"):
        if key in value:
            clean[key] = bool(value.get(key))
    if "turn_index" in value:
        clean["turn_index"] = _clamp_int(value.get("turn_index"), 0, 1000000)
    recent = [_compact(item, 300) for item in _list_values(value.get("recent_events")) if _compact(item, 300)]
    if recent:
        clean["recent_events"] = recent[:20]
    summaries = value.get("character_state_summaries")
    if isinstance(summaries, dict):
        clean["character_state_summaries"] = {
            normalize_persona_id(key): _compact(summary, 360)
            for key, summary in summaries.items()
            if normalize_persona_id(key) and _compact(summary, 360)
        }
    if isinstance(value.get("ar_state"), dict):
        clean["ar_state"] = dict(value.get("ar_state") or {})
    return clean


def _sanitize_master_story_personas(value: Any) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _list_values(value):
        if not isinstance(item, dict):
            continue
        persona_id = normalize_persona_id(item.get("id") or item.get("display_name") or "story_persona")
        if persona_id in seen:
            suffix = 2
            base = persona_id
            while f"{base}_{suffix}" in seen:
                suffix += 1
            persona_id = f"{base}_{suffix}"
        seen.add(persona_id)
        persona = {
            "id": persona_id,
            "enabled": bool(item.get("enabled", True)),
        }
        for key, limit in (
            ("display_name", 120),
            ("role", 120),
            ("description", 1200),
            ("system_prompt", 2400),
            ("ar_description", 1400),
            ("ar_system_prompt", 2400),
            ("speaking_style", 500),
            ("allowed_tone", 500),
            ("response_length", 80),
            ("temperature_hint", 80),
            ("memory_scope", 80),
            ("behavior_mode", 80),
            ("character_image_path", 1000),
        ):
            text = _compact(item.get(key), limit)
            if text:
                persona[key] = text
        persona["ar_profile_enabled"] = bool(item.get("ar_profile_enabled", True))
        persona["master_narrator"] = bool(item.get("master_narrator", False))
        tags = [_compact(tag, 40).lower() for tag in _list_values(item.get("tags")) if _compact(tag, 40)]
        if tags:
            persona["tags"] = list(dict.fromkeys(tags))[:16]
        visual = _sanitize_visual_profile(item.get("visual"))
        if visual:
            persona["visual"] = visual
        safety = _sanitize_persona_safety(item.get("safety"))
        if safety:
            persona["safety"] = safety
        clean.append(persona)
    return clean


def _sanitize_visual_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    for key in ("enabled", "keep_continuity", "include_scene_summary", "include_active_speaker", "auto_show_dock"):
        if key in value:
            clean[key] = bool(value.get(key))
    for key, limit in (
        ("mode", 80),
        ("provider", 80),
        ("model", 120),
        ("size", 60),
        ("style_preset", 120),
        ("character_description", 1800),
        ("clothing_props", 900),
        ("environment_style", 900),
        ("negative_prompt", 900),
    ):
        text = _compact(value.get(key), limit)
        if text:
            clean[key] = text
    for key, max_value in (("auto_reply_interval", 100), ("cooldown_seconds", 86400), ("max_auto_images_per_session", 100)):
        if key in value:
            clean[key] = _clamp_int(value.get(key), 0 if key != "auto_reply_interval" else 1, max_value)
    return clean


def _sanitize_persona_safety(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean = {
        "allow_adult_only": bool(value.get("allow_adult_only", False)),
        "avoid_real_person_impersonation": bool(value.get("avoid_real_person_impersonation", True)),
    }
    notes = _compact(value.get("notes"), 800)
    if notes:
        clean["notes"] = notes
    return clean


def _sanitize_content_safety(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    sfw = bool(source.get("sfw", True))
    return {
        "sfw": sfw,
        "allow_romance": bool(source.get("allow_romance", True)),
        "allow_mature_themes": bool(source.get("allow_mature_themes", not sfw)),
        "allow_explicit_sexual_content": False,
    }


def _sanitize_generation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, limit in (("source", 80), ("notes", 600)):
        text = _compact(value.get(key), limit)
        if text:
            clean[key] = text
    for key in ("requested_story_native_personas", "maximum_new_personas_to_create"):
        if key in value:
            clean[key] = _clamp_int(value.get(key), 0, 100)
    for key in ("use_existing_personas", "auto_create_missing_personas", "sfw_mode"):
        if key in value:
            clean[key] = bool(value.get(key))
    return clean


def _sanitize_persona_overrides(value: Any, allowed_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    allowed = {normalize_persona_id(item) for item in set(allowed_ids or set()) if str(item or "").strip()}
    clean: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        persona_id = normalize_persona_id(key)
        if not persona_id or persona_id not in allowed or not isinstance(item, dict):
            continue
        override: dict[str, Any] = {}
        for field, limit in (("display_name", 120), ("role", 120), ("description", 1200), ("ar_description", 1400), ("ar_system_prompt", 2000)):
            text = _compact(item.get(field), limit)
            if text:
                override[field] = text
        if override:
            clean[persona_id] = override
    return clean


def _sanitize_ar_state_payload(value: Any, *, known_persona_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    patch = sanitize_scene_patch(
        {
            "current_scene": value.get("current_scene"),
            "location": value.get("location"),
            "active_characters": value.get("active_characters"),
            "tension_level": value.get("tension_level"),
            "story_goal": value.get("story_goal"),
            "recent_event": "",
            "pending_choices": value.get("pending_choices"),
            "mood": value.get("mood"),
            "time_of_day": value.get("time_of_day"),
        },
        known_persona_ids=known_persona_ids,
    )
    events = [_compact(item, 260) for item in _list_values(value.get("recent_events")) if _compact(item, 260)]
    if events:
        patch["recent_events"] = events[-12:]
    player = _compact(value.get("player_intent"), 220)
    if player:
        patch["player_intent"] = player
    patch.pop("recent_event", None)
    return patch


def _master_story_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("id", "title", "mode", "session", "personas"):
        if key not in payload or payload.get(key) in (None, "", [], {}):
            errors.append(f"Missing required field: {key}.")
    personas = payload.get("personas")
    if not isinstance(personas, list):
        return [*errors, "Field 'personas' must be an array."]
    ids: list[str] = []
    for index, item in enumerate(personas, start=1):
        if not isinstance(item, dict):
            errors.append(f"Persona {index} must be an object.")
            continue
        persona_id = normalize_persona_id(item.get("id"))
        if not persona_id:
            errors.append(f"Persona {index} is missing id.")
        else:
            ids.append(persona_id)
        if not _compact(item.get("display_name"), 120):
            errors.append(f"Persona {index} is missing display_name.")
        if not _compact(item.get("role"), 120):
            errors.append(f"Persona {index} is missing role.")
        if not _compact(item.get("system_prompt") or item.get("ar_system_prompt"), 120):
            errors.append(f"Persona {index} must include system_prompt or ar_system_prompt.")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append("Duplicate persona id(s) in draft: " + ", ".join(duplicates) + ".")
    return errors


def _latest_visible_story_action(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO):[^\]]+\]", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"(?is)\[CHOICES\].*$", " ", raw)
    raw = re.sub(r"\[(?:/?NARRATOR|CHARACTER:\s*[^\]]+)\]", "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\b(?:Story|Assistant)\s*:\s*", " ", raw, flags=re.IGNORECASE)
    paragraphs = [re.sub(r"\s+", " ", part).strip(" -") for part in re.split(r"\n{2,}|\r?\n", raw)]
    blocked_starts = ("what do you do", "what's your next move", "whats your next move")
    for paragraph in reversed(paragraphs):
        lowered = paragraph.lower()
        if len(paragraph) < 24 or lowered.startswith(blocked_starts):
            continue
        return _compact(paragraph, 700)
    return _compact(raw, 700)


def _disallowed_visual_excerpt(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "[choices]",
            "hidden prompt",
            "prompt structure",
            "system prompt",
            "director note",
            "chain-of-thought",
        )
    )


def _available_audio_cue_map(available_cues: list[dict[str, Any]] | None) -> dict[str, dict[str, str]]:
    allowed: dict[str, dict[str, str]] = {}
    for item in list(available_cues or []):
        if not isinstance(item, dict) or not bool(item.get("ready", True)):
            continue
        cue_id = _audio_key(item.get("id") or item.get("name") or item.get("description"))
        description = _compact(item.get("description") or item.get("prompt") or item.get("id"), 160)
        if not cue_id or not description:
            continue
        audio_type = str(item.get("type") or "AUDIO").strip().upper()
        if audio_type == "AMBIENT":
            audio_type = "AMBIENCE"
        if audio_type == "SFX":
            audio_type = "FX"
        if audio_type not in {"AMBIENCE", "MUSIC", "FX", "STINGER", "AUDIO"}:
            audio_type = "AUDIO"
        tag = f"[{audio_type}: {description}]"
        entry = {"cue_id": cue_id, "tag": tag}
        allowed[f"id:{cue_id}"] = entry
        allowed[f"tag:{_normalize_audio_tag(tag).lower()}"] = entry
        allowed[f"text:{_audio_key(description)}"] = entry
    return allowed


def _resolve_audio_cue(candidate_id: str, candidate_tag: str, allowed: dict[str, dict[str, str]]) -> tuple[str, str] | None:
    for key in (
        f"id:{candidate_id}",
        f"tag:{candidate_tag.lower()}",
        f"text:{_audio_key(candidate_tag)}",
    ):
        entry = allowed.get(key)
        if entry:
            return entry["cue_id"], entry["tag"]
    return None


def _normalize_audio_tag(value: Any) -> str:
    text = _compact(value, 200)
    if not text:
        return ""
    match = re.match(r"^\[(AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO)\s*:\s*([^\]]+)\]$", text, flags=re.IGNORECASE)
    if not match:
        return text
    audio_type = match.group(1).upper()
    if audio_type == "AMBIENT":
        audio_type = "AMBIENCE"
    if audio_type == "SFX":
        audio_type = "FX"
    return f"[{audio_type}: {_compact(match.group(2), 160)}]"


def _audio_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _choice_text(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("text", "content", "label", "title", "action", "choice"):
            value = _compact(item.get(key), 180)
            if value:
                return re.sub(r"^(?:[-*]\s+|\d+[\.)]\s*)", "", value).strip()
        return ""
    text = _compact(item, 180)
    return re.sub(r"^(?:[-*]\s+|\d+[\.)]\s*)", "", text).strip()


def _compact(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    maximum = max(0, int(limit or 0))
    if len(text) <= maximum:
        return text
    if maximum <= 3:
        return text[:maximum]
    return text[: maximum - 3].rstrip() + "..."


def _list_values(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = int(minimum)
    return max(int(minimum), min(int(maximum), parsed))


__all__ = [
    "ARSceneStatePatch",
    "AudioCueSelection",
    "INSTRUCTOR_SETTING_DEFAULTS",
    "MasterStoryDraft",
    "PYDANTIC_AVAILABLE",
    "StructuredStoryTurn",
    "VisualBeat",
    "model_to_dict",
    "sanitize_audio_cue_selection",
    "sanitize_scene_patch",
    "sanitize_structured_story_turn",
    "sanitize_visual_beat",
    "structured_feature_enabled",
    "validate_master_story_draft",
]
