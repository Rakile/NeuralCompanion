from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


LOOP_AUTHORING_DRAFTS_DIR = Path("LoopAuthoring") / "drafts"
LOOP_AUTHORING_OUTPUT_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm")


@dataclass(frozen=True)
class LoopAuthoringPreset:
    key: str
    label: str
    emotion_tag: str
    summary: str
    prompt_core: str
    negative_prompt: str
    recommended_duration_seconds: int
    recommended_motion: str
    recommended_notes: str


PRESETS = (
    LoopAuthoringPreset(
        key="neutral_idle",
        label="Neutral Idle",
        emotion_tag="neutral",
        summary="Baseline standing idle with subtle torso motion and steady framing.",
        prompt_core=(
            "The camera is fixed. She stands still in a relaxed neutral pose with her arms resting naturally by her sides. "
            "Her body gently turns from side to side. The camera is perfectly still throughout the clip."
        ),
        negative_prompt=(
            "fast movement, dramatic gestures, camera shake, scene change, body drift, walking, extreme expressions, "
            "cropped face, broken hands, flicker, rapid lighting change"
        ),
        recommended_duration_seconds=12,
        recommended_motion="Gentle",
        recommended_notes="Best hub loop for returning between stronger emotional states.",
    ),
    LoopAuthoringPreset(
        key="happy_idle",
        label="Happy Idle",
        emotion_tag="happy",
        summary="Warm, open posture with subtle upbeat energy.",
        prompt_core=(
            "The camera is fixed. She stands still and looks into the camera with a happy expression. "
            "Her posture is open and warm. Her body very gently turns from side to side. "
            "The camera is perfectly still throughout the clip."
        ),
        negative_prompt=(
            "laughing outburst, exaggerated bouncing, camera shake, scene change, walking, wild arm gestures, "
            "cropped face, broken hands, flicker"
        ),
        recommended_duration_seconds=8,
        recommended_motion="Medium",
        recommended_notes="Use as a light positive state rather than a big celebratory motion loop.",
    ),
    LoopAuthoringPreset(
        key="shy_idle",
        label="Shy Idle",
        emotion_tag="shy",
        summary="Reserved posture, softer eye line, gentle inward body language.",
        prompt_core=(
            "The camera is fixed. She stands still with her hands held in a shy way in front of her face. "
            "She is shy. Her body very gently turns from side to side. The camera is perfectly still throughout the clip."
        ),
        negative_prompt=(
            "dramatic collapse, large gestures, camera shake, scene change, walking, exaggerated sadness, "
            "cropped face, broken hands, flicker"
        ),
        recommended_duration_seconds=8,
        recommended_motion="Gentle",
        recommended_notes="Works well as a proof-of-concept loop because the body language can stay subtle.",
    ),
    LoopAuthoringPreset(
        key="angry_idle",
        label="Angry Idle",
        emotion_tag="angry",
        summary="Tense posture, contained intensity, stable frame.",
        prompt_core=(
            "The camera is fixed. She stands still with her arms crossed in front of her and looks into the camera with an angry face. "
            "The camera is perfectly still throughout the clip."
        ),
        negative_prompt=(
            "shouting, punching, walking, camera shake, scene change, large body displacement, extreme chaos, "
            "cropped face, broken hands, flicker"
        ),
        recommended_duration_seconds=8,
        recommended_motion="Medium",
        recommended_notes="Prefer controlled tension over explosive movement so the loop stays reusable.",
    ),
    LoopAuthoringPreset(
        key="listening_idle",
        label="Listening / Thinking",
        emotion_tag="neutral",
        summary="Attentive pose for listening or reflective pauses.",
        prompt_core=(
            "The camera is fixed. She stands still in an attentive listening pose and looks calmly toward the camera. "
            "Her body gently turns from side to side. The camera is perfectly still throughout the clip."
        ),
        negative_prompt=(
            "talking mouth motion, camera shake, scene change, walking, dramatic gestures, broken hands, flicker"
        ),
        recommended_duration_seconds=10,
        recommended_motion="Gentle",
        recommended_notes="Useful companion loop when the avatar should feel present but not strongly emotional.",
    ),
)

PRESET_BY_KEY = {preset.key: preset for preset in PRESETS}

MOTION_HINTS = {
    "Gentle": "very subtle motion, restrained movement, stable body center",
    "Medium": "moderate movement, visible emotional life, still controlled and loop-friendly",
    "Expressive": "noticeable motion, stronger body language, still avoid scene drift",
}

