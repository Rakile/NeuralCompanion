from __future__ import annotations

from typing import Any

from addons.audio_story_mode.story_memory import NEEDS_CLARIFICATION


def _clean(text: str, limit: int = 420) -> str:
    value = " ".join(str(text or "").split()).strip()
    return value[:limit].rstrip(" \t\r\n,;:.-")


def _entry_identity(entry: dict[str, Any]) -> str:
    display = _clean(entry.get("display_name", ""), 80)
    parts = []
    for label, key in (
        ("identity", "visual_identity"),
        ("face", "face"),
        ("hair", "hair"),
        ("eyes", "eyes"),
        ("body", "body"),
        ("clothing", "clothing"),
        ("unique marks", "unique_markers"),
    ):
        value = _clean(entry.get(key, ""), 180)
        if value:
            parts.append(f"{label}: {value}")
    if not parts:
        parts.append(f"identity: {NEEDS_CLARIFICATION}")
    locked = "; ".join(parts)
    return f"{display}: {locked}" if display else locked


def build_grok_story_bible_prompt(
    *,
    current_scene: dict[str, Any],
    memory: dict[str, Any],
    selected_characters: list[str] | None = None,
    selected_location: str = "",
    style_settings: dict[str, Any] | None = None,
    character_reference_image_path: str = "",
    location_reference_image_path: str = "",
    include_reference_images: bool = False,
) -> str:
    memory = memory if isinstance(memory, dict) else {}
    style_settings = style_settings if isinstance(style_settings, dict) else {}
    characters = memory.get("characters", {}) if isinstance(memory.get("characters"), dict) else {}
    locations = memory.get("locations", {}) if isinstance(memory.get("locations"), dict) else {}
    style = memory.get("style", {}) if isinstance(memory.get("style"), dict) else {}
    selected_characters = list(selected_characters or current_scene.get("character_keys") or [])
    selected_location = str(selected_location or current_scene.get("location_key") or "").strip()

    character_blocks = []
    unknown_details = []
    for key in selected_characters:
        entry = characters.get(str(key), {}) if isinstance(characters, dict) else {}
        if not entry:
            unknown_details.append(f"{key}: {NEEDS_CLARIFICATION}")
            continue
        character_blocks.append(_entry_identity(entry))
        if NEEDS_CLARIFICATION.lower() in _entry_identity(entry).lower():
            unknown_details.append(f"{entry.get('display_name') or key}: {NEEDS_CLARIFICATION}")
    if not character_blocks:
        character_blocks.append(f"No locked recurring character identity yet; {NEEDS_CLARIFICATION}.")

    location_text = ""
    if selected_location and selected_location in locations:
        loc = locations.get(selected_location, {})
        details = [
            _clean(loc.get("display_name", ""), 80),
            _clean(loc.get("visual_description", ""), 220),
            _clean(loc.get("mood", ""), 80),
            ", ".join(_clean(item, 80) for item in loc.get("recurring_details", []) if str(item or "").strip()),
        ]
        location_text = "; ".join(part for part in details if part)
    if not location_text:
        location_text = NEEDS_CLARIFICATION
        unknown_details.append(f"location: {NEEDS_CLARIFICATION}")

    style_parts = [
        _clean(style_settings.get("style_suffix", ""), 180),
        _clean(style.get("global_visual_style", ""), 180),
        _clean(style.get("color_palette", ""), 120),
    ]
    style_text = "; ".join(part for part in style_parts if part) or NEEDS_CLARIFICATION
    camera = _clean(style_settings.get("camera") or style.get("camera_language") or current_scene.get("camera") or "cinematic medium shot", 120)
    scene_summary = _clean(current_scene.get("summary") or current_scene.get("text") or "", 320) or NEEDS_CLARIFICATION

    reference_rules = ""
    if include_reference_images:
        refs = []
        if character_reference_image_path:
            refs.append("preserve character reference image identity")
        if location_reference_image_path:
            refs.append("preserve location reference image layout")
        reference_rules = "; ".join(refs)

    sections = [
        "CHARACTER LOCK:\n" + "\n".join(character_blocks),
        "SCENE:\n" + scene_summary,
        "LOCATION:\n" + location_text,
        "STYLE:\n" + style_text,
        "CAMERA:\n" + camera,
        (
            "STRICT CONSISTENCY:\n"
            "Preserve the same face, age, hairstyle, body type, clothing language, unique marks, and color palette for recurring characters. "
            "Do not redesign known characters."
        ),
        "UNKNOWN DETAILS:\n" + ("; ".join(unknown_details) if unknown_details else "No missing locked details noted."),
    ]
    if reference_rules:
        sections.append("REFERENCE HOOKS:\n" + reference_rules)
    prompt = "\n\n".join(section.strip() for section in sections if section.strip()).strip()
    return prompt[:1800].rstrip(" \t\r\n,;:.-")
