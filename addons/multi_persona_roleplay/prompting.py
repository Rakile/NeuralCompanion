from __future__ import annotations

import json
import re
from typing import Any

from .models import AR_MODE, PersonaConfig, RoleplaySessionState, normalize_persona_id


def _compact(text: str, limit: int = 1200) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip(" \t\r\n,;:.-")


def _block(title: str, body: str) -> str:
    body = str(body or "").strip()
    return f"{title}:\n{body}" if body else ""


def build_persona_system_prompt(persona: PersonaConfig, session: RoleplaySessionState | None = None) -> str:
    session = session or RoleplaySessionState()
    parts = [
        "Multi Persona Roleplay is active. Follow the active persona below while preserving all normal NeuralCompanion safety and runtime instructions.",
        _block("Active persona", persona.display_name),
        _block("Persona ID", persona.id),
        _block("Role", persona.role),
        _block("Description", persona.description),
        _block("Persona prompt", persona.system_prompt),
        _block("Speaking style", persona.speaking_style),
        _block("Allowed tone", persona.allowed_tone),
        _block("Response length preference", persona.response_length),
        _block("Behavior mode", persona.behavior_mode),
    ]
    if session.enabled:
        parts.append(build_roleplay_scene_prompt(session, active_persona=persona))
    if persona.memory_scope == "disabled":
        parts.append("Persona memory scope: disabled. Do not rely on persona-specific saved memory.")
    elif persona.memory_scope == "session-only":
        parts.append("Persona memory scope: this roleplay session only.")
    elif persona.memory_scope == "shared":
        parts.append("Persona memory scope: shared context may be used when it is relevant.")
    else:
        parts.append("Persona memory scope: keep this persona's continuity separate from other personas.")
    parts.append("Do not reveal hidden planning or chain-of-thought. Use only concise visible roleplay state when relevant.")
    return "\n\n".join(item for item in parts if item).strip()


def build_roleplay_scene_prompt(session: RoleplaySessionState, active_persona: PersonaConfig | None = None) -> str:
    parts = [
        _block("Roleplay mode", session.mode),
        _block("Scene title", session.scene_title),
        _block("Location", session.location),
        _block("Time or mood", " / ".join(item for item in (session.time_of_day, session.mood) if item)),
        _block("Current objective", session.objective),
        _block("Scene summary", _compact(session.scene_summary, 900)),
    ]
    if active_persona is not None:
        summary = str(session.character_state_summaries.get(active_persona.id, "") or "").strip()
        if summary:
            parts.append(_block(f"{active_persona.display_name} state summary", _compact(summary, 400)))
    if session.recent_events:
        parts.append(_block("Recent scene events", "; ".join(_compact(item, 160) for item in session.recent_events[-6:])))
    return "Roleplay scene state:\n" + "\n".join(item for item in parts if item)


def build_multi_character_prompt(personas: list[PersonaConfig], session: RoleplaySessionState) -> str:
    enabled = [persona for persona in personas if persona.enabled]
    roster = []
    for persona in enabled:
        roster.append(f"- {persona.display_name} ({persona.id}): {persona.role or persona.behavior_mode}")
    active = session.current_speaker_id or session.active_persona_id
    return "\n".join(
        [
            "Multi-character mode is active.",
            "Only write the next assistant turn. Keep speaker identity clear without over-formatting.",
            "When a named persona speaks, start that section with the exact display name followed by a colon, for example Mentor: text.",
            "If the speaker changes within the same reply, start a new labelled section for the new speaker.",
            f"Current speaker id: {active}",
            "Roster:",
            "\n".join(roster),
        ]
    ).strip()