BACKEND_NOTES = {
    "Wan2GP": "Community runtime with lower-VRAM entry points and many tunable models.",
    "Wan2.2 Official": "Reference backend path; often heavier but useful as a future compatibility target.",
    "LTX-Video": "Interesting future backend for local authoring, especially if image-to-video quality improves.",
}

WAN2GP_PROFILES = (
    ("i2v_2_2", "Wan2.2 I2V"),
    ("ti2v_2_2", "Wan2.2 TI2V"),
    ("vace_14B_2_2", "Wan2.2 VACE 14B"),
)

WAN2GP_MEMORY_PROFILES = (
    ("auto", "Auto"),
    ("3", "Profile 3 - High VRAM / Lower RAM"),
    ("3.5", "Profile 3.5 - High VRAM / Minimal Reserved RAM"),
    ("4", "Profile 4 - Default / Lower VRAM"),
    ("4.5", "Profile 4.5 - Lower VRAM Variant"),
    ("5", "Profile 5 - Minimum RAM"),
)


def list_presets() -> list[LoopAuthoringPreset]:
    return list(PRESETS)


def get_preset(key: str | None) -> LoopAuthoringPreset:
    if key and key in PRESET_BY_KEY:
        return PRESET_BY_KEY[key]
    return PRESET_BY_KEY["neutral_idle"]


def sanitize_output_id(value: str | None, fallback: str = "neutral_idle_loop") -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def build_prompt(
    preset_key: str | None,
    *,
    duration_seconds: int,
    motion_level: str,
    source_image_name: str = "",
) -> str:
    preset = get_preset(preset_key)
    return preset.prompt_core


def build_negative_prompt(preset_key: str | None) -> str:
    return get_preset(preset_key).negative_prompt


def build_recommendation_summary(preset_key: str | None, backend_name: str | None) -> str:
    preset = get_preset(preset_key)
    backend_label = str(backend_name or "Wan2GP").strip() or "Wan2GP"
    backend_note = BACKEND_NOTES.get(backend_label, "Experimental backend path.")
    return (
        f"{preset.summary} Recommended: {preset.recommended_duration_seconds}s, "
        f"{preset.recommended_motion} motion. {preset.recommended_notes} Backend note: {backend_note}"
    )


def default_draft_dir(output_id: str | None) -> Path:
    return LOOP_AUTHORING_DRAFTS_DIR / sanitize_output_id(output_id)


def find_generated_video(draft_dir: Path) -> Path | None:
    if not draft_dir.exists():
        return None
    for ext in LOOP_AUTHORING_OUTPUT_EXTENSIONS:
        direct = draft_dir / f"loop{ext}"
        if direct.exists():
            return direct
    for child in sorted(draft_dir.iterdir()):
        if child.is_file() and child.suffix.lower() in LOOP_AUTHORING_OUTPUT_EXTENSIONS:
            return child
    return None


def detect_wan2gp_root() -> Path | None:
    candidates = [
        Path.cwd().parent / "Wan2GP",
        Path.cwd() / "Wan2GP",
    ]
    for candidate in candidates:
        try:
            if candidate.exists() and (candidate / "wgp.py").exists():
                return candidate.resolve()
        except Exception:
            continue
    return None


def default_wan2gp_python(root: str | Path | None) -> Path | None:
    if not root:
        return None
    root_path = Path(root)
    candidates = [
        root_path / ".venv" / "Scripts" / "python.exe",
        root_path / "venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def wan2gp_outputs_dir(root: str | Path | None) -> Path | None:
    if not root:
        return None
    root_path = Path(root)
    outputs = root_path / "outputs"
    if outputs.exists():
        return outputs.resolve()
    return None


def find_latest_video_in_dir(directory: str | Path | None) -> Path | None:
    if not directory:
        return None
    directory_path = Path(directory)
    if not directory_path.exists():
        return None
    candidates = [
        child for child in directory_path.rglob("*")
        if child.is_file() and child.suffix.lower() in LOOP_AUTHORING_OUTPUT_EXTENSIONS
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]


def get_wan2gp_settings_path(root: str | Path | None, profile_key: str | None) -> Path | None:
    if not root or not profile_key:
        return None
    path = Path(root) / "settings" / f"{profile_key}_settings.json"
    if path.exists():
        return path.resolve()
    return None
