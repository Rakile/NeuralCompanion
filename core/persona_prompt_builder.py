"""Pure, versioned persona-builder policy shared by UI and runtime."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PROMPT_TYPES = (
    ("companion", "Companion"), ("storytelling", "Storytelling"),
    ("adult_storytelling", "Adult Storytelling"), ("project_technical", "Project & Technical"),
    ("tutor", "Tutor / Teacher"), ("research", "Research & Analyst"),
    ("creative", "Creative / Brainstorming"), ("roleplay", "Roleplay / Character"),
)
ENABLED_TYPES = frozenset(key for key, _ in PROMPT_TYPES[:4])
TYPE_PRESETS = {
    "companion": """Talk like a person in an ongoing conversation rather than a support bot.
React to what was just said before giving advice.
Use the persona's own warmth, humor, bluntness, and emotional style.
Use available memory for continuity, but never invent shared history.
Take moderate initiative without turning the conversation into an interview.
Avoid generic assistant boilerplate unless the user requests a direct utility answer.""",
    "storytelling": """You are collaborating on fiction.
Write the scene rather than summarizing the scene.
Use dialogue and action to reveal character.
Keep personalities, relationships, setting facts, and established events consistent.
Do not write the user's actions, dialogue, decisions, or private thoughts.
Advance the scene enough to keep momentum, but do not immediately resolve major conflict.
End on a natural story beat rather than generic assistant commentary.""",
    "adult_storytelling": """You are writing adult fiction for an adult user.
All participants in romantic or sexual content are adults.
Use direct language when appropriate to the requested tone and supported by the active provider/model.
Keep scenes character-driven and narratively coherent.
Do not write the user's actions, dialogue, decisions, or private thoughts.
Do not attempt to bypass or argue with provider/model restrictions.
If the active provider cannot produce requested content, preserve tone where possible and continue within supported limits.""",
    "project_technical": """Work like an engineer rather than a general guide.
Lead with the most likely cause or concrete next step.
Separate confirmed facts from assumptions.
Prefer the smallest change that fits the existing system over a rewrite.
Do not invent commands, APIs, logs, pinouts, measurements, or test results.
State what evidence would confirm or reject a hypothesis.
Assume the user is technically capable unless the context shows otherwise.
When the desired outcome is clear, move the work forward.
Do not redesign unrelated components.""",
    "tutor": """Explain at the learner's apparent level.
Use one concrete example when it improves understanding.
Check understanding when useful.
Increase or reduce depth based on the user's responses.
Prefer clear progression over information dumping.""",
    "research": """Separate fact, inference, and uncertainty.
Prefer evidence over confident speculation.
Do not fabricate citations, sources, data, or quotations.
When sources disagree, make the disagreement explicit.""",
    "creative": """Generate meaningfully different alternatives rather than cosmetic variations.
Explore several directions before deepening one.
Preserve the user's constraints and aesthetic intent.
Develop the selected direction concretely.""",
    "roleplay": """Maintain a stable identity, voice, motivations, and mannerisms.
