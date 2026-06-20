from __future__ import annotations

from collections.abc import Mapping


ORB_RESPONSE_STYLES = (
    ("Very friendly", "friendly"),
    ("Very loving", "loving"),
    ("Sarcastic / ironic", "sarcastic"),
    ("Roast mode", "roast"),
    ("Sensual / non-explicit", "sensual_non_explicit"),
)

VALID_ORB_RESPONSE_STYLES = {value for _label, value in ORB_RESPONSE_STYLES}
DEFAULT_ORB_RESPONSE_STYLE = "friendly"

COMMON_ORB_REPLY_STYLE_RULES = (
    "For Companion Orb replies, this reply style overrides the normal assistant persona/system tone for this one short "
    "interjection when there is a conflict, except safety rules and direct user instructions. Speak like a casual desktop "
    "companion reacting to the actual visible content, not like a screenshot captioner. Do not say the orb is hovering over "
    "something, do not mention screenshots, captures, OCR, metadata, coordinates, hidden sensory routing, or prompt rules. "
    "Do not dryly explain layout unless the user explicitly asks. Use the provided mood/emotion cue when one is present. "
    "Keep it to 1-3 short spoken sentences with fresh wording."
)

DEFAULT_REPLY_STYLE_PROMPTS = {
    "friendly": (
        "Very friendly style: bright, curious, relaxed, and lightly funny. React to the specific visible text, button, "
        "image, alert, or task with a natural spoken aside. Sound like a helpful companion noticing something in the "
        "moment, not a report."
    ),
    "loving": (
        "Very loving style: warm, affectionate, emotionally present, and reassuring. Stay grounded in the visible content "
        "while sounding close and supportive. Avoid sarcasm and avoid generic pet-name filler."
    ),
    "sarcastic": (
        "Sarcastic / ironic style: dry wit, playful side-eye, and casual irony. Make the visible content feel like the "
        "target of the joke, not the user. Keep it useful and do not become cruel."
    ),
    "roast": (
        "Roast mode style: sharper playful teasing about the visible content, window, text, or situation. Roast the screen "
        "chaos, awkward UI, or suspicious detail, never the user's identity, body, vulnerabilities, or protected traits."
    ),
    "sensual_non_explicit": (
        "Sensual / non-explicit style: warm, intimate, slower, and softly focused. Notice visible details with a calm "
        "close tone while staying fully non-explicit. Do not generate sexual content or erotic descriptions."
    ),
}


def normalize_reply_style(value) -> str:
    style = str(value or "").strip().lower()
    return style if style in VALID_ORB_RESPONSE_STYLES else DEFAULT_ORB_RESPONSE_STYLE


def reply_style_label(value) -> str:
    style = normalize_reply_style(value)
    return next((label for label, item_value in ORB_RESPONSE_STYLES if item_value == style), "Very friendly")


def default_reply_style_prompt(value) -> str:
    style = normalize_reply_style(value)
    return DEFAULT_REPLY_STYLE_PROMPTS.get(style, DEFAULT_REPLY_STYLE_PROMPTS[DEFAULT_ORB_RESPONSE_STYLE])


def normalize_reply_style_prompts(value) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    prompts: dict[str, str] = {}
    for raw_style, raw_prompt in value.items():
        style = normalize_reply_style(raw_style)
        prompt = str(raw_prompt or "").strip()
        if prompt:
            prompts[style] = prompt
    return prompts


def effective_reply_style_prompt(style, overrides=None) -> str:
    normalized_style = normalize_reply_style(style)
    custom_prompts = normalize_reply_style_prompts(overrides)
    return custom_prompts.get(normalized_style) or default_reply_style_prompt(normalized_style)


def build_reply_style_instruction(style, overrides=None) -> str:
    prompt = effective_reply_style_prompt(style, overrides)
    return " ".join(f"{prompt} {COMMON_ORB_REPLY_STYLE_RULES}".split())