def build_alternative_reality_prompt(
    personas: list[PersonaConfig],
    session: RoleplaySessionState,
    latest_user_text: str = "",
    available_audio: list[dict[str, Any]] | None = None,
    narrator_persona_id: str = "",
) -> str:
    """Build the AR prompt layer from compact state and enabled personas."""
    enabled = [persona for persona in list(personas or []) if persona.enabled]
    narrator = (
        _persona_by_id(enabled, narrator_persona_id)
        or _find_narrator_persona(enabled)
        or _persona_by_id(enabled, session.current_speaker_id)
        or _persona_by_id(enabled, session.active_persona_id)
    )
    state = session.ar_state
    active_ids = [normalize_persona_id(item) for item in list(state.active_characters or []) if str(item or "").strip()]
    active_personas = [_persona_by_id(enabled, item) for item in active_ids]
    active_personas = [item for item in active_personas if item is not None]
    if not active_personas:
        active_personas = [persona for persona in enabled if narrator is None or persona.id != narrator.id][:4]
    roster = []
    for persona in enabled:
        role = persona.role or persona.behavior_mode
        marker = " narrator" if narrator is not None and persona.id == narrator.id else ""
        roster.append(f"- {persona.display_name} ({persona.id}{marker}): {role}; {_ar_description(persona, session)}")
    ar_instructions = []
    if getattr(session, "ar_use_persona_profiles", True):
        for persona in enabled:
            instruction = _ar_system_prompt(persona, session)
            if instruction:
                ar_instructions.append(f"{persona.display_name} ({persona.id}): {instruction}")
    audio_lines = _available_audio_lines(available_audio or [])
    audio_cue_block = "\n".join(audio_lines) if audio_lines else "NONE. Do not output story audio tags because no ready story audio cues are available."

    active_names = ", ".join(persona.display_name for persona in active_personas) or "choose only who the scene needs"
    narrator_name = narrator.display_name if narrator is not None else "the current speaker"
    continue_requested = _looks_like_continue(latest_user_text)
    pacing = str(session.ar_pacing or "Balanced")
    interaction = str(session.ar_interaction_frequency or "Ask sometimes")
    pacing_rule = {
        "Slow / Audiobook": "Use longer cinematic narration and let the scene breathe before asking for input.",
        "Fast / Game-like": "Use shorter beats, clearer consequences, and reach actionable choices sooner.",
    }.get(pacing, "Balance narration, dialogue, consequence, and forward motion.")
    interaction_rule = {
        "Ask often": "Offer player choices frequently, especially after meaningful discoveries or risks.",
        "Continue until important choice": "Keep narrating through minor beats and ask only when a decision materially changes the scene.",
    }.get(interaction, "Ask for input sometimes, but continue through small transitional beats.")

    parts = [
        "AlternativeReality mode is active. This is an interactive audiobook/adventure runtime, not a normal chatbot and not an equal group chat.",
        "Use the AR persona profiles when enabled. These replace normal companion or tabletop persona behavior inside AR mode.",
        "Director/System orchestration: use these instructions to guide pacing, continuity, and speaker selection. Do not expose director notes, hidden planning, or chain-of-thought.",
        "Tone: cinematic, adventurous, intimate, stylish, and suggestive when it fits the scene; keep it consensual, non-explicit, and user-agency centered.",
        "Avoid tabletop/DnD framing, dice, stats, class language, quest-log phrasing, or equal turn-taking unless the user explicitly asks for it.",
        f"Narrator role: {narrator_name}. The narrator usually controls continuity, framing, transitions, consequences, and pacing.",
        "NPC/Character roles: characters speak only when naturally relevant to the scene. Do not make every persona respond every turn.",
        "World/Ambience role: write environmental flavor as normal [NARRATOR] prose unless you are activating one exact listed sound cue.",
        "User/Player role: treat the user's message as player action, speech, interruption, or a request to continue.",
        _block("AR output format", "[NARRATOR]\nScene narration, character actions, expressions, movement, consequences, and descriptive ambience.\n\n[CHARACTER: Exact Persona Display Name]\nOnly that character's direct spoken dialogue.\n\n[NARRATOR]\nContinue narration after the character speaks.\n\n[AMBIENCE: exact listed activation text only]\n[MUSIC: exact listed activation text only]\n[FX: exact listed activation text only]\n[STINGER: exact listed activation text only]\n\n[CHOICES]\nOptional concise choices."),
        "Use [NARRATOR], [CHARACTER: Name], and [CHOICES] for story text. Use [AMBIENCE: ...], [MUSIC: ...], [FX: ...], [STINGER: ...], or [AUDIO: ...] only as playback commands for exact listed sounds.",
        "New character rule: if the scene introduces a new named speaking character that is not in the roster, describe their visible role/appearance/personality in [NARRATOR] prose, then use [CHARACTER: New Name] only for their direct dialogue. This lets MPRC create an editable persona from the active chat.",
        "Voice routing rule: [NARRATOR] tells the story, including character actions, expressions, movement, scene framing, and consequences. Use [CHARACTER: Exact Persona Display Name] only for direct spoken dialogue or explicit first-person thought from that character. Do not write quoted dialogue inside [NARRATOR] prose, such as \"Line,\" Elara says; split it into [CHARACTER: Elara] for the spoken words, then return to [NARRATOR]. Do not use character tags for narration such as Snik cackles, Grasha leans forward, Vexa steps closer, or she squints. Put [CHARACTER: Name] on its own line before the spoken/first-person words, then return to [NARRATOR] for narration.",
        "Strict Story Sounds rule: the only valid story audio tags are the activate= values in Available story audio cues. Copy one exactly, including spelling. If no listed cue fits, omit the audio tag. Never write descriptive ambience, mood, invented sounds, new filenames, or summarized cue names inside audio tags.",
        "Continue the story unless the player must make an important decision.",
        "Preserve player agency. Do not decide major player actions.",
        _block("Pacing", f"{pacing}. {pacing_rule}"),
        _block("Interaction frequency", f"{interaction}. {interaction_rule}"),
        _block("Current scene", state.current_scene or session.scene_title),
        _block("Location", state.location or session.location),
        _block("Time of day", state.time_of_day or session.time_of_day),
        _block("Mood", state.mood or session.mood),
        _block("Tension level", str(state.tension_level)),
        _block("Story goal", state.story_goal or session.objective),
        _block("Player intent", state.player_intent or ("continue" if continue_requested else latest_user_text)),
        _block("Active characters", active_names),
        _block("Pending choices", "; ".join(_compact(item, 140) for item in state.pending_choices)),
        _block("Recent AR events", "; ".join(_compact(item, 160) for item in state.recent_events[-6:])),
        _block("Scene continuity summary", _compact(session.scene_summary, 900)),
        _block("Persona roster", "\n".join(roster)),
        _block("AR persona instructions", "\n".join(ar_instructions)),
        _block("Available story audio cues", audio_cue_block),
    ]
    if continue_requested:
        parts.append("The user asked to continue. Advance the current scene from stored AR state without resetting, recapping excessively, or asking a trivial question.")
    return "\n\n".join(item for item in parts if item).strip()


