from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .models import AR_DIALOGUE_DENSITY_MODES, PersonaConfig, RoleplaySessionState, normalize_persona_id


CAST_MODE_FOCUSED_SPEAKER = "focused_speaker"
CAST_MODE_JOINED_CAST = "joined_cast"
_CAST_MODES = {CAST_MODE_FOCUSED_SPEAKER, CAST_MODE_JOINED_CAST}
DEFAULT_DIALOGUE_DENSITY = "Balanced narrator + character dialogue"


@dataclass(frozen=True)
class StoryDirectorSection:
    title: str
    body: str

    def render(self) -> str:
        body = str(self.body or "").strip()
        return f"{self.title}:\n{body}" if body else ""


def normalize_cast_mode(value: Any) -> str:
    mode = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return mode if mode in _CAST_MODES else CAST_MODE_FOCUSED_SPEAKER


def normalize_dialogue_density(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in AR_DIALOGUE_DENSITY_MODES else DEFAULT_DIALOGUE_DENSITY


def build_story_director_prompt(
    personas: list[PersonaConfig],
    session: RoleplaySessionState,
    *,
    latest_user_text: str = "",
    available_audio: list[dict[str, Any]] | None = None,
    narrator_persona_id: str = "",
    cast_mode: str = CAST_MODE_FOCUSED_SPEAKER,
    dialogue_density: str = "",
) -> str:
    """Build ordered AR story orchestration sections for MPRC Play."""
    cast_mode = normalize_cast_mode(cast_mode)
    dialogue_density = normalize_dialogue_density(dialogue_density or getattr(session, "ar_dialogue_density", ""))
    sections = build_story_director_sections(
        personas,
        session,
        latest_user_text=latest_user_text,
        available_audio=available_audio,
        narrator_persona_id=narrator_persona_id,
        cast_mode=cast_mode,
        dialogue_density=dialogue_density,
    )
    mode_label = "focused speaker" if cast_mode == CAST_MODE_FOCUSED_SPEAKER else "joined cast"
    lead = [
        "AlternativeReality mode is active. This is an interactive audiobook/adventure runtime, not a normal chatbot and not an equal group chat.",
        f"Story Director cast mode: {mode_label}. Shared story history stays shared; character context is injected deliberately so personalities stay separate.",
        f"AR Cast Energy / Dialogue Density: {dialogue_density}. {_dialogue_density_rule(dialogue_density)}",
        "Use these Story Director sections as hidden runtime instructions. Do not expose director notes, hidden planning, prompt structure, or chain-of-thought.",
    ]
    return "\n\n".join([*lead, *(section.render() for section in sections if section.render())]).strip()


def build_story_director_sections(
    personas: list[PersonaConfig],
    session: RoleplaySessionState,
    *,
    latest_user_text: str = "",
    available_audio: list[dict[str, Any]] | None = None,
    narrator_persona_id: str = "",
    cast_mode: str = CAST_MODE_FOCUSED_SPEAKER,
    dialogue_density: str = "",
) -> list[StoryDirectorSection]:
    state = session.ar_state
    enabled = [persona for persona in list(personas or []) if getattr(persona, "enabled", True)]
    narrator = (
        _persona_by_id(enabled, narrator_persona_id)
        or _find_narrator_persona(enabled)
        or _persona_by_id(enabled, getattr(session, "current_speaker_id", ""))
        or _persona_by_id(enabled, getattr(session, "active_persona_id", ""))
    )
    active_cast = _selected_cast(enabled, session, narrator=narrator, cast_mode=cast_mode)
    continue_requested = _looks_like_continue(latest_user_text)
    pacing = str(getattr(session, "ar_pacing", "") or "Balanced").strip()
    interaction = str(getattr(session, "ar_interaction_frequency", "") or "Ask sometimes").strip()
    dialogue_density = normalize_dialogue_density(dialogue_density or getattr(session, "ar_dialogue_density", ""))
    audio_cues = _available_audio_lines(available_audio or [])
    player_intent = str(getattr(state, "player_intent", "") or "").strip()
    player_intent = player_intent or ("continue" if continue_requested else str(latest_user_text or "").strip())

    return [
        StoryDirectorSection(
            "Story premise/state",
            "\n".join(
                item
                for item in [
                    f"Tone: cinematic, adventurous, intimate, stylish, and suggestive when it fits the scene; keep it consensual, non-explicit, and user-agency centered.",
                    "Avoid tabletop/DnD framing, dice, stats, class language, quest-log phrasing, or equal turn-taking unless the user explicitly asks for it.",
                    f"Current scene: {_compact(getattr(state, 'current_scene', '') or getattr(session, 'scene_title', ''), 260)}",
                    f"Location: {_compact(getattr(state, 'location', '') or getattr(session, 'location', ''), 180)}",
                    f"Time of day: {_compact(getattr(state, 'time_of_day', '') or getattr(session, 'time_of_day', ''), 90)}",
                    f"Mood: {_compact(getattr(state, 'mood', '') or getattr(session, 'mood', ''), 120)}",
                    f"Tension level: {int(getattr(state, 'tension_level', 0) or 0)}",
                    f"Story goal: {_compact(getattr(state, 'story_goal', '') or getattr(session, 'objective', ''), 260)}",
                    f"Player intent: {_compact(player_intent, 260)}",
                    f"Pending choices: {_join_compact(getattr(state, 'pending_choices', []), 6, 140)}",
                    f"Recent AR events: {_join_compact(list(getattr(state, 'recent_events', []) or [])[-6:], 6, 170)}",
                    f"Scene continuity summary: {_compact(getattr(session, 'scene_summary', ''), 900)}",
                ]
                if str(item or "").strip()
            ),
        ),
        StoryDirectorSection(
            "Active cast",
            "\n".join(_cast_lines(active_cast, session=session, narrator=narrator, include_instructions=True))
            or "Choose only who the scene needs.",
        ),
        StoryDirectorSection(
            "Speaker discipline",
            "\n".join(
                [
                    f"Narrator role: {getattr(narrator, 'display_name', '') or 'the current speaker'}. The narrator controls continuity, framing, transitions, consequences, and pacing.",
                    "NPC/Character roles: characters speak only when naturally relevant to the scene. Do not make every persona respond every turn.",
                    "Use active cast information as character-card context, not as a requirement for every listed character to speak.",
                    "Most story turns should include at least one character speaking when active characters are present.",
                    "Do not keep all dialogue in narrator prose.",
                    "Use [CHARACTER: Exact Name] for spoken lines.",
                    "Narrator frames action; characters create tension, opinions, interruptions, emotion.",
                    f"Dialogue density mode: {dialogue_density}. {_dialogue_density_rule(dialogue_density)}",
                    "If a new named speaking character appears, describe their visible role/appearance/personality in [NARRATOR] prose first, then use [CHARACTER: New Name] only for direct dialogue.",
                ]
            ),
        ),
        StoryDirectorSection(
            "Story progression rules",
            "\n".join(
                [
                    f"Pacing: {pacing}. {_pacing_rule(pacing)}",
                    f"Interaction frequency: {interaction}. {_interaction_rule(interaction)}",
                    "Progression rule: the latest player action overrides older scene memory. If the player leaves, enters, travels, opens a door, or moves to a new place, advance to that new visible place unless an immediate concrete obstacle blocks it.",
                    "Location rule: after visible movement, write the new location clearly in narration and continue from there on later turns.",
                    "Continue the story unless the player must make an important decision.",
                    "Preserve player agency. Do not decide major player actions, private thoughts, or consent for the player.",
                ]
            ),
        ),
        StoryDirectorSection(
            "Visual Reply beat rules",
            "\n".join(
                [
                    "Select one visible image beat from the latest story action: a concrete character action, reveal, location change, important object, or emotional reaction.",
                    "Prefer the newest visible action over older scene summary. Do not generate an image from [CHOICES] text, hidden planning, prompt notes, or stale opening premise.",
                    "Keep Visual Reply prompts grounded in current location, mood, time of day, active speaker, and recurring character appearance.",
                    "If nothing visible changed, choose a quiet atmospheric beat from the current scene instead of inventing a new event.",
                ]
            ),
        ),
        StoryDirectorSection(
            "Multi-voice output contract",
            "\n".join(
                [
                    "[NARRATOR]\nScene narration, character actions, expressions, movement, consequences, and descriptive ambience.",
                    "[CHARACTER: Exact Persona Display Name]\nOnly that character's direct spoken dialogue or explicit first-person thought.",
                    "[NARRATOR]\nContinue narration after the character speaks.",
                    "[AMBIENCE: exact listed activation text only]\n[MUSIC: exact listed activation text only]\n[FX: exact listed activation text only]\n[STINGER: exact listed activation text only]",
                    "[CHOICES]\nOptional concise choices.",
                    "Split direct speech into [CHARACTER: Exact Name] blocks so multi-TTS can route each voice cleanly.",
                    "Never put third-person actions, facial expressions, attribution, movement, or consequences inside [CHARACTER] blocks.",
                    "Do not write quoted dialogue inside [NARRATOR] prose, such as \"Line,\" Elara says. Split it into a character block, then return to narrator.",
                    "Strict Story Sounds rule: the only valid story audio tags are exact activate= values from Available story audio cues. If no listed cue fits, omit the audio tag.",
                    "Available story audio cues:\n" + ("\n".join(audio_cues) if audio_cues else "NONE. Do not output story audio tags because no ready story audio cues are available."),
                ]
            ),
        ),
        StoryDirectorSection(
            "Continue/choice nudge",
            _continue_choice_nudge(continue_requested=continue_requested, interaction=interaction),
        ),
    ]


def build_visual_beat_context(
    *,
    persona: PersonaConfig | None,
    personas: list[PersonaConfig] | None = None,
    session: RoleplaySessionState,
    reason: str = "manual",
    source_text: str = "",
) -> dict[str, str]:
    """Return stable visible-story inputs for Visual Reply prompt assembly."""
    state = getattr(session, "ar_state", None)
    latest_visible_action = _visible_story_action(source_text, 700)
    visual_subject, visual_subject_source = _visual_subject_for_beat(
        persona=persona,
        personas=list(personas or []),
        latest_visible_action=latest_visible_action,
        source_text=source_text,
    )
    current_scene = _compact(getattr(state, "current_scene", ""), 320) if state is not None else ""
    location = _compact(getattr(state, "location", ""), 160) if state is not None else ""
    time_of_day = _compact(getattr(state, "time_of_day", ""), 90) if state is not None else ""
    mood = _compact(getattr(state, "mood", ""), 120) if state is not None else ""
    recent = []
    if state is not None:
        recent.extend(str(item or "").strip() for item in list(getattr(state, "recent_events", []) or [])[-2:])
    recent.extend(str(item or "").strip() for item in list(getattr(session, "recent_events", []) or [])[-2:])
    return {
        "reason": str(reason or "manual").strip() or "manual",
        "visual_subject_id": str(getattr(visual_subject, "id", "") or "").strip(),
        "visual_subject": str(getattr(visual_subject, "display_name", "") or "").strip(),
        "visual_subject_source": visual_subject_source,
        "latest_visible_action": latest_visible_action,
        "current_scene": current_scene,
        "location": location or _compact(getattr(session, "location", ""), 160),
        "time_of_day": time_of_day or _compact(getattr(session, "time_of_day", ""), 90),
        "mood": mood or _compact(getattr(session, "mood", ""), 120),
        "story_goal": _compact(getattr(state, "story_goal", "") or getattr(session, "objective", ""), 220),
        "scene_summary": _compact(getattr(session, "scene_summary", ""), 320),
        "recent_visible_events": "; ".join(_compact(item, 180) for item in recent if item),
    }


def _selected_cast(
    personas: list[PersonaConfig],
    session: RoleplaySessionState,
    *,
    narrator: PersonaConfig | None,
    cast_mode: str,
) -> list[PersonaConfig]:
    if normalize_cast_mode(cast_mode) == CAST_MODE_JOINED_CAST:
        return list(personas)

    state = getattr(session, "ar_state", None)
    active_ids = [
        normalize_persona_id(item)
        for item in list(getattr(state, "active_characters", []) or [])
        if str(item or "").strip()
    ]
    active_ids.extend(
        normalize_persona_id(item)
        for item in [getattr(session, "current_speaker_id", ""), getattr(session, "active_persona_id", "")]
        if str(item or "").strip()
    )
    selected: list[PersonaConfig] = []
    if narrator is not None:
        selected.append(narrator)
    for persona_id in active_ids:
        persona = _persona_by_id(personas, persona_id)
        if persona is not None:
            selected.append(persona)
    if len({persona.id for persona in selected}) <= 1:
        selected.extend(persona for persona in personas if narrator is None or persona.id != narrator.id)
    return _unique_personas(selected)[:6]


def _cast_lines(
    personas: list[PersonaConfig],
    *,
    session: RoleplaySessionState,
    narrator: PersonaConfig | None,
    include_instructions: bool,
) -> list[str]:
    lines: list[str] = []
    for persona in personas:
        marker = " [narrator]" if narrator is not None and persona.id == narrator.id else ""
        bits = [
            f"- {persona.display_name} ({persona.id}){marker}",
            _compact(str(getattr(persona, "role", "") or getattr(persona, "behavior_mode", "") or ""), 120),
            _compact(_ar_description(persona, session), 220),
        ]
        line = ": ".join(item for item in bits[:2] if item)
        if bits[2]:
            line = f"{line}; {bits[2]}" if line else bits[2]
        if include_instructions:
            instruction = _compact(_ar_system_prompt(persona, session), 260)
            if instruction:
                line = f"{line}; instruction={instruction}"
        if line:
            lines.append(line)
    return lines


def _unique_personas(personas: list[PersonaConfig]) -> list[PersonaConfig]:
    seen: set[str] = set()
    result: list[PersonaConfig] = []
    for persona in personas:
        persona_id = normalize_persona_id(getattr(persona, "id", "") or "")
        if not persona_id or persona_id in seen:
            continue
        seen.add(persona_id)
        result.append(persona)
    return result


def _find_narrator_persona(personas: list[PersonaConfig]) -> PersonaConfig | None:
    for persona in personas:
        if str(getattr(persona, "display_name", "") or "").strip().lower() == "story narrator":
            return persona
    for persona in personas:
        text = " ".join(
            [
                str(getattr(persona, "id", "") or ""),
                str(getattr(persona, "role", "") or ""),
                str(getattr(persona, "behavior_mode", "") or ""),
                ",".join(str(item or "") for item in list(getattr(persona, "tags", []) or [])),
            ]
        ).lower()
        if "narrator" in text:
            return persona
    return None


def _persona_by_id(personas: list[PersonaConfig], persona_id: str) -> PersonaConfig | None:
    wanted = normalize_persona_id(persona_id)
    for persona in personas:
        if normalize_persona_id(getattr(persona, "id", "") or "") == wanted:
            return persona
    return None


def _ar_description(persona: PersonaConfig, session: RoleplaySessionState) -> str:
    if getattr(session, "ar_use_persona_profiles", True) and getattr(persona, "ar_profile_enabled", True):
        text = str(getattr(persona, "ar_description", "") or "").strip()
        if text:
            return text
    return str(getattr(persona, "description", "") or "").strip()


def _ar_system_prompt(persona: PersonaConfig, session: RoleplaySessionState) -> str:
    if not (getattr(session, "ar_use_persona_profiles", True) and getattr(persona, "ar_profile_enabled", True)):
        return ""
    prompt = str(getattr(persona, "ar_system_prompt", "") or "").strip()
    if prompt == "Use [NARRATOR] for scene framing. Do not speak as Mira unless a [CHARACTER: Mira] section is needed.":
        return "Use [NARRATOR] for scene framing. Characters only speak in their own [CHARACTER: Name] sections."
    return prompt


def _available_audio_lines(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in list(items or [])[:16]:
        if not isinstance(item, dict):
            continue
        cue_id = str(item.get("id") or "").strip()
        if not cue_id:
            continue
        audio_type = str(item.get("type") or "Audio").strip() or "Audio"
        description = _compact(str(item.get("description") or item.get("prompt") or "").strip(), 180)
        file_name = str(item.get("file_name") or "").strip()
        ready = "ready" if item.get("ready", True) else "missing"
        label = f"- {cue_id}: {audio_type}"
        if description:
            label += f"; {description}"
        if file_name:
            label += f"; file={file_name}"
        label += f"; {ready}"
        tag = _audio_activation_tag(audio_type)
        label += f"; activate=[{tag}: {description or cue_id}]"
        lines.append(label)
    return lines


def _audio_activation_tag(audio_type: str) -> str:
    normalized = str(audio_type or "").strip().lower()
    if normalized == "music":
        return "MUSIC"
    if normalized in {"fx", "sfx"}:
        return "FX"
    if normalized == "stinger":
        return "STINGER"
    if normalized in {"ambience", "ambient"}:
        return "AMBIENCE"
    return "AUDIO"


def _pacing_rule(pacing: str) -> str:
    return {
        "Slow / Audiobook": "Use longer cinematic narration and let the scene breathe before asking for input.",
        "Fast / Game-like": "Use shorter beats, clearer consequences, and reach actionable choices sooner.",
    }.get(str(pacing or "").strip(), "Balance narration, dialogue, consequence, and forward motion.")


def _interaction_rule(interaction: str) -> str:
    return {
        "Ask often": "Offer player choices frequently, especially after meaningful discoveries or risks.",
        "Continue until important choice": "Keep narrating through minor beats and ask only when a decision materially changes the scene.",
    }.get(str(interaction or "").strip(), "Ask for input sometimes, but continue through small transitional beats.")


def _dialogue_density_rule(dialogue_density: str) -> str:
    return {
        "Cinematic narrator-led": (
            "Let narration lead the camera and atmosphere, but do not absorb direct dialogue when active characters are present."
        ),
        "Ensemble scene": (
            "Use the active cast as scene context and let two or more relevant characters speak when it creates tension or contrast."
        ),
        "High-dialogue character drama": (
            "Favor vivid character exchanges, interruptions, disagreement, desire, fear, and opinion; keep narrator prose shorter between spoken beats."
        ),
    }.get(
        str(dialogue_density or "").strip(),
        "Balance narrator framing with at least one relevant character voice on most active-character turns.",
    )


def _continue_choice_nudge(*, continue_requested: bool, interaction: str) -> str:
    lines = []
    if continue_requested:
        lines.append("The user asked to continue. The player asked to continue. Advance the current scene from stored AR state without resetting, recapping excessively, or asking a trivial question.")
    else:
        lines.append("Respond to the latest player action directly, then carry consequences forward into the next visible beat.")
    if str(interaction or "").strip() == "Ask often":
        lines.append("End with [CHOICES] when there are meaningful playable options.")
    elif str(interaction or "").strip() == "Continue until important choice":
        lines.append('Do not stop for minor transitions. Ask "What\'s your next move?" only at a meaningful decision point.')
    else:
        lines.append("Offer [CHOICES] for real decisions; otherwise end with a clear opening for the player.")
    return "\n".join(lines)


def _visible_story_action(text: str, limit: int = 700) -> str:
    value = str(text or "")
    value = re.sub(
        r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO):[^\]]+\]",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?is)\[CHOICES\].*$", " ", value)
    tag_pattern = re.compile(r"\[(NARRATOR|CHARACTER:\s*[^\]]+)\]", flags=re.IGNORECASE)
    matches = list(tag_pattern.finditer(value))
    narrator_blocks: list[str] = []
    fallback_blocks: list[str] = []
    if matches:
        prefix = _compact(value[: matches[0].start()], limit)
        if prefix:
            fallback_blocks.append(prefix)
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
            block = _compact(value[match.end() : end], limit)
            if not block:
                continue
            fallback_blocks.append(block)
            if not str(match.group(1) or "").strip().lower().startswith("character"):
                narrator_blocks.append(block)
    else:
        fallback = _compact(value, limit)
        if fallback:
            fallback_blocks.append(fallback)

    source = narrator_blocks[-1] if narrator_blocks else (fallback_blocks[-1] if fallback_blocks else "")
    return _compact(source, limit)


