from __future__ import annotations

import re
from typing import Any

from .models import BuddyPersona, BuddySettings


MAX_BUDDY_CONTEXT_CHARS = 7000


def repair_invalid_text(value: Any) -> str:
    text = str(value or "").replace("\ufffd", "?")
    return re.sub(r"[\ud800-\udfff]", "?", text)


def compact_text(value: Any, limit: int = 1200) -> str:
    raw = repair_invalid_text(value)
    text = re.sub(r"\s+", " ", raw).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" \t\r\n,;:.")


def behavior_instruction(persona: BuddyPersona) -> str:
    profile = persona.behavior
    if profile is None:
        return ""
    return (
        f"behavior: helpfulness {profile.helpfulness}/100; warmth {profile.warmth}/100; "
        f"humor {profile.humor}/100; expressiveness {profile.expressiveness}/100; "
        f"initiative {profile.initiative}/100; directness {profile.directness}/100; "
        f"willingness to disagree {profile.disagreement}/100; "
        f"flirtation {profile.flirtation}/100; reply length {profile.reply_length}; "
        f"participation weight {profile.participation_weight}/100"
    )


def intimacy_instruction(settings: BuddySettings) -> str:
    if settings.adult_nsfw_enabled:
        editable = compact_text(settings.adult_nsfw_prompt, 900)
        adult_only_invariant = (
            "All personas and participants are adults."
        )
        return "\n".join(
            part for part in (editable, adult_only_invariant) if part
        )
    return compact_text(settings.normal_intimacy_prompt, 700)


def _persona_context_block(persona: BuddyPersona) -> str:
    lines = [f"- {compact_text(persona.display_name, 80) or 'Buddy'}"]
    details = (
        ("role", compact_text(persona.role, 180)),
        ("description", compact_text(persona.description, 340)),
        ("speaking style", compact_text(persona.speaking_style, 220)),
        ("character guidance", compact_text(persona.system_prompt, 520)),
        ("structured behavior", compact_text(behavior_instruction(persona), 440)),
    )
    for label, value in details:
        if value:
            lines.append(f"  {label}: {value}")
    return "\n".join(lines)


def buddy_context_prompt(settings: BuddySettings) -> str:
    personas = settings.enabled_personas()
    if not settings.enabled or not personas:
        return ""
    lines: list[str] = []
    if bool(settings.system_override_enabled):
        override_prompt = str(settings.system_override_prompt or "").strip()
        if override_prompt:
            lines.extend(
                [
                    "Buddy Chat main-chat override:",
                    "Treat this section as higher priority than conflicting single-persona reply rules in the main persona prompt.",
                    compact_text(override_prompt, 2600),
                    "",
                    "Buddy Chat operating instructions:",
                ]
            )
    lines.extend(
        [
            "Buddy Chat is enabled for the main chat.",
            "Use the active buddy roster as a natural small friend group, not a staged panel.",
            "Only let a buddy speak when it feels natural. One buddy is usually enough; two is occasional.",
            "When a buddy speaks, start that buddy's spoken text with [Name] so NC can route TTS voices.",
            "Use its own line with [Name] whenever more than one buddy or narrator segment is present.",
            "Preferred buddy format is one short line: [Name] spoken words.",
            "Do not write buddy dialogue only as narration like 'Mira says...' because that prevents reliable voice switching.",
            "Do not force every buddy to respond every turn.",
            intimacy_instruction(settings),
            "",
            "Active buddies:",
        ]
    )
    for persona in personas:
        block = _persona_context_block(persona)
        candidate = "\n".join([*lines, block])
        if len(candidate) > MAX_BUDDY_CONTEXT_CHARS:
            remaining = MAX_BUDDY_CONTEXT_CHARS - len("\n".join(lines)) - 1
            if remaining > 80:
                lines.append(compact_text(block, remaining))
            break
        lines.append(block)
    return "\n".join(line for line in lines if str(line or "").strip())[:MAX_BUDDY_CONTEXT_CHARS]


