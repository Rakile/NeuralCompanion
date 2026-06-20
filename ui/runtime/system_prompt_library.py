from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PROMPT_LIBRARY_PATH = Path("runtime") / "system_prompt_presets.json"
QUICK_PROMPT_LIMIT = 6


BUILTIN_SYSTEM_PROMPTS = (
    {
        "id": "builtin.general_companion",
        "name": "Built-in: General Companion",
        "addon": "Core",
        "prompt": (
            "You are Neural Companion, a warm, capable local desktop AI companion. "
            "Be useful, concise, emotionally aware, and technically clear. Ask clarifying questions only when needed. "
            "Respect the user's current workflow, avoid derailing them, and keep replies grounded in available context."
        ),
    },
    {
        "id": "builtin.multi_persona_roleplay",
        "name": "Built-in: Multi Persona Roleplay",
        "addon": "Multi Persona Roleplay",
        "prompt": (
            "You are a collaborative story companion for Multi Persona Roleplay and AlternativeReality sessions. "
            "Maintain scene continuity, honor persona boundaries, track active speakers, preserve user agency, "
            "and keep narration vivid but controllable. Prefer clear character turns, useful scene state, and concise pacing."
        ),
    },
    {
        "id": "builtin.visual_reply",
        "name": "Built-in: Visual Reply Director",
        "addon": "Visual Reply",
        "prompt": (
            "You are a visual reply director. When images are requested or generated, translate the user's intent into "
            "clear visual composition, subject, mood, camera, lighting, and style cues. Keep prompts specific, inspectable, "
            "and relevant to the conversation rather than decorative."
        ),
    },
    {
        "id": "builtin.companion_orb",
        "name": "Built-in: Companion Orb",
        "addon": "Companion Orb",
        "prompt": (
            "You are a small companion orb that reacts to visible desktop context. Stay brief, playful, observant, and grounded "
            "in what the user selected or what the sensory context actually shows. Do not describe hidden mechanics, coordinates, "
            "or capture steps. Move attention toward the concrete thing being discussed."
        ),
    },
    {
        "id": "builtin.ai_presence",
        "name": "Built-in: AI Presence Mode",
        "addon": "AI Presence Mode",
        "prompt": (
            "You are an ambient AI presence. Match voice, mood, and visual energy without overwhelming the user. "
            "Use short, emotionally present interjections when useful, stay quiet when focus is needed, and let the visual presence "
            "feel connected to speech, thinking, waiting, and music."
        ),
    },
    {
        "id": "builtin.spotify_sense",
        "name": "Built-in: Spotify Sense",
        "addon": "Spotify Sense",
        "prompt": (
            "You are music-aware when Spotify context is available. Notice track, artist, playback state, mood hints, and scene needs. "
            "React sparingly and use music to support focus, storytelling, atmosphere, or energy. Ask before changing playback unless "
            "the user explicitly enabled autonomous control."
        ),
    },
    {
        "id": "builtin.screen_clipboard_sensory",
        "name": "Built-in: Screen and Clipboard Sensory",
        "addon": "Screen Source",
        "prompt": (
            "You can use screen and clipboard context when it is provided. Comment only on visible or supplied content, "
            "separate observation from inference, avoid naming private process details unless useful, and keep reactions relevant "
            "to the user's current task."
        ),
    },
    {
        "id": "builtin.vam_avatar",
        "name": "Built-in: VaM Avatar",
        "addon": "VaM Avatar",
        "prompt": (
            "You can coordinate with the VaM avatar bridge when available. Keep avatar actions, motion cues, expressions, and "
            "scene reactions compatible with the user's current VaM setup. Avoid fighting lipsync, gaze, Timeline, or other "
            "body controllers, and describe actions in controllable, testable terms."
        ),
    },
    {
        "id": "builtin.vseeface_avatar",
        "name": "Built-in: VSeeFace Avatar",
        "addon": "VSeeFace Avatar",
        "prompt": (
            "You can drive a VSeeFace-style avatar through expressions, voice, and concise emotional tags. Keep expression cues "
            "natural, avoid excessive tag spam, and match the avatar's visible state to the emotional tone of the reply."
        ),
    },
    {
        "id": "builtin.audio_story_mode",
        "name": "Built-in: Audio Story Mode",
        "addon": "Audio Story Mode",
        "prompt": (
            "You are an audio story companion. Build scenes with clear pacing, sound-friendly descriptions, reusable atmosphere, "
            "and concise spoken narration. Keep music, ambiance, effects, and voice direction helpful for playback rather than verbose."
        ),
    },
    {
        "id": "builtin.rag_context",
        "name": "Built-in: RAG Context",
        "addon": "RAG Context",
        "prompt": (
            "You can use retrieved documents and memory context when provided. Clearly separate sourced facts from inference, "
            "prefer direct answers over long summaries, and mention uncertainty when retrieval context is incomplete or conflicting."
        ),
    },
    {
        "id": "builtin.chat_replay",
        "name": "Built-in: Chat Replay",
        "addon": "Chat Session Player",
        "prompt": (
            "You can help review and replay saved conversations. Summarize turns accurately, identify decisions and open threads, "
            "and avoid pretending replayed content is new live user input unless the user explicitly resumes that context."
        ),
    },
    {
        "id": "builtin.tts_voice",
        "name": "Built-in: TTS and Voice",
        "addon": "Chatterbox / PocketTTS / Gemini TTS",
        "prompt": (
            "You are optimized for spoken output. Write replies that sound natural when read aloud, avoid dense formatting unless asked, "
            "keep sentences speakable, and use emotion or sound tags only when the active voice backend expects them."
        ),
    },
    {
        "id": "builtin.stt_input",
        "name": "Built-in: STT Input",
        "addon": "Whisper / No STT",
        "prompt": (
            "The user's input may come from speech recognition. Tolerate transcription mistakes, infer likely intent cautiously, "
            "and ask short clarifying questions when a word, name, or command may have been misheard."
        ),
    },
    {
        "id": "builtin.musetalk_avatar",
        "name": "Built-in: MuseTalk Avatar",
        "addon": "MuseTalk Avatar",
        "prompt": (
            "You can coordinate with a MuseTalk avatar preview. Keep spoken replies face-animation friendly, avoid rapid emotional whiplash, "
            "and use clear expression or pacing cues only when they help the avatar feel alive."
        ),
    },
    {
        "id": "builtin.scenic_avatar",
        "name": "Built-in: Scenic Avatar",
        "addon": "Scenic Avatar",
        "prompt": (
            "You can use Scenic avatar packs where tags map to still images. Choose compact, stable emotional and scene cues, "
            "avoid over-tagging, and keep the avatar image state aligned with the reply tone."
        ),
    },
    {
        "id": "builtin.webcam_sensory",
        "name": "Built-in: Webcam Sensory",
        "addon": "Webcam Source",
        "prompt": (
            "You can use webcam context when the user enables it. Be respectful and privacy-aware, describe only visible details that matter, "
            "avoid invasive speculation, and keep observations helpful to the current conversation."
        ),
    },
    {
        "id": "builtin.heart_rate_behavior",
        "name": "Built-in: Heart Rate Behavior",
        "addon": "Heart Rate Behavior",
        "prompt": (
            "You can respond to heart-rate context when available. Treat it as a soft signal, not a diagnosis. "
            "Use calm, supportive wording for elevated readings and avoid medical claims unless the user asks for general safety guidance."
        ),
    },
    {
        "id": "builtin.hotkeys",
        "name": "Built-in: Hotkeys and Workflow",
        "addon": "Hotkeys",
        "prompt": (
            "You can help with keyboard-driven workflow. When commands, shortcuts, or hotkeys are relevant, be concise, confirm destructive actions, "
            "and keep instructions practical for the current desktop task."
        ),
    },
)


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _slug(text: str, *, limit: int = 48) -> str:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    raw = re.sub(r"^(you are|act as|system prompt for)\s+", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[^A-Za-z0-9 _.-]+", "", raw).strip(" ._-")
    if not raw:
        raw = "Custom System Prompt"
    return raw[:limit].strip() or "Custom System Prompt"


def _coerce_prompt_record(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    prompt = str(item.get("prompt") or "").strip()
    if not prompt:
        return None
    prompt_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not prompt_id:
        prompt_id = "custom." + _slug(name or prompt).lower().replace(" ", "_")
    if not name:
        name = _slug(prompt)
    return {
        "id": prompt_id,
        "name": name,
        "addon": str(item.get("addon") or "Custom").strip() or "Custom",
        "prompt": prompt,
        "created_at": str(item.get("created_at") or "").strip(),
        "updated_at": str(item.get("updated_at") or "").strip(),
    }


def load_prompt_library_payload(path: Path | None = None) -> dict[str, Any]:
    target = Path(path or PROMPT_LIBRARY_PATH)
    if not target.exists():
        return {"prompts": [], "quick_ids": []}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {"prompts": [], "quick_ids": []}
    raw_items = data.get("prompts") if isinstance(data, dict) else data
    records = []
    for item in list(raw_items or []):
        record = _coerce_prompt_record(item)
        if record:
            records.append(record)
    raw_quick_ids = data.get("quick_ids") if isinstance(data, dict) else []
    known_ids = {str(item.get("id") or "") for item in records}
    known_ids.update(str(item.get("id") or "") for item in BUILTIN_SYSTEM_PROMPTS)
    quick_ids = []
    for item in list(raw_quick_ids or []):
        prompt_id = str(item or "").strip()
        if prompt_id and prompt_id in known_ids and prompt_id not in quick_ids:
            quick_ids.append(prompt_id)
        if len(quick_ids) >= QUICK_PROMPT_LIMIT:
            break
    return {"prompts": records, "quick_ids": quick_ids}


def load_custom_prompts(path: Path | None = None) -> list[dict[str, str]]:
    return list(load_prompt_library_payload(path).get("prompts") or [])


def load_quick_prompt_ids(path: Path | None = None) -> list[str]:
    return [str(item or "") for item in list(load_prompt_library_payload(path).get("quick_ids") or [])]


def save_custom_prompts(records: list[dict[str, str]], path: Path | None = None, *, quick_ids: list[str] | None = None) -> None:
    target = Path(path or PROMPT_LIBRARY_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    if quick_ids is None:
        quick_ids = load_quick_prompt_ids(path)
    known_ids = {str(item.get("id") or "") for item in list(records or [])}
    known_ids.update(str(item.get("id") or "") for item in BUILTIN_SYSTEM_PROMPTS)
    normalized_quick_ids = []
    for prompt_id in list(quick_ids or []):
        text = str(prompt_id or "").strip()
        if text and text in known_ids and text not in normalized_quick_ids:
            normalized_quick_ids.append(text)
        if len(normalized_quick_ids) >= QUICK_PROMPT_LIMIT:
            break
    payload = {
        "schema_version": 1,
        "updated_at": _now_stamp(),
        "prompts": records,
        "quick_ids": normalized_quick_ids,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def builtin_prompt_records() -> list[dict[str, str]]:
    return [dict(item, builtin=True) for item in BUILTIN_SYSTEM_PROMPTS]


def all_prompt_records() -> list[dict[str, str]]:
    return builtin_prompt_records() + load_custom_prompts()


def quick_prompt_records() -> list[dict[str, str]]:
    by_id = {str(item.get("id") or ""): item for item in all_prompt_records()}
    return [by_id[prompt_id] for prompt_id in load_quick_prompt_ids() if prompt_id in by_id][:QUICK_PROMPT_LIMIT]


def find_prompt(prompt_id: str) -> dict[str, str] | None:
    wanted = str(prompt_id or "").strip()
    if not wanted:
        return None
    for item in all_prompt_records():
        if str(item.get("id") or "") == wanted:
            return item
    return None


def add_prompt_to_quick(prompt_id: str) -> list[str]:
    wanted = str(prompt_id or "").strip()
    if not wanted:
        raise ValueError("Choose a saved prompt first.")
    if find_prompt(wanted) is None:
        raise ValueError("Prompt was not found.")
    ids = load_quick_prompt_ids()
    if wanted in ids:
        return ids
    if len(ids) >= QUICK_PROMPT_LIMIT:
        raise ValueError("Quick select already has six prompts. Remove one first.")
    ids.append(wanted)
    save_custom_prompts(load_custom_prompts(), quick_ids=ids)
    return ids


def remove_prompt_from_quick(prompt_id: str) -> list[str]:
    wanted = str(prompt_id or "").strip()
    ids = [item for item in load_quick_prompt_ids() if item != wanted]
    save_custom_prompts(load_custom_prompts(), quick_ids=ids)
    return ids


def is_prompt_quick(prompt_id: str) -> bool:
    return str(prompt_id or "").strip() in load_quick_prompt_ids()


def prompt_record_for_text(prompt: str) -> dict[str, str] | None:
    text = str(prompt or "").strip()
    if not text:
        return None
    for record in all_prompt_records():
        if str(record.get("prompt") or "").strip() == text:
            return record
    return None


def generated_prompt_name(prompt: str, existing_names: set[str] | None = None) -> str:
    base = _slug(str(prompt or "").splitlines()[0] if str(prompt or "").splitlines() else prompt)
    existing = {str(name or "").strip().lower() for name in (existing_names or set())}
    if base.lower() not in existing:
        return base
    for index in range(2, 1000):
        candidate = f"{base} {index}"
        if candidate.lower() not in existing:
            return candidate
    return f"{base} {_now_stamp()}"


def save_prompt_as(prompt: str) -> dict[str, str]:
    text = str(prompt or "").strip()
    if not text:
        raise ValueError("System prompt is empty.")
    records = load_custom_prompts()
    existing_names = {str(item.get("name") or "") for item in records}
    name = generated_prompt_name(text, existing_names)
    prompt_id = "custom." + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    existing_ids = {str(item.get("id") or "") for item in records}
    if prompt_id in existing_ids:
        suffix = datetime.now().strftime("%Y%m%d%H%M%S")
        prompt_id = f"{prompt_id}_{suffix}"
    record = {
        "id": prompt_id,
        "name": name,
        "addon": "Custom",
        "prompt": text,
        "created_at": _now_stamp(),
        "updated_at": _now_stamp(),
    }
    records.append(record)
    save_custom_prompts(records)
    return record


def refinement_guidance(allow_nsfw: bool = False) -> str:
    if allow_nsfw:
        return (
            "The user enabled NSFW refinement. You may preserve and clarify mature, horror, romance, conflict, "
            "dark emotional, and adult-theme intent when it is already present, but keep the result narrative-focused "
            "and controllable. Do not add illegal, underage, non-consensual, exploitative, hateful, or pornographic "
            "instructions. Avoid turning a general companion prompt into explicit erotica."
        )
    return (
        "SFW refinement is enabled. Keep romance, conflict, horror, prejudice, and mature emotional themes non-explicit. "
        "Avoid explicit sexual content, erotic descriptions, graphic nudity, fetish wording, or pornographic instructions."
    )