def _visual_subject_for_beat(
    *,
    persona: PersonaConfig | None,
    personas: list[PersonaConfig],
    latest_visible_action: str,
    source_text: str,
) -> tuple[PersonaConfig | None, str]:
    cast = [item for item in personas if item is not None and not _persona_looks_like_narrator(item)]
    latest_match: tuple[int, int, PersonaConfig] | None = None
    action = str(latest_visible_action or "")
    for cast_persona in cast:
        for alias in _visual_subject_aliases(cast_persona, cast):
            matches = list(re.finditer(rf"(?<![\w]){re.escape(alias)}(?![\w])", action, flags=re.IGNORECASE))
            if not matches:
                continue
            candidate = (matches[-1].start(), len(alias), cast_persona)
            if latest_match is None or candidate[:2] > latest_match[:2]:
                latest_match = candidate
    if latest_match is not None:
        return latest_match[2], "latest_visible_action"

    labels = re.findall(r"\[CHARACTER:\s*([^\]]+)\]", str(source_text or ""), flags=re.IGNORECASE)
    for raw_name in reversed(labels):
        wanted = str(raw_name or "").strip().lower()
        for cast_persona in cast:
            if wanted in {
                str(getattr(cast_persona, "id", "") or "").strip().lower(),
                str(getattr(cast_persona, "display_name", "") or "").strip().lower(),
            }:
                return cast_persona, "character_label"

    if persona is not None and not _persona_looks_like_narrator(persona):
        return persona, "requested_persona"
    return None, "scene"


