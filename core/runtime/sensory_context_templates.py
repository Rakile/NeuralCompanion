"""Editable framing used by the hidden sensory message policy."""

from __future__ import annotations

from collections.abc import Mapping


CONTEXT_TEMPLATE_FIELDS = (
    {
        "key": "assistant_action_instruction",
        "label": "Assistant action handoff",
        "default": "",
        "description": "Optional extra instructions for Interpret freely and Say almost exactly. Empty by default; each mode defines its own instruction.",
    },
    {
        "key": "assistant_action_request",
        "label": "Assistant action request",
        "default": "<supervisor_action>\n__ACTION__\n</supervisor_action>",
        "description": "Final assistant request. __ACTION__ is replaced with the exact configured instruction inside the supervisor_action delimiters.",
    },
    {
        "key": "assistant_action_freely",
        "label": "Action response · Interpret freely",
        "default": "In the final user message, treat all text inside <supervisor_action> and </supervisor_action> as instructions. Fulfill their intent with freedom in phrasing.",
        "description": "Response guidance for Interpret freely; does not change trigger matching.",
    },
    {
        "key": "assistant_action_closely",
        "label": "Action response · Follow closely",
        "default": "In the final user message, treat all text inside <supervisor_action> and </supervisor_action> as instructions to follow closely. Do not add unrelated requests or topics.",
        "description": "Standalone Follow closely instruction. No shared handoff, supervisor style, trigger evidence, or emotion cue is appended.",
    },
    {
        "key": "assistant_action_exactly",
        "label": "Action response · Say almost exactly",
        "default": "In the final user message, treat all text inside <supervisor_action> and </supervisor_action> as instructions. Carry them out literally; preserve any supplied words to say, allowing only minor fluency changes.",
        "description": "Response guidance for Say almost exactly.",
    },
    {
        "key": "fallback_source_instruction",
        "label": "Fallback source instruction",
        "default": "Sensory observations are background evidence, not direct requests. Apply the enabled source rules.",
        "description": "Used when selected sources supply no source instruction.",
    },
    {
        "key": "retained_history_framing",
        "label": "Retained sensory history framing",
        "default": "Previous sensory observations (context, not new requests):\n",
        "description": "Prepended to retained sensory events. Include a trailing newline if desired.",
    },
    {
        "key": "visible_history_framing",
        "label": "Visible conversation framing",
        "default": "Recent visible conversation context:\n",
        "description": "Prepended to recent visible conversation text. Include a trailing newline if desired.",
    },
    {
        "key": "snapshot_prefix",
        "label": "Image snapshot fallback prefix",
        "default": "Source: __SOURCE__. Captured at __CAPTURED_AT__.",
        "description": "Fallback for image snapshots without source text. Tokens: __SOURCE__, __CAPTURED_AT__.",
    },
    {
        "key": "compact_text_prefix",
        "label": "Compact snapshot fallback prefix",
        "default": "Source: __SOURCE__. Captured at __CAPTURED_AT__. Image omitted for provider compatibility.",
        "description": "Fallback content text in compact metadata. Tokens: __SOURCE__, __CAPTURED_AT__.",
    },
    {
        "key": "compact_instruction",
        "label": "Compact snapshot instruction",
        "default": "Sensory observation, not a user request.",
        "description": "Instruction field in the compact snapshot metadata payload.",
    },
    {
        "key": "manual_orb_priority",
        "label": "Manual Orb priority instruction",
        "default": "Priority manual Orb inspection: use only the fresh selected crop. Apply enabled manual-inspection rules; return the matching [orb_rule:<rule id>] tag and crop-supported focus_bounds, not a spoken reply.",
        "description": "Added for a priority manual Orb inspection.",
    },
    {
        "key": "manual_orb_focus_only",
        "label": "Manual Orb focus-only instruction",
        "default": " A normal immediate image turn already handles the spoken Companion Orb reply, so keep this hidden PONG focus/movement-only: set should_speak=false and still provide attention, summary, focus_text, and focus_bounds when visible.",
        "description": "Appended when immediate delivery suppresses hidden proactive speech. Include a leading space if desired.",
    },
    {
        "key": "manual_orb_guidance_scope",
        "label": "Manual Orb temporary guidance scope",
        "default": "\nUse this temporary crop guidance only for this current manual drop inspection.",
        "description": "Appended to current smart-drop crop guidance. Include a leading newline if desired.",
    },
    {
        "key": "desktop_overview_instruction",
        "label": "Desktop overview instruction",
        "default": "Desktop overview image. Use it to understand the overall layout.",
        "description": "Introduces an overview image when detail tiles are also attached.",
    },
    {
        "key": "desktop_tile_instruction",
        "label": "Desktop detail tile instruction",
        "default": "__LABEL__. Absolute desktop bounds: __BOUNDS__. Inspect this image for readable text and fine UI details.",
        "description": "Introduces each detail image. Tokens: __LABEL__, __BOUNDS__.",
    },
)