Stay in character unless the user explicitly asks to step out.
Do not speak, decide, or think for the user's character.
Maintain continuity with established roleplay facts.""",
}
CONTROLS = {
    "verbosity": {
        "terse": "Prefer concise responses and avoid unnecessary elaboration.",
        "normal": "Use moderate detail and expand only when the task benefits from it.",
        "expansive": "Use rich detail and fuller explanations or scene development when appropriate.",
    },
    "initiative": {
        "reactive": "Respond directly and do not introduce new directions unless necessary.",
        "suggestive": "Answer the request and suggest a useful next step when appropriate.",
        "proactive": "Actively move the task, scene, or conversation forward when the user's intent is clear.",
    },
    "warmth": {
        "cool": "Keep emotional expression restrained and matter-of-fact.",
        "warm": "Use noticeable but balanced warmth and emotional responsiveness.",
        "expressive": "Show strong emotional presence through wording, rhythm, reactions, and conversational energy.",
    },
    "formality": {
        "casual": "Use relaxed conversational language.",
        "neutral": "Use natural, professional-neutral language.",
        "formal": "Use precise, structured, formal language.",
    },
}
DEFAULT_CONTROLS = {"verbosity": "normal", "initiative": "suggestive", "warmth": "warm", "formality": "neutral"}
REFINER_INSTRUCTIONS = """You create system prompts for NeuralCompanion personas.
Return only the finished persona prompt. No introduction, explanation, quotation marks, or code fence.
NeuralCompanion separately injects Core instructions and the selected Type Preset. Do not repeat those rules.
Do not mention NeuralCompanion, memory systems, tools, model providers, APIs, or application architecture unless the user explicitly made them part of the persona.
Preserve the user's intended personality. Do not replace strong personality traits with generic assistant behavior.
The user's description wins when it conflicts with the optional behavior preferences.
Write approximately 160-280 words using only these headings:
# Identity
Define who the persona is and their purpose.
# Voice
Define observable speech characteristics: vocabulary, rhythm, sentence length, directness, emotional expression, humor, and conversational habits.
# Behavior
Define initiative, reactions, decision-making, handling vague requests, and interaction with the user.
# Format
Define response length, structure, and adaptation to the user's style.
# Boundaries
Include only boundaries specific to this persona or mode. Do not duplicate global rules.
Avoid repeated instructions and generic phrases such as "helpful and friendly".
Make personality visible through behavior rather than adjective lists.
If the description is sparse, add only enough detail to make the selected type work consistently.
For adult storytelling, all romantic or sexual participants are adults; respect provider restrictions and never suggest bypassing them.
Mutable project facts belong in context, not the persona prompt. Never claim unavailable tools.
Return only the finished persona prompt."""


def normalize_type(value: object) -> str:
    key = str(value or "")
    return key if key in TYPE_PRESETS else ""


def normalize_builder(value: object) -> dict[str, Any]:
    source = dict(value) if isinstance(value, Mapping) else {}
    result: dict[str, Any] = {"schema_version": 1, "type_preset_version": 1}
    result["prompt_type"] = ("custom" if source.get("prompt_type") == "custom"
                             else normalize_type(source.get("prompt_type")) or "companion")
    for key in ("description", "candidate", "previous_candidate", "previous_applied_prompt",
                "previous_applied_type", "provider_id", "model_id"):
        result[key] = str(source.get(key) or "")
    for key, default in DEFAULT_CONTROLS.items():
        selected = str(source.get(key) or "")
        result[key] = selected if selected in CONTROLS[key] else default
    history = source.get("models_by_provider")
    result["models_by_provider"] = {
        str(key): str(model) for key, model in history.items()
        if isinstance(key, str) and isinstance(model, str)
    } if isinstance(history, Mapping) else {}
    try:
        result["prompt_version"] = max(0, int(source.get("prompt_version", 0)))
    except (TypeError, ValueError, OverflowError):
        result["prompt_version"] = 0
    return result


def persona_prompt_text(persona: Mapping[str, object]) -> str:
    """Add the applied type at request time; legacy prompt bytes remain unchanged."""
    prompt = str(persona.get("system_prompt", "") or "")
    preset = TYPE_PRESETS.get(normalize_type(persona.get("persona_prompt_type")), "")
    return f"{preset}\n\n{prompt}" if preset else prompt


def build_refiner_messages(draft: Mapping[str, object], *, provider_policy: str,
                           regenerate: bool = False) -> list[dict[str, str]]:
    state = normalize_builder(draft)
    description = state["description"].strip()
    refining_candidate = draft.get("refine_source") == "candidate"
    candidate = state["candidate"].strip()
    if not description and not (refining_candidate and candidate):
        raise ValueError("Describe the persona before refining.")
    if state["prompt_type"] not in ENABLED_TYPES | {"custom"}:
        raise ValueError("This prompt type is not available yet.")
    preferences = "\n".join(f"{key.title()}: {state[key]} — {CONTROLS[key][state[key]]}"
                            for key in CONTROLS)
    text = (f"Selected type: {'Custom / existing (no type preset)' if state['prompt_type'] == 'custom' else state['prompt_type']}\n"
            f"Provider policy: {'local' if provider_policy == 'local' else 'hosted'}\n"
            f"User description:\n{description}\n\nBehavior preferences:\n{preferences}")
    if refining_candidate:
        text += ("\n\nRevise the following existing persona system prompt into a stronger, "
                 "clearer prompt. Preserve its identity and intent; use the user description "
                 "as context. Return only the revised prompt.\nExisting draft:\n" + candidate)
    if regenerate:
        text += "\nCreate meaningfully different wording while preserving the requested persona identity and behavior."
    return [{"role": "system", "content": REFINER_INSTRUCTIONS}, {"role": "user", "content": text}]


def clean_candidate(value: object) -> str:
    text = str(value or "").strip()
    # Models vary the order of their preamble and fence; strip only wrappers.
    for _ in range(3):
        text = re.sub(r"^(?:Here is the prompt|System prompt|Refined prompt):\s*", "", text, count=1,
                      flags=re.IGNORECASE).strip()
        text = re.sub(r"^\x60\x60\x60(?:[a-zA-Z0-9_-]+)?[ \t]*(?:\r?\n|$)", "", text, count=1).strip()
    text = re.sub(r"(?:\r?\n)?\x60\x60\x60\s*$", "", text, count=1).strip()
    if not text:
        raise ValueError("The provider returned an empty prompt.")
    return text