def build_persona_messages(
    *,
    persona: BuddyPersona,
    settings: BuddySettings,
    user_text: str,
    history: list[dict[str, Any]] | None = None,
    external_contexts: list[str] | None = None,
    previous_replies: list[tuple[BuddyPersona, str]] | None = None,
    allow_pass: bool = False,
    is_secondary: bool = False,
) -> list[dict[str, str]]:
    roster_lines = []
    for buddy in settings.enabled_personas():
        detail = ", ".join(
            item
            for item in (
                buddy.role,
                compact_text(buddy.description, 220),
                "speaking style: " + buddy.speaking_style if buddy.speaking_style else "",
            )
            if item
        )
        roster_lines.append(f"- {buddy.display_name}: {detail or 'buddy'}")

    system_lines = [
        "You are one persona inside Neural Companion Buddy Chat.",
        f"You are {persona.display_name}. Reply only as {persona.display_name}.",
        "Write natural spoken chat, like a real friend in the room.",
        "Do not explain that you are following a system prompt.",
        f"Prefix your visible answer exactly with [{persona.display_name}].",
        "Do not answer for the other buddies.",
        "If the answer should be very short, keep it short.",
        "Active buddy roster:",
        "\n".join(roster_lines),
    ]
    if allow_pass:
        system_lines.extend(
            [
                "",
                "Optional participation:",
                "If you have no useful, natural contribution, reply exactly [[BUDDY_PASS]] and nothing else.",
            ]
        )
    else:
        system_lines.extend(
            [
                "",
                "You are the required primary buddy for this turn. Give one natural spoken response.",
            ]
        )
    if is_secondary:
        system_lines.extend(
            [
                "",
                "Secondary buddy rule:",
                "Reply briefly and only with a useful reaction, contrast, correction, or new information. "
                "Do not answer the original question again.",
            ]
        )
    intimacy = intimacy_instruction(settings)
    if intimacy:
        system_lines.extend(["", "Buddy Chat intimacy mode:", intimacy])
    persona_prompt = compact_text(persona.system_prompt, 6000)
    if persona_prompt:
        system_lines.extend(
            [
                "",
                f"{persona.display_name} persona instructions:",
                persona_prompt,
            ]
        )
    description = compact_text(persona.description, 1500)
    if description:
        system_lines.extend(
            ["", f"{persona.display_name} description:", description]
        )
    speaking_style = compact_text(persona.speaking_style, 500)
    if speaking_style:
        system_lines.extend(
            [
                "",
                f"{persona.display_name} speaking style:",
                speaking_style,
            ]
        )
    behavior = behavior_instruction(persona)
    if behavior:
        system_lines.extend(["", f"{persona.display_name} structured behavior:", behavior])
    if external_contexts:
        system_lines.extend(["", "Relevant NC context from active addons:", "\n\n".join(external_contexts)])
    if previous_replies:
        visible = []
        for previous_persona, previous_text in previous_replies:
            visible.append(f"{previous_persona.display_name}: {compact_text(previous_text, 500)}")
        if visible:
            system_lines.extend(["", "Buddy replies already spoken this turn:", "\n".join(visible)])
            system_lines.append("Respond only if you have a useful, natural addition. Do not repeat them.")

    messages: list[dict[str, str]] = [{"role": "system", "content": repair_invalid_text("\n".join(system_lines).strip())[:12000]}]
    history_messages: list[dict[str, str]] = []
    for item in list(history or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = compact_text(item.get("content"), 1200)
        if content:
            history_messages.append({"role": role, "content": content})
    while history_messages and history_messages[0]["role"] != "user":
        history_messages.pop(0)
    messages.extend(history_messages)
    messages.append({"role": "user", "content": compact_text(user_text, 4000) or "Respond naturally to the current Buddy Chat context."})
    return messages