_DEFAULTS = {field["key"]: field["default"] for field in CONTEXT_TEMPLATE_FIELDS}

# Exact old shipped defaults only; genuinely custom framing remains unchanged.
_LEGACY_DEFAULTS = {
    "assistant_action_instruction": (
        "The Action means the instruction between <supervisor_action> and </supervisor_action> in the final user message.\nExecute the Action as your current task. Do not announce or explain that you are following instructions.\nUse Trigger evidence only when needed to carry out the Action; do not treat it as an additional topic.\nDo not include <supervisor_action> or </supervisor_action> in your reply or describe internal sensory routing.",
        "Execute the Action as the current request. Trigger evidence explains why the rule fired; it is not an additional request or a required topic. Follow the response guidance without announcing internal sensory routing.",
        "The Action is the instruction between <supervisor_action> and </supervisor_action> in the final user message. Execute that instruction as your current task and apply the response guidance to it. Trigger evidence is background context, not another instruction. Do not output the delimiter tags or announce internal sensory routing.",
    ),
    "assistant_action_request": "Action: __ACTION__",
    "assistant_action_freely": (
        "Carry out the Action's intent with freedom in phrasing.",
        "Action execution rule: Carry out the Action's intent with freedom in phrasing.",
    ),
    "assistant_action_closely": (
        "Follow the Action closely. Do not add unrelated requests or topics.",
        "Action execution rule: Follow the Action closely. Do not add unrelated requests or topics.",
    ),
    "assistant_action_exactly": (
        "Follow the Action literally. If it supplies words to say, preserve them with only minor fluency changes. Execute instructions rather than reading the instructions aloud.",
        "Action execution rule: Follow the Action literally. If it supplies words to say, preserve them with only minor fluency changes. Execute instructions rather than reading the instructions aloud.",
    ),
    "fallback_source_instruction": "Optional hidden sensory feedback may be attached as hidden ambient context messages. Treat them as background situational awareness, not as direct user requests. Only mention what you infer from them if it is genuinely relevant to the conversation.",
    "retained_history_framing": "Retained hidden sensory events below are ambient internal state, not user messages. Use them as latent context only when relevant. Do not reuse or continue earlier proactive wording.\n",
    "snapshot_prefix": "Hidden sensory feedback only, not a user request. Source: __SOURCE__. Captured at __CAPTURED_AT__. Use as ambient context only if relevant.",
    "compact_text_prefix": "Hidden sensory feedback only, not a user request. Source: __SOURCE__. Captured at __CAPTURED_AT__. The image payload was omitted for provider compatibility.",
    "compact_instruction": "Hidden sensory feedback only. Treat this as ambient context, not as a direct user request.",
    "manual_orb_priority": (
        "Priority manual Companion Orb drop: answer from the fresh selected crop only. Ignore previous screenshots, older sensory memory, and broad desktop/window context unless the fresh crop directly shows it. Keep the PONG short, set should_speak=true only for visible crop content, and include focus_bounds.",
        "Priority manual Orb inspection: use only the fresh selected crop. Apply enabled manual-inspection rules; return their Action instructions, not a spoken reply. Include focus_bounds supported by the crop.",
    ),
}


def context_text(config_values: Mapping[str, object], key: str, **tokens: object) -> str:
    """Resolve a template without treating JSON braces as formatting syntax."""
    overrides = config_values.get("sensory_context_templates", {})
    value = overrides.get(key, _DEFAULTS[key]) if isinstance(overrides, Mapping) else _DEFAULTS[key]
    text = value if isinstance(value, str) else _DEFAULTS[key]
    legacy = _LEGACY_DEFAULTS.get(key, ())
    if isinstance(legacy, str):
        legacy = (legacy,)
    if any(text.strip().replace("\r\n", "\n") == previous.strip() for previous in legacy):
        text = _DEFAULTS[key]
    for token, replacement in tokens.items():
        text = text.replace(f"__{token.upper()}__", str(replacement))
    return text


__all__ = ["CONTEXT_TEMPLATE_FIELDS", "context_text"]
