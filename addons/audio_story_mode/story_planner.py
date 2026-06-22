from __future__ import annotations


def _text(value, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _truncate(value, limit: int = 180) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= int(limit):
        return text
    return text[: int(limit)].rstrip(" ,;:.-") + "..."


def _character_label(character_id: str, story_bible: dict) -> str:
    entry = dict((dict(story_bible.get("characters", {}) or {}).get(character_id) or {}))
    return _text(entry.get("label") or entry.get("display_name") or character_id, character_id)


def build_scene_review(scene_entry: dict, story_bible: dict | None = None, image_entry: dict | None = None) -> dict:
    """Build user-facing scene review fields for the Audio Story UI."""

    scene_entry = dict(scene_entry or {})
    story_bible = dict(story_bible or {})
    image_entry = dict(image_entry or {})
    try:
        scene_number = int(scene_entry.get("scene_index", 0) or 0) + 1
    except Exception:
        scene_number = 1
    character_ids = [str(item or "").strip() for item in list(scene_entry.get("active_character_ids", []) or []) if str(item or "").strip()]
    characters = ", ".join(_character_label(item, story_bible) for item in character_ids)
    beat = _text(
        scene_entry.get("scene_summary")
        or scene_entry.get("summary")
        or scene_entry.get("key_action")
        or scene_entry.get("text"),
        "No scene beat selected yet.",
    )
    prompt = _text(scene_entry.get("prompt") or image_entry.get("prompt_text"), "")
    image_path = _text(image_entry.get("image_path"), "")
    return {
        "scene": f"Scene {scene_number}",
        "scene_id": _text(scene_entry.get("scene_id"), ""),
        "beat": _truncate(beat, 220),
        "characters": characters or "No active cast detected",
        "location": _text(scene_entry.get("location_label"), "No location detected"),
        "mood": _text(scene_entry.get("mood"), "No mood detected"),
        "mode": _text(scene_entry.get("generation_mode"), "fresh"),
        "prompt": _truncate(prompt, 220),
        "image_status": "Ready" if image_path else "Waiting for generated image",
    }