def _visual_subject_aliases(persona: PersonaConfig, cast: list[PersonaConfig]) -> list[str]:
    aliases = {
        str(getattr(persona, "display_name", "") or "").strip(),
        str(getattr(persona, "id", "") or "").strip().replace("_", " "),
    }
    display_name = str(getattr(persona, "display_name", "") or "").strip()
    first_name = display_name.split()[0] if display_name else ""
    if first_name and sum(
        1
        for item in cast
        if str(getattr(item, "display_name", "") or "").strip().lower().split()[:1] == [first_name.lower()]
    ) == 1:
        aliases.add(first_name)
    return sorted((alias for alias in aliases if alias), key=len, reverse=True)


def _persona_looks_like_narrator(persona: PersonaConfig) -> bool:
    text = " ".join(
        [
            str(getattr(persona, "id", "") or ""),
            str(getattr(persona, "display_name", "") or ""),
            str(getattr(persona, "role", "") or ""),
            str(getattr(persona, "behavior_mode", "") or ""),
            " ".join(str(item or "") for item in list(getattr(persona, "tags", []) or [])),
        ]
    ).lower()
    return "narrator" in text


def _select_visual_sentence(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    sentences = [
        item.strip(" \t\r\n")
        for item in re.split(r"(?<=[.!?])\s+", value)
        if item.strip(" \t\r\n")
    ]
    if not sentences:
        return value
    return sentences[-1]


def _looks_like_continue(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return cleaned in {"continue", "go on", "keep going", "let the narrator continue", "continue the story", "next"}


def _join_compact(items: Any, count: int, limit: int) -> str:
    values = [_compact(item, limit) for item in list(items or []) if str(item or "").strip()]
    return "; ".join(values[-max(0, int(count or 0)):]) or "none"


def _compact(text: Any, limit: int = 1200) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    cut = value[: max(0, limit - 3)].rstrip(" \t\r\n,;:.-")
    boundary = cut.rfind(" ")
    if boundary >= max(24, int(limit * 0.55)):
        cut = cut[:boundary].rstrip(" \t\r\n,;:.-")
    return (cut + "...") if cut else value[:limit]