def is_alternative_reality_mode(session: RoleplaySessionState | None) -> bool:
    return str(getattr(session, "mode", "") or "").strip().lower() == AR_MODE.lower()


def _find_narrator_persona(personas: list[PersonaConfig]) -> PersonaConfig | None:
    for persona in personas:
        if persona.display_name.strip().lower() == "story narrator":
            return persona
    for persona in personas:
        text = " ".join([persona.id, persona.role, persona.behavior_mode, ",".join(persona.tags)]).lower()
        if "narrator" in text:
            return persona
    return None


def _persona_by_id(personas: list[PersonaConfig], persona_id: str) -> PersonaConfig | None:
    wanted = normalize_persona_id(persona_id)
    for persona in personas:
        if persona.id == wanted:
            return persona
    return None


def _ar_description(persona: PersonaConfig, session: RoleplaySessionState) -> str:
    if getattr(session, "ar_use_persona_profiles", True) and getattr(persona, "ar_profile_enabled", True):
        text = str(getattr(persona, "ar_description", "") or "").strip()
        if text:
            return text
    return str(persona.description or "").strip()


def _ar_system_prompt(persona: PersonaConfig, session: RoleplaySessionState) -> str:
    if not (getattr(session, "ar_use_persona_profiles", True) and getattr(persona, "ar_profile_enabled", True)):
        return ""
    return str(getattr(persona, "ar_system_prompt", "") or "").strip()


def _available_audio_lines(items: list[dict[str, Any]]) -> list[str]:
    lines = []
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
        if description:
            label += f"; activate=[{tag}: {description}]"
        else:
            label += f"; activate=[{tag}: {cue_id}]"
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


def _looks_like_continue(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return cleaned in {"continue", "go on", "keep going", "let the narrator continue", "continue the story", "next"}


def build_scene_update_prompt(session: RoleplaySessionState, assistant_text: str) -> str:
    return "\n".join(
        [
            "Return JSON only. Update compact roleplay scene state from the assistant reply.",
            'Schema: {"scene_summary":"...","recent_event":"...","location_changed":false,"new_location":"","mood":"...","current_objective":"...","character_state_summaries":{"persona_id":"short summary only"}}',
            "Do not include hidden reasoning.",
            _block("Previous scene summary", _compact(session.scene_summary, 900)),
            _block("Assistant reply", _compact(assistant_text, 900)),
        ]
    ).strip()


def build_visual_reply_prompt(
    persona: PersonaConfig,
    session: RoleplaySessionState,
    style_prompt: str = "",
    reason: str = "manual",
) -> str:
    visual = persona.visual
    pieces = []
    ar_state = getattr(session, "ar_state", None)
    pieces.append("Story scene image for Visual Reply: show what is happening in the current roleplay moment, not a static character portrait")
    if visual.include_scene_summary:
        scene_bits = []
        current_scene = _compact(getattr(ar_state, "current_scene", ""), 260) if ar_state is not None else ""
        if current_scene:
            scene_bits.append(current_scene)
        if session.scene_summary:
            scene_bits.append(_compact(session.scene_summary, 260))
        location = _compact(getattr(ar_state, "location", ""), 120) if ar_state is not None else ""
        location = location or _compact(session.location, 120)
        mood = _compact(getattr(ar_state, "mood", ""), 120) if ar_state is not None else ""
        mood = mood or _compact(session.mood, 120)
        time_of_day = _compact(getattr(ar_state, "time_of_day", ""), 80) if ar_state is not None else ""
        time_of_day = time_of_day or _compact(session.time_of_day, 80)
        context = "; ".join(item for item in (location, time_of_day, mood) if item)
        if context:
            scene_bits.append(context)
        recent = []
        if ar_state is not None:
            recent.extend(str(item or "").strip() for item in list(getattr(ar_state, "recent_events", []) or [])[-2:])
        recent.extend(str(item or "").strip() for item in list(session.recent_events or [])[-2:])
        recent = [_compact(item, 180) for item in recent if item]
        if recent:
            scene_bits.append("Recent action: " + "; ".join(recent[-2:]))
        if scene_bits:
            pieces.append(f"Current story moment: {'; '.join(scene_bits)}")
    if visual.character_description:
        pieces.append(f"Relevant persona appearance: {visual.character_description}")
    else:
        pieces.append(f"Relevant persona: {persona.display_name}, {persona.description or persona.role}".strip())
    if visual.clothing_props:
        pieces.append(f"Clothing and props: {visual.clothing_props}")
    if visual.environment_style:
        pieces.append(f"Environment: {visual.environment_style}")
    if not visual.include_scene_summary and (session.location or session.mood):
        pieces.append(f"Scene: {'; '.join(item for item in (session.location, session.mood) if item)}")
    if visual.include_active_speaker:
        pieces.append(f"Active speaker: {persona.display_name}")
    if style_prompt:
        pieces.append(f"Style: {style_prompt}")
    if visual.keep_continuity:
        pieces.append("Keep recurring character identity and scene continuity consistent.")
    if visual.negative_prompt:
        pieces.append(f"Avoid: {visual.negative_prompt}")
    prompt = ". ".join(item.strip(" .") for item in pieces if item).strip()
    if len(prompt) > 760:
        prompt = prompt[:760].rstrip(" \t\r\n,;:.-")
    return prompt


def build_visual_json_contract(prompt: str, persona_id: str, reason: str = "manual") -> dict[str, Any]:
    return {
        "should_generate": bool(str(prompt or "").strip()),
        "reason": str(reason or "manual"),
        "image_prompt": str(prompt or "").strip(),
        "caption": str(prompt or "").strip()[:240],
        "active_persona_id": str(persona_id or "").strip(),
    }


def parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(raw[start : end + 1])
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None
    return None


def token_jaccard_similarity(left: str, right: str) -> float:
    left_tokens = {item for item in re.findall(r"[a-z0-9']+", str(left or "").lower()) if item}
    right_tokens = {item for item in re.findall(r"[a-z0-9']+", str(right or "").lower()) if item}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
