from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import threading
import time
import traceback
import uuid
import copy
import queue
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from addons.audio_story_mode import runtime_bridge as audio_story_runtime
from addons.audio_story_mode.visual_stream import (
    AudioStoryVisualStreamServer,
    cast_image_to_chromecast,
    chromecast_dependency_error,
    discover_chromecast_devices,
    install_chromecast_dependencies,
    set_current_audio_path,
    set_stream_playback_state,
    stop_chromecast,
)
from addons.audio_story_mode.prompt_builder import build_grok_story_bible_prompt
from addons.audio_story_mode.session_schema import audio_story_mode_session_payload, flatten_audio_story_mode_settings
from addons.audio_story_mode.story_analyzer import StoryAnalyzer
from addons.audio_story_mode.story_memory import StoryMemoryStore, merge_story_memory
from addons.audio_story_mode.story_modes import normalize_analysis_mode
from PySide6 import QtCore, QtGui, QtWidgets

try:
    from PySide6 import QtMultimedia
except Exception:
    QtMultimedia = None


class _LazyModuleProxy:
    def __init__(self, module_name: str):
        self._module_name = str(module_name)
        self._module = None

    def _resolve(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def is_loaded(self) -> bool:
        return self._module is not None

    def __getattr__(self, item):
        return getattr(self._resolve(), str(item))


chat_providers = _LazyModuleProxy("core.chat_providers")


class _AudioStoryNoWheelComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class _AudioStoryNoWheelSpinBox(QtWidgets.QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


_AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS = {
    "characters": 420,
    "location": 320,
    "props": 220,
    "style": 300,
    "world": 240,
    "continuity": 360,
    "preserve": 260,
    "avoid": 180,
}

_AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT = 1800
_AUDIO_STORY_LLM_ANALYSIS_TIMEOUT_SECONDS = 120.0
_AUDIO_STORY_LLM_ANALYSIS_MAX_CHUNKS = 24
_AUDIO_STORY_XAI_IMAGE_ASPECT_RATIOS = (
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "2:1",
    "1:2",
    "19.5:9",
    "9:19.5",
    "20:9",
    "9:20",
    "auto",
)
_AUDIO_STORY_XAI_IMAGE_RESOLUTIONS = ("1k", "2k")
_AUDIO_STORY_XAI_IMAGE_RESPONSE_FORMATS = ("b64_json",)

_AUDIO_STORY_CONTROL_TOOLTIPS = {
    "audio_story_intro_label": "Audio Story turns an imported story or audiobook into transcript windows, scene prompts, generated visuals, and synced playback.",
    "audio_story_path_edit": "Current source audio for Audio Story Mode. Import a file, then transcribe it before playback or image generation can run.",
    "audio_story_import_button": "Choose the audiobook or story audio file. Importing a new file clears the current transcript, images, and cached story timing.",
    "audio_story_playback_label": "Playback source used when Audio Story plays the timeline.",
    "audio_story_playback_mode_combo": "Playback source. Imported Audio is cheapest and fastest; TTS Narration renders a new local narration track from the transcript before playing.",
    "audio_story_precision_label": "Overall cost and quality preset for transcript chunking, image cadence, story analysis, and prompt detail.",
    "audio_story_cost_profile_combo": "Overall cost/quality preset. Economy avoids extra LLM analysis and makes fewer images; Detailed and Cinematic use richer prompts and denser image timing.",
    "audio_story_settings_preset_label": "Reusable Audio Story settings profile. Presets do not include the imported audio file.",
    "audio_story_settings_preset_combo": "Choose or type a reusable Audio Story settings preset name.",
    "audio_story_settings_preset_save_button": "Save the current Audio Story settings to the selected preset name. Existing presets with the same name are overwritten.",
    "audio_story_settings_preset_load_button": "Load the selected Audio Story settings preset. If a transcript is already loaded, story windows and prompts are rebuilt with the loaded settings.",
    "audio_story_transcribe_seconds_label": "Transcript window size used when splitting the audio into story chunks.",
    "audio_story_transcribe_seconds_slider": "Transcript analysis window size. Smaller values give finer scene detection but more chunks to analyze.",
    "audio_story_transcribe_seconds_value_label": "Current transcript window size in seconds.",
    "audio_story_transcription_range_label": "Source-audio range to transcribe.",
    "audio_story_transcription_start_spin": "First source-audio second included when transcribing. Use 0 to start at the beginning.",
    "audio_story_transcription_end_spin": "Last source-audio second included when transcribing. Use the audio duration to transcribe through the end.",
    "audio_story_image_frequency_label": "Target image cadence when Image Timing is Fixed Seconds.",
    "audio_story_image_frequency_slider": "Fixed-seconds image cadence, capped at 60 seconds. Lower values create more image prompts and can increase image API cost.",
    "audio_story_image_frequency_value_label": "Current fixed image cadence in seconds.",
    "audio_story_image_timing_label": "Strategy used to decide when a new story image should appear.",
    "audio_story_image_timing_combo": "Image timing mode. Fixed Seconds uses the cadence slider; Scene Changes groups transcript chunks by detected scene boundaries.",
    "audio_story_continuity_label": "How strongly generated prompts preserve characters, locations, props, and style between scenes.",
    "audio_story_continuity_slider": "Continuity strength. Higher values preserve recurring details more aggressively, but may make major scene changes less flexible.",
    "audio_story_continuity_value_label": "Current continuity strength.",
    "audio_story_generate_ahead_label": "How many future story images Audio Story may prepare before playback reaches them.",
    "audio_story_generate_ahead_slider": "How many future story images to prepare ahead of playback. Higher values reduce visible waiting but can spend image API calls earlier.",
    "audio_story_generate_ahead_value_label": "Current generate-ahead image count.",
    "audio_story_styles_label": "Visual style layers added to generated story image prompts.",
    "audio_story_style_live_checkbox": "Allow style changes during playback. When off, style edits update saved settings without regenerating visuals mid-playback.",
    "audio_story_master_prompt_label": "Story-wide visual prompt anchoring for the global Visual Reply master prompt.",
    "audio_story_master_prompt_button": "Temporarily drive the global Visuals master prompt from this story. Turning it off restores the previous Visuals master prompt when possible.",
    "audio_story_master_prompt_mode_combo": "How forcefully the story-generated master prompt should anchor visual identity. Stronger modes improve consistency but make prompts longer.",
    "audio_story_prompt_blocks_label": "Per-section character budgets used when Audio Story builds image prompts.",
    "audio_story_prompt_cap_label": "Hard limit for the final combined image prompt.",
    "audio_story_prompt_safety_cap_spin": "Hard cap for the final prompt sent to the image provider. Lower caps reduce payload size; higher caps preserve more continuity and scene detail.",
    "audio_story_story_analysis_label": "Optional LLM pass that extracts story structure before image prompt generation.",
    "audio_story_llm_analysis_checkbox": "Use an LLM to extract story bible, character/location anchors, scene boundaries, and ready image-prompt fragments.",
    "audio_story_analysis_mode_label": "Depth of story analysis used for image prompt planning.",
    "audio_story_analysis_mode_combo": "Scene Only keeps the per-scene prompt path. Story Bible persists character, location, prop, and style memory for stronger consistency.",
    "audio_story_analysis_provider_label": "Provider used for transcript analysis and prompt planning.",
    "audio_story_analysis_provider_combo": "Where transcript analysis and prompt planning runs. Current Chat Provider follows your active chat runtime.",
    "audio_story_analysis_model_label": "Optional model override used only for Audio Story analysis.",
    "audio_story_analysis_model_combo": "Model used only for Audio Story analysis and prompt planning. Auto uses the provider default; you can type a model id manually.",
    "audio_story_xai_image_settings_label": "Provider-specific image generation options. These xAI options are only used when Visual Reply is set to xAI / Grok.",
    "audio_story_xai_image_settings_hint": "Audio Story uses the active Visual Reply provider. xAI-specific overrides are ignored by other providers.",
    "audio_story_xai_aspect_ratio_label": "Aspect ratio for generated Audio Story images.",
    "audio_story_xai_aspect_ratio_combo": "Aspect ratio sent to xAI image generation for Audio Story visuals.",
    "audio_story_xai_resolution_label": "Resolution for generated Audio Story images.",
    "audio_story_xai_resolution_combo": "Resolution sent to xAI image generation. Higher values can cost more or take longer.",
    "audio_story_xai_response_format_label": "Response format requested from the xAI image API.",
    "audio_story_xai_response_format_combo": "Response format requested from xAI. b64_json keeps stable local files for playback and casting.",
    "audio_story_xai_n_label": "Number of images requested from xAI per API call.",
    "audio_story_xai_n_spin": "Number of images requested per API call. Audio Story still uses one image per timeline scene.",
    "audio_story_transcribe_button": "Run local Whisper transcription, then build story windows, scene metadata, and image prompts for this session.",
    "audio_story_scene_status_label": "Current scene summary and override state.",
    "audio_story_scene_character_label": "Character continuity pins for the selected scene.",
    "audio_story_pin_location_button": "Pin the current detected location as a continuity anchor for later images.",
    "audio_story_force_fresh_button": "Force this image window to start as a new scene when automatic detection keeps continuing too long.",
    "audio_story_force_continuation_button": "Force this image window to continue the previous scene when automatic detection splits too often.",
    "audio_story_anchor_label": "Scene-specific positive anchor text.",
    "audio_story_scene_anchor_edit": "Override the selected scene's visual anchor text. This becomes the primary scene focus for future prompts.",
    "audio_story_scene_anchor_apply_button": "Apply this anchor override and refresh matching prompts/images for the selected scene.",
    "audio_story_negative_prompt_label": "Scene-specific things to avoid in generated images.",
    "audio_story_scene_negative_prompt_edit": "Extra negative prompt text for the current scene. It is added to the scene's Avoid block before image generation.",
    "audio_story_negative_prompt_anchor_button": "Keep this negative prompt as a persistent anchor for every future scene until unpinned.",
    "audio_story_scene_negative_prompt_apply_button": "Apply this negative prompt override and refresh matching prompts/images for the selected scene.",
    "audio_story_play_button": "Start or resume playback from the current timeline position and sync the active story image to the audio.",
    "audio_story_pause_button": "Pause playback without clearing the current timeline position or active image.",
    "audio_story_stop_button": "Stop playback, return to the beginning, and show the first story image when available.",
    "audio_story_time_label": "Current playback position and total duration.",
    "audio_story_position_slider": "Scrub through the current audio story timeline. The preview jumps to the image window that matches the selected time.",
    "audio_story_status_label": "Current Audio Story runtime status.",
    "audio_story_stream_enabled_checkbox": "Serve the current story image as a local network web page for browser-capable devices and casting workflows.",
    "audio_story_stream_port_spin": "Local HTTP port used for the visual stream page.",
    "audio_story_stream_url_label": "Local network URL for the Audio Story visual stream when enabled.",
    "audio_story_cast_device_combo": "Chromecast or Google Cast device to show Audio Story visuals on.",
    "audio_story_cast_refresh_button": "Search your local network for Chromecast devices.",
    "audio_story_cast_install_button": "Install PyChromecast and Zeroconf for Chromecast discovery and casting.",
    "audio_story_cast_button": "Cast the current Audio Story visual to the selected Chromecast.",
    "audio_story_cast_stop_button": "Stop media playback on the selected Chromecast.",
    "audio_story_cast_prompt_checkbox": "Show or hide the current image prompt overlay on the Chromecast stream page.",
    "audio_story_cast_status_label": "Chromecast discovery and casting status.",
    "audio_story_summary_label": "Summary of the current transcript windows and generated visual timeline.",
    "audio_story_transcript_edit": "Read-only transcript windows used for scene detection and prompt generation.",
}


def _audio_story_cost_profiles():
    return [
        {
            "id": "economy",
            "label": "Economy",
            "description": "Lowest API cost. Fewer images, no LLM story analysis, shorter prompts.",
            "transcribe_seconds": 12,
            "image_frequency_seconds": 20,
            "image_timing_mode": "fixed",
            "generate_ahead_frames": 1,
            "continuity_strength": 0.6,
            "master_prompt_enabled": False,
            "master_prompt_mode": "simple",
            "use_llm_story_analysis": False,
            "story_analysis_provider_mode": "current",
            "prompt_block_limits": {
                "characters": 260,
                "location": 220,
                "props": 140,
                "style": 180,
                "world": 180,
                "continuity": 220,
                "preserve": 180,
                "avoid": 140,
            },
            "prompt_safety_cap": 1000,
        },
        {
            "id": "balanced",
            "label": "Balanced",
            "description": "Default tradeoff. Reuses cached images well and avoids extra LLM analysis costs.",
            "transcribe_seconds": 8,
            "image_frequency_seconds": 12,
            "image_timing_mode": "fixed",
            "generate_ahead_frames": 1,
            "continuity_strength": 0.8,
            "master_prompt_enabled": False,
            "master_prompt_mode": "medium",
            "use_llm_story_analysis": False,
            "story_analysis_provider_mode": "current",
            "prompt_block_limits": dict(_AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS),
            "prompt_safety_cap": _AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT,
        },
        {
            "id": "detailed",
            "label": "Detailed",
            "description": "Higher precision. Uses LLM story analysis and denser image changes for better scene anchoring.",
            "transcribe_seconds": 8,
            "image_frequency_seconds": 8,
            "image_timing_mode": "scene_changes",
            "generate_ahead_frames": 2,
            "continuity_strength": 0.88,
            "master_prompt_enabled": True,
            "master_prompt_mode": "strong",
            "use_llm_story_analysis": True,
            "story_analysis_provider_mode": "deepseek",
            "prompt_block_limits": {
                "characters": 520,
                "location": 420,
                "props": 280,
                "style": 420,
                "world": 320,
                "continuity": 460,
                "preserve": 340,
                "avoid": 220,
            },
            "prompt_safety_cap": 2400,
        },
        {
            "id": "cinematic",
            "label": "Cinematic",
            "description": "Maximum scene precision. Most expensive because prompts are larger and new images arrive more often.",
            "transcribe_seconds": 6,
            "image_frequency_seconds": 6,
            "image_timing_mode": "scene_changes",
            "generate_ahead_frames": 3,
            "continuity_strength": 0.95,
            "master_prompt_enabled": True,
            "master_prompt_mode": "strongest",
            "use_llm_story_analysis": True,
            "story_analysis_provider_mode": "deepseek",
            "prompt_block_limits": {
                "characters": 680,
                "location": 520,
                "props": 340,
                "style": 560,
                "world": 420,
                "continuity": 620,
                "preserve": 420,
                "avoid": 260,
            },
            "prompt_safety_cap": 3200,
        },
    ]


def _audio_story_cost_profile_definition(profile_id: str):
    normalized = str(profile_id or "").strip().lower()
    for item in _audio_story_cost_profiles():
        if str(item.get("id") or "").strip().lower() == normalized:
            return dict(item)
    return {}


def _audio_story_style_presets():
    return [
        {"id": "realistic", "label": "Realistic", "prompt": "realistic lighting, grounded detail"},
        {"id": "cartoon", "label": "Cartoon", "prompt": "stylized shapes, clean outlines"},
        {"id": "retro", "label": "Retro", "prompt": "retro print mood, halftone texture"},
        {"id": "cyberpunk", "label": "Cyberpunk", "prompt": "neon atmosphere, vivid contrast"},
    ]


def _audio_story_master_prompt_modes():
    return [
        ("simple", "Simple"),
        ("medium", "Medium"),
        ("strong", "Strong"),
        ("strongest", "Strongest"),
    ]


def _audio_story_slug(text: str, *, prefix: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
    if not value:
        value = prefix
    return f"{prefix}_{value[:36]}"


def _audio_story_sentence_split(text: str) -> list[str]:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return []
    parts = re.split(r"(?<=[.!?])\s+", value)
    return [part.strip() for part in parts if part and part.strip()]


def _audio_story_truncate(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if len(value) <= int(limit):
        return value
    return value[: max(0, int(limit))].rstrip(" \t\r\n,;:.-")


def _audio_story_visual_brief(text: str, limit: int = 260) -> str:
    """Keep transcript-derived image prompts focused on visible scene facts."""
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return ""
    value = re.sub(r'"[^"]{1,220}"', " ", value)
    value = re.sub(r"'[^']{1,220}'", " ", value)
    value = re.sub(
        r"\b(?:i|we|you|he|she|they)\s+(?:think|thought|feel|felt|know|knew|wonder|wondered|remember|remembered|realize|realized|try|tried|hope|hoped|want|wanted|can't|cannot|couldn't|shouldn't|wouldn't)\b[^.!?;]*[.!?;]?",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:my|his|her|their|our)\s+(?:stomach|heart|head|mind|thoughts?|fear|panic|pain|hunger|nausea|guilt|hope)\b[^.!?;]*[.!?;]?",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(?:says?|said|asks?|asked|replies?|replied|whispers?|whispered|shouts?|shouted)\b[^.!?;]*[.!?;]?", " ", value, flags=re.IGNORECASE)
    sentences = _audio_story_sentence_split(value)
    if sentences:
        value = " ".join(sentences[:2])
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n,;:.-")
    return _audio_story_truncate(value, int(limit))


def _audio_story_unique_keep_order(values) -> list[str]:
    seen = set()
    result = []
    for value in list(values or []):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _audio_story_keyword_tokens(text: str) -> list[str]:
    value = re.sub(r"[^a-z0-9' -]+", " ", str(text or "").lower())
    tokens = []
    for token in re.findall(r"[a-z0-9']+", value):
        if len(token) < 3 or token in _AUDIO_STORY_COMMON_WORDS:
            continue
        tokens.append(token)
    return tokens


def _audio_story_sentence_matches(sentence: str, phrases) -> bool:
    text = str(sentence or "")
    for phrase in list(phrases or []):
        value = str(phrase or "").strip()
        if value and re.search(rf"(?<![A-Za-z0-9']){re.escape(value)}(?![A-Za-z0-9'])", text, flags=re.IGNORECASE):
            return True
    return False


def _audio_story_is_character_candidate(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip(" ,;:.!?\"'"))
    if not value:
        return False
    lowered = value.lower()
    blocked = {
        "he", "she", "it", "they", "them", "him", "her", "his", "hers", "their", "theirs",
        "i", "me", "my", "mine", "we", "us", "our", "you", "your", "yours",
        "yes", "ok", "okay", "that", "this", "there", "then", "now",
        "for", "and", "but", "or", "because", "in", "at", "on", "after", "before",
    }
    if lowered in blocked or lowered in _AUDIO_STORY_COMMON_WORDS:
        return False
    words = re.findall(r"[A-Za-z0-9']+", value)
    if not words or len(words) > 3:
        return False
    if any(word.lower() in blocked for word in words):
        return False
    title_tokens = {"mr", "mrs", "ms", "miss", "dr", "sir", "lady", "lord", "captain", "professor"}
    if len(words) > 1 and words[0].lower() not in title_tokens and not all(word[:1].isupper() for word in words):
        return False
    return True


def _audio_story_normalize_character_label(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip(" ,;:.!?\"'"))
    if not value:
        return ""
    title_match = re.search(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Sir|Lady|Lord|Captain|Professor)\.?\s+[A-Z][a-z]+\b", value)
    if title_match is not None:
        value = title_match.group(0).strip()
    return value if _audio_story_is_character_candidate(value) else ""


def _audio_story_clean_location_candidate(text: str, *, prefix: str = "") -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip(" ,;:.!?\"'"))
    if not value:
        return ""
    value = re.split(
        r"\b(?:and|but|then|while|when|because|that|who|which|where|with|without|for|from|before|after)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" ,;:.!?\"'")
    words = re.findall(r"[a-z0-9']+", value.lower())
    if not words or len(words) > 5:
        return ""
    pronouns = {"he", "she", "they", "them", "his", "her", "their", "me", "you", "we", "i", "my", "your", "our"}
    if any(word in pronouns for word in words):
        return ""
    if len(words) == 1 and words[0] in _AUDIO_STORY_COMMON_WORDS:
        return ""
    prefix_words = re.findall(r"[a-z']+", str(prefix or "").lower())
    # "look at X" and similar clauses usually identify attention targets, not places.
    attention_verbs = {"look", "looking", "looks", "see", "sees", "saw", "watch", "watching", "stare", "staring", "notice", "notices"}
    if prefix_words and prefix_words[-1] in attention_verbs:
        return ""
    return value


_AUDIO_STORY_COMMON_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "they", "their", "there", "into", "onto", "about",
    "would", "could", "should", "have", "has", "had", "were", "was", "been", "being", "then", "than", "when",
    "while", "where", "what", "which", "who", "whom", "whose", "into", "over", "under", "after", "before",
    "later", "meanwhile", "again", "some", "more", "most", "very", "just", "only", "also", "still", "back",
    "around", "through", "because", "make", "makes", "made", "doing", "doing", "done", "like", "such",
    "story", "audio", "visual", "image", "images", "scene", "scenes", "chunk", "chunks", "chapter", "chapters",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
}

_AUDIO_STORY_TRANSITION_MARKERS = (
    "later",
    "meanwhile",
    "the next morning",
    "the next day",
    "moments later",
    "suddenly",
    "elsewhere",
    "back at",
    "cut to",
    "afterward",
    "afterwards",
    "as they",
    "a short while later",
    "hours later",
    "days later",
    "soon after",
)

_AUDIO_STORY_LOCATION_KEYWORDS = (
    "room",
    "house",
    "home",
    "apartment",
    "kitchen",
    "bedroom",
    "bathroom",
    "hall",
    "hallway",
    "street",
    "road",
    "city",
    "town",
    "village",
    "forest",
    "woods",
    "park",
    "garden",
    "school",
    "classroom",
    "office",
    "lab",
    "laboratory",
    "castle",
    "ship",
    "spaceship",
    "station",
    "train",
    "car",
    "bridge",
    "cafe",
    "bar",
    "diner",
    "shop",
    "market",
    "beach",
    "shore",
    "harbor",
    "harbour",
    "harbour",
    "hospital",
    "clinic",
    "warehouse",
    "attic",
    "basement",
    "alley",
    "park",
    "plaza",
    "tower",
    "temple",
    "church",
    "cathedral",
    "dungeon",
    "throne room",
    "control room",
    "workshop",
    "studio",
)

_AUDIO_STORY_TIME_OF_DAY_MARKERS = (
    "dawn",
    "sunrise",
    "morning",
    "noon",
    "afternoon",
    "sunset",
    "dusk",
    "evening",
    "night",
    "midnight",
    "late night",
)

_AUDIO_STORY_MOOD_MARKERS = (
    "joyful",
    "happy",
    "tense",
    "calm",
    "fearful",
    "mysterious",
    "melancholic",
    "hopeful",
    "somber",
    "angry",
    "romantic",
    "playful",
    "quiet",
    "chaotic",
)

_AUDIO_STORY_CHARACTER_HINTS = (
    "woman",
    "man",
    "girl",
    "boy",
    "person",
    "detective",
    "scientist",
    "doctor",
    "artist",
    "student",
    "pilot",
    "engineer",
    "soldier",
    "wizard",
    "witch",
    "knight",
    "prince",
    "princess",
    "queen",
    "king",
    "robot",
    "android",
    "child",
    "teen",
    "adult",
    "goblin",
    "elf",
    "dragon",
)

_AUDIO_STORY_PROP_HINTS = (
    "book",
    "key",
    "map",
    "car",
    "ship",
    "sword",
    "gun",
    "phone",
    "device",
    "laptop",
    "camera",
    "lantern",
    "ring",
    "crown",
    "mask",
    "letter",
    "photo",
    "artifact",
    "crystal",
    "gadget",
    "tablet",
    "shield",
)

_AUDIO_STORY_WORLD_HINTS = {
    "fantasy": "fantasy world",
    "medieval": "medieval setting",
    "kingdom": "kingdom setting",
    "castle": "castle setting",
    "sci-fi": "science fiction world",
    "scifi": "science fiction world",
    "space": "spacefaring world",
    "cyberpunk": "cyberpunk world",
    "noir": "noir mood",
    "modern": "modern setting",
    "contemporary": "contemporary setting",
    "historical": "historical setting",
    "post-apocalyptic": "post-apocalyptic world",
    "post apocalyptic": "post-apocalyptic world",
    "western": "western setting",
    "victorian": "victorian era",
    "steampunk": "steampunk world",
    "urban": "urban environment",
    "rural": "rural environment",
}


class AudioStoryModeController(QtCore.QObject):
    transcriptionProgress = QtCore.Signal(object)
    transcriptionFinished = QtCore.Signal(object)
    transcriptionFailed = QtCore.Signal(str)
    ttsRenderFinished = QtCore.Signal(object)
    ttsRenderFailed = QtCore.Signal(str)
    imageReady = QtCore.Signal(object)
    imageFailed = QtCore.Signal(object)
    chromecastJobFinished = QtCore.Signal(object)

    def __init__(self, context=None):
        super().__init__()
        self.context = context
        self.dialogs = context.get_service("qt.dialogs") if context is not None else None
        self.shell = context.get_service("qt.shell") if context is not None else None
        self.capability_bridge = context.get_service("addons.capabilities") if context is not None else None
        self.visual_reply_service = context.get_service("qt.visual_reply") if context is not None else None
        self.audio_story_tab_widget = None
        self.audio_player = None
        self.audio_output = None
        self.imported_audio_path = ""
        self.imported_audio_duration_seconds = 0.0
        self.transcript_chunks = []
        self.full_transcript_text = ""
        self.story_style_guide = ""
        self._transcription_job_id = 0
        self._tts_render_job_id = 0
        self._image_generation_token = 0
        self._image_generation_worker_running = False
        self._image_generation_active_start_index = -1
        self._image_generation_requested_end_index = -1
        self._visual_generation_blocked = False
        self._user_scrubbing = False
        self._pending_autoplay_tts = False
        self._player_source_key = ""
        self._current_chunk_index = -1
        self._stored_transcribe_seconds = 8
        self._stored_transcription_start_seconds = 0
        self._stored_transcription_end_seconds = 0
        self._stored_image_frequency_seconds = 12
        self._stored_image_timing_mode = "fixed"
        self._stored_generate_ahead_frames = 1
        self._stored_continuity_strength = 0.8
        self._stored_style_change_live = False
        self._stored_style_prompts = {item["id"]: item["prompt"] for item in _audio_story_style_presets()}
        self._stored_style_labels = {item["id"]: item["label"] for item in _audio_story_style_presets()}
        self._stored_style_enabled = []
        self._stored_playback_mode_label = "Play Imported Audio"
        self._stored_cost_profile_id = "balanced"
        self._stored_story_master_prompt_enabled = False
        self._stored_story_master_prompt_mode = "medium"
        self._stored_audio_story_analysis_mode = self._normalize_audio_story_analysis_mode(
            audio_story_runtime.runtime_config_value("audio_story_analysis_mode", "scene_only")
        )
        self._stored_use_llm_story_analysis = False
        self._stored_story_analysis_provider_mode = "current"
        self._stored_story_analysis_model = ""
        self._stored_prompt_block_limits = dict(_AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS)
        self._stored_prompt_safety_cap = _AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT
        self._stored_visual_stream_enabled = False
        self._stored_visual_stream_port = 8765
        self._stored_chromecast_device_name = ""
        self._stored_chromecast_cast_active = False
        self._stored_chromecast_stream_page_active = False
        self._stored_chromecast_show_prompt = False
        self._story_generated_master_prompt = ""
        self._story_master_prompt_previous_runtime_value = None
        self._tts_render_in_progress = False
        self._pending_play_request = None
        self._tts_bundle = None
        self._tts_signature = ""
        self._image_cache = {}
        self._prompt_image_cache = {}
        self._llm_story_analysis_cache = {}
        self._visual_client = None
        self._visual_client_signature = ""
        self._xai_reference_edit_warning_shown = False
        self._visual_stream_server = None
        self._chromecast_devices = []
        self._chromecast_busy = False
        self._chromecast_job_done = None
        self._active_chromecast_device_name = ""
        self._raw_transcript_segments = []
        self.story_bible = {}
        self.scene_plan = []
        self.scene_overrides = {
            "pinned_character_ids": [],
            "pinned_location_ids": [],
            "forced_scene_modes": {},
            "scene_anchor_overrides": {},
            "scene_negative_prompt_overrides": {},
            "global_negative_prompt": "",
            "global_negative_prompt_enabled": False,
        }
        self.continuity_memory = {
            "last_scene_id": "",
            "last_scene_index": -1,
            "last_generated_image_path": "",
            "last_prompt_signature": "",
            "last_prompt_text": "",
            "scenes": {},
            "characters": {},
            "locations": {},
        }
        self.character_anchors = {}
        self.location_anchors = {}
        self._last_transcription_audio_duration = 0.0
        self._lock = threading.RLock()
        self._cache_root = self.context.storage.resolve("cache") if self.context is not None else (Path("runtime") / "audio_story_mode")
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._preset_root = self.context.storage.resolve("presets") if self.context is not None else (Path("runtime") / "audio_story_mode" / "presets")
        self._preset_root.mkdir(parents=True, exist_ok=True)
        self._visual_refresh_timer = QtCore.QTimer(self)
        self._visual_refresh_timer.setSingleShot(True)
        self._visual_refresh_timer.setInterval(220)
        self._visual_refresh_timer.timeout.connect(self._flush_scheduled_visual_refresh)
        self._story_rebuild_timer = QtCore.QTimer(self)
        self._story_rebuild_timer.setSingleShot(True)
        self._story_rebuild_timer.setInterval(420)
        self._story_rebuild_timer.timeout.connect(self._flush_scheduled_story_payload_rebuild)
        self._pending_story_rebuild_status_text = ""
        self._theme_refresh_timer = QtCore.QTimer(self)
        self._theme_refresh_timer.setSingleShot(True)
        self._theme_refresh_timer.setInterval(80)
        self._theme_refresh_timer.timeout.connect(self.apply_theme_palette)
        self.transcriptionProgress.connect(self._on_transcription_progress)
        self.transcriptionFinished.connect(self._on_transcription_finished)
        self.transcriptionFailed.connect(self._on_transcription_failed)
        self.ttsRenderFinished.connect(self._on_tts_render_finished)
        self.ttsRenderFailed.connect(self._on_tts_render_failed)
        self.imageReady.connect(self._on_image_ready)
        self.imageFailed.connect(self._on_image_failed)
        self.chromecastJobFinished.connect(self._on_chromecast_job_finished)

    def _visual_reply_capability(self, capability: str, payload=None, default=None):
        bridge = getattr(self, "capability_bridge", None)
        invoker = getattr(bridge, "invoke", None)
        if not callable(invoker):
            return default
        request = dict(payload or {})
        request.setdefault("runtime_config", audio_story_runtime.runtime_config())
        try:
            result = invoker(str(capability or ""), request)
        except Exception:
            return default
        return default if result is None else result

    def _visual_reply_generation_info(self) -> dict:
        return dict(self._visual_reply_capability("runtime.generation", {}, {}) or {})

    def _visual_reply_current_state(self) -> dict:
        return dict(self._visual_reply_capability("runtime.current_state", {}, {}) or {})

    def _visual_reply_set_state(self, state: dict) -> bool:
        return bool(self._visual_reply_capability("runtime.set_state", {"state": dict(state or {})}, False))

    def _visual_reply_story_style_guide(self, text: str, *, continuity_strength: float = 0.8) -> str:
        return str(
            self._visual_reply_capability(
                "runtime.story_style_guide",
                {
                    "text": str(text or ""),
                    "continuity_strength": float(continuity_strength),
                },
                "",
            )
            or ""
        )

    def _visual_reply_story_prompt(self, text: str, *, emotion: str = "", story_style_guide: str = "") -> str:
        return str(
            self._visual_reply_capability(
                "runtime.story_prompt",
                {
                    "text": str(text or ""),
                    "emotion": str(emotion or ""),
                    "story_style_guide": str(story_style_guide or ""),
                },
                "",
            )
            or ""
        )

    def _visual_reply_normalize_prompt_text(self, prompt: str) -> str:
        return str(self._visual_reply_capability("runtime.normalize_prompt", {"prompt": str(prompt or "")}, "") or "")

    def _visual_reply_apply_style_anchor(self, prompt: str) -> str:
        return str(self._visual_reply_capability("runtime.apply_style_anchor", {"prompt": str(prompt or "")}, str(prompt or "")) or "")

    def _visual_reply_output_base(self, prefix: str, index: int):
        value = self._visual_reply_capability(
            "runtime.output_base",
            {
                "prefix": str(prefix or "visual_reply"),
                "index": int(index),
            },
            None,
        )
        return Path(value) if value is not None else Path("runtime") / "visual_replies" / f"{prefix}_{int(time.time())}_{index}"

    def _visual_reply_client(self):
        client = self._visual_reply_capability("runtime.client", {}, None)
        if client is None:
            raise RuntimeError("Visual Reply client is unavailable.")
        return client

    def _visual_reply_write_image_from_response(self, response, output_base_path):
        output_path = self._visual_reply_capability(
            "runtime.write_image_from_response",
            {
                "response": response,
                "output_base_path": str(output_base_path),
            },
            None,
        )
        if output_path is None:
            raise RuntimeError("Visual Reply image writer is unavailable.")
        return Path(output_path)

    def eventFilter(self, watched, event):
        root = getattr(self, "audio_story_tab_widget", None)
        if root is not None:
            event_type = event.type() if event is not None else None
            if watched is root:
                qevent_type = getattr(QtCore.QEvent, "Type", QtCore.QEvent)
                theme_event_types = {
                    getattr(qevent_type, "ApplicationPaletteChange", None),
                    getattr(qevent_type, "PaletteChange", None),
                    getattr(qevent_type, "Polish", None),
                    getattr(qevent_type, "Show", None),
                    getattr(qevent_type, "StyleChange", None),
                }
                if event_type in theme_event_types:
                    self._schedule_theme_palette_refresh()
            wheel_type = getattr(getattr(QtCore.QEvent, "Type", QtCore.QEvent), "Wheel", None)
            if event_type == wheel_type and self._watched_inside_audio_story_panel(watched):
                if self._scroll_audio_story_panel_from_wheel(event):
                    return True
        return super().eventFilter(watched, event)

    def _watched_inside_audio_story_panel(self, watched):
        root = getattr(self, "audio_story_tab_widget", None)
        if root is None or watched is None:
            return False
        if watched is root:
            return True
        if not isinstance(watched, QtCore.QObject):
            return False
        parent = watched
        while parent is not None:
            if parent is root:
                return True
            try:
                parent = parent.parent()
            except Exception:
                return False
        return False

    def _scroll_audio_story_panel_from_wheel(self, event):
        scroll_area = getattr(self, "audio_story_scroll_area", None)
        if scroll_area is None or not hasattr(scroll_area, "verticalScrollBar"):
            return False
        try:
            scrollbar = scroll_area.verticalScrollBar()
            delta = event.angleDelta().y() if hasattr(event, "angleDelta") else 0
        except Exception:
            return False
        if scrollbar is None or not delta:
            return False
        try:
            step = scrollbar.singleStep() or 20
            scrollbar.setValue(scrollbar.value() - int(delta / 120) * step * 3)
            return True
        except Exception:
            return False

    def _install_audio_story_interaction_filters(self, root):
        if root is None:
            return
        widgets = [root]
        try:
            widgets.extend(root.findChildren(QtWidgets.QWidget))
        except Exception:
            pass
        for widget in widgets:
            try:
                widget.installEventFilter(self)
            except Exception:
                pass

    def _force_audio_story_runtime_enabled(self):
        root = getattr(self, "audio_story_tab_widget", None)
        if root is None:
            return
        widgets = [root]
        try:
            widgets.extend(root.findChildren(QtWidgets.QWidget))
        except Exception:
            pass
        for widget in widgets:
            try:
                widget.setEnabled(True)
            except Exception:
                pass
        self._refresh_controls()

    def _schedule_theme_palette_refresh(self):
        timer = getattr(self, "_theme_refresh_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()

    def _audio_story_color_luminance(self, color):
        if not isinstance(color, QtGui.QColor):
            color = QtGui.QColor(str(color or "#000000"))
        if not color.isValid():
            color = QtGui.QColor("#000000")
        red = color.redF()
        green = color.greenF()
        blue = color.blueF()
        return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)

    def _audio_story_contrast_text(self, color, *, light="#111827", dark="#ffffff"):
        return light if self._audio_story_color_luminance(QtGui.QColor(str(color))) > 0.56 else dark

    def _audio_story_colored_button_style(self, *, background: str, hover: str, pressed: str, border: str, disabled_bg: str, disabled_text: str):
        return (
            "QPushButton {{ padding: 6px 12px; min-height: 30px; border-radius: 10px; "
            "background: {background}; border: 1px solid {border}; color: #ffffff; font-weight: 700; }}"
            "QPushButton:hover {{ background: {hover}; border: 1px solid {hover}; }}"
            "QPushButton:pressed {{ background: {pressed}; border: 1px solid {pressed}; }}"
            "QPushButton:disabled {{ background: {disabled_bg}; color: {disabled_text}; border: 1px solid {disabled_bg}; }}"
        ).format(
            background=background,
            hover=hover,
            pressed=pressed,
            border=border,
            disabled_bg=disabled_bg,
            disabled_text=disabled_text,
        )

    def _audio_story_playback_button_style(self, role: str, *, disabled_bg: str = "#17212e", disabled_text: str = "#71839a"):
        role = str(role or "").strip().lower()
        if role == "play":
            return self._audio_story_colored_button_style(
                background="#17803d",
                hover="#1f9f4f",
                pressed="#11662f",
                border="#25b85d",
                disabled_bg=disabled_bg,
                disabled_text=disabled_text,
            )
        if role == "pause":
            return self._audio_story_colored_button_style(
                background="#2563eb",
                hover="#3b82f6",
                pressed="#1d4ed8",
                border="#60a5fa",
                disabled_bg=disabled_bg,
                disabled_text=disabled_text,
            )
        if role == "stop":
            return self._audio_story_colored_button_style(
                background="#dc2626",
                hover="#ef4444",
                pressed="#b91c1c",
                border="#f87171",
                disabled_bg=disabled_bg,
                disabled_text=disabled_text,
            )
        return ""

    def _audio_story_theme_colors(self, palette_data=None):
        if isinstance(palette_data, dict):
            panel_color = QtGui.QColor(
                str(
                    palette_data.get(
                        "panel_bg",
                        palette_data.get("window_bg", palette_data.get("field_bg", "#101923")),
                    )
                    or "#101923"
                )
            )
            panel_value = panel_color.name()
            field_value = str(palette_data.get("field_bg", palette_data.get("base", "#101923")) or "#101923")
            is_dark = self._audio_story_color_luminance(panel_color) < 0.48
            if is_dark:
                return {
                    "text": str(palette_data.get("text_strong", palette_data.get("text", "#f5f8fc")) or "#f5f8fc"),
                    "muted": str(palette_data.get("text", "#c2cedc") or "#c2cedc"),
                    "subtle": str(palette_data.get("text_muted", "#93a7bc") or "#93a7bc"),
                    "panel_bg": panel_value,
                    "field_bg": field_value,
                    "menu_bg": str(palette_data.get("menu_bg", palette_data.get("field_bg", "#162232")) or "#162232"),
                    "button_bg": str(palette_data.get("button_bg", "#22344c") or "#22344c"),
                    "button_hover": str(palette_data.get("button_hover", "#2a4160") or "#2a4160"),
                    "button_pressed": str(palette_data.get("button_pressed", "#1d2e43") or "#1d2e43"),
                    "disabled_bg": str(palette_data.get("disabled_bg", "#17212e") or "#17212e"),
                    "disabled_text": str(palette_data.get("text_disabled", palette_data.get("text_muted", "#7f91a7")) or "#7f91a7"),
                    "border": str(palette_data.get("button_border", palette_data.get("surface_border", "#35506c")) or "#35506c"),
                    "accent": str(palette_data.get("accent_bg", "#4d8dff") or "#4d8dff"),
                    "accent_border": str(palette_data.get("accent_border", palette_data.get("button_border", "#6a95ff")) or "#6a95ff"),
                    "accent_text": "#ffffff",
                }
            return {
                "text": str(palette_data.get("text_strong", palette_data.get("text", "#15110c")) or "#15110c"),
                "muted": str(palette_data.get("text", "#4e4435") or "#4e4435"),
                "subtle": str(palette_data.get("text_muted", "#665942") or "#665942"),
                "panel_bg": panel_value,
                "field_bg": field_value,
                "menu_bg": str(palette_data.get("menu_bg", palette_data.get("field_bg", "#f3e7d6")) or "#f3e7d6"),
                "button_bg": str(palette_data.get("button_bg", "#eadcc8") or "#eadcc8"),
                "button_hover": str(palette_data.get("button_hover", "#dfcfb9") or "#dfcfb9"),
                "button_pressed": str(palette_data.get("button_pressed", "#d2bea2") or "#d2bea2"),
                "disabled_bg": str(palette_data.get("disabled_bg", "#d8ccb8") or "#d8ccb8"),
                "disabled_text": str(palette_data.get("text_disabled", palette_data.get("text_muted", "#7d705e")) or "#7d705e"),
                "border": str(palette_data.get("button_border", palette_data.get("surface_border", "#a89372")) or "#a89372"),
                "accent": str(palette_data.get("accent_bg", "#806847") or "#806847"),
                "accent_border": str(palette_data.get("accent_border", palette_data.get("button_border", "#a18a66")) or "#a18a66"),
                "accent_text": "#ffffff",
            }
        root = getattr(self, "audio_story_tab_widget", None)
        palette = root.palette() if root is not None else QtWidgets.QApplication.palette()
        window_color = palette.color(QtGui.QPalette.Window)
        base_color = palette.color(QtGui.QPalette.Base)
        is_dark = self._audio_story_color_luminance(window_color) < 0.48
        if is_dark:
            return {
                "text": "#f5f8fc",
                "muted": "#c2cedc",
                "subtle": "#93a7bc",
                "panel_bg": "#18202a",
                "field_bg": base_color.name() if self._audio_story_color_luminance(base_color) < 0.5 else "#101923",
                "menu_bg": "#162232",
                "button_bg": "#22344c",
                "button_hover": "#2a4160",
                "button_pressed": "#1d2e43",
                "disabled_bg": "#17212e",
                "disabled_text": "#7f91a7",
                "border": "#35506c",
                "accent": "#4d8dff",
                "accent_border": "#6a95ff",
                "accent_text": "#ffffff",
            }
        return {
            "text": "#15110c",
            "muted": "#4e4435",
            "subtle": "#665942",
            "panel_bg": "#f5f6f8",
            "field_bg": "#fbf4ea",
            "menu_bg": "#f3e7d6",
            "button_bg": "#eadcc8",
            "button_hover": "#dfcfb9",
            "button_pressed": "#d2bea2",
            "disabled_bg": "#d8ccb8",
            "disabled_text": "#7d705e",
            "border": "#a89372",
            "accent": "#806847",
            "accent_border": "#a18a66",
            "accent_text": "#ffffff",
        }

    def _capture_audio_story_designer_styles(self, root):
        if root is None:
            return
        try:
            widgets = [root]
            widgets.extend(root.findChildren(QtWidgets.QWidget))
            for widget in widgets:
                widget.setProperty("_audio_story_designer_style_sheet", str(widget.styleSheet() or ""))
        except RuntimeError:
            return

    def apply_theme_palette(self, palette_data=None):
        root = getattr(self, "audio_story_tab_widget", None)
        if root is None:
            return
        def _style_with_designer_override(widget, theme_style: str) -> str:
            designer_style = ""
            try:
                designer_style = str(widget.property("_audio_story_designer_style_sheet") or "")
            except Exception:
                designer_style = ""
            if designer_style.strip():
                return f"{theme_style}{designer_style}"
            return theme_style
        def _set_style_if_changed(widget, stylesheet: str):
            if widget is None or not hasattr(widget, "setStyleSheet"):
                return
            try:
                if str(widget.styleSheet() or "") != str(stylesheet or ""):
                    widget.setStyleSheet(str(stylesheet or ""))
            except RuntimeError:
                raise
            except Exception:
                return

        colors = self._audio_story_theme_colors(palette_data)
        text = colors["text"]
        muted = colors["muted"]
        subtle = colors["subtle"]
        panel_bg = colors["panel_bg"]
        field_bg = colors["field_bg"]
        menu_bg = colors["menu_bg"]
        button_bg = colors["button_bg"]
        button_hover = colors["button_hover"]
        button_pressed = colors["button_pressed"]
        disabled_bg = colors["disabled_bg"]
        disabled_text = colors["disabled_text"]
        border = colors["border"]
        accent = colors["accent"]
        accent_border = colors["accent_border"]
        accent_text = colors["accent_text"]
        button_text = self._audio_story_contrast_text(button_bg, light=text, dark="#ffffff")
        try:
            widget_count = len(root.findChildren(QtWidgets.QWidget))
        except Exception:
            widget_count = -1
        theme_key = (
            id(root),
            widget_count,
            text,
            muted,
            subtle,
            panel_bg,
            field_bg,
            menu_bg,
            button_bg,
            button_hover,
            button_pressed,
            disabled_bg,
            disabled_text,
            border,
            accent,
            accent_border,
            accent_text,
        )
        if getattr(self, "_audio_story_theme_apply_key", None) == theme_key:
            return
        self._audio_story_theme_apply_key = theme_key
        root_style = (
            "QWidget#audio_story_mode_tab {{ background: {field_bg}; }}"
            "QScrollArea#audio_story_scroll_area {{ background: {field_bg}; border: 0px; }}"
            "QScrollArea#audio_story_scroll_area > QWidget,"
            "QScrollArea#audio_story_scroll_area > QWidget > QWidget,"
            "QWidget#audio_story_scroll_content {{ background: {field_bg}; }}"
            "QWidget#audio_story_mode_tab QLabel {{ background: transparent; }}"
            "QWidget#audio_story_mode_tab QFrame#Panel {{"
            " background: {panel_bg}; border: 1px solid {border}; border-radius: 10px;"
            "}}"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_audio_group,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_timing_group,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_prompt_group,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_analysis_group,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_xai_group {{"
            " background: {panel_bg}; border: 1px solid {border}; border-radius: 10px;"
            " margin-top: 14px; padding: 18px 12px 12px 12px; font-weight: 600;"
            "}}"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_audio_group::title,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_timing_group::title,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_prompt_group::title,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_analysis_group::title,"
            "QWidget#audio_story_mode_tab QGroupBox#audio_story_xai_group::title {{"
            " background: {panel_bg}; subcontrol-origin: margin; left: 10px; padding: 0 6px;"
            "}}"
        ).format(field_bg=field_bg, panel_bg=panel_bg, border=border)
        input_style = (
            "background: {field_bg}; color: {text}; border: 1px solid {border}; "
            "border-radius: 8px; padding: 4px 8px; selection-background-color: {accent}; "
            "selection-color: {accent_text};"
        ).format(field_bg=field_bg, text=text, border=border, accent=accent, accent_text=accent_text)
        disabled_input_style = (
            "background: {disabled_bg}; color: {disabled_text}; border: 1px solid {border};"
        ).format(disabled_bg=disabled_bg, disabled_text=disabled_text, border=border)
        combo_style = (
            "QComboBox {{ {input_style} min-height: 24px; }}"
            "QComboBox:disabled {{ {disabled_input_style} }}"
            "QComboBox::drop-down {{ width: 28px; border-left: 1px solid {border}; border-top-right-radius: 8px; border-bottom-right-radius: 8px; background: {button_bg}; }}"
            "QComboBox::down-arrow {{ width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 7px solid {button_text}; margin-right: 8px; }}"
            "QComboBox QAbstractItemView {{ background: {menu_bg}; color: {text}; border: 1px solid {border}; outline: 0; selection-background-color: {accent}; selection-color: {accent_text}; }}"
            "QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 4px 8px; color: {text}; background: {menu_bg}; }}"
            "QComboBox QAbstractItemView::item:selected {{ background: {accent}; color: {accent_text}; }}"
        ).format(
            input_style=input_style,
            disabled_input_style=disabled_input_style,
            border=border,
            button_bg=button_bg,
            button_text=button_text,
            menu_bg=menu_bg,
            text=text,
            accent=accent,
            accent_text=accent_text,
        )
        line_style = (
            "QLineEdit {{ {input_style} min-height: 24px; }}"
            "QLineEdit:disabled {{ {disabled_input_style} }}"
        ).format(input_style=input_style, disabled_input_style=disabled_input_style)
        plain_style = (
            "QPlainTextEdit {{ {input_style} }}"
            "QPlainTextEdit:disabled {{ {disabled_input_style} }}"
        ).format(input_style=input_style, disabled_input_style=disabled_input_style)
        spin_style = (
            "QSpinBox {{ {input_style} min-height: 24px; }}"
            "QSpinBox:disabled {{ {disabled_input_style} }}"
            "QSpinBox::up-button, QSpinBox::down-button {{ background: {button_bg}; border-left: 1px solid {border}; width: 18px; }}"
        ).format(input_style=input_style, disabled_input_style=disabled_input_style, button_bg=button_bg, border=border)
        button_style = (
            "QPushButton {{ padding: 6px 12px; min-height: 30px; border-radius: 10px; "
            "background: {button_bg}; border: 1px solid {border}; color: {button_text}; font-weight: 600; }}"
            "QPushButton:hover {{ background: {button_hover}; border: 1px solid {accent_border}; }}"
            "QPushButton:pressed {{ background: {button_pressed}; }}"
            "QPushButton:checked {{ background: {accent}; color: {accent_text}; border: 1px solid {accent_border}; }}"
            "QPushButton:disabled {{ background: {disabled_bg}; color: {disabled_text}; border: 1px solid {border}; }}"
        ).format(
            button_bg=button_bg,
            border=border,
            button_text=button_text,
            button_hover=button_hover,
            accent_border=accent_border,
            button_pressed=button_pressed,
            accent=accent,
            accent_text=accent_text,
            disabled_bg=disabled_bg,
            disabled_text=disabled_text,
        )
        checkbox_style = (
            "QCheckBox {{ color: {text}; spacing: 6px; }}"
            "QCheckBox:disabled {{ color: {disabled_text}; }}"
            "QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid {border}; background: {field_bg}; }}"
            "QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent_border}; }}"
        ).format(text=text, disabled_text=disabled_text, border=border, field_bg=field_bg, accent=accent, accent_border=accent_border)
        try:
            _set_style_if_changed(root, _style_with_designer_override(root, root_style))
            scroll_area = getattr(self, "audio_story_scroll_area", None)
            if scroll_area is not None:
                _set_style_if_changed(
                    scroll_area,
                    "QScrollArea#audio_story_scroll_area {{ background: {field_bg}; border: 0px; }}"
                    "QScrollArea#audio_story_scroll_area > QWidget,"
                    "QScrollArea#audio_story_scroll_area > QWidget > QWidget {{ background: {field_bg}; }}"
                    .format(field_bg=field_bg),
                )
                try:
                    _set_style_if_changed(scroll_area.viewport(), f"background: {field_bg}; border: 0px;")
                except Exception:
                    pass
            scroll_content = root.findChild(QtWidgets.QWidget, "audio_story_scroll_content")
            if scroll_content is not None:
                _set_style_if_changed(
                    scroll_content,
                    f"QWidget#audio_story_scroll_content {{ background: {field_bg}; }}",
                )
            panel_style = (
                "QFrame#Panel {{ background: {panel_bg}; border: 1px solid {border}; border-radius: 10px; }}"
            ).format(panel_bg=panel_bg, border=border)
            for panel in root.findChildren(QtWidgets.QFrame, "Panel"):
                _set_style_if_changed(panel, panel_style)
            category_group_style = (
                "QGroupBox {{"
                " background: {panel_bg}; color: {text}; border: 1px solid {border}; border-radius: 10px;"
                " margin-top: 14px; padding: 18px 12px 12px 12px; font-weight: 600;"
                "}}"
                "QGroupBox::title {{"
                " subcontrol-origin: margin; subcontrol-position: top left;"
                " background: {panel_bg}; left: 12px; padding: 0 6px; color: {text};"
                "}}"
            ).format(panel_bg=panel_bg, text=text, border=border)
            for group_name in (
                "audio_story_audio_group",
                "audio_story_timing_group",
                "audio_story_prompt_group",
                "audio_story_analysis_group",
                "audio_story_xai_group",
            ):
                group = root.findChild(QtWidgets.QGroupBox, group_name)
                if group is not None:
                    _set_style_if_changed(group, category_group_style)
            for label in root.findChildren(QtWidgets.QLabel):
                existing = str(label.property("_audio_story_designer_style_sheet") or label.styleSheet() or "")
                if "font-weight: 700" in existing:
                    _set_style_if_changed(label, _style_with_designer_override(label, f"background: transparent; font-size: 13px; font-weight: 700; color: {text};"))
                elif "font-size: 11px" in existing:
                    _set_style_if_changed(label, _style_with_designer_override(label, f"background: transparent; color: {subtle}; font-size: 11px;"))
                elif label in {
                    getattr(self, "audio_story_transcribe_seconds_value_label", None),
                    getattr(self, "audio_story_image_frequency_value_label", None),
                    getattr(self, "audio_story_continuity_value_label", None),
                    getattr(self, "audio_story_generate_ahead_value_label", None),
                    getattr(self, "audio_story_time_label", None),
                    getattr(self, "audio_story_status_label", None),
                    getattr(self, "audio_story_summary_label", None),
                }:
                    _set_style_if_changed(label, _style_with_designer_override(label, f"background: transparent; color: {muted};"))
                else:
                    _set_style_if_changed(label, _style_with_designer_override(label, f"background: transparent; color: {text};"))
            for checkbox in root.findChildren(QtWidgets.QCheckBox):
                _set_style_if_changed(checkbox, _style_with_designer_override(checkbox, checkbox_style))
            for slider in root.findChildren(QtWidgets.QSlider):
                _set_style_if_changed(slider, _style_with_designer_override(slider, "QSlider { background: transparent; }"))
            for button in root.findChildren(QtWidgets.QPushButton):
                if button is getattr(self, "audio_story_play_button", None):
                    _set_style_if_changed(button, _style_with_designer_override(button, self._audio_story_playback_button_style("play", disabled_bg=disabled_bg, disabled_text=disabled_text)))
                elif button is getattr(self, "audio_story_pause_button", None):
                    _set_style_if_changed(button, _style_with_designer_override(button, self._audio_story_playback_button_style("pause", disabled_bg=disabled_bg, disabled_text=disabled_text)))
                elif button is getattr(self, "audio_story_stop_button", None):
                    _set_style_if_changed(button, _style_with_designer_override(button, self._audio_story_playback_button_style("stop", disabled_bg=disabled_bg, disabled_text=disabled_text)))
                else:
                    _set_style_if_changed(button, _style_with_designer_override(button, button_style))
            for edit in root.findChildren(QtWidgets.QLineEdit):
                _set_style_if_changed(edit, _style_with_designer_override(edit, line_style))
                edit.setPalette(root.palette())
            for plain_edit in root.findChildren(QtWidgets.QPlainTextEdit):
                _set_style_if_changed(plain_edit, _style_with_designer_override(plain_edit, plain_style))
                plain_edit.setPalette(root.palette())
            for spin in root.findChildren(QtWidgets.QSpinBox):
                _set_style_if_changed(spin, _style_with_designer_override(spin, spin_style))
                spin.setPalette(root.palette())
            for combo in root.findChildren(QtWidgets.QComboBox):
                _set_style_if_changed(combo, _style_with_designer_override(combo, combo_style))
                combo.setPalette(root.palette())
                line_edit = combo.lineEdit() if combo.isEditable() else None
                if line_edit is not None:
                    _set_style_if_changed(line_edit, line_style)
                    line_edit.setPalette(root.palette())
                view = combo.view()
                if view is not None:
                    _set_style_if_changed(view,
                        "QListView {{ background: {menu_bg}; color: {text}; border: 1px solid {border}; outline: 0; }}"
                        "QListView::item {{ background: {menu_bg}; color: {text}; min-height: 24px; padding: 4px 8px; }}"
                        "QListView::item:selected {{ background: {accent}; color: {accent_text}; }}"
                    .format(menu_bg=menu_bg, text=text, border=border, accent=accent, accent_text=accent_text))
                    view.setPalette(root.palette())
                model = combo.model()
                if model is not None:
                    foreground = QtGui.QBrush(QtGui.QColor(text))
                    background = QtGui.QBrush(QtGui.QColor(menu_bg))
                    for row in range(int(combo.count())):
                        index = model.index(row, 0)
                        model.setData(index, foreground, QtCore.Qt.ForegroundRole)
                        model.setData(index, background, QtCore.Qt.BackgroundRole)
        except RuntimeError:
            return

    def build_runtime_widget(self, root=None):
        existing = self.audio_story_tab_widget
        if existing is not None:
            return existing
        if root is not None:
            bound = self._bind_designer_runtime_widget(root)
            if bound is not None:
                return bound
        raise RuntimeError("Audio Story Mode requires its Designer .ui file; runtime fallback UI is disabled.")

    def _ui_child(self, root, object_name, cls=None):
        if root is None:
            return None
        widget = root.findChild(QtCore.QObject, str(object_name))
        if widget is None:
            return None
        if cls is not None and not isinstance(widget, cls):
            return None
        return widget

    def _set_audio_story_tooltip(self, widget, text):
        text = str(text or "").strip()
        if widget is None or not text:
            return
        for setter_name in ("setToolTip", "setStatusTip", "setWhatsThis"):
            setter = getattr(widget, setter_name, None)
            if callable(setter):
                try:
                    setter(text)
                except Exception:
                    pass

    def _apply_audio_story_tooltips(self, root):
        if root is None:
            return
        for object_name, tooltip in _AUDIO_STORY_CONTROL_TOOLTIPS.items():
            self._set_audio_story_tooltip(root.findChild(QtCore.QObject, str(object_name)), tooltip)

    def _bind_designer_runtime_widget(self, root):
        # The Designer shell owns fixed layout. Runtime code only binds behavior
        # and still creates data-driven rows such as style presets and prompt caps.
        path_edit = self._ui_child(root, "audio_story_path_edit", QtWidgets.QLineEdit)
        import_button = self._ui_child(root, "audio_story_import_button", QtWidgets.QPushButton)
        transcribe_button = self._ui_child(root, "audio_story_transcribe_button", QtWidgets.QPushButton)
        if any(item is None for item in (path_edit, import_button, transcribe_button)):
            return None

        root.setObjectName("audio_story_mode_tab")
        self._capture_audio_story_designer_styles(root)
        root.setEnabled(True)
        self.audio_story_tab_widget = root
        self.audio_story_scroll_area = self._ui_child(root, "audio_story_scroll_area", QtWidgets.QScrollArea)
        if self.audio_story_scroll_area is not None:
            self.audio_story_scroll_area.setEnabled(True)
            self.audio_story_scroll_area.setWidgetResizable(True)
            try:
                self.audio_story_scroll_area.viewport().installEventFilter(self)
            except Exception:
                pass
        scroll_content = self._ui_child(root, "audio_story_scroll_content", QtWidgets.QWidget)
        if scroll_content is not None:
            scroll_content.setEnabled(True)
        self._install_audio_story_interaction_filters(root)
        QtCore.QTimer.singleShot(0, self._force_audio_story_runtime_enabled)
        QtCore.QTimer.singleShot(250, self._force_audio_story_runtime_enabled)

        compact_button_style = self._audio_story_compact_button_style()
        style_button_style = (
            "QPushButton { padding: 6px 10px; }"
            "QPushButton:checked { background: #4d8dff; color: white; border: 1px solid #6a95ff; }"
        )

        self.audio_story_path_edit = path_edit
        self.audio_story_path_edit.setReadOnly(True)
        self.audio_story_path_edit.setPlaceholderText("Import an audiobook or story audio file...")
        self.audio_story_import_button = import_button
        self.audio_story_import_button.setStyleSheet(compact_button_style)
        self.audio_story_import_button.clicked.connect(self._choose_audio_file)

        self.audio_story_playback_mode_combo = self._ui_child(root, "audio_story_playback_mode_combo", QtWidgets.QComboBox)
        if self.audio_story_playback_mode_combo is not None:
            self.audio_story_playback_mode_combo.addItems(["Play Imported Audio", "Use TTS Narration"])
            self.audio_story_playback_mode_combo.currentTextChanged.connect(self._on_playback_mode_changed)
            combo_index = self.audio_story_playback_mode_combo.findText(str(self._stored_playback_mode_label or "").strip())
            if combo_index >= 0:
                self.audio_story_playback_mode_combo.setCurrentIndex(combo_index)

        self.audio_story_cost_profile_combo = self._ui_child(root, "audio_story_cost_profile_combo", QtWidgets.QComboBox)
        if self.audio_story_cost_profile_combo is not None:
            for profile in _audio_story_cost_profiles():
                self.audio_story_cost_profile_combo.addItem(str(profile.get("label") or str(profile.get("id") or "").title()), str(profile.get("id") or "").strip().lower())
            self.audio_story_cost_profile_combo.addItem("Custom", "custom")
            self.audio_story_cost_profile_combo.currentIndexChanged.connect(self._on_audio_story_cost_profile_changed)

        self.audio_story_settings_preset_combo = self._ui_child(root, "audio_story_settings_preset_combo", QtWidgets.QComboBox)
        if self.audio_story_settings_preset_combo is not None:
            self.audio_story_settings_preset_combo.setEditable(True)
        self.audio_story_settings_preset_save_button = self._ui_child(root, "audio_story_settings_preset_save_button", QtWidgets.QPushButton)
        if self.audio_story_settings_preset_save_button is not None:
            self.audio_story_settings_preset_save_button.setStyleSheet(compact_button_style)
            self.audio_story_settings_preset_save_button.clicked.connect(self._save_audio_story_settings_preset)
        self.audio_story_settings_preset_load_button = self._ui_child(root, "audio_story_settings_preset_load_button", QtWidgets.QPushButton)
        if self.audio_story_settings_preset_load_button is not None:
            self.audio_story_settings_preset_load_button.setStyleSheet(compact_button_style)
            self.audio_story_settings_preset_load_button.clicked.connect(self._load_audio_story_settings_preset)

        self.audio_story_transcribe_seconds_slider = self._ui_child(root, "audio_story_transcribe_seconds_slider", QtWidgets.QSlider)
        if self.audio_story_transcribe_seconds_slider is not None:
            self.audio_story_transcribe_seconds_slider.setRange(1, max(8, int(self._stored_transcribe_seconds or 8)))
            self.audio_story_transcribe_seconds_slider.setValue(max(1, int(self._stored_transcribe_seconds or 8)))
            self.audio_story_transcribe_seconds_slider.valueChanged.connect(self._on_transcribe_seconds_changed)
        self.audio_story_transcribe_seconds_label = self._ui_child(root, "audio_story_transcribe_seconds_label", QtWidgets.QLabel)
        if self.audio_story_transcribe_seconds_label is not None:
            self.audio_story_transcribe_seconds_label.setText("Transcription Granularity")
        self.audio_story_transcribe_seconds_value_label = self._ui_child(root, "audio_story_transcribe_seconds_value_label", QtWidgets.QLabel)
        self.audio_story_transcription_start_spin = self._ui_child(root, "audio_story_transcription_start_spin", QtWidgets.QSpinBox)
        self.audio_story_transcription_end_spin = self._ui_child(root, "audio_story_transcription_end_spin", QtWidgets.QSpinBox)
        for spin in (self.audio_story_transcription_start_spin, self.audio_story_transcription_end_spin):
            if spin is not None:
                spin.setSuffix(" s")
                spin.valueChanged.connect(self._on_transcription_range_changed)

        self.audio_story_image_frequency_slider = self._ui_child(root, "audio_story_image_frequency_slider", QtWidgets.QSlider)
        if self.audio_story_image_frequency_slider is not None:
            self.audio_story_image_frequency_slider.setRange(1, 60)
            self.audio_story_image_frequency_slider.setValue(max(1, min(60, int(self._stored_image_frequency_seconds or 12))))
            self.audio_story_image_frequency_slider.valueChanged.connect(self._on_image_frequency_changed)
        self.audio_story_image_frequency_value_label = self._ui_child(root, "audio_story_image_frequency_value_label", QtWidgets.QLabel)

        self.audio_story_image_timing_combo = self._ui_child(root, "audio_story_image_timing_combo", QtWidgets.QComboBox)
        if self.audio_story_image_timing_combo is not None:
            self.audio_story_image_timing_combo.addItem("Fixed Seconds", "fixed")
            self.audio_story_image_timing_combo.addItem("Scene Changes", "scene_changes")
            self.audio_story_image_timing_combo.currentIndexChanged.connect(self._on_image_timing_mode_changed)

        self.audio_story_continuity_slider = self._ui_child(root, "audio_story_continuity_slider", QtWidgets.QSlider)
        if self.audio_story_continuity_slider is not None:
            self.audio_story_continuity_slider.setRange(0, 100)
            self.audio_story_continuity_slider.setSingleStep(1)
            self.audio_story_continuity_slider.setPageStep(5)
            self.audio_story_continuity_slider.setValue(int(round(float(self._stored_continuity_strength or 0.8) * 100.0)))
            self.audio_story_continuity_slider.valueChanged.connect(self._on_continuity_strength_changed)
        self.audio_story_continuity_value_label = self._ui_child(root, "audio_story_continuity_value_label", QtWidgets.QLabel)

        self.audio_story_style_buttons = {}
        self.audio_story_style_edits = {}
        style_grid_widget = self._ui_child(root, "audio_story_style_grid_widget", QtWidgets.QWidget)
        style_layout = style_grid_widget.layout() if style_grid_widget is not None else None
        if style_layout is None:
            style_layout = self._ui_child(root, "audio_story_style_grid_layout", QtWidgets.QGridLayout)
        if style_layout is not None:
            style_layout.setHorizontalSpacing(10)
            style_layout.setVerticalSpacing(6)
            for style_index, style_def in enumerate(_audio_story_style_presets()):
                style_id = str(style_def.get("id") or "").strip().lower()
                row_group = style_index // 2
                column = style_index % 2
                button_row = row_group * 2
                edit_row = button_row + 1
                style_label = self._audio_story_style_label(style_def)
                button = QtWidgets.QPushButton(style_label)
                button.setCheckable(True)
                button.setStyleSheet(style_button_style)
                button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                self._set_audio_story_tooltip(
                    button,
                    f"Toggle the {style_label} style layer for generated story image prompts. Right-click to rename this button.",
                )
                button.toggled.connect(lambda checked, style_id=style_id: self._on_audio_story_style_toggled(style_id, checked))
                button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(lambda _pos, style_id=style_id: self._on_audio_story_style_label_edit_requested(style_id))
                edit = QtWidgets.QLineEdit()
                edit.setClearButtonEnabled(True)
                edit.setMinimumWidth(120)
                edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                self._set_audio_story_tooltip(
                    edit,
                    f"Prompt text injected when the {style_label} style layer is active.",
                )
                edit.editingFinished.connect(lambda style_id=style_id, edit=edit: self._on_audio_story_style_text_changed(style_id, edit.text()))
                style_layout.addWidget(button, button_row, column)
                style_layout.addWidget(edit, edit_row, column)
                style_layout.setColumnStretch(column, 1)
                self.audio_story_style_buttons[style_id] = button
                self.audio_story_style_edits[style_id] = edit

        self.audio_story_style_live_checkbox = self._ui_child(root, "audio_story_style_live_checkbox", QtWidgets.QCheckBox)
        if self.audio_story_style_live_checkbox is not None:
            self.audio_story_style_live_checkbox.toggled.connect(self._on_audio_story_style_live_changed)
        self.audio_story_master_prompt_button = self._ui_child(root, "audio_story_master_prompt_button", QtWidgets.QPushButton)
        if self.audio_story_master_prompt_button is not None:
            self.audio_story_master_prompt_button.setCheckable(True)
            self.audio_story_master_prompt_button.setChecked(bool(self._stored_story_master_prompt_enabled))
            self.audio_story_master_prompt_button.setStyleSheet(style_button_style)
            self.audio_story_master_prompt_button.toggled.connect(self._on_story_master_prompt_toggled)
        self.audio_story_master_prompt_mode_combo = self._ui_child(root, "audio_story_master_prompt_mode_combo", QtWidgets.QComboBox)
        if self.audio_story_master_prompt_mode_combo is not None:
            for value, label in _audio_story_master_prompt_modes():
                self.audio_story_master_prompt_mode_combo.addItem(label, value)
            current_mode_index = self.audio_story_master_prompt_mode_combo.findData(str(self._stored_story_master_prompt_mode or "medium").strip().lower())
            if current_mode_index >= 0:
                self.audio_story_master_prompt_mode_combo.setCurrentIndex(current_mode_index)
            self.audio_story_master_prompt_mode_combo.currentIndexChanged.connect(self._on_story_master_prompt_mode_changed)

        self.audio_story_llm_analysis_checkbox = self._ui_child(root, "audio_story_llm_analysis_checkbox", QtWidgets.QCheckBox)
        if self.audio_story_llm_analysis_checkbox is not None:
            self.audio_story_llm_analysis_checkbox.toggled.connect(self._on_llm_story_analysis_toggled)
        self.audio_story_analysis_mode_combo = self._ui_child(root, "audio_story_analysis_mode_combo", QtWidgets.QComboBox)
        if self.audio_story_analysis_mode_combo is not None:
            self.audio_story_analysis_mode_combo.addItem("Scene Only", "scene_only")
            self.audio_story_analysis_mode_combo.addItem("Story Bible", "story_bible")
            self.audio_story_analysis_mode_combo.currentIndexChanged.connect(self._on_audio_story_analysis_mode_changed)
        self.audio_story_analysis_provider_combo = self._ui_child(root, "audio_story_analysis_provider_combo", QtWidgets.QComboBox)
        if self.audio_story_analysis_provider_combo is not None:
            self.audio_story_analysis_provider_combo.addItem("Current Chat Provider", "current")
            self.audio_story_analysis_provider_combo.addItem("DeepSeek", "deepseek")
            self.audio_story_analysis_provider_combo.addItem("Local LM Studio", "lmstudio")
            self.audio_story_analysis_provider_combo.currentIndexChanged.connect(self._on_story_analysis_provider_mode_changed)
        self.audio_story_analysis_model_combo = self._ui_child(root, "audio_story_analysis_model_combo", QtWidgets.QComboBox)
        if self.audio_story_analysis_model_combo is not None:
            self.audio_story_analysis_model_combo.setEditable(True)
            self.audio_story_analysis_model_combo.addItem("Auto", "")
            self.audio_story_analysis_model_combo.currentIndexChanged.connect(self._on_story_analysis_model_changed)
            line_edit = self.audio_story_analysis_model_combo.lineEdit()
            if line_edit is not None:
                line_edit.editingFinished.connect(self._on_story_analysis_model_edit_finished)
        self._bind_xai_image_settings_controls(root)

        self.audio_story_prompt_limit_spins = {}
        prompt_limits_widget = self._ui_child(root, "audio_story_prompt_limits_widget", QtWidgets.QWidget)
        prompt_limits_layout = prompt_limits_widget.layout() if prompt_limits_widget is not None else None
        if prompt_limits_layout is not None:
            for limit_index, (limit_key, default_value) in enumerate(_AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS.items()):
                row = limit_index // 2
                column = (limit_index % 2) * 2
                label = QtWidgets.QLabel(limit_key.replace("_", " ").title())
                spin = _AudioStoryNoWheelSpinBox()
                tooltip = (
                    f"Maximum characters allowed for the {limit_key.replace('_', ' ')} prompt block. "
                    "Lower values reduce prompt size; higher values preserve more detail."
                )
                self._set_audio_story_tooltip(label, tooltip)
                self._set_audio_story_tooltip(spin, tooltip)
                spin.setRange(40, 1600)
                spin.setSingleStep(20)
                spin.setValue(int(self._stored_prompt_block_limits.get(limit_key, default_value) or default_value))
                spin.setSuffix(" chars")
                spin.valueChanged.connect(lambda value, limit_key=limit_key: self._on_prompt_block_limit_changed(limit_key, value))
                prompt_limits_layout.addWidget(label, row, column)
                prompt_limits_layout.addWidget(spin, row, column + 1)
                prompt_limits_layout.setColumnStretch(column + 1, 1)
                self.audio_story_prompt_limit_spins[limit_key] = spin
        self.audio_story_prompt_safety_cap_spin = self._ui_child(root, "audio_story_prompt_safety_cap_spin", QtWidgets.QSpinBox)
        if self.audio_story_prompt_safety_cap_spin is not None:
            self.audio_story_prompt_safety_cap_spin.setRange(400, 6000)
            self.audio_story_prompt_safety_cap_spin.setSingleStep(100)
            self.audio_story_prompt_safety_cap_spin.setValue(int(self._stored_prompt_safety_cap or _AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT))
            self.audio_story_prompt_safety_cap_spin.setSuffix(" chars")
            self.audio_story_prompt_safety_cap_spin.valueChanged.connect(self._on_prompt_safety_cap_changed)
        self.audio_story_generate_ahead_slider = self._ui_child(root, "audio_story_generate_ahead_slider", QtWidgets.QSlider)
        if self.audio_story_generate_ahead_slider is not None:
            self.audio_story_generate_ahead_slider.setRange(0, 12)
            self.audio_story_generate_ahead_slider.setValue(max(0, int(self._stored_generate_ahead_frames or 0)))
            self.audio_story_generate_ahead_slider.valueChanged.connect(self._on_generate_ahead_frames_changed)
        self.audio_story_generate_ahead_value_label = self._ui_child(root, "audio_story_generate_ahead_value_label", QtWidgets.QLabel)

        self.audio_story_transcribe_button = transcribe_button
        self.audio_story_transcribe_button.setStyleSheet(compact_button_style)
        self.audio_story_transcribe_button.clicked.connect(self._start_transcription)
        self.audio_story_transcription_progress_bar = self._ui_child(root, "audio_story_transcription_progress_bar", QtWidgets.QProgressBar)
        if self.audio_story_transcription_progress_bar is not None:
            self.audio_story_transcription_progress_bar.setRange(0, 100)
            self.audio_story_transcription_progress_bar.setValue(0)
            self.audio_story_transcription_progress_bar.setTextVisible(True)

        self.audio_story_scene_status_label = self._ui_child(root, "audio_story_scene_status_label", QtWidgets.QLabel)
        self.audio_story_scene_character_button_row = self._ui_child(root, "audio_story_scene_character_grid", QtWidgets.QGridLayout)
        self.audio_story_pin_location_button = self._ui_child(root, "audio_story_pin_location_button", QtWidgets.QPushButton)
        if self.audio_story_pin_location_button is not None:
            self.audio_story_pin_location_button.setCheckable(True)
            self.audio_story_pin_location_button.setStyleSheet(compact_button_style)
            self.audio_story_pin_location_button.toggled.connect(self._on_pin_location_toggled)
        self.audio_story_force_fresh_button = self._ui_child(root, "audio_story_force_fresh_button", QtWidgets.QPushButton)
        if self.audio_story_force_fresh_button is not None:
            self.audio_story_force_fresh_button.setCheckable(True)
            self.audio_story_force_fresh_button.setStyleSheet(compact_button_style)
            self.audio_story_force_fresh_button.toggled.connect(lambda checked: self._on_force_scene_mode_changed("fresh", checked))
        self.audio_story_force_continuation_button = self._ui_child(root, "audio_story_force_continuation_button", QtWidgets.QPushButton)
        if self.audio_story_force_continuation_button is not None:
            self.audio_story_force_continuation_button.setCheckable(True)
            self.audio_story_force_continuation_button.setStyleSheet(compact_button_style)
            self.audio_story_force_continuation_button.toggled.connect(lambda checked: self._on_force_scene_mode_changed("continuation", checked))
        self.audio_story_scene_anchor_edit = self._ui_child(root, "audio_story_scene_anchor_edit", QtWidgets.QPlainTextEdit)
        self.audio_story_scene_anchor_apply_button = self._ui_child(root, "audio_story_scene_anchor_apply_button", QtWidgets.QPushButton)
        if self.audio_story_scene_anchor_apply_button is not None:
            self.audio_story_scene_anchor_apply_button.setStyleSheet(compact_button_style)
            self.audio_story_scene_anchor_apply_button.clicked.connect(self._apply_scene_anchor_override)
        self.audio_story_scene_negative_prompt_edit = self._ui_child(root, "audio_story_scene_negative_prompt_edit", QtWidgets.QPlainTextEdit)
        self.audio_story_negative_prompt_anchor_button = self._ui_child(root, "audio_story_negative_prompt_anchor_button", QtWidgets.QPushButton)
        if self.audio_story_negative_prompt_anchor_button is not None:
            self.audio_story_negative_prompt_anchor_button.setCheckable(True)
            self.audio_story_negative_prompt_anchor_button.setChecked(bool(self.scene_overrides.get("global_negative_prompt_enabled", False)))
            self.audio_story_negative_prompt_anchor_button.setStyleSheet(compact_button_style)
            self.audio_story_negative_prompt_anchor_button.toggled.connect(self._on_negative_prompt_anchor_toggled)
        self.audio_story_scene_negative_prompt_apply_button = self._ui_child(root, "audio_story_scene_negative_prompt_apply_button", QtWidgets.QPushButton)
        if self.audio_story_scene_negative_prompt_apply_button is not None:
            self.audio_story_scene_negative_prompt_apply_button.setStyleSheet(compact_button_style)
            self.audio_story_scene_negative_prompt_apply_button.clicked.connect(self._apply_scene_negative_prompt_override)

        self.audio_story_play_button = self._ui_child(root, "audio_story_play_button", QtWidgets.QPushButton)
        if self.audio_story_play_button is not None:
            self.audio_story_play_button.setStyleSheet(self._audio_story_playback_button_style("play"))
            self.audio_story_play_button.clicked.connect(self._play_story)
        self.audio_story_pause_button = self._ui_child(root, "audio_story_pause_button", QtWidgets.QPushButton)
        if self.audio_story_pause_button is not None:
            self.audio_story_pause_button.setStyleSheet(self._audio_story_playback_button_style("pause"))
            self.audio_story_pause_button.clicked.connect(self._pause_story)
        self.audio_story_stop_button = self._ui_child(root, "audio_story_stop_button", QtWidgets.QPushButton)
        if self.audio_story_stop_button is not None:
            self.audio_story_stop_button.setStyleSheet(self._audio_story_playback_button_style("stop"))
            self.audio_story_stop_button.clicked.connect(self._stop_story)
        self.audio_story_time_label = self._ui_child(root, "audio_story_time_label", QtWidgets.QLabel)
        self.audio_story_position_slider = self._ui_child(root, "audio_story_position_slider", QtWidgets.QSlider)
        if self.audio_story_position_slider is not None:
            self.audio_story_position_slider.setRange(0, 0)
            self.audio_story_position_slider.sliderPressed.connect(self._on_slider_pressed)
            self.audio_story_position_slider.sliderReleased.connect(self._on_slider_released)
            self.audio_story_position_slider.sliderMoved.connect(self._on_slider_moved)
        self.audio_story_status_label = self._ui_child(root, "audio_story_status_label", QtWidgets.QLabel)
        self.audio_story_stream_enabled_checkbox = self._ui_child(root, "audio_story_stream_enabled_checkbox", QtWidgets.QCheckBox)
        if self.audio_story_stream_enabled_checkbox is not None:
            self.audio_story_stream_enabled_checkbox.toggled.connect(self._on_visual_stream_toggled)
        self.audio_story_stream_port_spin = self._ui_child(root, "audio_story_stream_port_spin", QtWidgets.QSpinBox)
        if self.audio_story_stream_port_spin is not None:
            self.audio_story_stream_port_spin.setRange(1024, 65535)
            self.audio_story_stream_port_spin.setValue(int(self._stored_visual_stream_port or 8765))
            self.audio_story_stream_port_spin.valueChanged.connect(self._on_visual_stream_port_changed)
        self.audio_story_stream_url_label = self._ui_child(root, "audio_story_stream_url_label", QtWidgets.QLabel)
        self.audio_story_cast_prompt_checkbox = self._ui_child(root, "audio_story_cast_prompt_checkbox", QtWidgets.QCheckBox)
        if self.audio_story_cast_prompt_checkbox is not None:
            self.audio_story_cast_prompt_checkbox.setChecked(bool(self._stored_chromecast_show_prompt))
            self.audio_story_cast_prompt_checkbox.toggled.connect(self._on_chromecast_show_prompt_toggled)
        self.audio_story_cast_device_combo = self._ui_child(root, "audio_story_cast_device_combo", QtWidgets.QComboBox)
        if self.audio_story_cast_device_combo is not None:
            self.audio_story_cast_device_combo.currentIndexChanged.connect(self._on_chromecast_device_changed)
        self.audio_story_cast_refresh_button = self._ui_child(root, "audio_story_cast_refresh_button", QtWidgets.QPushButton)
        if self.audio_story_cast_refresh_button is not None:
            self.audio_story_cast_refresh_button.setStyleSheet(compact_button_style)
            self.audio_story_cast_refresh_button.clicked.connect(self._refresh_chromecast_devices)
        self.audio_story_cast_install_button = self._ui_child(root, "audio_story_cast_install_button", QtWidgets.QPushButton)
        if self.audio_story_cast_install_button is None:
            self.audio_story_cast_install_button = QtWidgets.QPushButton("Install PyChromecast")
            self.audio_story_cast_install_button.setObjectName("audio_story_cast_install_button")
            status_parent = root.findChild(QtWidgets.QWidget, "audio_story_cast_status_label")
            parent_widget = status_parent.parentWidget() if status_parent is not None else None
            parent_layout = parent_widget.layout() if parent_widget is not None else None
            if parent_layout is not None:
                parent_layout.addWidget(self.audio_story_cast_install_button)
        if self.audio_story_cast_install_button is not None:
            self.audio_story_cast_install_button.setStyleSheet(compact_button_style)
            self.audio_story_cast_install_button.clicked.connect(self._install_chromecast_dependencies)
        self.audio_story_cast_button = self._ui_child(root, "audio_story_cast_button", QtWidgets.QPushButton)
        if self.audio_story_cast_button is not None:
            self.audio_story_cast_button.setStyleSheet(compact_button_style)
            self.audio_story_cast_button.clicked.connect(self._cast_current_visual_to_chromecast)
        self.audio_story_cast_stop_button = self._ui_child(root, "audio_story_cast_stop_button", QtWidgets.QPushButton)
        if self.audio_story_cast_stop_button is not None:
            self.audio_story_cast_stop_button.setStyleSheet(compact_button_style)
            self.audio_story_cast_stop_button.clicked.connect(self._stop_chromecast_cast)
        self.audio_story_cast_status_label = self._ui_child(root, "audio_story_cast_status_label", QtWidgets.QLabel)
        self.audio_story_summary_label = self._ui_child(root, "audio_story_summary_label", QtWidgets.QLabel)
        self.audio_story_transcript_edit = self._ui_child(root, "audio_story_transcript_edit", QtWidgets.QPlainTextEdit)
        if self.audio_story_transcript_edit is not None:
            self.audio_story_transcript_edit.setReadOnly(True)
            self.audio_story_transcript_edit.setMinimumHeight(160)

        if self.imported_audio_path:
            self.audio_story_path_edit.setText(str(self.imported_audio_path))
        self._sync_transcribe_seconds_slider()
        self._sync_transcription_range_controls()
        self._sync_image_frequency_slider()
        self._sync_image_timing_mode_controls()
        self._sync_continuity_slider()
        self._sync_generate_ahead_slider()
        self._sync_audio_story_style_controls()
        self._sync_story_master_prompt_controls()
        self._sync_audio_story_analysis_mode_controls()
        self._sync_llm_story_analysis_controls()
        self._sync_xai_image_settings_controls()
        self._sync_prompt_block_limit_controls()
        self._sync_prompt_safety_cap_control()
        self._sync_visual_stream_controls()
        self._sync_audio_story_cost_profile_controls()
        self._refresh_audio_story_settings_presets()
        self._refresh_controls()
        self._apply_audio_story_tooltips(root)
        self.apply_theme_palette()
        return root

    def _audio_story_compact_button_style(self):
        return (
            "QPushButton { "
            "padding: 6px 12px; "
            "min-height: 30px; "
            "border-radius: 10px; "
            "background: #22344c; "
            "border: 1px solid #35506c; "
            "color: #f2f5f9; "
            "font-weight: 600; "
            "}"
            "QPushButton:hover { background: #2a4160; border: 1px solid #4d6c8f; } "
            "QPushButton:pressed { background: #1d2e43; } "
            "QPushButton:disabled { background: #17212e; color: #71839a; border: 1px solid #243345; }"
        )

    def _reset_story_consistency_state(self):
        self.story_bible = {}
        self.scene_plan = []
        self.scene_overrides = {
            "pinned_character_ids": [],
            "pinned_location_ids": [],
            "forced_scene_modes": {},
            "scene_anchor_overrides": {},
            "scene_negative_prompt_overrides": {},
            "global_negative_prompt": "",
            "global_negative_prompt_enabled": False,
        }
        self.continuity_memory = {
            "last_scene_id": "",
            "last_scene_index": -1,
            "last_generated_image_path": "",
            "last_prompt_signature": "",
            "last_prompt_text": "",
            "scenes": {},
            "characters": {},
            "locations": {},
        }
        self.character_anchors = {}
        self.location_anchors = {}

    def _normalize_image_timing_mode(self, value=None):
        normalized = str(value if value is not None else self._stored_image_timing_mode or "fixed").strip().lower()
        return normalized if normalized in {"fixed", "scene_changes"} else "fixed"

    def _image_timing_mode(self):
        self._stored_image_timing_mode = self._normalize_image_timing_mode()
        return str(self._stored_image_timing_mode or "fixed")

    def _sync_image_timing_mode_controls(self):
        combo = getattr(self, "audio_story_image_timing_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            target_index = combo.findData(self._image_timing_mode())
            if target_index >= 0:
                combo.setCurrentIndex(target_index)
        finally:
            combo.blockSignals(False)

    def _normalize_image_frequency_seconds(self, value=None):
        try:
            seconds = int(value if value is not None else self._stored_image_frequency_seconds or 12)
        except Exception:
            seconds = 12
        return max(1, min(60, seconds))

    def _audio_story_cost_profile_snapshot(self, profile_def=None):
        profile = dict(profile_def or {})
        return {
            "transcribe_seconds": max(1, int(profile.get("transcribe_seconds", self._stored_transcribe_seconds) or self._stored_transcribe_seconds or 8)),
            "image_frequency_seconds": self._normalize_image_frequency_seconds(profile.get("image_frequency_seconds", self._stored_image_frequency_seconds)),
            "image_timing_mode": self._normalize_image_timing_mode(profile.get("image_timing_mode", self._stored_image_timing_mode)),
            "generate_ahead_frames": max(0, int(profile.get("generate_ahead_frames", self._stored_generate_ahead_frames) or self._stored_generate_ahead_frames or 0)),
            "continuity_strength": round(float(self._normalize_continuity_strength(profile.get("continuity_strength", self._stored_continuity_strength))), 3),
            "master_prompt_enabled": bool(profile.get("master_prompt_enabled", self._stored_story_master_prompt_enabled)),
            "master_prompt_mode": str(profile.get("master_prompt_mode", self._stored_story_master_prompt_mode or "medium") or self._stored_story_master_prompt_mode or "medium").strip().lower(),
            "use_llm_story_analysis": bool(profile.get("use_llm_story_analysis", self._stored_use_llm_story_analysis)),
            "story_analysis_provider_mode": self._normalize_story_analysis_provider_mode(profile.get("story_analysis_provider_mode", self._stored_story_analysis_provider_mode)),
            "prompt_block_limits": self._normalize_prompt_block_limits(profile.get("prompt_block_limits", self._stored_prompt_block_limits)),
            "prompt_safety_cap": int(self._normalize_prompt_safety_cap(profile.get("prompt_safety_cap", self._stored_prompt_safety_cap))),
        }

    def _current_audio_story_cost_profile_snapshot(self):
        return {
            "transcribe_seconds": max(1, int(self._stored_transcribe_seconds or 8)),
            "image_frequency_seconds": self._normalize_image_frequency_seconds(),
            "image_timing_mode": self._image_timing_mode(),
            "generate_ahead_frames": max(0, int(self._stored_generate_ahead_frames or 0)),
            "continuity_strength": round(float(self._normalize_continuity_strength(self._stored_continuity_strength)), 3),
            "master_prompt_enabled": bool(self._stored_story_master_prompt_enabled),
            "master_prompt_mode": self._audio_story_master_prompt_mode(),
            "use_llm_story_analysis": bool(self._stored_use_llm_story_analysis),
            "story_analysis_provider_mode": self._story_analysis_provider_mode(),
            "prompt_block_limits": self._normalize_prompt_block_limits(self._stored_prompt_block_limits),
            "prompt_safety_cap": int(self._normalize_prompt_safety_cap(self._stored_prompt_safety_cap)),
        }

    def _detect_audio_story_cost_profile_id(self):
        current = self._current_audio_story_cost_profile_snapshot()
        for profile in _audio_story_cost_profiles():
            if current == self._audio_story_cost_profile_snapshot(profile):
                return str(profile.get("id") or "").strip().lower()
        return "custom"

    def _sync_audio_story_cost_profile_controls(self):
        combo = getattr(self, "audio_story_cost_profile_combo", None)
        if combo is None:
            return
        resolved_profile = self._detect_audio_story_cost_profile_id()
        self._stored_cost_profile_id = resolved_profile if resolved_profile != "custom" else str(self._stored_cost_profile_id or "custom")
        combo.blockSignals(True)
        try:
            target_index = combo.findData(resolved_profile)
            if target_index < 0:
                target_index = combo.findData("custom")
            if target_index >= 0:
                combo.setCurrentIndex(target_index)
            description = ""
            if resolved_profile != "custom":
                description = str(_audio_story_cost_profile_definition(resolved_profile).get("description", "") or "").strip()
            combo.setToolTip(
                description
                or "Custom mix of Audio Story precision settings. Choose a named profile again to snap back to a preset."
            )
        finally:
            combo.blockSignals(False)

    def _apply_audio_story_cost_profile(self, profile_id: str, *, rebuild_story: bool = True):
        profile = _audio_story_cost_profile_definition(profile_id)
        if not profile:
            self._sync_audio_story_cost_profile_controls()
            return False
        snapshot = self._audio_story_cost_profile_snapshot(profile)
        self._stored_cost_profile_id = str(profile.get("id") or "balanced").strip().lower() or "balanced"
        self._stored_transcribe_seconds = int(snapshot["transcribe_seconds"])
        self._stored_image_frequency_seconds = int(snapshot["image_frequency_seconds"])
        self._stored_image_timing_mode = str(snapshot["image_timing_mode"] or "fixed")
        self._stored_generate_ahead_frames = int(snapshot["generate_ahead_frames"])
        self._stored_continuity_strength = float(snapshot["continuity_strength"])
        self._stored_story_master_prompt_enabled = bool(snapshot["master_prompt_enabled"])
        self._stored_story_master_prompt_mode = str(snapshot["master_prompt_mode"] or "medium").strip().lower() or "medium"
        self._stored_use_llm_story_analysis = bool(snapshot["use_llm_story_analysis"])
        self._stored_story_analysis_provider_mode = str(snapshot["story_analysis_provider_mode"] or "current").strip().lower() or "current"
        self._stored_prompt_block_limits = dict(snapshot["prompt_block_limits"] or {})
        self._stored_prompt_safety_cap = int(snapshot["prompt_safety_cap"])
        self._sync_transcribe_seconds_slider()
        self._sync_image_frequency_slider()
        self._sync_image_timing_mode_controls()
        self._sync_continuity_slider()
        self._sync_generate_ahead_slider()
        self._sync_story_master_prompt_controls()
        self._sync_llm_story_analysis_controls()
        self._sync_story_analysis_provider_controls()
        self._sync_prompt_block_limit_controls()
        self._sync_prompt_safety_cap_control()
        self._sync_audio_story_cost_profile_controls()
        if rebuild_story and self._raw_transcript_segments:
            status_text = (
                f"Analyzing story with {self._story_analysis_provider_status_label()}..."
                if self._stored_use_llm_story_analysis
                else "Rebuilding audio story analysis..."
            )
            self._start_story_payload_rebuild_job(status_text=status_text)
        else:
            self._sync_story_generated_master_prompt(refresh_visuals=False)
        self._refresh_controls()
        return True

    def _on_audio_story_cost_profile_changed(self, _index: int):
        combo = getattr(self, "audio_story_cost_profile_combo", None)
        if combo is None:
            return
        profile_id = str(combo.currentData() or "").strip().lower()
        if not profile_id or profile_id == "custom":
            self._sync_audio_story_cost_profile_controls()
            return
        self._apply_audio_story_cost_profile(profile_id, rebuild_story=True)

    def _audio_story_settings_preset_payload(self):
        return {
            "version": 1,
            "transcribe_seconds": max(1, int(self._stored_transcribe_seconds or 8)),
            "image_frequency_seconds": self._normalize_image_frequency_seconds(),
            "image_timing_mode": self._image_timing_mode(),
            "generate_ahead_frames": max(0, int(self._stored_generate_ahead_frames or 0)),
            "continuity_strength": float(self._normalize_continuity_strength(self._stored_continuity_strength)),
            "cost_profile": str(self._detect_audio_story_cost_profile_id() or self._stored_cost_profile_id or "balanced"),
            "style_prompts": dict(self._stored_style_prompts or {}),
            "style_labels": dict(self._stored_style_labels or {}),
            "style_enabled": list(self._stored_style_enabled or []),
            "style_change_live": bool(self._stored_style_change_live),
            "story_master_prompt_enabled": bool(self._stored_story_master_prompt_enabled),
            "story_master_prompt_mode": self._audio_story_master_prompt_mode(),
            "audio_story_analysis_mode": self._audio_story_analysis_mode(),
            "use_llm_story_analysis": bool(self._stored_use_llm_story_analysis),
            "story_analysis_provider_mode": self._story_analysis_provider_mode(),
            "story_analysis_model": self._story_analysis_model_override(),
            "xai_image_settings": self._current_xai_image_settings(),
            "prompt_block_limits": self._prompt_block_limits(),
            "prompt_safety_cap": int(self._stored_prompt_safety_cap or _AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT),
            "playback_mode": str(self.audio_story_playback_mode_combo.currentText() or "Play Imported Audio") if hasattr(self, "audio_story_playback_mode_combo") else str(self._stored_playback_mode_label or "Play Imported Audio"),
        }

    def _apply_audio_story_settings_preset_payload(self, payload, *, rebuild_story: bool = True):
        data = dict(payload or {})
        try:
            self._stored_transcribe_seconds = max(1, int(data.get("transcribe_seconds", self._stored_transcribe_seconds) or self._stored_transcribe_seconds or 8))
        except Exception:
            pass
        self._stored_image_frequency_seconds = self._normalize_image_frequency_seconds(data.get("image_frequency_seconds", self._stored_image_frequency_seconds))
        self._stored_image_timing_mode = self._normalize_image_timing_mode(data.get("image_timing_mode", self._stored_image_timing_mode))
        try:
            self._stored_generate_ahead_frames = max(0, int(data.get("generate_ahead_frames", self._stored_generate_ahead_frames) or 0))
        except Exception:
            pass
        self._stored_continuity_strength = self._normalize_continuity_strength(data.get("continuity_strength", self._stored_continuity_strength))
        if isinstance(data.get("style_prompts"), dict):
            for style_def in _audio_story_style_presets():
                style_id = str(style_def.get("id") or "").strip().lower()
                if style_id:
                    self._stored_style_prompts[style_id] = str(data["style_prompts"].get(style_id, self._stored_style_prompts.get(style_id, style_def.get("prompt", ""))) or "").strip()
        if isinstance(data.get("style_labels"), dict):
            for style_def in _audio_story_style_presets():
                style_id = str(style_def.get("id") or "").strip().lower()
                if style_id:
                    default_label = str(style_def.get("label") or style_id.title())
                    self._stored_style_labels[style_id] = str(data["style_labels"].get(style_id, self._stored_style_labels.get(style_id, default_label)) or default_label).strip()
        if isinstance(data.get("style_enabled"), (list, tuple, set)):
            valid_ids = {str(item.get("id") or "").strip().lower() for item in _audio_story_style_presets()}
            self._stored_style_enabled = [str(item or "").strip().lower() for item in data.get("style_enabled", []) if str(item or "").strip().lower() in valid_ids]
        if data.get("style_change_live") is not None:
            self._stored_style_change_live = bool(data.get("style_change_live"))
        if data.get("story_master_prompt_enabled") is not None:
            self._stored_story_master_prompt_enabled = bool(data.get("story_master_prompt_enabled"))
        story_master_prompt_mode = str(data.get("story_master_prompt_mode") or "").strip().lower()
        if story_master_prompt_mode in {value for value, _label in _audio_story_master_prompt_modes()}:
            self._stored_story_master_prompt_mode = story_master_prompt_mode
        if data.get("audio_story_analysis_mode") is not None:
            self._stored_audio_story_analysis_mode = self._normalize_audio_story_analysis_mode(data.get("audio_story_analysis_mode"))
            audio_story_runtime.update_runtime_config("audio_story_analysis_mode", self._stored_audio_story_analysis_mode)
        if data.get("use_llm_story_analysis") is not None:
            self._stored_use_llm_story_analysis = bool(data.get("use_llm_story_analysis"))
        if data.get("story_analysis_provider_mode") is not None:
            self._stored_story_analysis_provider_mode = self._normalize_story_analysis_provider_mode(data.get("story_analysis_provider_mode"))
        if data.get("story_analysis_model") is not None:
            self._stored_story_analysis_model = self._normalize_story_analysis_model(data.get("story_analysis_model"))
        if isinstance(data.get("xai_image_settings"), dict):
            xai_settings = dict(data.get("xai_image_settings") or {})
            normalized_xai_settings = {
                "xai_image_aspect_ratio": self._normalize_xai_image_aspect_ratio(xai_settings.get("xai_image_aspect_ratio")),
                "xai_image_resolution": self._normalize_xai_image_resolution(xai_settings.get("xai_image_resolution")),
                "xai_image_response_format": self._normalize_xai_image_response_format(xai_settings.get("xai_image_response_format")),
                "xai_image_n": self._normalize_xai_image_n(xai_settings.get("xai_image_n")),
            }
            for key, value in normalized_xai_settings.items():
                audio_story_runtime.update_runtime_config(key, value)
        if isinstance(data.get("prompt_block_limits"), dict):
            self._stored_prompt_block_limits = self._normalize_prompt_block_limits(data.get("prompt_block_limits"))
        if data.get("prompt_safety_cap") is not None:
            self._stored_prompt_safety_cap = self._normalize_prompt_safety_cap(data.get("prompt_safety_cap"))
        playback_mode = str(data.get("playback_mode") or "").strip()
        if playback_mode:
            self._stored_playback_mode_label = playback_mode
        self._sync_transcribe_seconds_slider()
        self._sync_image_frequency_slider()
        self._sync_image_timing_mode_controls()
        self._sync_continuity_slider()
        self._sync_generate_ahead_slider()
        self._sync_audio_story_style_controls()
        self._sync_story_master_prompt_controls()
        self._sync_audio_story_analysis_mode_controls()
        self._sync_llm_story_analysis_controls()
        self._sync_story_analysis_provider_controls()
        self._sync_story_analysis_model_controls()
        self._sync_xai_image_settings_controls()
        self._sync_prompt_block_limit_controls()
        self._sync_prompt_safety_cap_control()
        if hasattr(self, "audio_story_playback_mode_combo") and playback_mode:
            index = self.audio_story_playback_mode_combo.findText(playback_mode)
            if index >= 0:
                self.audio_story_playback_mode_combo.setCurrentIndex(index)
        self._sync_audio_story_cost_profile_controls()
        if rebuild_story and self._raw_transcript_segments:
            status_text = (
                f"Analyzing story with {self._story_analysis_provider_status_label()}..."
                if self._stored_use_llm_story_analysis
                else "Rebuilding audio story analysis..."
            )
            self._start_story_payload_rebuild_job(status_text=status_text)
        else:
            self._sync_story_generated_master_prompt(refresh_visuals=False)
        self._refresh_controls()

    def _audio_story_preset_slug(self, name: str):
        slug = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(name or "").strip()).strip(" ._")
        return slug or "audio_story_preset"

    def _audio_story_settings_preset_path(self, name: str):
        return self._preset_root / f"{self._audio_story_preset_slug(name)}.json"

    def _audio_story_settings_preset_names(self):
        names = []
        try:
            for path in sorted(self._preset_root.glob("*.json"), key=lambda item: item.stem.lower()):
                names.append(path.stem)
        except Exception:
            return []
        return names

    def _refresh_audio_story_settings_presets(self):
        combo = getattr(self, "audio_story_settings_preset_combo", None)
        if combo is None:
            return
        current = str(combo.currentText() or "").strip()
        names = self._audio_story_settings_preset_names()
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(names)
            if current:
                index = combo.findText(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
                elif combo.isEditable():
                    combo.setEditText(current)
        finally:
            combo.blockSignals(False)
        load_button = getattr(self, "audio_story_settings_preset_load_button", None)
        if load_button is not None:
            load_button.setEnabled(bool(names))

    def _selected_audio_story_settings_preset_name(self):
        combo = getattr(self, "audio_story_settings_preset_combo", None)
        return str(combo.currentText() if combo is not None else "").strip()

    def _save_audio_story_settings_preset(self):
        name = self._selected_audio_story_settings_preset_name()
        if not name:
            name, accepted = QtWidgets.QInputDialog.getText(
                self.audio_story_tab_widget if self.audio_story_tab_widget is not None else None,
                "Save Audio Story Preset",
                "Preset name:",
                text="Audio Story Preset",
            )
            if not accepted:
                return
            name = str(name or "").strip()
        if not name:
            return
        path = self._audio_story_settings_preset_path(name)
        payload = self._audio_story_settings_preset_payload()
        payload["name"] = name
        payload["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._preset_root.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            self._set_status(f"Saved Audio Story preset: {name}")
        except Exception as exc:
            self._set_status(f"Failed to save Audio Story preset: {exc}")
            return
        self._refresh_audio_story_settings_presets()
        combo = getattr(self, "audio_story_settings_preset_combo", None)
        if combo is not None:
            index = combo.findText(path.stem)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _load_audio_story_settings_preset(self):
        name = self._selected_audio_story_settings_preset_name()
        if not name:
            self._set_status("Choose an Audio Story preset to load.")
            return
        path = self._audio_story_settings_preset_path(name)
        if not path.exists():
            self._set_status(f"Audio Story preset not found: {name}")
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._set_status(f"Failed to load Audio Story preset: {exc}")
            return
        self._apply_audio_story_settings_preset_payload(payload, rebuild_story=True)
        self._set_status(f"Loaded Audio Story preset: {name}")

    def export_session_state(self):
        flat_payload = {
            "audio_story_mode_audio_path": str(self.imported_audio_path or "").strip(),
            "audio_story_mode_transcribe_seconds": int(self.audio_story_transcribe_seconds_slider.value()) if hasattr(self, "audio_story_transcribe_seconds_slider") else int(self._stored_transcribe_seconds or 8),
            "audio_story_mode_transcription_start_seconds": int(self.audio_story_transcription_start_spin.value()) if hasattr(self, "audio_story_transcription_start_spin") else int(self._stored_transcription_start_seconds or 0),
            "audio_story_mode_transcription_end_seconds": int(self.audio_story_transcription_end_spin.value()) if hasattr(self, "audio_story_transcription_end_spin") else int(self._stored_transcription_end_seconds or 0),
            "audio_story_mode_image_frequency_seconds": self._normalize_image_frequency_seconds(int(self.audio_story_image_frequency_slider.value()) if hasattr(self, "audio_story_image_frequency_slider") else self._stored_image_frequency_seconds),
            "audio_story_mode_image_timing_mode": self._image_timing_mode(),
            "audio_story_mode_generate_ahead_frames": int(self._stored_generate_ahead_frames or 0),
            "audio_story_mode_continuity_strength": float(self._stored_continuity_strength or 0.8),
            "audio_story_mode_cost_profile": str(self._detect_audio_story_cost_profile_id() or self._stored_cost_profile_id or "balanced"),
            "audio_story_mode_style_prompts": dict(self._stored_style_prompts or {}),
            "audio_story_mode_style_labels": dict(self._stored_style_labels or {}),
            "audio_story_mode_style_enabled": list(self._stored_style_enabled or []),
            "audio_story_mode_style_change_live": bool(self._stored_style_change_live),
            "audio_story_mode_story_master_prompt_enabled": bool(self._stored_story_master_prompt_enabled),
            "audio_story_mode_story_master_prompt_mode": str(self._stored_story_master_prompt_mode or "medium"),
            "audio_story_mode_analysis_mode": self._audio_story_analysis_mode(),
            "audio_story_mode_use_llm_story_analysis": bool(self._stored_use_llm_story_analysis),
            "audio_story_mode_story_analysis_provider_mode": self._story_analysis_provider_mode(),
            "audio_story_mode_story_analysis_model": self._story_analysis_model_override(),
            "audio_story_mode_xai_image_settings": self._current_xai_image_settings(),
            "audio_story_mode_prompt_block_limits": self._prompt_block_limits(),
            "audio_story_mode_prompt_safety_cap": int(self._stored_prompt_safety_cap or _AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT),
            "audio_story_mode_visual_stream_enabled": bool(self._stored_visual_stream_enabled),
            "audio_story_mode_visual_stream_port": int(self._stored_visual_stream_port or 8765),
            "audio_story_mode_chromecast_device_name": str(self._stored_chromecast_device_name or "").strip(),
            "audio_story_mode_chromecast_cast_active": bool(self._stored_chromecast_cast_active),
            "audio_story_mode_chromecast_show_prompt": bool(self._stored_chromecast_show_prompt),
            "audio_story_mode_playback_mode": str(self.audio_story_playback_mode_combo.currentText() or "Play Imported Audio") if hasattr(self, "audio_story_playback_mode_combo") else "Play Imported Audio",
        }
        return audio_story_mode_session_payload(flat_payload)

    def import_session_state(self, session):
        payload = flatten_audio_story_mode_settings(session or {})
        audio_path = str(payload.get("audio_story_mode_audio_path") or "").strip()
        if audio_path:
            self.imported_audio_path = audio_path
            self._refresh_imported_audio_duration()
        if audio_path and hasattr(self, "audio_story_path_edit"):
            self.audio_story_path_edit.setText(audio_path)
        if audio_path:
            self._sync_transcribe_seconds_slider()
            self._sync_image_frequency_slider()
        seconds_value = payload.get("audio_story_mode_transcribe_seconds")
        if seconds_value is not None:
            try:
                self._stored_transcribe_seconds = max(1, int(seconds_value or 8))
                self._sync_transcribe_seconds_slider()
            except Exception:
                pass
        start_value = payload.get("audio_story_mode_transcription_start_seconds")
        if start_value is not None:
            try:
                self._stored_transcription_start_seconds = max(0, int(start_value or 0))
            except Exception:
                pass
        end_value = payload.get("audio_story_mode_transcription_end_seconds")
        if end_value is not None:
            try:
                self._stored_transcription_end_seconds = max(0, int(end_value or 0))
            except Exception:
                pass
        if start_value is not None or end_value is not None or audio_path:
            self._sync_transcription_range_controls()
        image_frequency_value = payload.get("audio_story_mode_image_frequency_seconds")
        if image_frequency_value is not None:
            try:
                self._stored_image_frequency_seconds = self._normalize_image_frequency_seconds(image_frequency_value)
                self._sync_image_frequency_slider()
            except Exception:
                pass
        image_timing_mode = payload.get("audio_story_mode_image_timing_mode")
        if image_timing_mode is not None:
            self._stored_image_timing_mode = self._normalize_image_timing_mode(image_timing_mode)
            self._sync_image_timing_mode_controls()
        generate_ahead_value = payload.get("audio_story_mode_generate_ahead_frames")
        if generate_ahead_value is not None:
            try:
                self._stored_generate_ahead_frames = max(0, int(generate_ahead_value or 0))
                self._sync_generate_ahead_slider()
            except Exception:
                pass
        continuity_strength = payload.get("audio_story_mode_continuity_strength")
        if continuity_strength is not None:
            try:
                self._stored_continuity_strength = self._normalize_continuity_strength(continuity_strength)
                self._sync_continuity_slider()
            except Exception:
                pass
        cost_profile = str(payload.get("audio_story_mode_cost_profile") or "").strip().lower()
        if cost_profile in {str(item.get("id") or "").strip().lower() for item in _audio_story_cost_profiles()}:
            self._stored_cost_profile_id = cost_profile
        style_prompts = payload.get("audio_story_mode_style_prompts")
        if isinstance(style_prompts, dict):
            for style_def in _audio_story_style_presets():
                style_id = str(style_def.get("id") or "").strip().lower()
                if style_id:
                    self._stored_style_prompts[style_id] = str(style_prompts.get(style_id, self._stored_style_prompts.get(style_id, style_def.get("prompt", ""))) or self._stored_style_prompts.get(style_id, style_def.get("prompt", ""))).strip()
        style_labels = payload.get("audio_story_mode_style_labels")
        if isinstance(style_labels, dict):
            for style_def in _audio_story_style_presets():
                style_id = str(style_def.get("id") or "").strip().lower()
                if style_id:
                    default_label = str(style_def.get("label") or style_id.title())
                    self._stored_style_labels[style_id] = str(style_labels.get(style_id, self._stored_style_labels.get(style_id, default_label)) or default_label).strip()
        style_enabled = payload.get("audio_story_mode_style_enabled")
        if isinstance(style_enabled, (list, tuple, set)):
            valid_ids = {str(item.get("id") or "").strip().lower() for item in _audio_story_style_presets()}
            self._stored_style_enabled = [str(item or "").strip().lower() for item in style_enabled if str(item or "").strip().lower() in valid_ids]
        if payload.get("audio_story_mode_style_change_live") is not None:
            self._stored_style_change_live = bool(payload.get("audio_story_mode_style_change_live"))
        self._sync_audio_story_style_controls()
        if payload.get("audio_story_mode_story_master_prompt_enabled") is not None:
            self._stored_story_master_prompt_enabled = bool(payload.get("audio_story_mode_story_master_prompt_enabled"))
        story_master_prompt_mode = str(payload.get("audio_story_mode_story_master_prompt_mode") or "").strip().lower()
        if story_master_prompt_mode in {value for value, _label in _audio_story_master_prompt_modes()}:
            self._stored_story_master_prompt_mode = story_master_prompt_mode
        self._sync_story_master_prompt_controls()
        analysis_mode = payload.get("audio_story_mode_analysis_mode")
        if analysis_mode is not None:
            self._stored_audio_story_analysis_mode = self._normalize_audio_story_analysis_mode(analysis_mode)
            audio_story_runtime.update_runtime_config("audio_story_analysis_mode", self._stored_audio_story_analysis_mode)
        self._sync_audio_story_analysis_mode_controls()
        if payload.get("audio_story_mode_use_llm_story_analysis") is not None:
            self._stored_use_llm_story_analysis = bool(payload.get("audio_story_mode_use_llm_story_analysis"))
        self._sync_llm_story_analysis_controls()
        analysis_provider_mode = payload.get("audio_story_mode_story_analysis_provider_mode")
        if analysis_provider_mode is not None:
            self._stored_story_analysis_provider_mode = self._normalize_story_analysis_provider_mode(analysis_provider_mode)
        self._sync_story_analysis_provider_controls()
        analysis_model = payload.get("audio_story_mode_story_analysis_model")
        if analysis_model is not None:
            self._stored_story_analysis_model = self._normalize_story_analysis_model(analysis_model)
        self._sync_story_analysis_model_controls()
        xai_image_settings = payload.get("audio_story_mode_xai_image_settings")
        if isinstance(xai_image_settings, dict):
            normalized_xai_settings = {
                "xai_image_aspect_ratio": self._normalize_xai_image_aspect_ratio(xai_image_settings.get("xai_image_aspect_ratio")),
                "xai_image_resolution": self._normalize_xai_image_resolution(xai_image_settings.get("xai_image_resolution")),
                "xai_image_response_format": self._normalize_xai_image_response_format(xai_image_settings.get("xai_image_response_format")),
                "xai_image_n": self._normalize_xai_image_n(xai_image_settings.get("xai_image_n")),
            }
            for key, value in normalized_xai_settings.items():
                audio_story_runtime.update_runtime_config(key, value)
        self._sync_xai_image_settings_controls()
        prompt_block_limits = payload.get("audio_story_mode_prompt_block_limits")
        if isinstance(prompt_block_limits, dict):
            self._stored_prompt_block_limits = self._normalize_prompt_block_limits(prompt_block_limits)
        self._sync_prompt_block_limit_controls()
        prompt_safety_cap = payload.get("audio_story_mode_prompt_safety_cap")
        if prompt_safety_cap is not None:
            self._stored_prompt_safety_cap = self._normalize_prompt_safety_cap(prompt_safety_cap)
        self._sync_prompt_safety_cap_control()
        if payload.get("audio_story_mode_visual_stream_enabled") is not None:
            self._stored_visual_stream_enabled = bool(payload.get("audio_story_mode_visual_stream_enabled"))
        visual_stream_port = payload.get("audio_story_mode_visual_stream_port")
        if visual_stream_port is not None:
            try:
                self._stored_visual_stream_port = max(1024, min(65535, int(visual_stream_port or 8765)))
            except Exception:
                self._stored_visual_stream_port = 8765
        if self._stored_visual_stream_enabled:
            self._start_visual_stream(silent=True)
        else:
            self._stop_visual_stream()
        chromecast_name = str(payload.get("audio_story_mode_chromecast_device_name") or "").strip()
        if chromecast_name:
            self._stored_chromecast_device_name = chromecast_name
        if payload.get("audio_story_mode_chromecast_cast_active") is not None:
            self._stored_chromecast_cast_active = bool(payload.get("audio_story_mode_chromecast_cast_active"))
        if payload.get("audio_story_mode_chromecast_show_prompt") is not None:
            self._stored_chromecast_show_prompt = bool(payload.get("audio_story_mode_chromecast_show_prompt"))
            checkbox = getattr(self, "audio_story_cast_prompt_checkbox", None)
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(self._stored_chromecast_show_prompt))
                checkbox.blockSignals(False)
        self._sync_visual_stream_controls()
        self._sync_chromecast_controls()
        self._sync_audio_story_cost_profile_controls()
        playback_mode = str(payload.get("audio_story_mode_playback_mode") or "").strip()
        if playback_mode:
            self._stored_playback_mode_label = playback_mode
            if hasattr(self, "audio_story_playback_mode_combo"):
                index = self.audio_story_playback_mode_combo.findText(playback_mode)
                if index >= 0:
                    self.audio_story_playback_mode_combo.setCurrentIndex(index)
        bible = payload.get("audio_story_mode_story_bible")
        if isinstance(bible, dict):
            self.story_bible = dict(bible)
        scene_plan = payload.get("audio_story_mode_scene_plan")
        if isinstance(scene_plan, list):
            self.scene_plan = [dict(item) if isinstance(item, dict) else item for item in scene_plan]
        scene_overrides = payload.get("audio_story_mode_scene_overrides")
        if isinstance(scene_overrides, dict):
            self.scene_overrides = {
                "pinned_character_ids": list(scene_overrides.get("pinned_character_ids", []) or []),
                "pinned_location_ids": list(scene_overrides.get("pinned_location_ids", []) or []),
                "forced_scene_modes": dict(scene_overrides.get("forced_scene_modes", {}) or {}),
                "scene_anchor_overrides": dict(scene_overrides.get("scene_anchor_overrides", {}) or {}),
                "scene_negative_prompt_overrides": dict(scene_overrides.get("scene_negative_prompt_overrides", {}) or {}),
                "global_negative_prompt": str(scene_overrides.get("global_negative_prompt", "") or "").strip(),
                "global_negative_prompt_enabled": bool(scene_overrides.get("global_negative_prompt_enabled", False)),
            }
        continuity_memory = payload.get("audio_story_mode_continuity_memory")
        if isinstance(continuity_memory, dict):
            self.continuity_memory = dict(continuity_memory)
        character_anchors = payload.get("audio_story_mode_character_anchors")
        if isinstance(character_anchors, dict):
            self.character_anchors = dict(character_anchors)
        location_anchors = payload.get("audio_story_mode_location_anchors")
        if isinstance(location_anchors, dict):
            self.location_anchors = dict(location_anchors)
        self._refresh_controls()
        return None

    def shutdown(self):
        self._transcription_job_id += 1
        self._tts_render_job_id += 1
        self._cancel_visual_generation()
        self._pending_play_request = None
        try:
            self._visual_refresh_timer.stop()
        except Exception:
            pass
        try:
            self._story_rebuild_timer.stop()
        except Exception:
            pass
        if audio_story_runtime.engine_loaded():
            self._sync_story_generated_master_prompt(refresh_visuals=False)
        self._stop_story()
        self._stop_visual_stream()
        return None

    def _ensure_player(self):
        if QtMultimedia is None or self.audio_player is not None:
            return
        self.audio_output = QtMultimedia.QAudioOutput()
        self.audio_player = QtMultimedia.QMediaPlayer()
        self.audio_player.setAudioOutput(self.audio_output)
        self.audio_player.positionChanged.connect(self._on_player_position_changed)
        self.audio_player.durationChanged.connect(self._on_player_duration_changed)
        self.audio_player.playbackStateChanged.connect(self._on_player_state_changed)
        try:
            self.audio_player.errorOccurred.connect(self._on_player_error)
        except Exception:
            pass

    def _cache_file(self, name: str) -> Path:
        path = self._cache_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _set_status(self, message: str):
        if hasattr(self, "audio_story_status_label"):
            self.audio_story_status_label.setText(str(message or "").strip())

    def _set_transcription_progress(self, percent: int, message: str):
        text = str(message or "").strip()
        bar = getattr(self, "audio_story_transcription_progress_bar", None)
        if bar is not None:
            value = max(0, min(100, int(percent or 0)))
            bar.setValue(value)
            bar.setFormat(f"{value}%")
        if text:
            self._set_status(text)

    def _emit_transcription_progress(self, job_id: int, percent: int, message: str, *, stage: str = ""):
        self.transcriptionProgress.emit(
            {
                "job_id": int(job_id),
                "percent": max(0, min(100, int(percent or 0))),
                "message": str(message or "").strip(),
                "stage": str(stage or "").strip(),
            }
        )

    def _show_warning(self, title: str, message: str):
        if self.dialogs is not None:
            self.dialogs.warning(title, message)

    def _refresh_imported_audio_duration(self):
        path = str(self.imported_audio_path or "").strip()
        if not path:
            self.imported_audio_duration_seconds = 0.0
            return
        try:
            if Path(path).exists():
                self.imported_audio_duration_seconds = max(0.0, audio_story_runtime.audio_duration_seconds(path))
            else:
                self.imported_audio_duration_seconds = 0.0
        except Exception:
            self.imported_audio_duration_seconds = 0.0

    def _choose_audio_file(self):
        if self.dialogs is None:
            return
        path, _selected = self.dialogs.open_file(
            "Import Story Audio",
            str(Path(self.imported_audio_path).parent if self.imported_audio_path else self._cache_root),
            "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.wma);;All Files (*.*)",
        )
        path = str(path or "").strip()
        if not path:
            return
        self.imported_audio_path = path
        self._refresh_imported_audio_duration()
        self._stored_transcription_start_seconds = 0
        self._stored_transcription_end_seconds = int(math.ceil(self.imported_audio_duration_seconds)) if self.imported_audio_duration_seconds > 0 else 0
        self.transcript_chunks = []
        self.full_transcript_text = ""
        self.story_style_guide = ""
        self._raw_transcript_segments = []
        self._reset_story_consistency_state()
        self._last_transcription_audio_duration = 0.0
        self._pending_play_request = None
        self._tts_bundle = None
        self._tts_signature = ""
        self._image_cache = {}
        self._prompt_image_cache = {}
        self._current_chunk_index = -1
        if hasattr(self, "audio_story_path_edit"):
            self.audio_story_path_edit.setText(path)
        if hasattr(self, "audio_story_transcript_edit"):
            self.audio_story_transcript_edit.clear()
        if hasattr(self, "audio_story_summary_label"):
            self.audio_story_summary_label.setText("Audio imported. Press 'Transcribe Audio' to build transcript windows and prompts.")
        self._sync_transcribe_seconds_slider()
        self._sync_transcription_range_controls()
        self._sync_image_frequency_slider()
        self._stop_story()
        self._refresh_controls()

    def _start_transcription(self):
        path = str(self.imported_audio_path or "").strip()
        if not path:
            self._show_warning("Audio Story Mode", "Import an audio file first.")
            return
        if not Path(path).exists():
            self._show_warning("Audio Story Mode", f"Audio file not found:\n{path}")
            return
        self._refresh_imported_audio_duration()
        self._sync_transcription_range_controls()
        chunk_seconds = max(1, int(self.audio_story_transcribe_seconds_slider.value())) if hasattr(self, "audio_story_transcribe_seconds_slider") else int(self._stored_transcribe_seconds or 8)
        transcription_start_seconds, transcription_end_seconds = self._effective_transcription_range_seconds()
        if self.imported_audio_duration_seconds > 0 and transcription_end_seconds <= transcription_start_seconds:
            self._show_warning("Audio Story Mode", "Choose a transcription end second that is after the start second.")
            return
        self._transcription_job_id += 1
        job_id = self._transcription_job_id
        image_frequency_seconds = self._normalize_image_frequency_seconds(int(self.audio_story_image_frequency_slider.value())) if hasattr(self, "audio_story_image_frequency_slider") else self._normalize_image_frequency_seconds()
        continuity_strength = float(self._stored_continuity_strength or 0.8)
        self._set_transcription_progress(1, "Preparing audio transcription...")
        self.audio_story_transcribe_button.setEnabled(False)
        threading.Thread(
            target=self._run_transcription_job,
            args=(job_id, path, chunk_seconds, image_frequency_seconds, continuity_strength, transcription_start_seconds, transcription_end_seconds),
            daemon=True,
        ).start()

    def _run_transcription_job(self, job_id: int, path: str, chunk_seconds: int, image_frequency_seconds: int, continuity_strength: float, transcription_start_seconds: int = 0, transcription_end_seconds: int = 0):
        temp_transcription_path = None
        try:
            if not audio_story_runtime.ensure_whisper_ready():
                raise RuntimeError("Failed to initialize the local Whisper model.")
            audio_duration = audio_story_runtime.audio_duration_seconds(path)
            range_start = max(0.0, float(transcription_start_seconds or 0))
            range_end = max(0.0, float(transcription_end_seconds or 0))
            if audio_duration > 0:
                range_start = min(range_start, audio_duration)
                range_end = audio_duration if range_end <= 0 else min(range_end, audio_duration)
            transcribe_path = path
            if audio_duration > 0 and (range_start > 0.0 or (range_end > 0.0 and range_end < audio_duration)):
                if range_end <= range_start:
                    raise RuntimeError("The selected transcription range is empty.")
                self._emit_transcription_progress(job_id, 4, "Preparing selected audio range...", stage="audio_slice")
                source_audio = audio_story_runtime.audio_from_file(path)
                start_ms = max(0, int(round(range_start * 1000.0)))
                end_ms = max(start_ms, int(round(range_end * 1000.0)))
                temp_transcription_path = self._cache_file(f"transcription_range_{job_id}_{uuid.uuid4().hex[:10]}.wav")
                source_audio[start_ms:end_ms].export(str(temp_transcription_path), format="wav")
                transcribe_path = str(temp_transcription_path)
            segments, _info = audio_story_runtime.transcribe_audio(transcribe_path)
            raw_segments = []
            progress_duration = max(0.001, (range_end - range_start) if range_end > range_start else audio_duration)
            for segment in segments:
                text = str(getattr(segment, "text", "") or "").strip()
                if not text:
                    continue
                start_seconds = max(0.0, float(getattr(segment, "start", 0.0) or 0.0) + range_start)
                end_seconds = max(start_seconds, float(getattr(segment, "end", 0.0) or 0.0) + range_start)
                if audio_duration > 0:
                    clip_end_seconds = range_end if range_end > range_start else audio_duration
                    if start_seconds >= clip_end_seconds:
                        continue
                    end_seconds = min(audio_duration, clip_end_seconds, end_seconds)
                raw_segments.append(
                    {
                        "start_seconds": start_seconds,
                        "end_seconds": end_seconds,
                        "text": text,
                    }
                )
                if audio_duration > 0:
                    range_progress = max(0.0, min(1.0, ((end_seconds - range_start) / progress_duration)))
                    percent = 14 + int(min(58.0, range_progress * 58.0))
                    self._emit_transcription_progress(
                        job_id,
                        percent,
                        f"Transcribing audio... {min(100, int(range_progress * 100.0))}%",
                        stage="whisper_transcribe",
                    )
            self._emit_transcription_progress(job_id, 74, "Building transcript windows and scene plan...", stage="story_build")
            payload = self._build_story_payload(
                job_id=job_id,
                path=path,
                audio_duration=audio_duration,
                raw_segments=raw_segments,
                chunk_seconds=chunk_seconds,
                image_frequency_seconds=image_frequency_seconds,
                continuity_strength=continuity_strength,
                transcription_start_seconds=int(round(range_start)),
                transcription_end_seconds=int(round(range_end)) if range_end > 0 else 0,
                progress_callback=lambda percent, message: self._emit_transcription_progress(job_id, percent, message, stage="story_build"),
            )
            self._emit_transcription_progress(job_id, 100, "Audio story transcription complete.", stage="done")
            self.transcriptionFinished.emit(payload)
        except Exception as exc:
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip() or str(exc)
            self.transcriptionFailed.emit(detail)
        finally:
            if temp_transcription_path is not None:
                audio_story_runtime.safe_delete(str(temp_transcription_path))

    def _build_transcript_chunks(self, raw_segments, audio_duration_seconds: float, chunk_seconds: float, *, base_start_seconds: float = 0.0):
        if chunk_seconds <= 0:
            chunk_seconds = 8.0
        base_start_seconds = max(0.0, float(base_start_seconds or 0.0))
        buckets = {}
        for segment in list(raw_segments or []):
            text = str(segment.get("text", "") or "").strip()
            if not text:
                continue
            start_seconds = max(0.0, float(segment.get("start_seconds", 0.0) or 0.0))
            end_seconds = max(start_seconds, float(segment.get("end_seconds", start_seconds) or start_seconds))
            bucket_index = int(max(0.0, start_seconds - base_start_seconds) // chunk_seconds)
            bucket = buckets.setdefault(
                bucket_index,
                {
                    "start_seconds": base_start_seconds + (float(bucket_index) * chunk_seconds),
                    "end_seconds": min(audio_duration_seconds, base_start_seconds + (float(bucket_index + 1) * chunk_seconds)) if audio_duration_seconds > 0 else base_start_seconds + (float(bucket_index + 1) * chunk_seconds),
                    "texts": [],
                    "raw_end_seconds": end_seconds,
                },
            )
            bucket["texts"].append(text)
            bucket["raw_end_seconds"] = max(float(bucket.get("raw_end_seconds", 0.0) or 0.0), end_seconds)
        chunks = []
        for bucket_index in sorted(buckets.keys()):
            bucket = buckets[bucket_index]
            text = " ".join(bucket.get("texts", [])).strip()
            if not text:
                continue
            end_seconds = max(float(bucket.get("end_seconds", 0.0) or 0.0), float(bucket.get("raw_end_seconds", 0.0) or 0.0))
            if audio_duration_seconds > 0:
                end_seconds = min(audio_duration_seconds, end_seconds)
            chunks.append(
                {
                    "start_seconds": max(0.0, float(bucket.get("start_seconds", 0.0) or 0.0)),
                    "end_seconds": max(0.0, end_seconds),
                    "text": text,
                }
            )
        return chunks

    def _build_image_chunks(self, raw_segments, audio_duration_seconds: float, image_frequency_seconds: float, *, base_start_seconds: float = 0.0):
        if image_frequency_seconds <= 0:
            image_frequency_seconds = 12.0
        base_start_seconds = max(0.0, float(base_start_seconds or 0.0))
        buckets = {}
        for segment in list(raw_segments or []):
            text = str(segment.get("text", "") or "").strip()
            if not text:
                continue
            start_seconds = max(0.0, float(segment.get("start_seconds", 0.0) or 0.0))
            end_seconds = max(start_seconds, float(segment.get("end_seconds", start_seconds) or start_seconds))
            bucket_index = int(max(0.0, start_seconds - base_start_seconds) // image_frequency_seconds)
            bucket = buckets.setdefault(
                bucket_index,
                {
                    "start_seconds": base_start_seconds + (float(bucket_index) * image_frequency_seconds),
                    "end_seconds": min(audio_duration_seconds, base_start_seconds + (float(bucket_index + 1) * image_frequency_seconds)) if audio_duration_seconds > 0 else base_start_seconds + (float(bucket_index + 1) * image_frequency_seconds),
                    "texts": [],
                    "raw_end_seconds": end_seconds,
                },
            )
            bucket["texts"].append(text)
            bucket["raw_end_seconds"] = max(float(bucket.get("raw_end_seconds", 0.0) or 0.0), end_seconds)
        image_chunks = []
        for bucket_index in sorted(buckets.keys()):
            bucket = buckets[bucket_index]
            text = " ".join(bucket.get("texts", [])).strip()
            if not text:
                continue
            end_seconds = max(float(bucket.get("end_seconds", 0.0) or 0.0), float(bucket.get("raw_end_seconds", 0.0) or 0.0))
            if audio_duration_seconds > 0:
                end_seconds = min(audio_duration_seconds, end_seconds)
            image_chunks.append(
                {
                    "start_seconds": max(0.0, float(bucket.get("start_seconds", 0.0) or 0.0)),
                    "end_seconds": max(0.0, end_seconds),
                    "text": text,
                }
            )
        return image_chunks

    def _build_story_payload(self, *, job_id: int, path: str, audio_duration: float, raw_segments, chunk_seconds: int, image_frequency_seconds: int, continuity_strength: float, transcription_start_seconds: int = 0, transcription_end_seconds: int = 0, progress_callback=None):
        def progress(percent: int, message: str):
            if callable(progress_callback):
                try:
                    progress_callback(int(percent), str(message or "").strip())
                except Exception:
                    pass

        progress(76, "Building transcript and image timing windows...")
        base_start_seconds = max(0.0, float(transcription_start_seconds or 0.0))
        transcript_windows = self._build_transcript_chunks(raw_segments, audio_duration, float(chunk_seconds), base_start_seconds=base_start_seconds)
        image_timing_mode = self._image_timing_mode()
        image_chunk_seconds = float(chunk_seconds if image_timing_mode == "scene_changes" else image_frequency_seconds)
        image_chunks = self._build_image_chunks(raw_segments, audio_duration, image_chunk_seconds, base_start_seconds=base_start_seconds)
        if image_chunks and float(image_chunks[0].get("start_seconds", 0.0) or 0.0) > base_start_seconds:
            image_chunks[0]["start_seconds"] = base_start_seconds
        full_text = " ".join(str(item.get("text", "") or "").strip() for item in image_chunks).strip()
        progress(80, "Building visual style guide...")
        story_style_guide = self._visual_reply_story_style_guide(
            full_text,
            continuity_strength=self._normalize_continuity_strength(continuity_strength),
        )
        progress(84, "Building heuristic story anchors...")
        fallback_story_bible = self._build_story_bible(full_text, continuity_strength=continuity_strength)
        llm_analysis = {}
        if self._stored_use_llm_story_analysis and full_text and image_chunks:
            progress(86, f"Analyzing story with {self._story_analysis_provider_status_label()} (max {int(_AUDIO_STORY_LLM_ANALYSIS_TIMEOUT_SECONDS)}s)...")
            try:
                llm_analysis = self._build_llm_story_analysis_with_timeout(
                    full_text=full_text,
                    image_chunks=image_chunks,
                    story_style_guide=story_style_guide,
                    continuity_strength=continuity_strength,
                    fallback_story_bible=fallback_story_bible,
                )
            except Exception as exc:
                print(f"[AudioStoryMode] LLM story analysis failed; falling back to heuristic analysis: {exc}")
                progress(90, "Story analysis timed out or failed. Using heuristic analysis...")
                llm_analysis = {}
            else:
                progress(92, "Normalizing story analysis...")
        else:
            progress(90, "Using heuristic story analysis...")
        story_bible = dict(llm_analysis.get("story_bible") or fallback_story_bible)
        llm_scene_map = {}
        for item in list(llm_analysis.get("scenes", []) or []):
            if not isinstance(item, dict):
                continue
            try:
                llm_scene_map[int(item.get("chunk_index", -1) or -1)] = dict(item)
            except Exception:
                continue
        scene_plan = []
        previous_scene = None
        scene_index = 0
        total_chunks = max(1, len(image_chunks))
        analysis_mode = self._audio_story_analysis_mode()
        print(f"[StoryBible] mode selected: {analysis_mode}")
        story_memory_store = None
        story_memory = None
        story_analyzer = None
        if analysis_mode == "story_bible":
            story_memory_store = self._story_bible_store(path)
            story_memory = story_memory_store.load()
            story_analyzer = StoryAnalyzer()
            print(
                f"[StoryBible] memory loaded path={story_memory_store.path} "
                f"characters={len(dict(story_memory.get('characters') or {}))} "
                f"locations={len(dict(story_memory.get('locations') or {}))}"
            )
        for index, chunk in enumerate(image_chunks):
            progress(92 + int((index / total_chunks) * 6), f"Building image prompt plan... {index + 1}/{total_chunks}")
            chunk["index"] = index
            llm_scene = dict(llm_scene_map.get(index) or {})
            if llm_scene:
                scene_entry, scene_index = self._scene_entry_from_llm_analysis(
                    llm_scene,
                    index=index,
                    chunk=chunk,
                    story_bible=story_bible,
                    previous_scene=previous_scene,
                    scene_index=scene_index,
                )
            else:
                features = self._infer_scene_features(str(chunk.get("text", "") or ""), story_bible, previous_scene=previous_scene)
                transition = self._classify_scene_transition(features, previous_scene, str(chunk.get("text", "") or ""), story_bible)
                if previous_scene is None or transition.get("is_new_scene", False):
                    scene_index += 1
                    scene_label = str(features.get("scene_label", "") or "").strip()
                    scene_id = _audio_story_slug(f"{scene_label}_{scene_index}", prefix="scene")
                    is_new_scene = True
                    continuation_of = str(previous_scene.get("scene_id", "") or "") if isinstance(previous_scene, dict) else ""
                else:
                    scene_id = str(previous_scene.get("scene_id", "") or "")
                    is_new_scene = False
                    continuation_of = scene_id
                location_ids = list(features.get("location_ids", []) or [])
                location_id = str(location_ids[0] if location_ids else previous_scene.get("location_id", "") if previous_scene else "") or ""
                location_label = ""
                if location_id:
                    location_entry = dict((story_bible.get("locations", {}) or {}).get(location_id) or {})
                    location_label = str(location_entry.get("label", "") or "").strip()
                scene_entry = {
                    "chunk_index": index,
                    "scene_index": scene_index,
                    "scene_id": scene_id,
                    "is_new_scene": bool(is_new_scene),
                    "continuation_of_scene_id": continuation_of,
                    "location_id": location_id,
                    "location_label": location_label,
                    "active_character_ids": list(features.get("active_character_ids", []) or []),
                    "prop_ids": list(features.get("prop_ids", []) or []),
                    "mood": str(features.get("mood", "") or "").strip(),
                    "time_of_day": str(features.get("time_of_day", "") or "").strip(),
                    "key_action": str(features.get("key_action", "") or "").strip(),
                    "summary": str(features.get("summary", "") or "").strip(),
                    "camera": str(features.get("camera", "") or "").strip(),
                    "continuity_priority": list(features.get("continuity_priority", []) or []),
                    "transition_score": float(transition.get("score", 0.0) or 0.0),
                    "transition_reasons": list(transition.get("reasons", []) or []),
                    "analysis_source": "heuristic",
                }
            scene_entry["reference_image_paths"] = self._story_reference_image_paths(scene_entry, previous_scene=previous_scene)
            scene_entry["generation_mode"] = self._choose_generation_mode(scene_entry, previous_scene=previous_scene).get("mode", "fresh")
            chunk["scene_id"] = scene_entry["scene_id"]
            chunk["scene_index"] = scene_entry["scene_index"]
            chunk["location_id"] = scene_entry["location_id"]
            chunk["location_label"] = scene_entry["location_label"]
            chunk["active_character_ids"] = list(scene_entry["active_character_ids"])
            chunk["prop_ids"] = list(scene_entry["prop_ids"])
            chunk["mood"] = scene_entry["mood"]
            chunk["time_of_day"] = scene_entry["time_of_day"]
            chunk["camera"] = scene_entry["camera"]
            chunk["is_scene_continuation"] = not scene_entry["is_new_scene"]
            chunk["continuity_priority"] = list(scene_entry["continuity_priority"])
            chunk["scene_summary"] = scene_entry["summary"]
            chunk["generation_mode"] = scene_entry["generation_mode"]
            chunk["reference_image_paths"] = list(scene_entry["reference_image_paths"])
            chunk["tts_start_seconds"] = None
            chunk["tts_end_seconds"] = None
            if analysis_mode == "story_bible" and story_memory_store is not None and story_memory is not None and story_analyzer is not None:
                update = story_analyzer.analyze(
                    str(chunk.get("text", "") or ""),
                    chunk_index=index,
                    timestamp=float(chunk.get("start_seconds", 0.0) or 0.0),
                    memory=story_memory,
                )
                story_memory, memory_changed = merge_story_memory(story_memory, update)
                scene_update = dict(update.get("scene") or {})
                scene_entry["story_bible_character_keys"] = list(scene_update.get("character_keys", []) or [])
                scene_entry["story_bible_location_key"] = str(scene_update.get("location_key", "") or "").strip()
                if memory_changed:
                    story_memory_store.save(story_memory)
                print(
                    f"[StoryBible] chunk={index} memory_updated={bool(memory_changed)} "
                    f"characters={len(dict(story_memory.get('characters') or {}))} "
                    f"locations={len(dict(story_memory.get('locations') or {}))}"
                )
                chunk["prompt"] = self._build_story_bible_image_prompt(
                    str(chunk.get("text", "") or ""),
                    chunk_index=index,
                    scene_entry=scene_entry,
                    memory=story_memory,
                    analyzer_update=update,
                )
            else:
                chunk["prompt"] = self._build_story_image_prompt(
                    str(chunk.get("text", "") or ""),
                    story_style_guide,
                    scene_entry=scene_entry,
                    story_bible=story_bible,
                    previous_scene=previous_scene,
                )
            scene_plan.append(scene_entry)
            previous_scene = scene_entry
        if image_timing_mode == "scene_changes":
            progress(98, "Collapsing prompt plan to scene changes...")
            image_chunks, scene_plan = self._collapse_story_chunks_to_scene_changes(
                image_chunks,
                scene_plan,
                story_bible=story_bible,
                story_style_guide=story_style_guide,
            )
            if analysis_mode == "story_bible" and story_memory_store is not None and story_memory is not None and story_analyzer is not None:
                story_memory = self._apply_story_bible_prompts_to_chunks(
                    image_chunks,
                    scene_plan,
                    story_memory_store=story_memory_store,
                    story_memory=story_memory,
                    story_analyzer=story_analyzer,
                )
        character_anchors = {}
        for entity_id, entity in dict(story_bible.get("characters", {}) or {}).items():
            existing_anchor = dict(self.character_anchors.get(entity_id) or {})
            anchor = dict(entity or {})
            anchor["image_path"] = str(existing_anchor.get("image_path", "") or "").strip()
            character_anchors[entity_id] = anchor
        location_anchors = {}
        for entity_id, entity in dict(story_bible.get("locations", {}) or {}).items():
            existing_anchor = dict(self.location_anchors.get(entity_id) or {})
            anchor = dict(entity or {})
            anchor["image_path"] = str(existing_anchor.get("image_path", "") or "").strip()
            location_anchors[entity_id] = anchor
        return {
            "job_id": job_id,
            "audio_path": path,
            "audio_duration_seconds": audio_duration,
            "chunk_seconds": int(chunk_seconds),
            "transcription_start_seconds": int(round(max(0.0, float(transcription_start_seconds or 0.0)))),
            "transcription_end_seconds": int(round(max(0.0, float(transcription_end_seconds or 0.0)))),
            "image_frequency_seconds": int(image_frequency_seconds),
            "image_timing_mode": image_timing_mode,
            "continuity_strength": float(self._normalize_continuity_strength(continuity_strength)),
            "transcript_chunks": image_chunks,
            "transcript_windows": transcript_windows,
            "full_text": full_text,
            "story_style_guide": story_style_guide,
            "story_bible": story_bible,
            "scene_plan": scene_plan,
            "character_anchors": character_anchors,
            "location_anchors": location_anchors,
            "raw_segments": list(raw_segments or []),
        }

    def _collapse_story_chunks_to_scene_changes(self, image_chunks, scene_plan, *, story_bible: dict, story_style_guide: str):
        paired = []
        for index, chunk in enumerate(list(image_chunks or [])):
            scene_entry = dict(list(scene_plan or [])[index] or {}) if index < len(list(scene_plan or [])) else {}
            paired.append((dict(chunk or {}), scene_entry))
        if not paired:
            return list(image_chunks or []), list(scene_plan or [])
        groups = []
        current_group = []
        current_scene_id = ""
        for chunk, scene_entry in paired:
            scene_id = str(scene_entry.get("scene_id", "") or "").strip() or f"chunk_{len(groups)}"
            starts_new_group = not current_group or scene_id != current_scene_id
            if starts_new_group:
                if current_group:
                    groups.append(current_group)
                current_group = []
                current_scene_id = scene_id
            current_group.append((chunk, scene_entry))
        if current_group:
            groups.append(current_group)
        collapsed_chunks = []
        collapsed_scenes = []
        previous_scene = None
        for new_index, group in enumerate(groups):
            group_chunks = [dict(item[0] or {}) for item in group]
            group_scenes = [dict(item[1] or {}) for item in group]
            first_chunk = group_chunks[0]
            last_chunk = group_chunks[-1]
            first_scene = dict(group_scenes[0] or {})
            combined_text = " ".join(str(chunk.get("text", "") or "").strip() for chunk in group_chunks if str(chunk.get("text", "") or "").strip()).strip()
            first_scene["chunk_index"] = int(new_index)
            first_scene["is_new_scene"] = True
            first_scene["continuation_of_scene_id"] = str(dict(previous_scene or {}).get("scene_id", "") or "")
            first_scene["active_character_ids"] = _audio_story_unique_keep_order(
                character_id
                for scene in group_scenes
                for character_id in list(scene.get("active_character_ids", []) or [])
            )
            first_scene["prop_ids"] = _audio_story_unique_keep_order(
                prop_id
                for scene in group_scenes
                for prop_id in list(scene.get("prop_ids", []) or [])
            )
            first_scene["continuity_priority"] = _audio_story_unique_keep_order(
                priority
                for scene in group_scenes
                for priority in list(scene.get("continuity_priority", []) or [])
            )
            first_scene["key_action"] = _audio_story_truncate(
                str(first_scene.get("key_action", "") or first_scene.get("summary", "") or combined_text).strip(),
                420,
            )
            first_scene["summary"] = _audio_story_truncate(
                str(first_scene.get("summary", "") or combined_text).strip(),
                420,
            )
            first_scene["reference_image_paths"] = self._story_reference_image_paths(first_scene, previous_scene=previous_scene)
            first_scene["generation_mode"] = self._choose_generation_mode(first_scene, previous_scene=previous_scene).get("mode", "fresh")
            collapsed_chunk = dict(first_chunk)
            collapsed_chunk.update(
                {
                    "index": int(new_index),
                    "start_seconds": max(0.0, float(first_chunk.get("start_seconds", 0.0) or 0.0)),
                    "end_seconds": max(0.0, float(last_chunk.get("end_seconds", first_chunk.get("end_seconds", 0.0)) or 0.0)),
                    "text": combined_text,
                    "scene_id": str(first_scene.get("scene_id", "") or "").strip(),
                    "scene_index": int(first_scene.get("scene_index", new_index + 1) or new_index + 1),
                    "location_id": str(first_scene.get("location_id", "") or "").strip(),
                    "location_label": str(first_scene.get("location_label", "") or "").strip(),
                    "active_character_ids": list(first_scene.get("active_character_ids", []) or []),
                    "prop_ids": list(first_scene.get("prop_ids", []) or []),
                    "mood": str(first_scene.get("mood", "") or "").strip(),
                    "time_of_day": str(first_scene.get("time_of_day", "") or "").strip(),
                    "camera": str(first_scene.get("camera", "") or "").strip(),
                    "is_scene_continuation": False,
                    "continuity_priority": list(first_scene.get("continuity_priority", []) or []),
                    "scene_summary": str(first_scene.get("summary", "") or "").strip(),
                    "generation_mode": str(first_scene.get("generation_mode", "") or "fresh").strip(),
                    "reference_image_paths": list(first_scene.get("reference_image_paths", []) or []),
                    "tts_start_seconds": None,
                    "tts_end_seconds": None,
                }
            )
            collapsed_chunk["prompt"] = self._build_story_image_prompt(
                combined_text,
                story_style_guide,
                scene_entry=first_scene,
                story_bible=story_bible,
                previous_scene=previous_scene,
            )
            collapsed_chunks.append(collapsed_chunk)
            collapsed_scenes.append(first_scene)
            previous_scene = first_scene
        return collapsed_chunks, collapsed_scenes

    def _apply_story_payload(self, payload, *, start_visual_generation: bool = True):
        self.imported_audio_path = str(payload.get("audio_path", "") or "").strip()
        self.imported_audio_duration_seconds = max(0.0, float(payload.get("audio_duration_seconds", 0.0) or 0.0))
        self.transcript_chunks = list(payload.get("transcript_chunks", []) or [])
        self.full_transcript_text = str(payload.get("full_text", "") or "").strip()
        self.story_style_guide = str(payload.get("story_style_guide", "") or "").strip()
        self._stored_transcribe_seconds = max(1, int(payload.get("chunk_seconds", self._stored_transcribe_seconds) or self._stored_transcribe_seconds))
        self._stored_transcription_start_seconds = max(0, int(payload.get("transcription_start_seconds", self._stored_transcription_start_seconds) or 0))
        self._stored_transcription_end_seconds = max(0, int(payload.get("transcription_end_seconds", self._stored_transcription_end_seconds) or 0))
        self._stored_image_frequency_seconds = self._normalize_image_frequency_seconds(payload.get("image_frequency_seconds", self._stored_image_frequency_seconds))
        self._stored_image_timing_mode = self._normalize_image_timing_mode(payload.get("image_timing_mode", self._stored_image_timing_mode))
        self._stored_continuity_strength = self._normalize_continuity_strength(payload.get("continuity_strength", self._stored_continuity_strength))
        self._raw_transcript_segments = list(payload.get("raw_segments", []) or [])
        self._last_transcription_audio_duration = self.imported_audio_duration_seconds
        self._pending_play_request = None
        with self._lock:
            self._image_generation_token += 1
            self._image_generation_worker_running = False
            self._image_generation_active_start_index = -1
            self._image_generation_requested_end_index = -1
        self._tts_bundle = None
        self._tts_signature = ""
        self._image_cache = {}
        self._prompt_image_cache = {}
        self._current_chunk_index = -1
        self.story_bible = dict(payload.get("story_bible", {}) or {})
        self.scene_plan = [dict(item) if isinstance(item, dict) else item for item in list(payload.get("scene_plan", []) or [])]
        self.character_anchors = dict(payload.get("character_anchors", {}) or {})
        self.location_anchors = dict(payload.get("location_anchors", {}) or {})
        self._sync_transcribe_seconds_slider()
        self._sync_transcription_range_controls()
        self._sync_image_frequency_slider()
        self._sync_image_timing_mode_controls()
        self._sync_continuity_slider()
        self._sync_generate_ahead_slider()
        self._sync_audio_story_style_controls()
        self._sync_story_master_prompt_controls()
        self._set_status(
            f"Transcription ready. {len(self.transcript_chunks)} image window(s) built from {self.imported_audio_duration_seconds:.1f}s of audio."
        )
        if hasattr(self, "audio_story_summary_label"):
            scene_count = len({str(item.get("scene_id", "") or "") for item in list(self.scene_plan or []) if isinstance(item, dict) and str(item.get("scene_id", "") or "").strip()})
            self.audio_story_summary_label.setText(
                f"Audio duration: {self._format_seconds(self.imported_audio_duration_seconds)}\n"
                f"Transcribed range: {self._format_seconds(self._stored_transcription_start_seconds)} - {self._format_seconds(self._stored_transcription_end_seconds)}\n"
                f"Image windows: {len(self.transcript_chunks)}\n"
                f"Scenes: {scene_count}\n"
                f"Image timing: {'Scene changes' if self._image_timing_mode() == 'scene_changes' else self._format_slider_seconds(self._stored_image_frequency_seconds)}\n"
                f"Continuity: {int(round(self._stored_continuity_strength * 100.0))}%\n"
                f"Story analysis: {self._story_analysis_summary_text()}\n"
                f"Story master prompt: {'on' if self._stored_story_master_prompt_enabled else 'off'} ({str(self._stored_story_master_prompt_mode or 'medium').title()})\n"
                f"Playback mode: {self.audio_story_playback_mode_combo.currentText() if hasattr(self, 'audio_story_playback_mode_combo') else 'Play Imported Audio'}"
            )
        if hasattr(self, "audio_story_transcript_edit"):
            lines = []
            for chunk in list(payload.get("transcript_windows", []) or self.transcript_chunks):
                lines.append(
                    f"[{self._format_seconds(float(chunk.get('start_seconds', 0.0) or 0.0))}"
                    f" - {self._format_seconds(float(chunk.get('end_seconds', 0.0) or 0.0))}] "
                    f"{str(chunk.get('text', '') or '').strip()}"
                )
            self.audio_story_transcript_edit.setPlainText("\n\n".join(lines))
        self._sync_story_generated_master_prompt(refresh_visuals=False)
        self._refresh_scene_override_controls()
        self._prepare_source_media()
        if start_visual_generation:
            self._restart_visual_generation_from_position(0.0)
        self._refresh_controls()

    def _rebuild_story_payload_from_cached_segments(self, *, preserve_playback: bool = False, preserve_audio_assets: bool = False):
        if not self._raw_transcript_segments or self._last_transcription_audio_duration <= 0.0:
            return
        previous_position_seconds = self._player_position_seconds()
        previous_state = None
        if self.audio_player is not None:
            try:
                previous_state = self.audio_player.playbackState()
            except Exception:
                previous_state = None
        previous_tts_bundle = dict(self._tts_bundle or {}) if preserve_audio_assets else None
        previous_tts_signature = str(self._tts_signature or "") if preserve_audio_assets else ""
        with self._lock:
            previous_image_cache = {int(index): dict(item or {}) for index, item in dict(self._image_cache or {}).items()}
            previous_prompt_cache = {str(key): dict(item or {}) for key, item in dict(self._prompt_image_cache or {}).items()}
        payload = self._build_story_payload(
            job_id=self._transcription_job_id,
            path=self.imported_audio_path,
            audio_duration=self._last_transcription_audio_duration,
            raw_segments=self._raw_transcript_segments,
            chunk_seconds=int(self._stored_transcribe_seconds or 8),
            image_frequency_seconds=int(self._stored_image_frequency_seconds or 12),
            continuity_strength=float(self._stored_continuity_strength or 0.8),
            transcription_start_seconds=int(self._stored_transcription_start_seconds or 0),
            transcription_end_seconds=int(self._stored_transcription_end_seconds or 0),
        )
        if not preserve_playback:
            self._stop_story()
        self._apply_story_payload(payload, start_visual_generation=False)
        with self._lock:
            self._image_cache.update(previous_image_cache)
            self._prompt_image_cache.update(previous_prompt_cache)
        self._reconcile_cached_images_for_current_prompts()
        if not preserve_playback:
            self._restart_visual_generation_from_position(0.0)
        if preserve_audio_assets:
            self._tts_bundle = previous_tts_bundle
            self._tts_signature = previous_tts_signature
        if preserve_playback and self.audio_player is not None:
            self.audio_player.setPosition(max(0, int(round(previous_position_seconds * 1000.0))))
            self._sync_visual_to_position(previous_position_seconds, force=True)
            playback_state_enum = getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlaybackState", None)
            playing_state = getattr(playback_state_enum, "PlayingState", None) if playback_state_enum is not None else getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlayingState", None)
            paused_state = getattr(playback_state_enum, "PausedState", None) if playback_state_enum is not None else getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PausedState", None)
            if previous_state == playing_state:
                self._start_playback_with_visual_sync(previous_position_seconds, status_text="Playing audio story with updated visuals.")
            elif previous_state == paused_state:
                self._set_status("Playback paused. Visual timing updated.")

    def _start_story_payload_rebuild_job(self, *, status_text: str = "Rebuilding audio story analysis..."):
        if not self._raw_transcript_segments or self._last_transcription_audio_duration <= 0.0:
            return
        self._transcription_job_id += 1
        job_id = self._transcription_job_id
        self._set_status(status_text)
        if hasattr(self, "audio_story_transcribe_button"):
            self.audio_story_transcribe_button.setEnabled(False)
        threading.Thread(
            target=self._run_story_payload_rebuild_job,
            args=(
                job_id,
                str(self.imported_audio_path or ""),
                float(self._last_transcription_audio_duration or 0.0),
                [dict(item or {}) for item in list(self._raw_transcript_segments or [])],
                int(self._stored_transcribe_seconds or 8),
                self._normalize_image_frequency_seconds(),
                float(self._stored_continuity_strength or 0.8),
                int(self._stored_transcription_start_seconds or 0),
                int(self._stored_transcription_end_seconds or 0),
            ),
            daemon=True,
        ).start()

    def _run_story_payload_rebuild_job(self, job_id: int, path: str, audio_duration: float, raw_segments, chunk_seconds: int, image_frequency_seconds: int, continuity_strength: float, transcription_start_seconds: int = 0, transcription_end_seconds: int = 0):
        try:
            payload = self._build_story_payload(
                job_id=job_id,
                path=path,
                audio_duration=audio_duration,
                raw_segments=raw_segments,
                chunk_seconds=chunk_seconds,
                image_frequency_seconds=image_frequency_seconds,
                continuity_strength=continuity_strength,
                transcription_start_seconds=transcription_start_seconds,
                transcription_end_seconds=transcription_end_seconds,
            )
            self.transcriptionFinished.emit(payload)
        except Exception as exc:
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip() or str(exc)
            self.transcriptionFailed.emit(detail)

    def _on_transcription_progress(self, payload):
        data = dict(payload or {})
        if int(data.get("job_id", 0) or 0) != self._transcription_job_id:
            return
        self._set_transcription_progress(
            int(data.get("percent", 0) or 0),
            str(data.get("message", "") or "").strip(),
        )

    def _on_transcription_finished(self, payload):
        if int(payload.get("job_id", 0) or 0) != self._transcription_job_id:
            return
        self.audio_story_transcribe_button.setEnabled(True)
        self._set_transcription_progress(100, "Audio story transcription complete.")
        self._apply_story_payload(payload)

    def _on_transcription_failed(self, detail: str):
        self.audio_story_transcribe_button.setEnabled(True)
        self._set_transcription_progress(0, "Transcription failed.")
        self._set_status(f"Transcription failed: {detail}")

    def _playback_mode_value(self):
        text = str(self.audio_story_playback_mode_combo.currentText() if hasattr(self, "audio_story_playback_mode_combo") else "Play Imported Audio").strip().lower()
        return "tts" if "tts" in text else "source"

    def _on_playback_mode_changed(self, _value):
        if hasattr(self, "audio_story_playback_mode_combo"):
            self._stored_playback_mode_label = str(self.audio_story_playback_mode_combo.currentText() or self._stored_playback_mode_label)
        self._stop_story()
        self._update_slider_range()
        self._refresh_controls()

    def _play_story(self):
        if QtMultimedia is None:
            self._show_warning("Audio Story Mode", "Qt Multimedia is not available in this environment.")
            return
        self._visual_generation_blocked = False
        self._ensure_player()
        if not self.transcript_chunks:
            self._show_warning("Audio Story Mode", "Transcribe the imported audio first.")
            return
        mode = self._playback_mode_value()
        if mode == "source":
            if not self._prepare_source_media():
                return
            self._start_playback_with_visual_sync(self._player_position_seconds(), status_text="Playing imported audio story.")
            self._sync_visual_stream_playback_state("playing")
            return
        signature = self._compute_tts_signature()
        if self._tts_bundle is None or self._tts_signature != signature or not Path(str(self._tts_bundle.get("audio_path", "") or "")).exists():
            self._pending_autoplay_tts = True
            self._start_tts_render(signature)
            return
        if not self._prepare_tts_media():
            return
        self._start_playback_with_visual_sync(self._player_position_seconds(), status_text="Playing TTS narration for the transcribed story.")
        self._sync_visual_stream_playback_state("playing")

    def _pause_story(self):
        if self.audio_player is None:
            return
        self.audio_player.pause()
        self._sync_visual_stream_playback_state("paused")
        self._set_status("Playback paused.")

    def _cancel_visual_generation(self):
        with self._lock:
            self._image_generation_token += 1
            self._image_generation_worker_running = False
            self._image_generation_active_start_index = -1
            self._image_generation_requested_end_index = -1

    def _stop_story(self):
        self._pending_play_request = None
        self._pending_autoplay_tts = False
        self._visual_generation_blocked = True
        self._cancel_visual_generation()
        if self.audio_player is not None:
            self.audio_player.stop()
            self.audio_player.setPosition(0)
        self._sync_visual_stream_playback_state("stopped", position_seconds=0.0)
        if bool(getattr(self, "_stored_chromecast_cast_active", False)) or bool(getattr(self, "_stored_chromecast_stream_page_active", False)):
            self._stop_chromecast_cast(stop_stream=True, silent=True)
        self._current_chunk_index = -1
        self._update_slider_range()
        if self.transcript_chunks:
            self._sync_visual_to_position(0.0, force=True, allow_generation=False)
        self._set_status("Playback stopped.")

    def _prepare_source_media(self):
        self._ensure_player()
        if self.audio_player is None:
            return False
        path = str(self.imported_audio_path or "").strip()
        if not path:
            self._show_warning("Audio Story Mode", "Import an audio file first.")
            return False
        key = f"source::{path}"
        if self._player_source_key != key:
            self.audio_player.setSource(QtCore.QUrl.fromLocalFile(str(Path(path).resolve())))
            self._player_source_key = key
        self._update_slider_range()
        return True

    def _prepare_tts_media(self):
        self._ensure_player()
        if self.audio_player is None:
            return False
        if not self._tts_bundle:
            return False
        path = str(self._tts_bundle.get("audio_path", "") or "").strip()
        if not path or not Path(path).exists():
            self._show_warning("Audio Story Mode", "The rendered TTS audio is missing. Render it again.")
            return False
        key = f"tts::{path}"
        if self._player_source_key != key:
            self.audio_player.setSource(QtCore.QUrl.fromLocalFile(str(Path(path).resolve())))
            self._player_source_key = key
        self._update_slider_range()
        return True

    def _start_tts_render(self, signature: str):
        self._tts_render_job_id += 1
        job_id = self._tts_render_job_id
        self._tts_render_in_progress = True
        self._set_status("Rendering TTS narration from the transcript windows...")
        self._refresh_controls()
        threading.Thread(
            target=self._run_tts_render_job,
            args=(job_id, signature, [dict(item) for item in self.transcript_chunks]),
            daemon=True,
        ).start()

    def _run_tts_render_job(self, job_id: int, signature: str, transcript_chunks):
        try:
            audio_path = self._cache_file(f"tts_story_{signature}.wav")
            metadata_path = self._cache_file(f"tts_story_{signature}.json")
            if audio_path.exists() and metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["job_id"] = job_id
                self.ttsRenderFinished.emit(metadata)
                return

            if not audio_story_runtime.init_tts():
                raise RuntimeError("Failed to initialize the active TTS backend.")

            chunk_target_chars, chunk_max_chars = audio_story_runtime.get_text_chunk_limits()
            combined_audio = audio_story_runtime.audio_silent(duration=0)
            rendered_chunks = []
            sample_rate = audio_story_runtime.tts_sample_rate(default=24000)
            voice_path = audio_story_runtime.tts_voice_path()

            for chunk in transcript_chunks:
                if job_id != self._tts_render_job_id:
                    return
                chunk_text = str(chunk.get("text", "") or "").strip()
                if not chunk_text:
                    segment_audio = audio_story_runtime.audio_silent(duration=250)
                else:
                    subchunks = audio_story_runtime.intelligent_chunk_text(chunk_text, chunk_target_chars, chunk_max_chars)
                    if not subchunks:
                        subchunks = [chunk_text]
                    segment_audio = audio_story_runtime.audio_silent(duration=0)
                    for subchunk in subchunks:
                        if job_id != self._tts_render_job_id:
                            return
                        configured_seed = audio_story_runtime.tts_seed()
                        if configured_seed > 0:
                            audio_story_runtime.set_seed(configured_seed)
                        kwargs = audio_story_runtime.tts_generation_kwargs()
                        if voice_path:
                            kwargs["audio_prompt_path"] = voice_path
                        wav = audio_story_runtime.generate_tts(subchunk, **kwargs)
                        temp_subchunk_path = self._cache_file(f"tts_piece_{job_id}_{uuid.uuid4().hex[:10]}.wav")
                        audio_story_runtime.save_tts_wav(str(temp_subchunk_path), wav, sample_rate)
                        try:
                            segment_audio += audio_story_runtime.audio_from_wav(str(temp_subchunk_path))
                        finally:
                            audio_story_runtime.safe_delete(str(temp_subchunk_path))
                playback_start_seconds = max(0.0, float(combined_audio.duration_seconds or 0.0))
                combined_audio += segment_audio
                playback_end_seconds = max(playback_start_seconds, float(combined_audio.duration_seconds or 0.0))
                rendered_chunk = dict(chunk)
                rendered_chunk["tts_start_seconds"] = playback_start_seconds
                rendered_chunk["tts_end_seconds"] = playback_end_seconds
                rendered_chunks.append(rendered_chunk)

            combined_audio.export(str(audio_path), format="wav")
            payload = {
                "job_id": job_id,
                "audio_path": str(audio_path),
                "duration_seconds": float(combined_audio.duration_seconds or 0.0),
                "chunks": rendered_chunks,
                "signature": signature,
            }
            metadata_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            self.ttsRenderFinished.emit(payload)
        except Exception as exc:
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip() or str(exc)
            self.ttsRenderFailed.emit(detail)

    def _compute_tts_signature(self):
        payload = {
            "texts": [str(item.get("text", "") or "").strip() for item in self.transcript_chunks],
            **audio_story_runtime.tts_settings_snapshot(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()[:16]

    def _on_tts_render_finished(self, payload):
        if int(payload.get("job_id", 0) or 0) != self._tts_render_job_id:
            return
        self._tts_render_in_progress = False
        self._tts_bundle = {
            "audio_path": str(payload.get("audio_path", "") or "").strip(),
            "duration_seconds": max(0.0, float(payload.get("duration_seconds", 0.0) or 0.0)),
        }
        self._tts_signature = str(payload.get("signature", "") or "").strip()
        rendered_chunks = list(payload.get("chunks", []) or [])
        if rendered_chunks and len(rendered_chunks) == len(self.transcript_chunks):
            self.transcript_chunks = rendered_chunks
        self._set_status("TTS narration rendered and ready to play.")
        self._refresh_controls()
        if self._pending_autoplay_tts:
            self._pending_autoplay_tts = False
            if self._prepare_tts_media():
                self._start_playback_with_visual_sync(self._player_position_seconds(), status_text="Playing TTS narration for the transcribed story.")

    def _on_tts_render_failed(self, detail: str):
        self._tts_render_in_progress = False
        self._pending_autoplay_tts = False
        self._set_status(f"TTS render failed: {detail}")
        self._refresh_controls()

    def _restart_visual_generation_from_position(self, position_seconds: float, *, force: bool = False, allow_when_stopped: bool = False):
        if not self.transcript_chunks:
            return 0
        if bool(getattr(self, "_visual_generation_blocked", False)) and not allow_when_stopped:
            return int(self._image_generation_token or 0)
        if not allow_when_stopped and not self._is_audio_story_currently_playing():
            return int(self._image_generation_token or 0)
        start_index = self._chunk_index_for_position(position_seconds)
        end_index = min(len(self.transcript_chunks) - 1, int(start_index) + max(0, int(self._stored_generate_ahead_frames or 0)))
        needs_generation = False
        for index in range(max(0, int(start_index)), min(len(self.transcript_chunks) - 1, int(end_index)) + 1):
            chunk = dict(self.transcript_chunks[index] or {})
            prompt_text = str(chunk.get("prompt", "") or "").strip()
            if not self._matching_cached_image_entry(index, prompt_text, scene_entry=chunk).get("image_path"):
                needs_generation = True
                break
        if not needs_generation:
            return int(self._image_generation_token or 0)
        with self._lock:
            if self._image_generation_worker_running and not force:
                self._image_generation_requested_end_index = max(int(self._image_generation_requested_end_index), int(end_index))
                active_start = int(self._image_generation_active_start_index)
                active_end = int(self._image_generation_requested_end_index)
                if active_start <= int(start_index) <= active_end:
                    return int(self._image_generation_token or 0)
            self._image_generation_token += 1
            token = self._image_generation_token
            self._image_generation_worker_running = True
            self._image_generation_active_start_index = int(start_index)
            self._image_generation_requested_end_index = int(end_index)
        threading.Thread(
            target=self._run_visual_generation,
            args=(token, int(start_index), int(end_index)),
            daemon=True,
        ).start()
        return token

    def _restart_missing_visual_generation_from_position(self, position_seconds: float, *, max_ahead_frames: int | None = None, force: bool = True, allow_when_stopped: bool = True):
        if not self.transcript_chunks:
            return int(self._image_generation_token or 0)
        start_index = self._chunk_index_for_position(position_seconds)
        ahead = int(self._stored_generate_ahead_frames or 0) if max_ahead_frames is None else max(0, int(max_ahead_frames or 0))
        end_index = min(len(self.transcript_chunks) - 1, int(start_index) + ahead)
        first_missing = -1
        for index in range(max(0, int(start_index)), int(end_index) + 1):
            chunk = dict(self.transcript_chunks[index] or {})
            if self._matching_cached_image_entry(index, str(chunk.get("prompt", "") or "").strip(), scene_entry=chunk).get("image_path"):
                continue
            first_missing = int(index)
            break
        if first_missing < 0:
            return int(self._image_generation_token or 0)
        original_ahead = self._stored_generate_ahead_frames
        try:
            self._stored_generate_ahead_frames = max(0, int(end_index) - int(first_missing))
            return self._restart_visual_generation_from_position(
                self._chunk_start_seconds(first_missing),
                force=force,
                allow_when_stopped=allow_when_stopped,
            )
        finally:
            self._stored_generate_ahead_frames = original_ahead

    def _start_playback_with_visual_sync(self, position_seconds: float, *, status_text: str):
        position_seconds = max(0.0, float(position_seconds or 0.0))
        if not self.transcript_chunks or self.audio_player is None:
            return
        start_index = self._chunk_index_for_position(position_seconds)
        chunk = dict(self.transcript_chunks[start_index] or {})
        cached = self._matching_cached_image_entry(start_index, str(chunk.get("prompt", "") or "").strip(), scene_entry=chunk)
        if cached.get("image_path"):
            self._pending_play_request = None
            self.audio_player.setPosition(max(0, int(round(position_seconds * 1000.0))))
            self._current_chunk_index = -1
            self._sync_visual_to_position(position_seconds, force=True, allow_generation=True)
            self.audio_player.play()
            self._sync_visual_stream_playback_state("playing", position_seconds=position_seconds)
            self._set_status(status_text)
            return
        token = self._restart_visual_generation_from_position(position_seconds, allow_when_stopped=True)
        self._pending_play_request = {
            "token": int(token),
            "index": int(start_index),
            "position_seconds": position_seconds,
            "status_text": str(status_text or "").strip(),
        }
        self._set_status("Preparing the first story image before playback starts...")

    def _run_visual_generation(self, token: int, start_index: int, end_index: int):
        index = max(0, int(start_index))
        try:
            while index <= min(len(self.transcript_chunks) - 1, int(end_index)):
                if token != self._image_generation_token:
                    return
                chunk = dict(self.transcript_chunks[index] or {})
                prompt_text = str(chunk.get("prompt", "") or "").strip()
                source_text = str(chunk.get("text", "") or "").strip()
                if not prompt_text:
                    index += 1
                    continue
                cached = self._matching_cached_image_entry(index, prompt_text, scene_entry=chunk)
                if cached.get("image_path"):
                    index += 1
                    with self._lock:
                        end_index = max(int(end_index), int(self._image_generation_requested_end_index))
                    continue
                try:
                    scene_entry = self._scene_entry_for_index(index)
                    image_entry = self._generate_visual_image(prompt_text, index=index, scene_entry=scene_entry)
                    if token != self._image_generation_token:
                        return
                    ready_payload = {
                        "token": token,
                        "index": index,
                        "image_path": str(image_entry.get("image_path", "") or "").strip(),
                        "prompt_text": prompt_text,
                        "source_text": source_text,
                        "prompt_signature": str(image_entry.get("prompt_signature", "") or "").strip(),
                        "generation_mode": str(image_entry.get("generation_mode", "") or "").strip(),
                        "reference_image_paths": list(image_entry.get("reference_image_paths", []) or []),
                    }
                    ready_entry = self._store_ready_image_entry(index, ready_payload, scene_entry=scene_entry, update_continuity=True)
                    if index == self._current_chunk_index and ready_entry.get("image_path"):
                        self._publish_ready_visual_entry(index, chunk=scene_entry, image_entry=ready_entry)
                    ready_payload["already_stored"] = True
                    self.imageReady.emit(ready_payload)
                except Exception as exc:
                    detail = "".join(traceback.format_exception_only(type(exc), exc)).strip() or str(exc)
                    is_moderated = self._is_visual_moderation_error(detail)
                    self.imageFailed.emit(
                        {
                            "token": token,
                            "index": index,
                            "detail": detail,
                            "moderated": bool(is_moderated),
                        }
                    )
                    if not is_moderated:
                        return
                index += 1
                with self._lock:
                    end_index = max(int(end_index), int(self._image_generation_requested_end_index))
        finally:
            with self._lock:
                if token == self._image_generation_token:
                    self._image_generation_worker_running = False
                    self._image_generation_active_start_index = -1
                    self._image_generation_requested_end_index = -1

    def _generate_visual_image(self, prompt_text: str, *, index: int, scene_entry=None):
        prompt_text = str(prompt_text or "").strip()
        if not prompt_text:
            raise RuntimeError("Visual prompt is empty.")
        if not bool(self._visual_reply_generation_info().get("enabled")):
            raise RuntimeError("Visual replies are disabled in the Visuals tab.")
        if not bool(self._visual_reply_generation_info().get("generation_available")):
            raise RuntimeError("Visual reply generation is unavailable. Check your image provider credentials.")
        scene_entry = dict(scene_entry or {})
        previous_scene = self._scene_entry_for_index(index - 1)
        scene_id = str(scene_entry.get("scene_id", "") or "").strip()
        scene_index = int(scene_entry.get("scene_index", 0) or 0)
        generation_mode = str(scene_entry.get("generation_mode", "") or "fresh").strip() or "fresh"
        reference_image_paths = self._story_reference_image_paths(scene_entry, previous_scene=previous_scene)
        prompt_signature, effective_prompt = self._visual_request_signature(
            prompt_text,
            scene_entry=scene_entry,
            generation_mode=generation_mode,
            reference_image_paths=reference_image_paths,
        )
        with self._lock:
            cached_entry = dict(self._prompt_image_cache.get(prompt_signature) or {})
        if cached_entry.get("image_path") and Path(str(cached_entry.get("image_path", "") or "")).exists():
            return cached_entry
        if generation_mode in {"edit", "multi_reference"} and reference_image_paths and self._visual_provider_supports_reference_edits():
            try:
                if generation_mode == "multi_reference" and len(reference_image_paths) > 1:
                    entry = self._generate_visual_image_from_multi_reference(effective_prompt, index=index, reference_image_paths=reference_image_paths)
                else:
                    entry = self._generate_visual_image_from_edit(effective_prompt, index=index, reference_image_paths=reference_image_paths)
            except Exception:
                entry = self._generate_visual_image_from_fresh(effective_prompt, index=index)
        else:
            if (
                str(self._visual_reply_generation_info().get("provider") or "").strip().lower() == "xai"
                and generation_mode in {"edit", "multi_reference"}
                and reference_image_paths
                and not bool(getattr(self, "_xai_reference_edit_warning_shown", False))
            ):
                self._xai_reference_edit_warning_shown = True
                self._set_status("xAI reference editing requires JSON / xAI SDK support and is not enabled in this build; falling back to fresh generation.")
            entry = self._generate_visual_image_from_fresh(effective_prompt, index=index)
        entry["prompt_signature"] = prompt_signature
        entry["scene_id"] = scene_id
        entry["scene_index"] = scene_index
        entry["generation_mode"] = generation_mode if generation_mode in {"fresh", "edit", "multi_reference"} else "fresh"
        entry["reference_image_paths"] = list(reference_image_paths or [])
        entry["scene_context"] = dict(scene_entry or {})
        with self._lock:
            self._prompt_image_cache[prompt_signature] = dict(entry)
        return entry

    def _store_ready_image_entry(self, index: int, payload: dict, *, scene_entry=None, update_continuity: bool = True):
        prompt_signature = str(payload.get("prompt_signature", "") or "").strip()
        generation_mode = str(payload.get("generation_mode", "") or "").strip()
        reference_image_paths = list(payload.get("reference_image_paths", []) or [])
        scene_entry = dict(scene_entry or self._scene_entry_for_index(index))
        entry = {
            "image_path": str(payload.get("image_path", "") or "").strip(),
            "prompt_text": str(payload.get("prompt_text", "") or "").strip(),
            "source_text": str(payload.get("source_text", "") or "").strip(),
            "prompt_signature": prompt_signature,
            "generation_mode": generation_mode,
            "reference_image_paths": list(reference_image_paths or []),
            "scene_id": str(scene_entry.get("scene_id", "") or "").strip(),
            "scene_index": int(scene_entry.get("scene_index", 0) or 0),
            "scene_context": dict(scene_entry or {}),
        }
        with self._lock:
            self._image_cache[int(index)] = dict(entry)
            if prompt_signature and entry.get("image_path") and Path(str(entry.get("image_path", "") or "")).exists():
                self._prompt_image_cache[prompt_signature] = dict(entry)
        if update_continuity and scene_entry:
            self._update_continuity_memory_from_image(scene_entry=scene_entry, image_entry=entry, prompt_signature=prompt_signature)
        return entry

    def _on_image_ready(self, payload):
        token = int(payload.get("token", 0) or 0)
        if token != self._image_generation_token:
            return
        index = int(payload.get("index", -1) or -1)
        scene_entry = self._scene_entry_for_index(index)
        if bool(payload.get("already_stored", False)):
            with self._lock:
                entry = dict(self._image_cache.get(int(index)) or {})
            if not entry:
                entry = self._store_ready_image_entry(index, payload, scene_entry=scene_entry, update_continuity=False)
        else:
            entry = self._store_ready_image_entry(index, payload, scene_entry=scene_entry, update_continuity=True)
        pending = dict(self._pending_play_request or {})
        if pending and int(pending.get("token", 0) or 0) == token and int(pending.get("index", -1) or -1) == index:
            position_seconds = max(0.0, float(pending.get("position_seconds", 0.0) or 0.0))
            status_text = str(pending.get("status_text", "") or "").strip()
            self._pending_play_request = None
            if entry.get("image_path"):
                self._publish_ready_visual_entry(index, chunk=scene_entry, image_entry=entry)
            if self.audio_player is not None:
                self.audio_player.setPosition(max(0, int(round(position_seconds * 1000.0))))
                self._current_chunk_index = -1
                self._sync_visual_to_position(position_seconds, force=True)
                self.audio_player.play()
                self._sync_visual_stream_playback_state("playing", position_seconds=position_seconds)
                self._set_status(status_text or "Playing audio story.")
            return
        if index == self._current_chunk_index:
            if entry.get("image_path"):
                self._publish_ready_visual_entry(index, chunk=scene_entry, image_entry=entry)
            else:
                self._publish_visual_for_index(index, keep_current_image=False)

    def _on_image_failed(self, payload):
        token = int(payload.get("token", 0) or 0)
        if token != self._image_generation_token:
            return
        index = int(payload.get("index", -1) or -1)
        detail = str(payload.get("detail", "") or "").strip() or "Visual generation failed."
        if bool(payload.get("moderated", False)):
            provider_label = "xAI / Grok" if str(self._visual_reply_generation_info().get("provider") or "") == "xai" else "image provider"
            status = f"{provider_label} rejected one story image prompt for content moderation. Skipping that chunk."
            self._set_status(status)
            current_state = dict(self._visual_reply_current_state() or {})
            current_image_path = str(current_state.get("image_path", "") or "").strip()
            pending = dict(self._pending_play_request or {})
            if pending and int(pending.get("token", 0) or 0) == token and int(pending.get("index", -1) or -1) == index:
                self._pending_play_request = None
                if self.audio_player is not None:
                    position_seconds = max(0.0, float(pending.get("position_seconds", 0.0) or 0.0))
                    status_text = str(pending.get("status_text", "") or "").strip()
                    self.audio_player.setPosition(max(0, int(round(position_seconds * 1000.0))))
                    self.audio_player.play()
                    self._set_status(status_text or status)
            if index == self._current_chunk_index and not current_image_path:
                self._visual_reply_set_state(
                    {
                        "status": "error",
                        "status_text": "Visual Reply skipped",
                        "detail_text": status,
                        "image_path": "",
                        "caption": "",
                        "request_id": f"audio_story_moderated_{index}_{int(time.time())}",
                        "updated_at": time.time(),
                }
            )
            return
        pending = dict(self._pending_play_request or {})
        if pending and int(pending.get("token", 0) or 0) == token and int(pending.get("index", -1) or -1) == index:
            self._pending_play_request = None
        self._visual_reply_set_state(
            {
                "status": "error",
                "status_text": "Visual Reply failed",
                "detail_text": detail,
                "image_path": "",
                "caption": "",
                "request_id": f"audio_story_error_{int(time.time())}",
                "updated_at": time.time(),
            }
        )
        self._set_status(detail)

    def _is_visual_moderation_error(self, detail: str):
        text = str(detail or "").strip().lower()
        if not text:
            return False
        moderation_markers = (
            "content moderation",
            "rejected by content moderation",
            "safety system",
            "safety filters",
            "policy violation",
        )
        return any(marker in text for marker in moderation_markers)

    def _publish_visual_for_index(self, index: int, *, keep_current_image: bool):
        index = int(index or 0)
        if index < 0 or index >= len(self.transcript_chunks):
            return
        chunk = dict(self.transcript_chunks[index] or {})
        prompt_text = str(chunk.get("prompt", "") or "").strip()
        cached = self._matching_cached_image_entry(index, prompt_text, scene_entry=chunk)
        current_state = dict(self._visual_reply_current_state() or {})
        current_image_path = str(current_state.get("image_path", "") or "").strip()
        retained_image_path = current_image_path if keep_current_image and current_image_path and Path(current_image_path).exists() else ""
        retained_caption = str(current_state.get("caption", "") or "").strip()
        if cached.get("image_path"):
            detail_bits = [
                str(cached.get("source_text", "") or "")[:200],
                f"scene {int(chunk.get('scene_index', 0) or 0)}" if chunk.get("scene_index") else "",
                str(chunk.get("generation_mode", "") or "").strip(),
            ]
            self._visual_reply_set_state(
                {
                    "status": "ready",
                    "status_text": "Visual Reply",
                    "detail_text": " • ".join(bit for bit in detail_bits if str(bit or "").strip()),
                    "image_path": str(cached.get("image_path", "") or "").strip(),
                    "caption": str(cached.get("prompt_text", prompt_text) or prompt_text).strip(),
                    "request_id": f"audio_story_chunk_{index}",
                    "updated_at": time.time(),
                }
            )
            self._recast_current_visual_if_needed()
            return
        self._visual_reply_set_state(
            {
                "status": "loading",
                "status_text": "Visual Reply generating...",
                "detail_text": "Preparing audio story image...",
                "image_path": retained_image_path,
                "caption": retained_caption or prompt_text,
                "request_id": f"audio_story_chunk_{index}",
                "keep_current_image": bool(retained_image_path),
                "updated_at": time.time(),
            }
        )
        self._recast_current_visual_if_needed()

    def _publish_ready_visual_entry(self, index: int, *, chunk: dict, image_entry: dict):
        prompt_text = str(chunk.get("prompt", "") or "").strip()
        detail_bits = [
            str(image_entry.get("source_text", "") or "")[:200],
            f"scene {int(chunk.get('scene_index', 0) or 0)}" if chunk.get("scene_index") else "",
            str(image_entry.get("generation_mode", "") or chunk.get("generation_mode", "") or "").strip(),
        ]
        self._visual_reply_set_state(
            {
                "status": "ready",
                "status_text": "Visual Reply",
                "detail_text": " • ".join(bit for bit in detail_bits if str(bit or "").strip()),
                "image_path": str(image_entry.get("image_path", "") or "").strip(),
                "caption": str(image_entry.get("prompt_text", prompt_text) or prompt_text).strip(),
                "request_id": f"audio_story_chunk_{index}",
                "updated_at": time.time(),
            }
        )

    def _active_timeline_duration_seconds(self):
        if self._playback_mode_value() == "tts" and self._tts_bundle is not None:
            return max(0.0, float(self._tts_bundle.get("duration_seconds", 0.0) or 0.0))
        return max(0.0, float(self.imported_audio_duration_seconds or 0.0))

    def _chunk_bounds_for_mode(self, chunk):
        if self._playback_mode_value() == "tts":
            start_seconds = chunk.get("tts_start_seconds")
            end_seconds = chunk.get("tts_end_seconds")
            if start_seconds is not None and end_seconds is not None:
                return max(0.0, float(start_seconds or 0.0)), max(0.0, float(end_seconds or 0.0))
        return max(0.0, float(chunk.get("start_seconds", 0.0) or 0.0)), max(0.0, float(chunk.get("end_seconds", 0.0) or 0.0))

    def _chunk_index_for_position(self, position_seconds: float):
        seconds = max(0.0, float(position_seconds or 0.0))
        if not self.transcript_chunks:
            return 0
        last_index = len(self.transcript_chunks) - 1
        for index, chunk in enumerate(self.transcript_chunks):
            start_seconds, end_seconds = self._chunk_bounds_for_mode(chunk)
            if index == last_index:
                if seconds >= start_seconds:
                    return index
                continue
            if start_seconds <= seconds < max(start_seconds + 0.001, end_seconds):
                return index
        return max(0, min(last_index, int(self._current_chunk_index if self._current_chunk_index >= 0 else 0)))

    def _chunk_start_seconds(self, index: int):
        try:
            chunk = dict(self.transcript_chunks[max(0, min(len(self.transcript_chunks) - 1, int(index)))] or {})
        except Exception:
            return 0.0
        start_seconds, _end_seconds = self._chunk_bounds_for_mode(chunk)
        return max(0.0, float(start_seconds or 0.0))

    def _sync_visual_to_position(self, position_seconds: float, *, force: bool = False, allow_generation: bool | None = None):
        if not self.transcript_chunks:
            return
        index = self._chunk_index_for_position(position_seconds)
        if not force and index == self._current_chunk_index:
            return
        keep_current_image = self._current_chunk_index >= 0
        self._current_chunk_index = index
        self._publish_visual_for_index(index, keep_current_image=keep_current_image)
        if allow_generation is None:
            allow_generation = self._pending_play_request is not None or self._is_audio_story_currently_playing()
        if self._pending_play_request is None and bool(allow_generation):
            self._restart_visual_generation_from_position(position_seconds, allow_when_stopped=bool(allow_generation))
        current_chunk = dict(self.transcript_chunks[index] or {})
        self._set_status(
            f"Chunk {index + 1}/{len(self.transcript_chunks)} active. "
            f"{self._format_seconds(position_seconds)} into the story."
        )
        if hasattr(self, "audio_story_summary_label"):
            self.audio_story_summary_label.setText(
                f"Audio duration: {self._format_seconds(self._active_timeline_duration_seconds())}\n"
                f"Transcript windows: {len(self.transcript_chunks)}\n"
                f"Current chunk: {index + 1}/{len(self.transcript_chunks)}\n"
                f"Current text: {str(current_chunk.get('text', '') or '').strip()[:260]}"
            )
        self._refresh_scene_override_controls()

    def _player_position_seconds(self):
        if self.audio_player is None:
            return 0.0
        return max(0.0, float(self.audio_player.position() or 0) / 1000.0)

    def _update_slider_range(self):
        duration_seconds = self._active_timeline_duration_seconds()
        duration_ms = max(0, int(round(duration_seconds * 1000.0)))
        if hasattr(self, "audio_story_position_slider"):
            self.audio_story_position_slider.blockSignals(True)
            self.audio_story_position_slider.setRange(0, duration_ms)
            position_ms = min(duration_ms, max(0, int(round(self._player_position_seconds() * 1000.0))))
            self.audio_story_position_slider.setValue(position_ms)
            self.audio_story_position_slider.blockSignals(False)
        if hasattr(self, "audio_story_time_label"):
            self.audio_story_time_label.setText(f"{self._format_seconds(self._player_position_seconds())} / {self._format_seconds(duration_seconds)}")

    def _on_player_position_changed(self, position_ms: int):
        duration_seconds = self._active_timeline_duration_seconds()
        position_seconds = max(0.0, float(position_ms or 0) / 1000.0)
        self._sync_visual_stream_playback_state(position_seconds=position_seconds)
        if hasattr(self, "audio_story_position_slider") and not self._user_scrubbing:
            self.audio_story_position_slider.blockSignals(True)
            self.audio_story_position_slider.setValue(max(0, int(position_ms or 0)))
            self.audio_story_position_slider.blockSignals(False)
        if hasattr(self, "audio_story_time_label"):
            self.audio_story_time_label.setText(f"{self._format_seconds(position_seconds)} / {self._format_seconds(duration_seconds)}")
        self._sync_visual_to_position(position_seconds)

    def _on_player_duration_changed(self, duration_ms: int):
        if duration_ms and self._playback_mode_value() == "source":
            self.imported_audio_duration_seconds = max(0.0, float(duration_ms or 0) / 1000.0)
            self._sync_transcribe_seconds_slider()
            self._sync_transcription_range_controls()
        self._update_slider_range()

    def _on_player_state_changed(self, _state):
        self._sync_visual_stream_playback_state()
        self._refresh_controls()

    def _on_player_error(self, *_args):
        if self.audio_player is None:
            return
        try:
            detail = str(self.audio_player.errorString() or "").strip()
        except Exception:
            detail = "Audio playback failed."
        self._set_status(detail or "Audio playback failed.")

    def _on_slider_pressed(self):
        self._user_scrubbing = True

    def _on_slider_moved(self, value: int):
        duration_seconds = self._active_timeline_duration_seconds()
        position_seconds = max(0.0, float(value or 0) / 1000.0)
        if hasattr(self, "audio_story_time_label"):
            self.audio_story_time_label.setText(f"{self._format_seconds(position_seconds)} / {self._format_seconds(duration_seconds)}")

    def _on_slider_released(self):
        self._user_scrubbing = False
        if self.audio_player is None or not hasattr(self, "audio_story_position_slider"):
            return
        target_ms = max(0, int(self.audio_story_position_slider.value() or 0))
        self.audio_player.setPosition(target_ms)
        target_seconds = max(0.0, float(target_ms) / 1000.0)
        self._sync_visual_stream_playback_state(position_seconds=target_seconds)
        self._restart_visual_generation_from_position(target_seconds)
        self._sync_visual_to_position(target_seconds, force=True)

    def _transcribe_seconds_slider_maximum(self):
        if self.imported_audio_duration_seconds > 0:
            return max(1, int(math.ceil(self.imported_audio_duration_seconds)))
        return max(8, int(self._stored_transcribe_seconds or 8))

    def _image_frequency_slider_maximum(self):
        if self.imported_audio_duration_seconds > 0:
            return max(1, min(60, int(round(self.imported_audio_duration_seconds))))
        return 60

    def _sync_transcribe_seconds_slider(self):
        slider = getattr(self, "audio_story_transcribe_seconds_slider", None)
        value_label = getattr(self, "audio_story_transcribe_seconds_value_label", None)
        maximum = self._transcribe_seconds_slider_maximum()
        current_value = max(1, min(maximum, int(self._stored_transcribe_seconds or 8)))
        if slider is not None:
            slider.blockSignals(True)
            slider.setRange(1, maximum)
            slider.setValue(current_value)
            slider.blockSignals(False)
        self._stored_transcribe_seconds = current_value
        if value_label is not None:
            value_label.setText(self._format_seconds(current_value))

    def _transcription_range_maximum(self):
        if self.imported_audio_duration_seconds > 0:
            return max(1, int(math.ceil(self.imported_audio_duration_seconds)))
        return max(0, int(self._stored_transcription_start_seconds or 0), int(self._stored_transcription_end_seconds or 0))

    def _effective_transcription_range_seconds(self):
        maximum = self._transcription_range_maximum()
        start_seconds = max(0, int(self._stored_transcription_start_seconds or 0))
        end_seconds = max(0, int(self._stored_transcription_end_seconds or 0))
        if maximum > 0:
            start_seconds = min(start_seconds, maximum)
            if end_seconds <= 0:
                end_seconds = maximum
            end_seconds = min(maximum, end_seconds)
        return start_seconds, end_seconds

    def _sync_transcription_range_controls(self):
        start_spin = getattr(self, "audio_story_transcription_start_spin", None)
        end_spin = getattr(self, "audio_story_transcription_end_spin", None)
        maximum = self._transcription_range_maximum()
        start_seconds, end_seconds = self._effective_transcription_range_seconds()
        if maximum > 0 and end_seconds < start_seconds:
            end_seconds = start_seconds
        self._stored_transcription_start_seconds = start_seconds
        self._stored_transcription_end_seconds = end_seconds
        for spin, value in ((start_spin, start_seconds), (end_spin, end_seconds)):
            if spin is None:
                continue
            spin.blockSignals(True)
            spin.setRange(0, maximum)
            spin.setValue(max(0, min(maximum, int(value or 0))))
            spin.blockSignals(False)

    def _on_transcription_range_changed(self, _value: int):
        start_spin = getattr(self, "audio_story_transcription_start_spin", None)
        end_spin = getattr(self, "audio_story_transcription_end_spin", None)
        if start_spin is not None:
            self._stored_transcription_start_seconds = max(0, int(start_spin.value() or 0))
        if end_spin is not None:
            self._stored_transcription_end_seconds = max(0, int(end_spin.value() or 0))
        maximum = self._transcription_range_maximum()
        if maximum > 0 and self._stored_transcription_end_seconds < self._stored_transcription_start_seconds:
            self._stored_transcription_end_seconds = self._stored_transcription_start_seconds
            if end_spin is not None:
                end_spin.blockSignals(True)
                end_spin.setValue(self._stored_transcription_end_seconds)
                end_spin.blockSignals(False)

    def _sync_image_frequency_slider(self):
        slider = getattr(self, "audio_story_image_frequency_slider", None)
        value_label = getattr(self, "audio_story_image_frequency_value_label", None)
        maximum = self._image_frequency_slider_maximum()
        current_value = max(1, min(maximum, int(self._stored_image_frequency_seconds or 12)))
        if slider is not None:
            slider.blockSignals(True)
            slider.setRange(1, maximum)
            slider.setValue(current_value)
            slider.blockSignals(False)
        self._stored_image_frequency_seconds = current_value
        if value_label is not None:
            value_label.setText(self._format_slider_seconds(current_value))

    def _normalize_continuity_strength(self, value):
        try:
            strength = float(value or 0.0)
        except Exception:
            strength = 0.8
        if strength > 1.0:
            strength = strength / 100.0
        return max(0.0, min(1.0, strength))

    def _sync_continuity_slider(self):
        slider = getattr(self, "audio_story_continuity_slider", None)
        value_label = getattr(self, "audio_story_continuity_value_label", None)
        strength = self._normalize_continuity_strength(self._stored_continuity_strength)
        self._stored_continuity_strength = strength
        percent = int(round(strength * 100.0))
        if slider is not None:
            slider.blockSignals(True)
            slider.setValue(percent)
            slider.blockSignals(False)
        if value_label is not None:
            value_label.setText(f"{percent}%")

    def _sync_generate_ahead_slider(self):
        slider = getattr(self, "audio_story_generate_ahead_slider", None)
        value_label = getattr(self, "audio_story_generate_ahead_value_label", None)
        frames = max(0, int(self._stored_generate_ahead_frames or 0))
        self._stored_generate_ahead_frames = frames
        if slider is not None:
            slider.blockSignals(True)
            slider.setValue(frames)
            slider.blockSignals(False)
        if value_label is not None:
            value_label.setText(f"{frames} frame" if frames == 1 else f"{frames} frames")

    def _audio_story_style_label(self, style_def_or_id):
        if isinstance(style_def_or_id, dict):
            style_id = str(style_def_or_id.get("id") or "").strip().lower()
            default_label = str(style_def_or_id.get("label") or style_id.title()).strip()
        else:
            style_id = str(style_def_or_id or "").strip().lower()
            style_def = next((item for item in _audio_story_style_presets() if str(item.get("id") or "").strip().lower() == style_id), {})
            default_label = str(style_def.get("label") or style_id.title()).strip()
        label = str((self._stored_style_labels or {}).get(style_id, default_label) or default_label).strip()
        return label or default_label or style_id.title()

    def _notify_audio_story_settings_changed(self):
        shell = getattr(self, "shell", None)
        notifier = getattr(shell, "notify_settings_changed", None)
        if callable(notifier):
            try:
                notifier()
            except Exception:
                pass

    def _sync_audio_story_style_controls(self):
        valid_ids = {str(item.get("id") or "").strip().lower() for item in _audio_story_style_presets()}
        enabled_set = {style_id for style_id in self._stored_style_enabled if style_id in valid_ids}
        for style_def in _audio_story_style_presets():
            style_id = str(style_def.get("id") or "").strip().lower()
            if not style_id:
                continue
            prompt_text = str(self._stored_style_prompts.get(style_id, style_def.get("prompt", "")) or style_def.get("prompt", "")).strip()
            self._stored_style_prompts[style_id] = prompt_text
            style_label = self._audio_story_style_label(style_def)
            button = dict(getattr(self, "audio_story_style_buttons", {}) or {}).get(style_id)
            if button is not None:
                button.blockSignals(True)
                button.setText(style_label)
                button.setToolTip(f"Toggle the {style_label} style layer for generated story image prompts. Right-click to rename this button.")
                button.setChecked(style_id in enabled_set)
                button.blockSignals(False)
            edit = dict(getattr(self, "audio_story_style_edits", {}) or {}).get(style_id)
            if edit is not None:
                edit.blockSignals(True)
                edit.setText(prompt_text)
                edit.blockSignals(False)
        checkbox = getattr(self, "audio_story_style_live_checkbox", None)
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(self._stored_style_change_live))
            checkbox.blockSignals(False)

    def _sync_story_master_prompt_controls(self):
        button = getattr(self, "audio_story_master_prompt_button", None)
        if button is not None:
            button.blockSignals(True)
            button.setChecked(bool(self._stored_story_master_prompt_enabled))
            button.blockSignals(False)
        combo = getattr(self, "audio_story_master_prompt_mode_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            target_mode = str(self._stored_story_master_prompt_mode or "medium").strip().lower()
            index = combo.findData(target_mode)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _normalize_audio_story_analysis_mode(self, value=None):
        return normalize_analysis_mode(value if value is not None else getattr(self, "_stored_audio_story_analysis_mode", "scene_only"))

    def _audio_story_analysis_mode(self):
        self._stored_audio_story_analysis_mode = self._normalize_audio_story_analysis_mode()
        return str(self._stored_audio_story_analysis_mode or "scene_only")

    def _sync_audio_story_analysis_mode_controls(self):
        combo = getattr(self, "audio_story_analysis_mode_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            index = combo.findData(self._audio_story_analysis_mode())
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _sync_llm_story_analysis_controls(self):
        checkbox = getattr(self, "audio_story_llm_analysis_checkbox", None)
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(self._stored_use_llm_story_analysis))
            checkbox.blockSignals(False)
        self._sync_story_analysis_provider_controls()

    def _normalize_story_analysis_provider_mode(self, value=None):
        normalized = str(value if value is not None else self._stored_story_analysis_provider_mode or "current").strip().lower()
        return normalized if normalized in {"current", "deepseek", "lmstudio"} else "current"

    def _story_analysis_provider_mode(self):
        self._stored_story_analysis_provider_mode = self._normalize_story_analysis_provider_mode()
        return str(self._stored_story_analysis_provider_mode or "current")

    def _story_analysis_provider_id(self):
        mode = self._story_analysis_provider_mode()
        if mode == "lmstudio":
            return "lmstudio"
        if mode == "deepseek":
            return "deepseek"
        runtime_provider = chat_providers.normalize_provider_id(
            audio_story_runtime.runtime_config_value("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        return runtime_provider

    def _story_analysis_provider_status_label(self):
        mode = self._story_analysis_provider_mode()
        if mode == "lmstudio":
            return "local LM Studio"
        if mode == "deepseek":
            return "DeepSeek"
        return "the current Chat Provider"

    def _story_analysis_saved_model_for_provider(self, provider: str):
        provider_key = chat_providers.normalize_provider_id(provider, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        settings_map = audio_story_runtime.runtime_config_value("chat_provider_settings", {}) or {}
        provider_settings = dict(settings_map.get(provider_key, {}) or {}) if isinstance(settings_map, dict) else {}
        return str(provider_settings.get("model_name") or "").strip()

    def _story_analysis_summary_text(self):
        if dict(self.story_bible or {}).get("analysis_source") != "llm":
            return "heuristic"
        provider_label = str(dict(self.story_bible or {}).get("analysis_provider", "") or "").strip()
        model_label = str(dict(self.story_bible or {}).get("analysis_model", "") or "").strip()
        label = provider_label or self._story_analysis_provider_status_label()
        if model_label:
            return f"LLM ({label} / {model_label})"
        return f"LLM ({label})"

    def _sync_story_analysis_provider_controls(self):
        combo = getattr(self, "audio_story_analysis_provider_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            target_index = combo.findData(self._story_analysis_provider_mode())
            if target_index >= 0:
                combo.setCurrentIndex(target_index)
        finally:
            combo.blockSignals(False)
        self._sync_story_analysis_model_controls()

    def _normalize_story_analysis_model(self, value=None):
        text = str(value if value is not None else self._stored_story_analysis_model or "").strip()
        return "" if text.lower() in {"", "auto", "automatic"} else text

    def _story_analysis_model_override(self):
        self._stored_story_analysis_model = self._normalize_story_analysis_model()
        return str(self._stored_story_analysis_model or "").strip()

    def _story_analysis_model_candidates(self, provider: str):
        saved_model = self._story_analysis_saved_model_for_provider(provider)
        if self._story_analysis_provider_mode() == "current":
            runtime_model = str(audio_story_runtime.runtime_config_value("model_name", "") or "").strip()
            models = []
            for model in (runtime_model, saved_model):
                if model and model not in models:
                    models.append(model)
            return models
        if chat_providers.get_provider(provider) is None:
            return []
        models = [saved_model] if saved_model else []
        try:
            error_placeholder = chat_providers.provider_model_error(provider)
            for item in list(chat_providers.list_models(provider, quiet=True) or []):
                model = str(item or "").strip()
                if model and model != error_placeholder and model not in models:
                    models.append(model)
        except Exception:
            pass
        return models

    def _sync_story_analysis_model_controls(self):
        combo = getattr(self, "audio_story_analysis_model_combo", None)
        if combo is None:
            return
        provider = self._story_analysis_provider_id()
        selected_model = self._story_analysis_model_override()
        models = self._story_analysis_model_candidates(provider)
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("Auto", "")
            for model in models:
                combo.addItem(model, model)
            target_index = combo.findData(selected_model)
            if selected_model and target_index < 0:
                combo.addItem(selected_model, selected_model)
                target_index = combo.findData(selected_model)
            combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _bind_xai_image_settings_controls(self, root):
        label = self._ui_child(root, "audio_story_xai_image_settings_label", QtWidgets.QLabel)
        if label is not None:
            label.setText("Provider Image Settings")
            label.setStyleSheet("font-size: 12px; font-weight: 700; color: #f2f5f9;")
            label.setWordWrap(True)
        hint = self._ui_child(root, "audio_story_xai_image_settings_hint", QtWidgets.QLabel)
        if hint is not None:
            hint.setText("Audio Story uses the active Visual Reply provider. These xAI overrides apply only when Visual Reply is set to xAI / Grok.")
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            hint.setWordWrap(True)
        self.audio_story_xai_aspect_ratio_combo = self._ui_child(root, "audio_story_xai_aspect_ratio_combo", QtWidgets.QComboBox)
        if self.audio_story_xai_aspect_ratio_combo is not None:
            self.audio_story_xai_aspect_ratio_combo.setToolTip("xAI image API aspect_ratio value.")
            self.audio_story_xai_aspect_ratio_combo.currentIndexChanged.connect(self._on_xai_image_settings_changed)
        self.audio_story_xai_resolution_combo = self._ui_child(root, "audio_story_xai_resolution_combo", QtWidgets.QComboBox)
        if self.audio_story_xai_resolution_combo is not None:
            self.audio_story_xai_resolution_combo.setToolTip("xAI image API resolution value.")
            self.audio_story_xai_resolution_combo.currentIndexChanged.connect(self._on_xai_image_settings_changed)
        self.audio_story_xai_response_format_combo = self._ui_child(root, "audio_story_xai_response_format_combo", QtWidgets.QComboBox)
        if self.audio_story_xai_response_format_combo is not None:
            self.audio_story_xai_response_format_combo.setToolTip("xAI image API response_format. b64_json keeps stable local files for playback and casting.")
            self.audio_story_xai_response_format_combo.currentIndexChanged.connect(self._on_xai_image_settings_changed)
        self.audio_story_xai_n_spin = self._ui_child(root, "audio_story_xai_n_spin", QtWidgets.QSpinBox)
        if self.audio_story_xai_n_spin is not None:
            self.audio_story_xai_n_spin.setRange(1, 10)
            self.audio_story_xai_n_spin.setToolTip("xAI image API n value. Audio Story still generates one timeline image per scene.")
            self.audio_story_xai_n_spin.valueChanged.connect(self._on_xai_image_settings_changed)
        self._populate_xai_image_settings_controls()
        self._sync_xai_image_settings_controls()

    def _populate_xai_image_settings_controls(self):
        for combo_name, values in (
            ("audio_story_xai_aspect_ratio_combo", _AUDIO_STORY_XAI_IMAGE_ASPECT_RATIOS),
            ("audio_story_xai_resolution_combo", _AUDIO_STORY_XAI_IMAGE_RESOLUTIONS),
            ("audio_story_xai_response_format_combo", _AUDIO_STORY_XAI_IMAGE_RESPONSE_FORMATS),
        ):
            combo = getattr(self, combo_name, None)
            if combo is None:
                continue
            combo.blockSignals(True)
            try:
                existing = [str(combo.itemData(index) or combo.itemText(index) or "") for index in range(combo.count())]
                if existing != list(values):
                    combo.clear()
                    for value in values:
                        combo.addItem(str(value), str(value))
            finally:
                combo.blockSignals(False)

    def _normalize_xai_image_aspect_ratio(self, value=None):
        text = str(value if value is not None else audio_story_runtime.runtime_config_value("xai_image_aspect_ratio", "16:9") or "16:9").strip()
        return text if text in _AUDIO_STORY_XAI_IMAGE_ASPECT_RATIOS else "16:9"

    def _normalize_xai_image_resolution(self, value=None):
        text = str(value if value is not None else audio_story_runtime.runtime_config_value("xai_image_resolution", "1k") or "1k").strip().lower()
        return text if text in _AUDIO_STORY_XAI_IMAGE_RESOLUTIONS else "1k"

    def _normalize_xai_image_response_format(self, value=None):
        text = str(value if value is not None else audio_story_runtime.runtime_config_value("xai_image_response_format", "b64_json") or "b64_json").strip().lower()
        return text if text in _AUDIO_STORY_XAI_IMAGE_RESPONSE_FORMATS else "b64_json"

    def _normalize_xai_image_n(self, value=None):
        try:
            count = int(value if value is not None else audio_story_runtime.runtime_config_value("xai_image_n", 1) or 1)
        except Exception:
            count = 1
        return max(1, min(10, count))

    def _sync_xai_image_settings_controls(self):
        self._populate_xai_image_settings_controls()
        combo = getattr(self, "audio_story_xai_aspect_ratio_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentText(self._normalize_xai_image_aspect_ratio())
            combo.blockSignals(False)
        combo = getattr(self, "audio_story_xai_resolution_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentText(self._normalize_xai_image_resolution())
            combo.blockSignals(False)
        combo = getattr(self, "audio_story_xai_response_format_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentText(self._normalize_xai_image_response_format())
            combo.blockSignals(False)
        spin = getattr(self, "audio_story_xai_n_spin", None)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(self._normalize_xai_image_n())
            spin.blockSignals(False)

    def _current_xai_image_settings(self):
        aspect_combo = getattr(self, "audio_story_xai_aspect_ratio_combo", None)
        resolution_combo = getattr(self, "audio_story_xai_resolution_combo", None)
        response_combo = getattr(self, "audio_story_xai_response_format_combo", None)
        n_spin = getattr(self, "audio_story_xai_n_spin", None)
        return {
            "xai_image_aspect_ratio": self._normalize_xai_image_aspect_ratio(aspect_combo.currentData() if aspect_combo is not None else None),
            "xai_image_resolution": self._normalize_xai_image_resolution(resolution_combo.currentData() if resolution_combo is not None else None),
            "xai_image_response_format": self._normalize_xai_image_response_format(response_combo.currentData() if response_combo is not None else None),
            "xai_image_n": self._normalize_xai_image_n(n_spin.value() if n_spin is not None else None),
        }

    def _normalize_prompt_block_limits(self, limits=None):
        source = dict(limits or self._stored_prompt_block_limits or {})
        normalized = {}
        for key, default_value in _AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS.items():
            try:
                value = int(source.get(key, default_value) or default_value)
            except Exception:
                value = int(default_value)
            normalized[key] = max(40, min(1600, value))
        return normalized

    def _prompt_block_limits(self):
        self._stored_prompt_block_limits = self._normalize_prompt_block_limits()
        return dict(self._stored_prompt_block_limits)

    def _sync_prompt_block_limit_controls(self):
        limits = self._prompt_block_limits()
        for key, spin in dict(getattr(self, "audio_story_prompt_limit_spins", {}) or {}).items():
            if spin is None:
                continue
            spin.blockSignals(True)
            spin.setValue(int(limits.get(key, _AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS.get(key, 240)) or 240))
            spin.blockSignals(False)

    def _normalize_prompt_safety_cap(self, value=None):
        try:
            cap = int(value if value is not None else self._stored_prompt_safety_cap or _AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT)
        except Exception:
            cap = _AUDIO_STORY_PROMPT_SAFETY_CAP_DEFAULT
        return max(400, min(6000, cap))

    def _sync_prompt_safety_cap_control(self):
        spin = getattr(self, "audio_story_prompt_safety_cap_spin", None)
        self._stored_prompt_safety_cap = self._normalize_prompt_safety_cap()
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(int(self._stored_prompt_safety_cap))
            spin.blockSignals(False)

    def _current_audio_story_style_suffix(self):
        prompts = dict(self._stored_style_prompts or {})
        enabled = list(self._stored_style_enabled or [])
        parts = []
        for style_id in enabled:
            prompt_text = str(prompts.get(style_id, "") or "").strip()
            if prompt_text:
                parts.append(prompt_text)
        if not parts:
            return ""
        return "; ".join(parts)

    def _story_bible_memory_path(self, audio_path: str = ""):
        source = str(audio_path or self.imported_audio_path or "audio_story").strip()
        stem = _audio_story_slug(Path(source).stem or "audio_story", prefix="story")
        digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:10]
        return self._cache_root / "story_bibles" / f"{stem}_{digest}.json"

    def _story_bible_store(self, audio_path: str = ""):
        return StoryMemoryStore(self._story_bible_memory_path(audio_path))

    def _build_story_bible_image_prompt(self, text: str, *, chunk_index: int, scene_entry: dict, memory: dict, analyzer_update: dict | None = None):
        scene_entry = dict(scene_entry or {})
        analyzer_update = dict(analyzer_update or {})
        scene_update = dict(analyzer_update.get("scene") or {})
        character_keys = list(scene_update.get("character_keys") or [])
        if not character_keys:
            character_keys = list(scene_entry.get("story_bible_character_keys") or [])
        location_key = str(scene_update.get("location_key") or scene_entry.get("story_bible_location_key") or "").strip()
        current_scene = {
            "summary": _audio_story_visual_brief(
                str(scene_entry.get("llm_image_prompt") or scene_entry.get("llm_scene_focus") or scene_entry.get("key_action") or text or "").strip(),
                320,
            ),
            "text": _audio_story_visual_brief(text, 320),
            "camera": str(scene_entry.get("camera", "") or "cinematic medium shot").strip(),
            "character_keys": character_keys,
            "location_key": location_key,
        }
        prompt = build_grok_story_bible_prompt(
            current_scene=current_scene,
            memory=memory,
            selected_characters=character_keys,
            selected_location=location_key,
            style_settings={
                "style_suffix": self._current_audio_story_style_suffix(),
                "camera": str(scene_entry.get("camera", "") or "cinematic medium shot").strip(),
            },
            character_reference_image_path=str(scene_entry.get("character_reference_image_path", "") or ""),
            location_reference_image_path=str(scene_entry.get("location_reference_image_path", "") or ""),
            include_reference_images=False,
        )
        print(f"[StoryBible] final prompt length: {len(prompt)}")
        if "Needs clarification" in prompt:
            print("[StoryBible] warning: prompt contains unknown visual details that need clarification.")
        return prompt

    def _apply_story_bible_prompts_to_chunks(self, chunks, scenes, *, story_memory_store, story_memory: dict, story_analyzer):
        memory = dict(story_memory or {})
        for index, chunk in enumerate(list(chunks or [])):
            scene_entry = dict(list(scenes or [])[index] or {}) if index < len(list(scenes or [])) else {}
            text = str(dict(chunk or {}).get("text", "") or "").strip()
            update = story_analyzer.analyze(
                text,
                chunk_index=int(index),
                timestamp=float(dict(chunk or {}).get("start_seconds", 0.0) or 0.0),
                memory=memory,
            )
            memory, memory_changed = merge_story_memory(memory, update)
            scene_update = dict(update.get("scene") or {})
            scene_entry["story_bible_character_keys"] = list(scene_update.get("character_keys", []) or [])
            scene_entry["story_bible_location_key"] = str(scene_update.get("location_key", "") or "").strip()
            if memory_changed:
                story_memory_store.save(memory)
            prompt = self._build_story_bible_image_prompt(
                text,
                chunk_index=int(index),
                scene_entry=scene_entry,
                memory=memory,
                analyzer_update=update,
            )
            try:
                chunks[index]["prompt"] = prompt
                scenes[index] = scene_entry
            except Exception:
                pass
        return memory

    def _build_story_image_prompt(self, text: str, story_style_guide: str, *, scene_entry=None, story_bible=None, previous_scene=None):
        base_text = str(text or "").strip()
        if not scene_entry or not isinstance(scene_entry, dict):
            style_suffix = self._current_audio_story_style_suffix()
            if style_suffix:
                prompt = f"Story illustration. {style_suffix}. Scene: {base_text}."
                if story_style_guide:
                    prompt = f"{prompt} {story_style_guide}"
            else:
                prompt = self._visual_reply_story_prompt(base_text, story_style_guide=story_style_guide)
            if style_suffix:
                prompt = prompt.strip()
            if len(prompt) > 760:
                prompt = prompt[:760].rstrip(" \t\r\n,;:.-")
            return prompt
        return self._compose_story_prompt(
            dict(scene_entry or {}),
            story_bible=dict(story_bible or self.story_bible or {}),
            story_style_guide=str(story_style_guide or self.story_style_guide or "").strip(),
            previous_scene=dict(previous_scene or {}) if isinstance(previous_scene, dict) else None,
        )

    def _audio_story_master_prompt_mode(self):
        mode = str(self._stored_story_master_prompt_mode or "medium").strip().lower()
        valid = {value for value, _label in _audio_story_master_prompt_modes()}
        return mode if mode in valid else "medium"

    def _build_story_generated_master_prompt(self):
        full_text = self._visual_reply_normalize_prompt_text(self.full_transcript_text)
        story_style_guide = str(self.story_style_guide or "").strip()
        style_suffix = self._current_audio_story_style_suffix()
        mode = self._audio_story_master_prompt_mode()
        mode_config = {
            "simple": {
                "context_limit": 160,
                "lead": "Keep one coherent visual style and the same recurring adult characters and places across this story.",
                "tail": "Let the story context shape the imagery without redesigning the cast between shots.",
            },
            "medium": {
                "context_limit": 240,
                "lead": "Keep one coherent visual language across this story and treat recurring adult characters, outfits, props, and locations as the same world.",
                "tail": "Use the story context to influence framing, mood, and world details while preserving continuity.",
            },
            "strong": {
                "context_limit": 340,
                "lead": "Strongly preserve a single visual identity for this story: the same adult faces, clothing silhouettes, props, and recognizable locations from image to image.",
                "tail": "Push the imagery to stay anchored in the story's recurring cast, atmosphere, and world-building with minimal redesign drift.",
            },
            "strongest": {
                "context_limit": 420,
                "lead": "Preserve this story like consecutive shots from the same film: the same adult characters, faces, hair, outfits, props, architecture, lighting logic, and world details unless the story explicitly changes them.",
                "tail": "Make the imagery heavily story-driven while preserving the exact same cast and visual identity as aggressively as possible.",
            },
        }
        config = dict(mode_config.get(mode) or mode_config["medium"])
        context_text = str(full_text or "").strip()
        if len(context_text) > int(config.get("context_limit", 240) or 240):
            context_text = context_text[: int(config.get("context_limit", 240) or 240)].rstrip(" \t\r\n,;:.-")
        parts = [str(config.get("lead", "") or "").strip()]
        if style_suffix:
            parts.append(style_suffix)
        if story_style_guide:
            parts.append(story_style_guide)
        if context_text:
            parts.append(f"Story context: {context_text}")
        tail = str(config.get("tail", "") or "").strip()
        if tail:
            parts.append(tail)
        prompt = " ".join(part for part in parts if str(part or "").strip()).strip()
        if len(prompt) > 420:
            prompt = prompt[:420].rstrip(" \t\r\n,;:.-")
        return prompt

    def _active_story_analysis_chat_provider(self):
        provider = self._story_analysis_provider_id()
        model = self._story_analysis_model_override()
        if chat_providers.get_provider(provider) is None:
            return provider, ""
        runtime_provider = provider
        if self._story_analysis_provider_mode() == "current":
            runtime_provider = chat_providers.normalize_provider_id(
                audio_story_runtime.runtime_config_value("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
                fallback=chat_providers.DEFAULT_PROVIDER_ID,
            )
        if not model and provider == runtime_provider:
            if self._story_analysis_provider_mode() == "current":
                model = str(audio_story_runtime.runtime_config_value("model_name", "") or "").strip()
        if not model:
            model = self._story_analysis_saved_model_for_provider(provider)
        if not model:
            try:
                error_placeholder = chat_providers.provider_model_error(provider)
                models = [
                    str(item or "").strip()
                    for item in list(chat_providers.list_models(provider, quiet=True) or [])
                    if str(item or "").strip() and str(item or "").strip() != error_placeholder
                ]
                model = models[0] if models else ""
            except Exception:
                model = ""
        return provider, model

    def _prepare_story_analysis_chat_request(self, *, provider: str, model: str, params: dict, additional_params: dict, min_output_tokens: int, timeout_seconds: float):
        if str(provider or "").strip().lower() == "lmstudio":
            audio_story_runtime.ensure_chat_provider_model_ready(provider, model)
        audio_story_runtime.apply_chat_provider_generation_fields(params, additional_params, provider=provider)
        min_tokens = max(1, int(min_output_tokens or 1))
        token_keys = [key for key in ("max_tokens", "max_completion_tokens") if key in params]
        if not token_keys:
            params["max_tokens"] = min_tokens
            token_keys = ["max_tokens"]
        for key in token_keys:
            try:
                value = int(float(params.get(key)))
            except Exception:
                params[key] = min_tokens
                continue
            if value >= 0 and value < min_tokens:
                params[key] = min_tokens
        params["response_format"] = {"type": "json_object"}
        try:
            timeout_value = float(params.get("timeout", 0) or 0)
        except Exception:
            timeout_value = 0.0
        params["timeout"] = max(timeout_value, float(timeout_seconds or 0.0))

    def _build_llm_story_analysis_with_timeout(self, **kwargs):
        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def worker():
            try:
                result_queue.put(("ok", self._build_llm_story_analysis(**kwargs)), block=False)
            except Exception as exc:
                try:
                    result_queue.put(("error", exc), block=False)
                except Exception:
                    pass

        thread = threading.Thread(target=worker, name="audio-story-llm-analysis", daemon=True)
        thread.start()
        try:
            status, value = result_queue.get(timeout=float(_AUDIO_STORY_LLM_ANALYSIS_TIMEOUT_SECONDS))
        except queue.Empty:
            raise TimeoutError(
                f"{self._story_analysis_provider_status_label()} story analysis exceeded "
                f"{int(_AUDIO_STORY_LLM_ANALYSIS_TIMEOUT_SECONDS)} seconds."
            )
        if status == "error":
            raise value
        return value

    def _build_llm_story_analysis(self, *, full_text: str, image_chunks: list[dict], story_style_guide: str, continuity_strength: float, fallback_story_bible: dict):
        provider, model = self._active_story_analysis_chat_provider()
        if not provider or not model:
            raise RuntimeError(f"No {self._story_analysis_provider_status_label()} model is available for LLM story analysis.")
        prompt_payload = self._llm_story_analysis_prompt_payload(
            full_text=full_text,
            image_chunks=image_chunks,
            story_style_guide=story_style_guide,
            continuity_strength=continuity_strength,
        )
        cache_payload = {
            "provider": str(provider or "").strip().lower(),
            "model": str(model or "").strip(),
            "provider_mode": self._story_analysis_provider_mode(),
            "prompt_payload": prompt_payload,
            "fallback_story_bible": fallback_story_bible,
        }
        cache_key = hashlib.sha1(json.dumps(cache_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        with self._lock:
            cached = copy.deepcopy(dict(self._llm_story_analysis_cache.get(cache_key) or {}))
        if cached.get("scenes") and cached.get("story_bible"):
            return cached
        raw_text = self._call_llm_story_analysis(provider=provider, model=model, prompt_payload=prompt_payload)
        try:
            parsed = self._parse_llm_json_object(raw_text)
        except Exception:
            repaired_text = self._repair_llm_story_analysis_json(raw_text, provider=provider, model=model)
            parsed = self._parse_llm_json_object(repaired_text)
        story_bible = self._normalize_llm_story_bible(
            parsed.get("story_bible") or {},
            fallback_story_bible=fallback_story_bible,
            story_style_guide=story_style_guide,
            continuity_strength=continuity_strength,
        )
        scenes = self._normalize_llm_scene_list(parsed.get("scenes") or [], image_chunks=image_chunks, story_bible=story_bible)
        if not scenes:
            raise RuntimeError("LLM story analysis returned no usable scenes.")
        story_bible["analysis_source"] = "llm"
        story_bible["analysis_provider_mode"] = self._story_analysis_provider_mode()
        story_bible["analysis_provider"] = chat_providers.provider_label(provider)
        story_bible["analysis_model"] = model
        result = {"story_bible": story_bible, "scenes": scenes}
        with self._lock:
            self._llm_story_analysis_cache[cache_key] = copy.deepcopy(result)
            while len(self._llm_story_analysis_cache) > 24:
                try:
                    self._llm_story_analysis_cache.pop(next(iter(self._llm_story_analysis_cache)))
                except Exception:
                    break
        return result

    def _llm_story_analysis_prompt_payload(self, *, full_text: str, image_chunks: list[dict], story_style_guide: str, continuity_strength: float):
        source_chunks = list(image_chunks or [])
        if len(source_chunks) > _AUDIO_STORY_LLM_ANALYSIS_MAX_CHUNKS:
            sampled = {}
            last_index = len(source_chunks) - 1
            for step in range(_AUDIO_STORY_LLM_ANALYSIS_MAX_CHUNKS):
                source_index = int(round((step / max(1, _AUDIO_STORY_LLM_ANALYSIS_MAX_CHUNKS - 1)) * last_index))
                sampled[source_index] = source_chunks[source_index]
            chunk_items = [(index, sampled[index]) for index in sorted(sampled.keys())]
        else:
            chunk_items = list(enumerate(source_chunks))
        per_chunk_limit = max(100, min(240, int(4800 / max(1, len(chunk_items)))))
        chunks = []
        for index, chunk in chunk_items:
            chunks.append(
                {
                    "chunk_index": int(index),
                    "start_seconds": round(float(chunk.get("start_seconds", 0.0) or 0.0), 2),
                    "end_seconds": round(float(chunk.get("end_seconds", 0.0) or 0.0), 2),
                    "text": _audio_story_truncate(str(chunk.get("text", "") or ""), per_chunk_limit),
                }
            )
        return {
            "task": "Analyze audiobook transcript chunks for consistent visual story generation.",
            "continuity_strength": round(float(self._normalize_continuity_strength(continuity_strength)), 3),
            "current_visual_style_guide": str(story_style_guide or "").strip(),
            "full_story_excerpt": _audio_story_truncate(full_text, 900),
            "sampled_chunk_count": len(chunks),
            "total_chunk_count": len(source_chunks),
            "chunks": chunks,
        }

    def _call_llm_story_analysis(self, *, provider: str, model: str, prompt_payload: dict):
        system_prompt = (
            "You are a visual story continuity analyst for an audiobook image generator. "
            "Return strict JSON only. Do not use markdown, comments, prose, code fences, or trailing commas. "
            "Create short, visible-only image briefs. Do not invent unnecessary characters, weapons, pregnancy, injuries, props, or location changes. "
            "Treat dialogue, inner thoughts, pain, fear, and body sensations as mood cues unless the transcript explicitly describes visible action. "
            "Prefer stable, reusable visual anchors for recurring people, places, props, and world details."
        )
        user_prompt = (
            "Create structured visual continuity metadata for these transcript chunks.\n\n"
            "Required JSON shape:\n"
            "{\n"
            '  "story_bible": {\n'
            '    "summary": "short story visual summary",\n'
            '    "global_visual_style": "stable style anchor",\n'
            '    "world_anchor": "recurring world, time period, palette, atmosphere",\n'
            '    "tone": ["tone words"],\n'
            '    "palette": ["palette or lighting cues"],\n'
            '    "time_period": "if inferable",\n'
            '    "characters": [{"id":"char_stable_id","label":"Name or role","aliases":["Name"],"summary":"role in story","appearance_anchor":"stable face/body/clothes/accessories"}],\n'
            '    "locations": [{"id":"loc_stable_id","label":"Location","aliases":["Location"],"summary":"location role","anchor_text":"stable architecture/layout/lighting"}],\n'
            '    "props": [{"id":"prop_stable_id","label":"Prop","aliases":["Prop"],"summary":"prop role","anchor_text":"stable visual description"}]\n'
            "  },\n"
            '  "scenes": [{\n'
            '    "chunk_index": 0,\n'
            '    "scene_id": "scene_stable_id",\n'
            '    "is_new_scene": true,\n'
            '    "continuation_of_scene_id": "",\n'
            '    "location_id": "loc_stable_id_or_empty",\n'
            '    "active_character_ids": ["char_stable_id"],\n'
            '    "prop_ids": ["prop_stable_id"],\n'
            '    "scene_focus": "visual focus, not raw transcript",\n'
            '    "image_prompt": "ready visual image prompt for this chunk, no raw transcript",\n'
            '    "key_action": "what should be pictured now",\n'
            '    "environment": "specific visible setting facts",\n'
            '    "mood": "mood",\n'
            '    "time_of_day": "if inferable",\n'
            '    "camera": "shot/framing suggestion",\n'
            '    "continuity_priority": ["characters","location","props","mood"],\n'
            '    "continuity": "what to preserve from previous image",\n'
            '    "preserve": "identity/location requirements",\n'
            '    "avoid": "image mistakes to avoid"\n'
            "  }]\n"
            "}\n\n"
            "Rules:\n"
            "- Return scene objects for the most important provided chunk_index values; missing chunks will be filled locally.\n"
            "- Use the exact same ids for recurring characters, locations, and props.\n"
            "- Scene text must be visible facts only, not copied raw transcript, dialogue, thoughts, or feelings.\n"
            "- image_prompt must be one natural-language visual sentence: subject + visible action + setting + mood/camera.\n"
            "- Do not describe pregnancy, guns, blood, wounds, children, monsters, or new cast members unless visibly explicit in this chunk.\n"
            "- If a chunk continues the same place/action, set is_new_scene=false and reuse scene_id.\n"
            "- If a new location, time jump, or major action shift occurs, set is_new_scene=true.\n"
            "- Keep all fields concise and useful for image prompting; favor continuity over novelty.\n\n"
            "Return compact minified JSON. Keep image_prompt under 220 characters and other text fields under 120 characters.\n\n"
            "Input JSON:\n"
            f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
        )
        params = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 3200,
            "response_format": {"type": "json_object"},
            "timeout": 120,
        }
        additional_params = {}
        if str(provider or "").strip().lower() == "deepseek":
            additional_params["thinking_type"] = "disabled"
        self._prepare_story_analysis_chat_request(
            provider=provider,
            model=model,
            params=params,
            additional_params=additional_params,
            min_output_tokens=3200,
            timeout_seconds=120,
        )
        last_error = None
        for _attempt in range(3):
            try:
                return str(chat_providers.complete_chat(provider, params, additional_params) or "").strip()
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                changed = False
                if "temperature" in message and "temperature" in params:
                    params.pop("temperature", None)
                    changed = True
                if ("max_tokens" in message or "max completion" in message) and "max_tokens" in params:
                    params.pop("max_tokens", None)
                    changed = True
                if ("response_format" in message or "json_object" in message) and "response_format" in params:
                    params.pop("response_format", None)
                    changed = True
                if (
                    "timeout" in message
                    and "timeout" in params
                    and any(marker in message for marker in ("unexpected", "unsupported", "unknown parameter", "invalid parameter"))
                ):
                    params.pop("timeout", None)
                    changed = True
                if not changed:
                    raise
        if last_error is not None:
            raise last_error
        return ""

    def _repair_llm_story_analysis_json(self, text: str, *, provider: str, model: str):
        raw_text = _audio_story_truncate(str(text or "").strip(), 24000)
        if not raw_text:
            raise RuntimeError("LLM story analysis returned an empty response.")
        params = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You repair malformed JSON. Return strict JSON only, no markdown, no prose. "
                        "Preserve the original keys and values as much as possible."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Repair this malformed story-analysis JSON into one valid compact JSON object. "
                        "If a list item or string is incomplete, close it safely rather than adding prose.\n\n"
                        f"{raw_text}"
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": 5000,
            "response_format": {"type": "json_object"},
            "timeout": 90,
        }
        additional_params = {}
        if str(provider or "").strip().lower() == "deepseek":
            additional_params["thinking_type"] = "disabled"
        self._prepare_story_analysis_chat_request(
            provider=provider,
            model=model,
            params=params,
            additional_params=additional_params,
            min_output_tokens=5000,
            timeout_seconds=90,
        )
        last_error = None
        for _attempt in range(3):
            try:
                return str(chat_providers.complete_chat(provider, params, additional_params) or "").strip()
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                changed = False
                if "temperature" in message and "temperature" in params:
                    params.pop("temperature", None)
                    changed = True
                if ("max_tokens" in message or "max completion" in message) and "max_tokens" in params:
                    params.pop("max_tokens", None)
                    changed = True
                if ("response_format" in message or "json_object" in message) and "response_format" in params:
                    params.pop("response_format", None)
                    changed = True
                if (
                    "timeout" in message
                    and "timeout" in params
                    and any(marker in message for marker in ("unexpected", "unsupported", "unknown parameter", "invalid parameter"))
                ):
                    params.pop("timeout", None)
                    changed = True
                if not changed:
                    raise
        if last_error is not None:
            raise last_error
        return ""

    def _parse_llm_json_object(self, text: str):
        value = str(text or "").strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE).strip()
            value = re.sub(r"\s*```$", "", value).strip()
        def parse_candidate(candidate: str):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Small local repair for common model output like "\_", "\.", or
                # "\(" inside JSON strings. These are invalid JSON escapes, but
                # preserving the literal character is safer than discarding LLM output.
                repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", candidate)
                return json.loads(repaired)
        try:
            parsed = parse_candidate(value)
        except Exception:
            start = value.find("{")
            end = value.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError("LLM story analysis did not return a JSON object.")
            parsed = parse_candidate(value[start : end + 1])
        if isinstance(parsed, str):
            parsed_text = parsed.strip()
            if parsed_text.startswith("{") and parsed_text.endswith("}"):
                parsed = parse_candidate(parsed_text)
        if not isinstance(parsed, dict):
            raise RuntimeError("LLM story analysis JSON root must be an object.")
        return parsed

    def _llm_string_list(self, value, *, limit: int = 8):
        if isinstance(value, str):
            candidates = re.split(r"[,;\n]+", value)
        elif isinstance(value, dict):
            candidates = value.values()
        else:
            candidates = list(value or []) if isinstance(value, (list, tuple, set)) else []
        return _audio_story_unique_keep_order(str(item or "").strip() for item in candidates if str(item or "").strip())[:limit]

    def _normalize_llm_entities(self, raw_entities, *, kind: str, fallback_prefix: str):
        if isinstance(raw_entities, dict):
            raw_items = []
            for key, value in raw_entities.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("id", key)
                else:
                    item = {"id": key, "label": value}
                raw_items.append(item)
        else:
            raw_items = [dict(item) for item in list(raw_entities or []) if isinstance(item, dict)]
        entities = {}
        for item in raw_items[:32]:
            label = str(item.get("label") or item.get("name") or item.get("role") or item.get("id") or "").strip()
            if not label:
                continue
            entity_id = str(item.get("id") or "").strip().lower()
            if not entity_id:
                entity_id = _audio_story_slug(label, prefix=fallback_prefix)
            entity_id = _audio_story_slug(entity_id, prefix=fallback_prefix) if not entity_id.startswith(f"{fallback_prefix}_") else entity_id
            aliases = self._llm_string_list(item.get("aliases") or [label], limit=8)
            summary = str(item.get("summary") or item.get("description") or item.get("role") or "").strip()
            anchor = str(
                item.get("appearance_anchor")
                or item.get("anchor_text")
                or item.get("visual_anchor")
                or item.get("description")
                or summary
                or ""
            ).strip()
            entities[entity_id] = {
                "id": entity_id,
                "label": label,
                "kind": kind,
                "mentions": max(1, int(item.get("mentions", 1) or 1)) if str(item.get("mentions", "1")).strip().isdigit() else 1,
                "sentences": [],
                "aliases": aliases,
                "summary": _audio_story_truncate(summary or anchor, 360),
                "anchor_text": _audio_story_truncate(anchor or summary, 420),
                "appearance_anchor": _audio_story_truncate(anchor or summary, 420) if kind == "character" else "",
                "image_path": str(item.get("image_path", "") or "").strip(),
            }
        return entities

    def _normalize_llm_story_bible(self, raw_bible, *, fallback_story_bible: dict, story_style_guide: str, continuity_strength: float):
        raw_bible = dict(raw_bible or {}) if isinstance(raw_bible, dict) else {}
        fallback_story_bible = dict(fallback_story_bible or {})
        global_style = dict(fallback_story_bible.get("global_style", {}) or {})
        global_style.update(
            {
                "story_style_guide": str(story_style_guide or global_style.get("story_style_guide", "") or "").strip(),
                "style_suffix": self._current_audio_story_style_suffix(),
                "master_prompt": str(self._story_generated_master_prompt or "").strip(),
                "style_enabled": list(self._stored_style_enabled or []),
                "style_prompts": dict(self._stored_style_prompts or {}),
                "master_prompt_enabled": bool(self._stored_story_master_prompt_enabled),
                "master_prompt_mode": self._audio_story_master_prompt_mode(),
                "continuity_strength": float(self._normalize_continuity_strength(continuity_strength)),
                "llm_global_visual_style": str(raw_bible.get("global_visual_style", "") or "").strip(),
            }
        )
        characters = self._normalize_llm_entities(raw_bible.get("characters"), kind="character", fallback_prefix="char")
        locations = self._normalize_llm_entities(raw_bible.get("locations"), kind="location", fallback_prefix="loc")
        props = self._normalize_llm_entities(raw_bible.get("props"), kind="prop", fallback_prefix="prop")
        if not characters:
            characters = dict(fallback_story_bible.get("characters", {}) or {})
        if not locations:
            locations = dict(fallback_story_bible.get("locations", {}) or {})
        if not props:
            props = dict(fallback_story_bible.get("props", {}) or {})
        atmosphere = str(
            raw_bible.get("atmosphere")
            or raw_bible.get("tone_palette_atmosphere")
            or raw_bible.get("world_anchor")
            or fallback_story_bible.get("atmosphere", "")
            or ""
        ).strip()
        world_cues = self._llm_string_list(raw_bible.get("world_cues") or raw_bible.get("world_anchor") or fallback_story_bible.get("world_cues", []), limit=8)
        return {
            "summary": _audio_story_truncate(str(raw_bible.get("summary") or fallback_story_bible.get("summary", "") or ""), 420),
            "global_style": global_style,
            "tone": self._llm_string_list(raw_bible.get("tone") or fallback_story_bible.get("tone", []), limit=6),
            "palette": self._llm_string_list(raw_bible.get("palette") or fallback_story_bible.get("palette", []), limit=6),
            "atmosphere": _audio_story_truncate(atmosphere, 520),
            "world_cues": world_cues,
            "time_period": str(raw_bible.get("time_period") or fallback_story_bible.get("time_period", "") or "").strip(),
            "characters": characters,
            "locations": locations,
            "props": props,
        }

    def _resolve_llm_entity_ids(self, raw_value, entities: dict, *, fallback_prefix: str, limit: int = 8):
        values = self._llm_string_list(raw_value, limit=limit)
        if not values:
            return []
        entity_map = dict(entities or {})
        label_to_id = {}
        for entity_id, entity in entity_map.items():
            labels = [str(entity.get("label", "") or "").strip(), *self._llm_string_list(entity.get("aliases", []), limit=12)]
            for label in labels:
                if label:
                    label_to_id[label.lower()] = str(entity_id)
        resolved = []
        for value in values:
            key = str(value or "").strip()
            if not key:
                continue
            lowered = key.lower()
            entity_id = key if key in entity_map else label_to_id.get(lowered, "")
            if not entity_id:
                entity_id = lowered if lowered.startswith(f"{fallback_prefix}_") else _audio_story_slug(key, prefix=fallback_prefix)
            resolved.append(entity_id)
        return _audio_story_unique_keep_order(resolved)[:limit]

    def _normalize_llm_scene_list(self, raw_scenes, *, image_chunks: list[dict], story_bible: dict):
        scenes = []
        max_index = max(0, len(image_chunks or []) - 1)
        for item in list(raw_scenes or []):
            if not isinstance(item, dict):
                continue
            try:
                chunk_index = int(item.get("chunk_index", -1) or -1)
            except Exception:
                continue
            if chunk_index < 0 or chunk_index > max_index:
                continue
            normalized = dict(item)
            normalized["chunk_index"] = chunk_index
            normalized["active_character_ids"] = self._resolve_llm_entity_ids(
                item.get("active_character_ids") or item.get("characters"),
                story_bible.get("characters", {}),
                fallback_prefix="char",
                limit=8,
            )
            normalized["prop_ids"] = self._resolve_llm_entity_ids(
                item.get("prop_ids") or item.get("props"),
                story_bible.get("props", {}),
                fallback_prefix="prop",
                limit=8,
            )
            location_ids = self._resolve_llm_entity_ids(
                item.get("location_id") or item.get("location") or item.get("locations"),
                story_bible.get("locations", {}),
                fallback_prefix="loc",
                limit=1,
            )
            normalized["location_id"] = location_ids[0] if location_ids else ""
            scenes.append(normalized)
        return sorted(scenes, key=lambda item: int(item.get("chunk_index", 0) or 0))

    def _scene_entry_from_llm_analysis(self, llm_scene: dict, *, index: int, chunk: dict, story_bible: dict, previous_scene, scene_index: int):
        llm_scene = dict(llm_scene or {})
        previous_scene = dict(previous_scene or {}) if isinstance(previous_scene, dict) else {}
        requested_new_scene = bool(llm_scene.get("is_new_scene", previous_scene == {}))
        if previous_scene and not requested_new_scene:
            resolved_scene_index = int(previous_scene.get("scene_index", scene_index) or scene_index)
            scene_id = str(llm_scene.get("scene_id") or previous_scene.get("scene_id") or "").strip()
            if not scene_id:
                scene_id = _audio_story_slug(f"scene_{resolved_scene_index}", prefix="scene")
            continuation_of = scene_id
        else:
            resolved_scene_index = int(scene_index) + 1
            scene_label = str(llm_scene.get("scene_id") or llm_scene.get("location_id") or llm_scene.get("scene_focus") or llm_scene.get("key_action") or f"scene {resolved_scene_index}").strip()
            scene_id = str(llm_scene.get("scene_id") or "").strip() or _audio_story_slug(f"{scene_label}_{resolved_scene_index}", prefix="scene")
            continuation_of = str(previous_scene.get("scene_id", "") or "") if previous_scene else ""
        location_id = str(llm_scene.get("location_id", "") or "").strip()
        location_label = ""
        if location_id:
            location_entry = dict((story_bible.get("locations", {}) or {}).get(location_id) or {})
            location_label = str(location_entry.get("label", "") or "").strip()
        scene_focus = str(llm_scene.get("scene_focus") or llm_scene.get("summary") or "").strip()
        image_prompt = str(llm_scene.get("image_prompt") or llm_scene.get("prompt") or "").strip()
        key_action = str(llm_scene.get("key_action") or llm_scene.get("action") or scene_focus or chunk.get("text", "") or "").strip()
        summary = str(llm_scene.get("summary") or scene_focus or key_action or "").strip()
        scene_entry = {
            "chunk_index": int(index),
            "scene_index": resolved_scene_index,
            "scene_id": scene_id,
            "is_new_scene": bool(not previous_scene or requested_new_scene),
            "continuation_of_scene_id": continuation_of,
            "location_id": location_id,
            "location_label": location_label,
            "active_character_ids": list(llm_scene.get("active_character_ids", []) or []),
            "prop_ids": list(llm_scene.get("prop_ids", []) or []),
            "mood": str(llm_scene.get("mood", "") or "").strip(),
            "time_of_day": str(llm_scene.get("time_of_day", "") or "").strip(),
            "key_action": _audio_story_truncate(key_action, 420),
            "summary": _audio_story_truncate(summary, 420),
            "camera": str(llm_scene.get("camera") or llm_scene.get("shot") or "").strip(),
            "continuity_priority": self._llm_string_list(llm_scene.get("continuity_priority") or ["characters", "location"], limit=8),
            "transition_score": 1.0 if requested_new_scene or not previous_scene else 0.05,
            "transition_reasons": ["llm_new_scene"] if requested_new_scene or not previous_scene else ["llm_continuation"],
            "analysis_source": "llm",
            "llm_scene_focus": scene_focus,
            "llm_image_prompt": _audio_story_visual_brief(image_prompt, 260),
            "llm_environment": str(llm_scene.get("environment", "") or "").strip(),
            "llm_style": str(llm_scene.get("style", "") or llm_scene.get("style_anchor", "") or "").strip(),
            "llm_world": str(llm_scene.get("world", "") or llm_scene.get("world_anchor", "") or "").strip(),
            "llm_continuity": str(llm_scene.get("continuity", "") or "").strip(),
            "llm_preserve": str(llm_scene.get("preserve", "") or "").strip(),
            "llm_avoid": str(llm_scene.get("avoid", "") or "").strip(),
        }
        return scene_entry, resolved_scene_index

    def _extract_story_entities(self, full_text: str):
        sentences = _audio_story_sentence_split(full_text)
        characters = {}
        locations = {}
        props = {}
        world_cues = []
        tones = []
        palettes = []
        time_period = ""

        def _first_descriptor(sentence: str, label: str):
            match = re.search(rf"(?<![A-Za-z0-9']){re.escape(str(label or '').strip())}(?![A-Za-z0-9'])", sentence, flags=re.IGNORECASE)
            if match is None:
                return ""
            before = sentence[max(0, match.start() - 48):match.start()].strip(" ,;:-")
            after = sentence[match.end(): match.end() + 96].strip(" ,;:-")
            return " ".join(part for part in (before, after) if part).strip()

        def _add_entity(entity_map, entity_id, label, kind, sentence, aliases=None):
            item = entity_map.setdefault(entity_id, {"id": entity_id, "label": label, "kind": kind, "mentions": 0, "sentences": [], "aliases": [], "summary": "", "anchor_text": "", "appearance_anchor": "", "image_path": ""})
            item["mentions"] = int(item.get("mentions", 0) or 0) + 1
            if sentence:
                item["sentences"].append(sentence)
            for alias in list(aliases or []):
                alias_text = str(alias or "").strip().lower()
                if alias_text and alias_text not in item["aliases"]:
                    item["aliases"].append(alias_text)

        candidate_names = Counter()
        candidate_locations = Counter()
        candidate_props = Counter()
        for sentence in sentences:
            lowered = sentence.lower()
            for marker, label in _AUDIO_STORY_WORLD_HINTS.items():
                if marker in lowered and label not in world_cues:
                    world_cues.append(label)
            for marker in _AUDIO_STORY_MOOD_MARKERS:
                if marker in lowered and marker not in tones:
                    tones.append(marker)
            for marker in _AUDIO_STORY_TIME_OF_DAY_MARKERS:
                if marker in lowered and marker not in palettes:
                    palettes.append(marker)
                    if not time_period:
                        time_period = marker
            for match in re.finditer(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Sir|Lady|Lord|Captain|Professor)\.?\s+[A-Z][a-z]+\b", sentence):
                label = _audio_story_normalize_character_label(match.group(0))
                if label:
                    candidate_names[label] += 1
            for match in re.finditer(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", sentence):
                label = _audio_story_normalize_character_label(match.group(0))
                if not label:
                    continue
                words = re.findall(r"[A-Za-z0-9']+", label)
                if len(words) == 1 and match.start() == 0:
                    continue
                if len(words) == 1 and sentence[max(0, match.start() - 16):match.start()].strip().lower().endswith((" no", " so", " yes")):
                    continue
                if any(keyword in label.lower() for keyword in _AUDIO_STORY_LOCATION_KEYWORDS):
                    continue
                candidate_names[label] += 1
            for pattern in (
                r"\b(?:in|at|inside|within|near|around|through|back\s+at|back\s+to|into|onto|on|aboard|inside\s+of|outside\s+of)\s+(?:the\s+|a\s+|an\s+)?([a-z][a-z0-9' -]{2,60})",
                r"\b(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:room|house|home|apartment|hall|street|city|town|village|forest|office|lab|workshop|studio|station|ship|market|cafe|diner|tower|castle|plaza|bridge|garden|kitchen|bedroom|bathroom)\b",
            ):
                for match in re.finditer(pattern, sentence):
                    label = _audio_story_clean_location_candidate(match.group(1), prefix=sentence[max(0, match.start() - 24):match.start()])
                    if label and label.lower() not in _AUDIO_STORY_COMMON_WORDS and len(label) >= 3:
                        candidate_locations[label] += 1
            for match in re.findall(r"\b(?:a|an|the)\s+([a-z][a-z0-9-]*(?:\s+[a-z][a-z0-9-]*){0,2})", sentence.lower()):
                label = str(match or "").strip()
                if label and label not in _AUDIO_STORY_COMMON_WORDS and any(hint in label for hint in _AUDIO_STORY_PROP_HINTS):
                    candidate_props[label] += 1

        if not candidate_names:
            for sentence in sentences:
                for hint in _AUDIO_STORY_CHARACTER_HINTS:
                    if _audio_story_sentence_matches(sentence, [hint]):
                        candidate_names[hint.title()] += 1
                        break
        if not candidate_locations:
            for sentence in sentences:
                for keyword in _AUDIO_STORY_LOCATION_KEYWORDS:
                    if keyword in sentence.lower():
                        candidate_locations[keyword] += 1
                        break
        if not candidate_props:
            for sentence in sentences:
                for hint in _AUDIO_STORY_PROP_HINTS:
                    if hint in sentence.lower():
                        candidate_props[hint] += 1
                        break

        for label, _count in candidate_names.most_common(10):
            if not _audio_story_is_character_candidate(label):
                continue
            entity_id = _audio_story_slug(label, prefix="char")
            related_sentences = [sentence for sentence in sentences if _audio_story_sentence_matches(sentence, [label])]
            summary_bits = []
            for sentence in related_sentences[:3]:
                summary_bits.append(_audio_story_truncate(sentence, 160))
            summary = _audio_story_truncate("; ".join(summary_bits), 220)
            _add_entity(characters, entity_id, label, "character", related_sentences[0] if related_sentences else "", aliases=[label])
            characters[entity_id]["summary"] = summary
            characters[entity_id]["appearance_anchor"] = summary
            characters[entity_id]["anchor_text"] = summary

        for label, _count in candidate_locations.most_common(10):
            entity_id = _audio_story_slug(label, prefix="loc")
            related_sentences = [sentence for sentence in sentences if _audio_story_sentence_matches(sentence, [label])]
            summary_bits = []
            for sentence in related_sentences[:3]:
                summary_bits.append(_audio_story_truncate(sentence, 160))
            summary = _audio_story_truncate("; ".join(summary_bits), 220)
            _add_entity(locations, entity_id, label, "location", related_sentences[0] if related_sentences else "", aliases=[label])
            locations[entity_id]["summary"] = summary
            locations[entity_id]["anchor_text"] = summary

        for label, _count in candidate_props.most_common(12):
            entity_id = _audio_story_slug(label, prefix="prop")
            related_sentences = [sentence for sentence in sentences if label in sentence.lower()]
            summary = _audio_story_truncate("; ".join(_audio_story_truncate(sentence, 120) for sentence in related_sentences[:2]), 220)
            _add_entity(props, entity_id, label, "prop", related_sentences[0] if related_sentences else "", aliases=[label])
            props[entity_id]["summary"] = summary
            props[entity_id]["anchor_text"] = summary

        return {
            "characters": characters,
            "locations": locations,
            "props": props,
            "tone": _audio_story_unique_keep_order(tones[:4]),
            "palette": _audio_story_unique_keep_order(palettes[:4]),
            "world_cues": _audio_story_unique_keep_order(world_cues[:6]),
            "time_period": str(time_period or "").strip(),
            "atmosphere": "; ".join(
                [
                    f"tone: {', '.join(_audio_story_unique_keep_order(tones[:3]))}" if tones else "",
                    f"time cues: {', '.join(_audio_story_unique_keep_order(palettes[:3]))}" if palettes else "",
                    f"world cues: {', '.join(_audio_story_unique_keep_order(world_cues[:4]))}" if world_cues else "",
                ]
            ).strip("; "),
        }

    def _build_story_bible(self, full_text: str, *, continuity_strength: float):
        entities = self._extract_story_entities(full_text)
        style_guide = str(self.story_style_guide or "").strip()
        master_prompt = str(self._story_generated_master_prompt or "").strip()
        style_suffix = self._current_audio_story_style_suffix()
        return {
            "summary": _audio_story_truncate(full_text, 260),
            "global_style": {
                "story_style_guide": style_guide,
                "style_suffix": style_suffix,
                "master_prompt": master_prompt,
                "style_enabled": list(self._stored_style_enabled or []),
                "style_prompts": dict(self._stored_style_prompts or {}),
                "master_prompt_enabled": bool(self._stored_story_master_prompt_enabled),
                "master_prompt_mode": self._audio_story_master_prompt_mode(),
                "continuity_strength": float(self._normalize_continuity_strength(continuity_strength)),
            },
            "tone": list(entities.get("tone", []) or []),
            "palette": list(entities.get("palette", []) or []),
            "atmosphere": str(entities.get("atmosphere", "") or "").strip(),
            "world_cues": list(entities.get("world_cues", []) or []),
            "time_period": str(entities.get("time_period", "") or "").strip(),
            "characters": dict(entities.get("characters", {}) or {}),
            "locations": dict(entities.get("locations", {}) or {}),
            "props": dict(entities.get("props", {}) or {}),
        }

    def _match_entity_ids(self, text: str, entities: dict, *, kind: str):
        lowered = str(text or "").lower()
        matches = []
        for entity_id, entity in dict(entities or {}).items():
            label = str(entity.get("label", "") or "").strip().lower()
            aliases = [str(alias or "").strip().lower() for alias in list(entity.get("aliases", []) or [])]
            if any(phrase for phrase in [label, *aliases] if phrase and phrase in lowered):
                matches.append(entity_id)
        if matches:
            return _audio_story_unique_keep_order(matches)
        fallback_hints = _AUDIO_STORY_CHARACTER_HINTS if kind == "character" else _AUDIO_STORY_LOCATION_KEYWORDS if kind == "location" else _AUDIO_STORY_PROP_HINTS
        for hint in fallback_hints:
            if re.search(rf"(?<![A-Za-z0-9']){re.escape(str(hint or '').strip())}(?![A-Za-z0-9'])", lowered, flags=re.IGNORECASE):
                return [hint.replace(" ", "_")]
        return []

    def _infer_scene_features(self, chunk_text: str, story_bible: dict, previous_scene=None):
        previous_scene = dict(previous_scene or {}) if isinstance(previous_scene, dict) else {}
        full_text = str(chunk_text or "").strip()
        sentences = _audio_story_sentence_split(full_text)
        characters = dict(story_bible.get("characters", {}) or {})
        locations = dict(story_bible.get("locations", {}) or {})
        props = dict(story_bible.get("props", {}) or {})
        active_character_ids = self._match_entity_ids(full_text, characters, kind="character")
        location_ids = self._match_entity_ids(full_text, locations, kind="location")
        prop_ids = self._match_entity_ids(full_text, props, kind="prop")
        if not location_ids and previous_scene.get("location_id"):
            location_ids = [str(previous_scene.get("location_id") or "").strip()]
        mood = str(previous_scene.get("mood", "") or "").strip()
        for marker in _AUDIO_STORY_MOOD_MARKERS:
            if marker in full_text.lower():
                mood = marker
                break
        time_of_day = str(previous_scene.get("time_of_day", "") or "").strip()
        for marker in _AUDIO_STORY_TIME_OF_DAY_MARKERS:
            if marker in full_text.lower():
                time_of_day = marker
                break
        key_action = _audio_story_visual_brief(" ".join(sentences[:2]) or full_text, 180)
        if not key_action:
            key_action = _audio_story_visual_brief(full_text, 180)
        if not key_action:
            key_action = _audio_story_truncate(full_text, 180)
        location_label = ""
        if location_ids:
            location_entry = dict(locations.get(location_ids[0]) or {})
            location_label = str(location_entry.get("label", "") or "").strip()
        if not location_label and previous_scene.get("location_label"):
            location_label = str(previous_scene.get("location_label") or "").strip()
        scene_label = location_label or key_action or f"scene {int(previous_scene.get('scene_index', 0) or 0) + 1}"
        camera = "wide shot" if not previous_scene else "medium shot"
        if len(active_character_ids) <= 1 and (mood in {"tense", "fearful", "intimate"} or not location_ids):
            camera = "close-up"
        if location_ids and not previous_scene.get("location_id"):
            camera = "establishing shot"
        continuity_priority = []
        if active_character_ids:
            continuity_priority.append("characters")
        if location_ids:
            continuity_priority.append("location")
        if prop_ids:
            continuity_priority.append("props")
        if mood:
            continuity_priority.append("mood")
        return {
            "active_character_ids": active_character_ids,
            "location_ids": location_ids,
            "prop_ids": prop_ids,
            "mood": mood,
            "time_of_day": time_of_day,
            "key_action": key_action,
            "scene_label": scene_label,
            "camera": camera,
            "continuity_priority": continuity_priority or ["continuity"],
            "summary": key_action,
        }

    def _classify_scene_transition(self, current_features: dict, previous_scene: dict | None, chunk_text: str, story_bible: dict):
        previous_scene = dict(previous_scene or {}) if isinstance(previous_scene, dict) else {}
        if not previous_scene:
            return {"score": 1.0, "is_new_scene": True, "reasons": ["first_scene"]}
        score = 0.0
        reasons = []
        lowered = str(chunk_text or "").lower()
        if any(marker in lowered for marker in _AUDIO_STORY_TRANSITION_MARKERS):
            score += 0.34
            reasons.append("transition_marker")
        prev_location = str(previous_scene.get("location_id", "") or "").strip()
        current_location = str((current_features.get("location_ids") or [""])[0] or "").strip()
        if current_location and current_location != prev_location:
            score += 0.30
            reasons.append("location_change")
        prev_chars = set(previous_scene.get("active_character_ids", []) or [])
        current_chars = set(current_features.get("active_character_ids", []) or [])
        if current_chars and current_chars != prev_chars:
            if current_chars - prev_chars:
                score += 0.18
                reasons.append("new_character_focus")
        prev_mood = str(previous_scene.get("mood", "") or "").strip()
        current_mood = str(current_features.get("mood", "") or "").strip()
        if current_mood and current_mood != prev_mood:
            score += 0.12
            reasons.append("mood_shift")
        prev_time = str(previous_scene.get("time_of_day", "") or "").strip()
        current_time = str(current_features.get("time_of_day", "") or "").strip()
        if current_time and current_time != prev_time:
            score += 0.10
            reasons.append("time_shift")
        prev_tokens = set(_audio_story_keyword_tokens(previous_scene.get("summary", "") or previous_scene.get("key_action", "") or ""))
        current_tokens = set(_audio_story_keyword_tokens(current_features.get("summary", "") or current_features.get("key_action", "") or ""))
        if prev_tokens or current_tokens:
            overlap = len(prev_tokens & current_tokens) / max(1, len(prev_tokens | current_tokens))
            score += max(0.0, 0.18 - (overlap * 0.18))
            if overlap < 0.35:
                reasons.append("low_token_overlap")
        if current_location and not prev_location:
            score += 0.08
        threshold = 0.38 + (0.34 * float(self._normalize_continuity_strength(self._stored_continuity_strength)))
        return {"score": min(1.0, score), "is_new_scene": score >= threshold, "reasons": reasons}

    def _build_character_anchor_text(self, story_bible: dict, character_ids: list[str]):
        parts = []
        for character_id in list(character_ids or []):
            entry = dict((story_bible.get("characters", {}) or {}).get(character_id) or {})
            if not entry:
                continue
            label = str(entry.get("label", "") or "").strip()
            if not _audio_story_is_character_candidate(label):
                continue
            anchor_text = str(entry.get("appearance_anchor", "") or entry.get("summary", "") or "").strip()
            if label or anchor_text:
                parts.append(f"{label}: {anchor_text}".strip(": ").strip())
        return "; ".join([part for part in parts if part])

    def _build_location_anchor_text(self, story_bible: dict, location_id: str):
        entry = dict((story_bible.get("locations", {}) or {}).get(location_id) or {})
        if not entry:
            return ""
        label = str(entry.get("label", "") or "").strip()
        anchor_text = str(entry.get("anchor_text", "") or entry.get("summary", "") or "").strip()
        if label and anchor_text:
            return f"{label}: {anchor_text}"
        return label or anchor_text

    def _build_continuity_block(self, scene_entry: dict, story_bible: dict, previous_scene=None):
        previous_scene = dict(previous_scene or {}) if isinstance(previous_scene, dict) else {}
        active_chars = list(scene_entry.get("active_character_ids", []) or [])
        character_block = self._build_character_anchor_text(story_bible, active_chars)
        location_id = str(scene_entry.get("location_id", "") or "").strip()
        location_block = self._build_location_anchor_text(story_bible, location_id)
        continuity_bits = []
        if character_block:
            continuity_bits.append(f"Preserve the recurring character identity: {character_block}.")
        if location_block:
            continuity_bits.append(f"Preserve the recurring location identity: {location_block}.")
        if previous_scene and previous_scene.get("scene_id") == scene_entry.get("scene_id"):
            continuity_bits.append("Continue the exact same scene and preserve composition continuity.")
        elif previous_scene:
            continuity_bits.append("Keep the same story world and preserve recurring identities while allowing the scene to move forward.")
        continuity_bits.append("Do not redesign faces, clothes, props, or location architecture unless the story explicitly changes them.")
        return " ".join(continuity_bits).strip()

    def _compose_story_prompt(self, scene_entry: dict, *, story_bible: dict, story_style_guide: str, previous_scene=None):
        scene_entry = dict(scene_entry or {})
        story_bible = dict(story_bible or {})
        block_limits = self._prompt_block_limits()
        style_bits = []
        global_style = dict(story_bible.get("global_style", {}) or {})
        style_suffix = str(global_style.get("style_suffix", "") or "").strip()
        if style_suffix:
            style_bits.append(style_suffix)
        if story_style_guide:
            style_bits.append(story_style_guide)
        if global_style.get("master_prompt_enabled") and global_style.get("master_prompt"):
            style_bits.append(str(global_style.get("master_prompt", "") or "").strip())
        if scene_entry.get("llm_style"):
            style_bits.append(str(scene_entry.get("llm_style", "") or "").strip())
        world_bits = []
        if story_bible.get("atmosphere"):
            world_bits.append(str(story_bible.get("atmosphere", "") or "").strip())
        if story_bible.get("world_cues"):
            world_bits.append("world cues: " + ", ".join(_audio_story_unique_keep_order(story_bible.get("world_cues", []) or [])[:4]))
        if story_bible.get("time_period"):
            world_bits.append(f"time period cue: {str(story_bible.get('time_period', '') or '').strip()}")
        if scene_entry.get("llm_world"):
            world_bits.append(str(scene_entry.get("llm_world", "") or "").strip())
        pinned_character_ids = [str(item or "").strip() for item in list(self.scene_overrides.get("pinned_character_ids", []) or []) if str(item or "").strip()]
        active_character_ids = _audio_story_unique_keep_order(list(scene_entry.get("active_character_ids", []) or []) + pinned_character_ids)
        character_text = self._build_character_anchor_text(story_bible, active_character_ids)
        location_id = str(scene_entry.get("location_id", "") or "").strip()
        pinned_location_ids = [str(item or "").strip() for item in list(self.scene_overrides.get("pinned_location_ids", []) or []) if str(item or "").strip()]
        if pinned_location_ids and (not location_id or location_id not in pinned_location_ids):
            location_id = pinned_location_ids[0]
        location_text = self._build_location_anchor_text(story_bible, location_id)
        style_text = " ".join([part for part in style_bits if part]).strip()
        world_text = " ".join([part for part in world_bits if part]).strip()
        props = []
        for prop_id in list(scene_entry.get("prop_ids", []) or [])[:4]:
            entry = dict((story_bible.get("props", {}) or {}).get(prop_id) or {})
            label = str(entry.get("label", "") or "").strip()
            anchor_text = str(entry.get("anchor_text", "") or entry.get("summary", "") or "").strip()
            if label or anchor_text:
                props.append(f"{label}: {anchor_text}".strip(": ").strip())
        scene_id = str(scene_entry.get("scene_id", "") or "").strip()
        anchor_override = str(dict(self.scene_overrides.get("scene_anchor_overrides", {}) or {}).get(scene_id, "") or "").strip()
        llm_image_prompt = str(scene_entry.get("llm_image_prompt", "") or "").strip()
        action = _audio_story_visual_brief(
            anchor_override or llm_image_prompt or str(scene_entry.get("llm_scene_focus", "") or scene_entry.get("key_action", "") or "").strip(),
            260 if llm_image_prompt and not anchor_override else 220,
        )
        if not action:
            mood = str(scene_entry.get("mood", "") or "").strip()
            action = _audio_story_truncate(f"{mood} quiet story moment" if mood else "quiet story moment", 80)
        environment = str(scene_entry.get("llm_environment", "") or "").strip()
        camera = str(scene_entry.get("camera", "") or "").strip()
        previous_scene = dict(previous_scene or {}) if isinstance(previous_scene, dict) else {}
        continuity_bits = []
        if previous_scene and previous_scene.get("scene_id") == scene_entry.get("scene_id"):
            continuity_bits.append("continue the same scene")
        elif previous_scene:
            continuity_bits.append("same story world")
        if character_text:
            continuity_bits.append("match recurring character identity")
        if location_text:
            continuity_bits.append("match recurring location layout")
        continuity = ", ".join(continuity_bits)
        if scene_entry.get("llm_continuity"):
            continuity = ", ".join([part for part in [continuity, str(scene_entry.get("llm_continuity", "") or "").strip()] if part]).strip()
        preserve_bits = [
            "preserve recurring identities, outfits, props, and location layout",
            "use only visible transcript facts",
        ]
        if scene_entry.get("llm_preserve"):
            preserve_bits.insert(0, str(scene_entry.get("llm_preserve", "") or "").strip())
        avoid_bits = [
            "text, captions, watermarks, speech bubbles",
            "invented cast, props, pregnancy, weapons, injuries, or location changes",
        ]
        negative_prompt_override = str(dict(self.scene_overrides.get("scene_negative_prompt_overrides", {}) or {}).get(scene_id, "") or "").strip()
        if negative_prompt_override:
            avoid_bits.insert(0, negative_prompt_override)
        global_negative_prompt = str(self.scene_overrides.get("global_negative_prompt", "") or "").strip()
        if bool(self.scene_overrides.get("global_negative_prompt_enabled", False)) and global_negative_prompt:
            avoid_bits.insert(0, global_negative_prompt)
        if scene_entry.get("llm_avoid"):
            avoid_bits.insert(0, str(scene_entry.get("llm_avoid", "") or "").strip())
        subject_bits = []
        if action:
            subject_bits.append(action)
        if character_text:
            subject_bits.append("recurring cast: " + _audio_story_truncate(character_text, min(180, block_limits["characters"])))
        if location_text:
            subject_bits.append("setting: " + _audio_story_truncate(location_text, min(160, block_limits["location"])))
        if environment:
            subject_bits.append(_audio_story_truncate(environment, 140))
        if props:
            subject_bits.append("visible props: " + _audio_story_truncate(", ".join(props), min(120, block_limits["props"])))
        if world_text:
            subject_bits.append(_audio_story_truncate(world_text, min(110, block_limits["world"])))
        blocks = [
            "Cinematic story frame: " + "; ".join(part for part in subject_bits if part).strip(" ;"),
            f"Framing: {camera}." if camera else "",
            f"Style: {_audio_story_truncate(style_text, min(160, block_limits['style']))}." if style_text else "",
            f"Continuity: {_audio_story_truncate(continuity, min(180, block_limits['continuity']))}." if continuity else "",
            f"Preserve: {_audio_story_truncate(', '.join(preserve_bits), min(140, block_limits['preserve']))}.",
            f"Avoid: {_audio_story_truncate(', '.join(avoid_bits), min(160, block_limits['avoid']))}.",
        ]
        prompt = " ".join(part for part in blocks if str(part or "").strip()).strip()
        safety_cap = min(self._normalize_prompt_safety_cap(), 900)
        if len(prompt) > safety_cap:
            prompt = prompt[:safety_cap].rstrip(" \t\r\n,;:.-")
        return prompt

    def _story_reference_image_paths(self, scene_entry: dict, previous_scene=None):
        references = []
        scene_entry = dict(scene_entry or {})
        previous_scene = dict(previous_scene or {}) if isinstance(previous_scene, dict) else {}
        continuity_memory = dict(self.continuity_memory or {})
        scenes_memory = dict(continuity_memory.get("scenes", {}) or {})
        if previous_scene.get("scene_id"):
            prev_scene_memory = dict(scenes_memory.get(str(previous_scene.get("scene_id", "") or ""), {}) or {})
            prev_image = str(prev_scene_memory.get("last_generated_image_path", "") or "").strip()
            if prev_image:
                references.append(prev_image)
        scene_id = str(scene_entry.get("scene_id", "") or "").strip()
        if scene_id:
            scene_memory = dict(scenes_memory.get(scene_id, {}) or {})
            scene_image = str(scene_memory.get("last_generated_image_path", "") or "").strip()
            if scene_image:
                references.append(scene_image)
        for character_id in list(scene_entry.get("active_character_ids", []) or []):
            anchor = dict((self.character_anchors or {}).get(character_id) or {})
            if not anchor:
                anchor = dict(dict(continuity_memory.get("characters", {}) or {}).get(character_id) or {})
            image_path = str(anchor.get("image_path", "") or "").strip()
            if image_path:
                references.append(image_path)
        for character_id in list(self.scene_overrides.get("pinned_character_ids", []) or []):
            anchor = dict((self.character_anchors or {}).get(str(character_id)) or {})
            if not anchor:
                anchor = dict(dict(continuity_memory.get("characters", {}) or {}).get(str(character_id)) or {})
            image_path = str(anchor.get("image_path", "") or "").strip()
            if image_path:
                references.append(image_path)
        location_id = str(scene_entry.get("location_id", "") or "").strip()
        if location_id:
            anchor = dict((self.location_anchors or {}).get(location_id) or {})
            if not anchor:
                anchor = dict(dict(continuity_memory.get("locations", {}) or {}).get(location_id) or {})
            image_path = str(anchor.get("image_path", "") or "").strip()
            if image_path:
                references.append(image_path)
        for location_id in list(self.scene_overrides.get("pinned_location_ids", []) or []):
            anchor = dict((self.location_anchors or {}).get(str(location_id)) or {})
            if not anchor:
                anchor = dict(dict(continuity_memory.get("locations", {}) or {}).get(str(location_id)) or {})
            image_path = str(anchor.get("image_path", "") or "").strip()
            if image_path:
                references.append(image_path)
        cleaned = []
        for path in _audio_story_unique_keep_order(references):
            try:
                if Path(path).exists():
                    cleaned.append(path)
            except Exception:
                continue
        return cleaned

    def _choose_generation_mode(self, scene_entry: dict, previous_scene=None):
        scene_entry = dict(scene_entry or {})
        previous_scene = dict(previous_scene or {}) if isinstance(previous_scene, dict) else {}
        scene_id = str(scene_entry.get("scene_id", "") or "").strip()
        forced_mode = str(dict(self.scene_overrides.get("forced_scene_modes", {}) or {}).get(scene_id, "") or "").strip().lower()
        if forced_mode == "fresh":
            return {"mode": "fresh", "reference_image_paths": [], "reason": "forced_fresh"}
        if forced_mode == "continuation":
            scene_entry["is_new_scene"] = False
            scene_entry["transition_score"] = 0.0
        if previous_scene.get("scene_id") and previous_scene.get("scene_id") == scene_entry.get("scene_id") and self._visual_provider_supports_reference_edits():
            return {"mode": "edit", "reference_image_paths": [], "reason": "same_scene"}
        if not self._visual_provider_supports_reference_edits():
            return {"mode": "fresh", "reference_image_paths": [], "reason": "no_reference_support"}
        references = self._story_reference_image_paths(scene_entry, previous_scene=previous_scene)
        is_new_scene = bool(scene_entry.get("is_new_scene", False))
        transition_score = float(scene_entry.get("transition_score", 0.0) or 0.0)
        if is_new_scene and transition_score >= 0.72 and len(scene_entry.get("active_character_ids", []) or []) <= 1 and not scene_entry.get("location_id"):
            return {"mode": "fresh", "reference_image_paths": [], "reason": "major_jump"}
        if len(references) >= 2:
            return {"mode": "multi_reference", "reference_image_paths": references[:3], "reason": "scene_continuity"}
        return {"mode": "edit", "reference_image_paths": references[:1], "reason": "single_reference"}

    def _reference_image_signature(self, path: str):
        try:
            stat = Path(path).stat()
        except Exception:
            return ""
        payload = {
            "path": str(Path(path).resolve()),
            "size": int(stat.st_size),
            "mtime": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()

    def _visual_provider_supports_reference_edits(self):
        provider = str(str(self._visual_reply_generation_info().get("provider") or "") or "").strip().lower()
        if provider != "openai":
            return False
        return bool(bool(self._visual_reply_generation_info().get("generation_available")))

    def _generate_visual_image_from_fresh(self, prompt_text: str, *, index: int):
        client = self._get_visual_client()
        generation_info = dict(self._visual_reply_generation_info() or {})
        provider = str(generation_info.get("provider") or "").strip().lower()
        diagnostics = dict(generation_info.get("diagnostics") or {})
        if diagnostics:
            print(f"[AudioStoryMode] Visual generation diagnostics: {diagnostics}")
        request_kwargs = {
            "model": str(generation_info.get("model") or ""),
            "prompt": str(prompt_text or "").strip(),
        }
        if provider == "xai":
            request_kwargs["response_format"] = str(generation_info.get("response_format") or "b64_json").strip() or "b64_json"
            extra_body = {
                str(key): value
                for key, value in dict(generation_info.get("extra_body") or {}).items()
                if str(key or "").strip() and str(value or "").strip()
            }
            if extra_body:
                request_kwargs["extra_body"] = extra_body
            request_kwargs["n"] = 1
        else:
            request_kwargs["size"] = str(generation_info.get("size") or "")
        response = client.images.generate(**request_kwargs)
        output_path = self._visual_reply_output_base("audio_story", index)
        output_path = self._visual_reply_write_image_from_response(response, output_path)
        return {
            "image_path": str(output_path),
            "prompt_text": str(prompt_text or "").strip(),
            "prompt_signature": "",
            "generation_mode": "fresh",
            "reference_image_paths": [],
        }

    def _generate_visual_image_from_references(self, prompt_text: str, *, index: int, reference_image_paths: list[str], generation_mode: str):
        if not reference_image_paths:
            raise RuntimeError("No reference images available for continuity generation.")
        if not self._visual_provider_supports_reference_edits():
            raise RuntimeError("The active image provider does not support reference edits.")
        client = self._get_visual_client()
        request_kwargs = {
            "model": str(self._visual_reply_generation_info().get("model") or ""),
            "prompt": str(prompt_text or "").strip(),
            "image": [],
            "size": str(self._visual_reply_generation_info().get("size") or ""),
        }
        with ExitStack() as stack:
            handles = []
            for path in list(reference_image_paths or [])[:3]:
                try:
                    handles.append(stack.enter_context(open(str(path), "rb")))
                except Exception:
                    continue
            if not handles:
                raise RuntimeError("No usable reference images could be opened.")
            request_kwargs["image"] = handles if len(handles) > 1 else handles[0]
            try:
                response = client.images.edit(**request_kwargs)
            except Exception:
                if len(handles) > 1:
                    request_kwargs["image"] = handles[0]
                    response = client.images.edit(**request_kwargs)
                else:
                    raise
        output_path = self._visual_reply_output_base("audio_story", index)
        output_path = self._visual_reply_write_image_from_response(response, output_path)
        return {
            "image_path": str(output_path),
            "prompt_text": str(prompt_text or "").strip(),
            "prompt_signature": "",
            "generation_mode": generation_mode,
            "reference_image_paths": list(reference_image_paths or []),
        }

    def _generate_visual_image_from_edit(self, prompt_text: str, *, index: int, reference_image_paths: list[str]):
        return self._generate_visual_image_from_references(prompt_text, index=index, reference_image_paths=reference_image_paths[:1], generation_mode="edit")

    def _generate_visual_image_from_multi_reference(self, prompt_text: str, *, index: int, reference_image_paths: list[str]):
        return self._generate_visual_image_from_references(prompt_text, index=index, reference_image_paths=reference_image_paths[:3], generation_mode="multi_reference")

    def _update_continuity_memory_from_image(self, *, scene_entry: dict, image_entry: dict, prompt_signature: str):
        scene_entry = dict(scene_entry or {})
        image_entry = dict(image_entry or {})
        image_path = str(image_entry.get("image_path", "") or "").strip()
        scene_id = str(scene_entry.get("scene_id", "") or "").strip()
        location_id = str(scene_entry.get("location_id", "") or "").strip()
        active_character_ids = list(scene_entry.get("active_character_ids", []) or [])
        continuity_memory = dict(self.continuity_memory or {})
        scenes_memory = dict(continuity_memory.get("scenes", {}) or {})
        characters_memory = dict(continuity_memory.get("characters", {}) or {})
        locations_memory = dict(continuity_memory.get("locations", {}) or {})
        if scene_id:
            scenes_memory[scene_id] = {
                "scene_id": scene_id,
                "scene_index": int(scene_entry.get("scene_index", 0) or 0),
                "location_id": location_id,
                "location_label": str(scene_entry.get("location_label", "") or "").strip(),
                "active_character_ids": list(active_character_ids),
                "last_generated_image_path": image_path,
                "last_prompt_signature": str(prompt_signature or "").strip(),
                "last_prompt_text": str(image_entry.get("prompt_text", "") or "").strip(),
                "generation_mode": str(image_entry.get("generation_mode", "") or "").strip(),
                "reference_image_paths": list(image_entry.get("reference_image_paths", []) or []),
            }
        for character_id in active_character_ids:
            if not character_id:
                continue
            anchor = dict(characters_memory.get(character_id) or {})
            anchor.update({"id": character_id, "image_path": image_path or str(anchor.get("image_path", "") or "").strip(), "last_seen_scene_id": scene_id, "last_prompt_signature": str(prompt_signature or "").strip()})
            self.character_anchors[character_id] = anchor
            characters_memory[character_id] = dict(anchor)
        if location_id:
            anchor = dict(locations_memory.get(location_id) or {})
            anchor.update({"id": location_id, "image_path": image_path or str(anchor.get("image_path", "") or "").strip(), "last_seen_scene_id": scene_id, "last_prompt_signature": str(prompt_signature or "").strip()})
            self.location_anchors[location_id] = anchor
            locations_memory[location_id] = dict(anchor)
        self.continuity_memory = {
            "last_scene_id": scene_id,
            "last_scene_index": int(scene_entry.get("scene_index", 0) or 0),
            "last_generated_image_path": image_path,
            "last_prompt_signature": str(prompt_signature or "").strip(),
            "last_prompt_text": str(image_entry.get("prompt_text", "") or "").strip(),
            "scenes": scenes_memory,
            "characters": characters_memory,
            "locations": locations_memory,
        }

    def _apply_scene_prompts(self):
        if not self.transcript_chunks:
            return
        story_bible = dict(self.story_bible or {})
        story_bible_mode = self._audio_story_analysis_mode() == "story_bible"
        story_memory = None
        story_analyzer = None
        if story_bible_mode:
            store = self._story_bible_store(self.imported_audio_path)
            story_memory = store.load()
            story_analyzer = StoryAnalyzer()
        scene_map = {}
        for scene_entry in list(self.scene_plan or []):
            if isinstance(scene_entry, dict):
                scene_map[int(scene_entry.get("chunk_index", -1) or -1)] = dict(scene_entry)
        for index, chunk in enumerate(self.transcript_chunks):
            scene_entry = dict(scene_map.get(int(index)) or {})
            previous_scene = dict(scene_map.get(int(index - 1)) or {}) if index > 0 else None
            chunk["scene_id"] = str(scene_entry.get("scene_id", "") or "")
            chunk["scene_index"] = int(scene_entry.get("scene_index", 0) or 0)
            chunk["location_id"] = str(scene_entry.get("location_id", "") or "")
            chunk["location_label"] = str(scene_entry.get("location_label", "") or "")
            chunk["active_character_ids"] = list(scene_entry.get("active_character_ids", []) or [])
            chunk["prop_ids"] = list(scene_entry.get("prop_ids", []) or [])
            chunk["mood"] = str(scene_entry.get("mood", "") or "")
            chunk["time_of_day"] = str(scene_entry.get("time_of_day", "") or "")
            chunk["camera"] = str(scene_entry.get("camera", "") or "")
            chunk["is_scene_continuation"] = not bool(scene_entry.get("is_new_scene", False))
            chunk["continuity_priority"] = list(scene_entry.get("continuity_priority", []) or [])
            chunk["scene_summary"] = str(scene_entry.get("summary", "") or "")
            if story_bible_mode and story_memory is not None and story_analyzer is not None:
                update = story_analyzer.analyze(str(chunk.get("text", "") or ""), chunk_index=index, memory=story_memory)
                chunk["prompt"] = self._build_story_bible_image_prompt(
                    str(chunk.get("text", "") or ""),
                    chunk_index=index,
                    scene_entry=scene_entry,
                    memory=story_memory,
                    analyzer_update=update,
                )
            else:
                chunk["prompt"] = self._build_story_image_prompt(
                    str(chunk.get("text", "") or ""),
                    str(self.story_style_guide or ""),
                    scene_entry=scene_entry,
                    story_bible=story_bible,
                    previous_scene=previous_scene,
                )

    def _rebuild_story_consistency_from_transcript(self, *, refresh_visuals: bool = False):
        if not self.transcript_chunks and not self._raw_transcript_segments:
            return
        if self._raw_transcript_segments and self._last_transcription_audio_duration > 0.0:
            payload = self._build_story_payload(
                job_id=self._transcription_job_id,
                path=self.imported_audio_path,
                audio_duration=self._last_transcription_audio_duration,
                raw_segments=self._raw_transcript_segments,
                chunk_seconds=int(self._stored_transcribe_seconds or 8),
                image_frequency_seconds=int(self._stored_image_frequency_seconds or 12),
                continuity_strength=float(self._stored_continuity_strength or 0.8),
            )
            self.transcript_chunks = list(payload.get("transcript_chunks", []) or [])
            self.full_transcript_text = str(payload.get("full_text", "") or "").strip()
            self.story_style_guide = str(payload.get("story_style_guide", "") or "").strip()
            self.story_bible = dict(payload.get("story_bible", {}) or {})
            self.scene_plan = list(payload.get("scene_plan", []) or [])
            self.character_anchors = dict(payload.get("character_anchors", {}) or {})
            self.location_anchors = dict(payload.get("location_anchors", {}) or {})
        with self._lock:
            previous_image_cache = {int(index): dict(item or {}) for index, item in dict(self._image_cache or {}).items()}
            previous_prompt_cache = {str(key): dict(item or {}) for key, item in dict(self._prompt_image_cache or {}).items()}
        self._apply_scene_prompts()
        with self._lock:
            self._image_cache.update(previous_image_cache)
            self._prompt_image_cache.update(previous_prompt_cache)
        self._reconcile_cached_images_for_current_prompts()
        if refresh_visuals:
            position_seconds = self._player_position_seconds()
            self._restart_visual_generation_from_position(position_seconds, force=True)
            self._sync_visual_to_position(position_seconds, force=True)
        self._refresh_scene_override_controls()

    def _set_visual_reply_master_prompt_runtime(self, prompt_text: str):
        normalized_prompt = str(prompt_text or "").strip()
        current_prompt = str(audio_story_runtime.runtime_config_value("visual_reply_master_style_prompt", "") or "").strip()
        if current_prompt == normalized_prompt:
            return False
        audio_story_runtime.update_runtime_config("visual_reply_master_style_prompt", normalized_prompt)
        if self.visual_reply_service is not None:
            try:
                self.visual_reply_service.refresh_hint()
            except Exception:
                pass
        if self.shell is not None:
            try:
                self.shell.notify_settings_changed()
            except Exception:
                pass
        return True

    def _sync_story_generated_master_prompt(self, *, refresh_visuals: bool = False):
        if not self._stored_story_master_prompt_enabled:
            current_prompt = str(audio_story_runtime.runtime_config_value("visual_reply_master_style_prompt", "") or "").strip()
            restore_prompt = self._story_master_prompt_previous_runtime_value
            if restore_prompt is None:
                self._story_generated_master_prompt = ""
                return False
            updated = False
            if current_prompt == str(self._story_generated_master_prompt or "").strip():
                updated = self._set_visual_reply_master_prompt_runtime(str(restore_prompt or "").strip())
            self._story_generated_master_prompt = ""
            self._story_master_prompt_previous_runtime_value = None
            if refresh_visuals and self.transcript_chunks and updated:
                self.refresh_master_style_anchor({"source": "audio_story_master_prompt_off"})
            return updated
        if not self.full_transcript_text:
            return False
        generated_prompt = self._build_story_generated_master_prompt()
        current_prompt = str(audio_story_runtime.runtime_config_value("visual_reply_master_style_prompt", "") or "").strip()
        if self._story_master_prompt_previous_runtime_value is None:
            if current_prompt != str(self._story_generated_master_prompt or "").strip():
                self._story_master_prompt_previous_runtime_value = current_prompt
            else:
                self._story_master_prompt_previous_runtime_value = ""
        self._story_generated_master_prompt = generated_prompt
        updated = self._set_visual_reply_master_prompt_runtime(generated_prompt)
        if refresh_visuals and self.transcript_chunks and updated:
            self.refresh_master_style_anchor({"source": "audio_story_master_prompt_on"})
        return updated

    def _schedule_visual_refresh(self):
        if not self.transcript_chunks:
            return False
        try:
            self._visual_refresh_timer.start()
            return True
        except Exception:
            self._apply_live_prompt_changes()
            return True

    def _schedule_story_payload_rebuild(self, *, status_text: str = "Updating audio story timing..."):
        if not self._raw_transcript_segments or self._last_transcription_audio_duration <= 0.0:
            return False
        self._pending_story_rebuild_status_text = str(status_text or "Updating audio story timing...").strip()
        self._set_status(self._pending_story_rebuild_status_text)
        try:
            self._story_rebuild_timer.start()
            return True
        except Exception:
            self._flush_scheduled_story_payload_rebuild()
            return True

    def _flush_scheduled_story_payload_rebuild(self):
        if not self._raw_transcript_segments or self._last_transcription_audio_duration <= 0.0:
            return
        status_text = str(self._pending_story_rebuild_status_text or "Updating audio story timing...").strip()
        if status_text:
            self._set_status(status_text)
        self._rebuild_story_payload_from_cached_segments()
        self._pending_story_rebuild_status_text = ""

    def _flush_scheduled_visual_refresh(self):
        if not self.transcript_chunks:
            return
        self._apply_live_prompt_changes()

    def _is_audio_story_currently_playing(self):
        if self.audio_player is None:
            return False
        try:
            state = self.audio_player.playbackState()
        except Exception:
            return False
        playback_state_enum = getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlaybackState", None)
        playing_state = getattr(playback_state_enum, "PlayingState", None) if playback_state_enum is not None else getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlayingState", None)
        return state == playing_state

    def _apply_live_prompt_changes(self):
        if not self.transcript_chunks:
            return
        story_style_guide = self._visual_reply_story_style_guide(
            self.full_transcript_text,
            continuity_strength=self._normalize_continuity_strength(self._stored_continuity_strength),
        )
        self.story_style_guide = story_style_guide
        if not self.story_bible and self._raw_transcript_segments:
            self._rebuild_story_consistency_from_transcript(refresh_visuals=False)
            return
        story_bible = dict(self.story_bible or {})
        global_style = dict(story_bible.get("global_style", {}) or {})
        global_style["story_style_guide"] = story_style_guide
        global_style["style_suffix"] = self._current_audio_story_style_suffix()
        global_style["master_prompt"] = str(self._story_generated_master_prompt or "").strip()
        global_style["style_enabled"] = list(self._stored_style_enabled or [])
        global_style["style_prompts"] = dict(self._stored_style_prompts or {})
        global_style["master_prompt_enabled"] = bool(self._stored_story_master_prompt_enabled)
        global_style["master_prompt_mode"] = self._audio_story_master_prompt_mode()
        global_style["continuity_strength"] = float(self._normalize_continuity_strength(self._stored_continuity_strength))
        story_bible["global_style"] = global_style
        self.story_bible = story_bible
        self._apply_scene_prompts()
        self._sync_story_generated_master_prompt(refresh_visuals=False)
        position_seconds = self._player_position_seconds()
        self._reconcile_cached_images_for_current_prompts()
        self._sync_visual_to_position(position_seconds, force=True)
        self._restart_missing_visual_generation_from_position(position_seconds, max_ahead_frames=0, force=True, allow_when_stopped=False)

    def _on_transcribe_seconds_changed(self, value: int):
        maximum = self._transcribe_seconds_slider_maximum()
        self._stored_transcribe_seconds = max(1, min(maximum, int(value or 1)))
        label = getattr(self, "audio_story_transcribe_seconds_value_label", None)
        if label is not None:
            label.setText(self._format_seconds(self._stored_transcribe_seconds))
        self._sync_audio_story_cost_profile_controls()
        if self._raw_transcript_segments:
            self._schedule_story_payload_rebuild(status_text="Updating transcript windows...")

    def _on_image_frequency_changed(self, value: int):
        self._stored_image_frequency_seconds = self._normalize_image_frequency_seconds(value)
        label = getattr(self, "audio_story_image_frequency_value_label", None)
        if label is not None:
            label.setText(self._format_slider_seconds(self._stored_image_frequency_seconds))
        self._sync_audio_story_cost_profile_controls()
        if self._raw_transcript_segments:
            self._schedule_story_payload_rebuild(status_text="Updating image timing windows...")

    def _on_image_timing_mode_changed(self, _index: int):
        combo = getattr(self, "audio_story_image_timing_combo", None)
        if combo is not None:
            self._stored_image_timing_mode = self._normalize_image_timing_mode(combo.currentData() or combo.currentText())
        self._sync_audio_story_cost_profile_controls()
        if self._raw_transcript_segments:
            self._schedule_story_payload_rebuild(status_text="Updating image timing mode...")

    def _on_continuity_strength_changed(self, value: int):
        self._stored_continuity_strength = self._normalize_continuity_strength(value)
        label = getattr(self, "audio_story_continuity_value_label", None)
        if label is not None:
            label.setText(f"{int(round(self._stored_continuity_strength * 100.0))}%")
        self._sync_audio_story_cost_profile_controls()
        if self._raw_transcript_segments:
            self._schedule_visual_refresh()

    def _on_generate_ahead_frames_changed(self, value: int):
        self._stored_generate_ahead_frames = max(0, int(value or 0))
        self._sync_generate_ahead_slider()
        self._sync_audio_story_cost_profile_controls()
        if self.transcript_chunks and self._is_audio_story_currently_playing():
            self._restart_visual_generation_from_position(self._player_position_seconds())

    def _on_audio_story_style_toggled(self, style_id: str, checked: bool):
        normalized_id = str(style_id or "").strip().lower()
        enabled_set = set(self._stored_style_enabled or [])
        if checked:
            enabled_set.add(normalized_id)
        else:
            enabled_set.discard(normalized_id)
        self._stored_style_enabled = [str(item.get("id") or "").strip().lower() for item in _audio_story_style_presets() if str(item.get("id") or "").strip().lower() in enabled_set]
        if self._raw_transcript_segments:
            if self._stored_style_change_live or not self._is_audio_story_currently_playing():
                self._schedule_visual_refresh()
            else:
                self._sync_story_generated_master_prompt(refresh_visuals=False)

    def _on_audio_story_style_text_changed(self, style_id: str, text: str):
        normalized_id = str(style_id or "").strip().lower()
        if not normalized_id:
            return
        self._stored_style_prompts[normalized_id] = str(text or "").strip()
        if self._raw_transcript_segments:
            if self._stored_style_change_live or not self._is_audio_story_currently_playing():
                self._schedule_visual_refresh()
            else:
                self._sync_story_generated_master_prompt(refresh_visuals=False)

    def _on_audio_story_style_label_edit_requested(self, style_id: str):
        normalized_id = str(style_id or "").strip().lower()
        if not normalized_id:
            return
        current_label = self._audio_story_style_label(normalized_id)
        text, accepted = QtWidgets.QInputDialog.getText(
            self.audio_story_tab_widget,
            "Rename Style Button",
            "Button text:",
            text=current_label,
        )
        if not accepted:
            return
        style_def = next((item for item in _audio_story_style_presets() if str(item.get("id") or "").strip().lower() == normalized_id), {})
        default_label = str(style_def.get("label") or normalized_id.title()).strip()
        new_label = str(text or "").strip() or default_label
        self._stored_style_labels[normalized_id] = new_label
        button = dict(getattr(self, "audio_story_style_buttons", {}) or {}).get(normalized_id)
        if button is not None:
            button.setText(new_label)
            button.setToolTip(f"Toggle the {new_label} style layer for generated story image prompts. Right-click to rename this button.")
        self._notify_audio_story_settings_changed()

    def _on_audio_story_style_live_changed(self, checked: bool):
        self._stored_style_change_live = bool(checked)
        if self._raw_transcript_segments and (self._stored_style_change_live or not self._is_audio_story_currently_playing()):
            self._schedule_visual_refresh()

    def _on_story_master_prompt_toggled(self, checked: bool):
        self._stored_story_master_prompt_enabled = bool(checked)
        self._sync_audio_story_cost_profile_controls()
        if self.transcript_chunks:
            self._schedule_visual_refresh()
        else:
            self._sync_story_generated_master_prompt(refresh_visuals=False)
        self._refresh_controls()

    def _on_story_master_prompt_mode_changed(self, _index: int):
        combo = getattr(self, "audio_story_master_prompt_mode_combo", None)
        if combo is not None:
            value = str(combo.currentData() or combo.currentText() or "").strip().lower()
            if value in {mode for mode, _label in _audio_story_master_prompt_modes()}:
                self._stored_story_master_prompt_mode = value
        self._sync_audio_story_cost_profile_controls()
        if self.transcript_chunks and self._stored_story_master_prompt_enabled:
            self._schedule_visual_refresh()
        else:
            self._sync_story_generated_master_prompt(refresh_visuals=False)
        self._refresh_scene_override_controls()

    def _on_llm_story_analysis_toggled(self, checked: bool):
        self._stored_use_llm_story_analysis = bool(checked)
        self._sync_audio_story_cost_profile_controls()
        if self._raw_transcript_segments:
            self._start_story_payload_rebuild_job(
                status_text=f"Analyzing story with {self._story_analysis_provider_status_label()}..." if self._stored_use_llm_story_analysis else "Rebuilding audio story analysis..."
            )
        self._refresh_controls()

    def _on_audio_story_analysis_mode_changed(self, _index: int):
        combo = getattr(self, "audio_story_analysis_mode_combo", None)
        if combo is not None:
            self._stored_audio_story_analysis_mode = self._normalize_audio_story_analysis_mode(combo.currentData() or combo.currentText())
        audio_story_runtime.update_runtime_config("audio_story_analysis_mode", self._audio_story_analysis_mode())
        print(f"[StoryBible] mode selected: {self._audio_story_analysis_mode()}")
        if self._raw_transcript_segments:
            self._start_story_payload_rebuild_job(status_text="Rebuilding audio story prompts...")
        self._refresh_controls()

    def _on_story_analysis_provider_mode_changed(self, _index: int):
        combo = getattr(self, "audio_story_analysis_provider_combo", None)
        if combo is not None:
            self._stored_story_analysis_provider_mode = self._normalize_story_analysis_provider_mode(combo.currentData() or combo.currentText())
        self._sync_story_analysis_provider_controls()
        self._stored_story_analysis_model = ""
        self._sync_story_analysis_model_controls()
        self._sync_audio_story_cost_profile_controls()
        if self._stored_use_llm_story_analysis and self._raw_transcript_segments:
            self._start_story_payload_rebuild_job(status_text=f"Analyzing story with {self._story_analysis_provider_status_label()}...")
        self._refresh_controls()

    def _on_story_analysis_model_changed(self, _index: int):
        combo = getattr(self, "audio_story_analysis_model_combo", None)
        if combo is not None:
            self._stored_story_analysis_model = self._normalize_story_analysis_model(combo.currentData() or combo.currentText())
        self._sync_audio_story_cost_profile_controls()
        if self._stored_use_llm_story_analysis and self._raw_transcript_segments:
            self._start_story_payload_rebuild_job(status_text=f"Analyzing story with {self._story_analysis_provider_status_label()}...")

    def _on_story_analysis_model_edit_finished(self):
        combo = getattr(self, "audio_story_analysis_model_combo", None)
        if combo is None:
            return
        self._stored_story_analysis_model = self._normalize_story_analysis_model(combo.currentText())
        self._sync_story_analysis_model_controls()
        self._sync_audio_story_cost_profile_controls()
        if self._stored_use_llm_story_analysis and self._raw_transcript_segments:
            self._start_story_payload_rebuild_job(status_text=f"Analyzing story with {self._story_analysis_provider_status_label()}...")

    def _on_xai_image_settings_changed(self, *_args):
        settings = self._current_xai_image_settings()
        for key, value in settings.items():
            audio_story_runtime.update_runtime_config(key, value)
        self._sync_xai_image_settings_controls()
        if self.transcript_chunks:
            self._reconcile_cached_images_for_current_prompts()
            self._schedule_visual_refresh()

    def _visual_stream_server_url(self):
        server = getattr(self, "_visual_stream_server", None)
        if server is not None and getattr(server, "running", False):
            return str(server.url)
        return ""

    def _sync_visual_stream_controls(self):
        checkbox = getattr(self, "audio_story_stream_enabled_checkbox", None)
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(self._stored_visual_stream_enabled))
            checkbox.blockSignals(False)
        spin = getattr(self, "audio_story_stream_port_spin", None)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(max(1024, min(65535, int(self._stored_visual_stream_port or 8765))))
            spin.setEnabled(not bool(self._stored_visual_stream_enabled))
            spin.blockSignals(False)
        label = getattr(self, "audio_story_stream_url_label", None)
        if label is not None:
            url = self._visual_stream_server_url()
            label.setText(url if url else "Stream off")

    def _start_visual_stream(self, *, silent: bool = False):
        if self._visual_stream_server is not None and self._visual_stream_server.running:
            self._stored_visual_stream_enabled = True
            self._sync_visual_stream_controls()
            return True
        try:
            self._visual_stream_server = AudioStoryVisualStreamServer(port=int(self._stored_visual_stream_port or 8765))
            url = self._visual_stream_server.start()
            self._stored_visual_stream_port = int(getattr(self._visual_stream_server, "port", self._stored_visual_stream_port) or self._stored_visual_stream_port or 8765)
        except Exception as exc:
            self._stored_visual_stream_enabled = False
            self._visual_stream_server = None
            if not silent:
                self._set_status(f"Could not start visual stream: {exc}")
            self._sync_visual_stream_controls()
            return False
        self._stored_visual_stream_enabled = True
        if not silent:
            self._set_status(f"Visual stream running at {url}")
        self._sync_visual_stream_controls()
        return True

    def _stop_visual_stream(self):
        if bool(getattr(self, "_stored_chromecast_cast_active", False)) or bool(getattr(self, "_stored_chromecast_stream_page_active", False)):
            self._stop_chromecast_cast(stop_stream=True, silent=True)
            return
        set_current_audio_path("")
        set_stream_playback_state(playback_state="stopped", position_seconds=0.0, show_prompt=False)
        server = getattr(self, "_visual_stream_server", None)
        self._visual_stream_server = None
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass
        self._stored_visual_stream_enabled = False
        self._sync_visual_stream_controls()

    def _on_visual_stream_toggled(self, checked: bool):
        if checked:
            self._start_visual_stream()
        else:
            self._stop_visual_stream()

    def _on_visual_stream_port_changed(self, value: int):
        self._stored_visual_stream_port = max(1024, min(65535, int(value or 8765)))
        self._sync_visual_stream_controls()

    def _cast_image_url(self):
        if not self._start_visual_stream(silent=True):
            return ""
        server = getattr(self, "_visual_stream_server", None)
        if server is None or not getattr(server, "running", False):
            return ""
        return f"{server.url.rstrip('/')}/current.jpg?fit=cast&w=1920&h=1080&ts={int(time.time())}"

    def _cast_stream_page_url(self):
        if not self._start_visual_stream(silent=True):
            return ""
        server = getattr(self, "_visual_stream_server", None)
        if server is None or not getattr(server, "running", False):
            return ""
        return f"{server.url.rstrip('/')}/?cast=1&ts={int(time.time())}"

    def _cast_audio_url(self):
        if not self._start_visual_stream(silent=True):
            return ""
        server = getattr(self, "_visual_stream_server", None)
        if server is None or not getattr(server, "running", False):
            return ""
        return f"{server.url.rstrip('/')}/audio?ts={int(time.time())}"

    def _active_audio_story_stream_path(self):
        mode = self._playback_mode_value()
        if mode == "tts":
            path = str(dict(self._tts_bundle or {}).get("audio_path", "") or "").strip()
            return path if path and Path(path).exists() else ""
        path = str(self.imported_audio_path or "").strip()
        return path if path and Path(path).exists() else ""

    def _audio_story_playback_state_label(self):
        if self.audio_player is None:
            return "stopped"
        try:
            state = self.audio_player.playbackState()
        except Exception:
            return "stopped"
        playback_state_enum = getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlaybackState", None)
        playing_state = getattr(playback_state_enum, "PlayingState", None) if playback_state_enum is not None else getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlayingState", None)
        paused_state = getattr(playback_state_enum, "PausedState", None) if playback_state_enum is not None else getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PausedState", None)
        if state == playing_state:
            return "playing"
        if state == paused_state:
            return "paused"
        return "stopped"

    def _sync_visual_stream_playback_state(self, playback_state: str = "", *, position_seconds: float | None = None):
        audio_path = self._active_audio_story_stream_path()
        set_current_audio_path(audio_path)
        if position_seconds is None:
            position_seconds = self._player_position_seconds()
        set_stream_playback_state(
            playback_state=playback_state or self._audio_story_playback_state_label(),
            position_seconds=position_seconds,
            show_prompt=bool(getattr(self, "_stored_chromecast_show_prompt", False)),
        )

    def _on_chromecast_show_prompt_toggled(self, checked: bool):
        self._stored_chromecast_show_prompt = bool(checked)
        self._sync_visual_stream_playback_state()

    def _sync_chromecast_controls(self):
        combo = getattr(self, "audio_story_cast_device_combo", None)
        if combo is not None:
            current_name = str(self._stored_chromecast_device_name or "").strip()
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem("Choose Chromecast...", "")
                for item in list(getattr(self, "_chromecast_devices", []) or []):
                    name = str(item.get("name", "") or "").strip()
                    if not name:
                        continue
                    combo.addItem(str(item.get("label", "") or name), name)
                index = combo.findData(current_name)
                if index >= 0:
                    combo.setCurrentIndex(index)
            finally:
                combo.blockSignals(False)
        dependency_error = chromecast_dependency_error()
        has_device = bool(str(self._stored_chromecast_device_name or "").strip())
        has_active_device = bool(str(getattr(self, "_active_chromecast_device_name", "") or "").strip())
        busy = bool(getattr(self, "_chromecast_busy", False))
        for button_name in ("audio_story_cast_refresh_button", "audio_story_cast_button", "audio_story_cast_stop_button"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.setEnabled(not busy and not bool(dependency_error))
        install_button = getattr(self, "audio_story_cast_install_button", None)
        if install_button is not None:
            install_button.setVisible(bool(dependency_error))
            install_button.setEnabled(not busy and bool(dependency_error))
        cast_button = getattr(self, "audio_story_cast_button", None)
        if cast_button is not None:
            cast_button.setEnabled(not busy and not bool(dependency_error) and has_device)
        stop_button = getattr(self, "audio_story_cast_stop_button", None)
        if stop_button is not None:
            stop_button.setEnabled(not busy and not bool(dependency_error) and (has_device or has_active_device))
        status = getattr(self, "audio_story_cast_status_label", None)
        if status is not None:
            if dependency_error:
                status.setText(dependency_error)
            elif busy:
                status.setText("Chromecast operation running...")
            elif self._stored_chromecast_stream_page_active and (has_device or has_active_device):
                status.setText(f"Casting Audio Story stream to {getattr(self, '_active_chromecast_device_name', '') or self._stored_chromecast_device_name}.")
            elif self._stored_chromecast_cast_active and (has_device or has_active_device):
                status.setText(f"Casting current Audio Story visual to {getattr(self, '_active_chromecast_device_name', '') or self._stored_chromecast_device_name}. New generated images will be re-cast automatically.")
            elif getattr(self, "_chromecast_devices", None):
                status.setText(f"Found {len(self._chromecast_devices)} Cast device(s).")
            else:
                status.setText("Chromecast discovery not run.")

    def _install_chromecast_dependencies(self):
        def worker():
            return install_chromecast_dependencies()

        def done(result):
            self._chromecast_busy = False
            ok = bool(result[0]) if isinstance(result, tuple) and result else bool(result)
            message = str(result[1] if isinstance(result, tuple) and len(result) > 1 else "")
            status = getattr(self, "audio_story_cast_status_label", None)
            if status is not None and message:
                status.setText(message)
            if message:
                self._set_status(message)
            self._sync_chromecast_controls()
            if ok:
                self._refresh_chromecast_devices()

        self._run_chromecast_job(worker, done)

    def _run_chromecast_job(self, worker, done):
        if bool(getattr(self, "_chromecast_busy", False)):
            return
        self._chromecast_busy = True
        self._chromecast_job_done = done if callable(done) else None
        self._sync_chromecast_controls()

        def _job():
            try:
                result = worker()
            except Exception as exc:
                result = (False, str(exc))
            self.chromecastJobFinished.emit(result)

        threading.Thread(target=_job, daemon=True).start()

    def _on_chromecast_job_finished(self, result):
        done = getattr(self, "_chromecast_job_done", None)
        self._chromecast_job_done = None
        if callable(done):
            done(result)
            return
        self._finish_chromecast_job(result)

    def _finish_chromecast_job(self, result, *, active: bool | None = None):
        self._chromecast_busy = False
        ok = False
        message = ""
        if isinstance(result, tuple):
            ok = bool(result[0])
            message = str(result[1] if len(result) > 1 else "")
        else:
            ok = bool(result)
            message = ""
        if active is not None and ok:
            self._stored_chromecast_cast_active = bool(active)
        status = getattr(self, "audio_story_cast_status_label", None)
        if status is not None and message:
            status.setText(message)
        if message:
            self._set_status(message)
        self._sync_chromecast_controls()

    def _refresh_chromecast_devices(self):
        def worker():
            return discover_chromecast_devices(timeout=7.0)

        def done(result):
            devices, error = result if isinstance(result, tuple) and len(result) == 2 else ([], "Chromecast discovery failed.")
            self._chromecast_busy = False
            self._chromecast_devices = list(devices or [])
            if error:
                self._set_status(f"Chromecast discovery failed: {error}")
                status = getattr(self, "audio_story_cast_status_label", None)
                if status is not None:
                    status.setText(f"Chromecast discovery failed: {error}")
            elif self._chromecast_devices:
                self._set_status(f"Found {len(self._chromecast_devices)} Chromecast device(s).")
            else:
                self._set_status("No Chromecast devices found on this network.")
            self._sync_chromecast_controls()

        self._run_chromecast_job(worker, done)

    def _on_chromecast_device_changed(self, _index: int):
        combo = getattr(self, "audio_story_cast_device_combo", None)
        previous_active_device = str(getattr(self, "_active_chromecast_device_name", "") or "").strip()
        if combo is not None:
            self._stored_chromecast_device_name = str(combo.currentData() or "").strip()
        next_device = str(self._stored_chromecast_device_name or "").strip()
        self._sync_chromecast_controls()
        if (
            previous_active_device
            and next_device
            and previous_active_device != next_device
            and bool(getattr(self, "_stored_chromecast_cast_active", False))
            and not bool(getattr(self, "_chromecast_busy", False))
        ):
            self._cast_current_visual_to_chromecast(previous_device_name=previous_active_device)

    def _cast_current_visual_to_chromecast(self, *, previous_device_name: str = ""):
        device_name = str(self._stored_chromecast_device_name or "").strip()
        previous_device_name = str(previous_device_name or getattr(self, "_active_chromecast_device_name", "") or "").strip()
        audio_path = self._active_audio_story_stream_path()
        set_current_audio_path(audio_path)
        self._sync_visual_stream_playback_state()
        image_url = self._cast_image_url()
        page_url = self._cast_stream_page_url()
        audio_url = self._cast_audio_url() if audio_path else ""
        if not image_url:
            self._stored_chromecast_cast_active = False
            self._stored_chromecast_stream_page_active = False
            self._active_chromecast_device_name = ""
            message = "Could not start visual stream for Chromecast. Try another port or allow Python through Windows Firewall."
            self._set_status(message)
            status = getattr(self, "audio_story_cast_status_label", None)
            if status is not None:
                status.setText(message)
            self._sync_chromecast_controls()
            return

        def worker():
            if previous_device_name and previous_device_name != device_name:
                stop_chromecast(previous_device_name, timeout=6.0)
            return cast_image_to_chromecast(device_name, image_url, page_url=page_url, audio_url=audio_url, timeout=12.0)

        def done(result):
            ok = bool(result[0]) if isinstance(result, tuple) and result else bool(result)
            message = str(result[1] if isinstance(result, tuple) and len(result) > 1 else "")
            self._stored_chromecast_stream_page_active = bool(ok and ("visuals and audio" in message.lower() or "audio only" in message.lower()))
            self._active_chromecast_device_name = device_name if ok else ""
            if not ok:
                self._stored_chromecast_cast_active = False
            self._finish_chromecast_job(result, active=True)

        self._run_chromecast_job(worker, done)

    def _stop_chromecast_cast(self, *, stop_stream: bool = True, silent: bool = False):
        target_names = []
        for name in (
            str(getattr(self, "_active_chromecast_device_name", "") or "").strip(),
            str(self._stored_chromecast_device_name or "").strip(),
        ):
            if name and name not in target_names:
                target_names.append(name)
        set_current_audio_path("")
        set_stream_playback_state(playback_state="stopped", position_seconds=0.0, show_prompt=False)

        def worker():
            if not target_names:
                return False, "Choose a Chromecast device first."
            messages = []
            ok_any = False
            for target_name in target_names:
                ok, message = stop_chromecast(target_name, timeout=8.0)
                ok_any = bool(ok_any or ok)
                if message:
                    messages.append(str(message))
            return ok_any, " ".join(messages).strip() or "Stopped Chromecast."

        def done(result):
            self._stored_chromecast_stream_page_active = False
            self._active_chromecast_device_name = ""
            if stop_stream:
                server = getattr(self, "_visual_stream_server", None)
                self._visual_stream_server = None
                if server is not None:
                    try:
                        server.stop()
                    except Exception:
                        pass
                self._stored_visual_stream_enabled = False
                self._sync_visual_stream_controls()
            if silent and isinstance(result, tuple):
                result = (result[0], "")
            self._finish_chromecast_job(result, active=False)

        self._run_chromecast_job(worker, done)

    def _recast_current_visual_if_needed(self):
        if not bool(getattr(self, "_stored_chromecast_cast_active", False)):
            return
        if not str(getattr(self, "_stored_chromecast_device_name", "") or "").strip():
            return
        if bool(getattr(self, "_stored_chromecast_stream_page_active", False)):
            return
        if bool(getattr(self, "_chromecast_busy", False)):
            return
        self._cast_current_visual_to_chromecast()

    def _on_prompt_block_limit_changed(self, limit_key: str, value: int):
        key = str(limit_key or "").strip().lower()
        if key not in _AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS:
            return
        limits = self._prompt_block_limits()
        limits[key] = max(40, min(1600, int(value or _AUDIO_STORY_PROMPT_BLOCK_LIMIT_DEFAULTS[key])))
        self._stored_prompt_block_limits = self._normalize_prompt_block_limits(limits)
        self._sync_audio_story_cost_profile_controls()
        if self.transcript_chunks:
            self._schedule_visual_refresh()

    def _on_prompt_safety_cap_changed(self, value: int):
        self._stored_prompt_safety_cap = self._normalize_prompt_safety_cap(value)
        self._sync_prompt_safety_cap_control()
        self._sync_audio_story_cost_profile_controls()
        if self.transcript_chunks:
            self._schedule_visual_refresh()

    def _current_scene_entry(self):
        if not self.transcript_chunks:
            return {}
        index = self._chunk_index_for_position(self._player_position_seconds())
        if index < 0 or index >= len(self.transcript_chunks):
            index = max(0, min(len(self.transcript_chunks) - 1, int(self._current_chunk_index if self._current_chunk_index >= 0 else 0)))
        return dict(self.transcript_chunks[index] or {})

    def _current_scene_id(self):
        return str(self._current_scene_entry().get("scene_id", "") or "").strip()

    def _current_scene_label(self):
        chunk = self._current_scene_entry()
        scene_id = str(chunk.get("scene_id", "") or "").strip()
        scene_index = int(chunk.get("scene_index", 0) or 0)
        summary = str(chunk.get("scene_summary", "") or chunk.get("key_action", "") or chunk.get("text", "") or "").strip()
        parts = [f"Scene {scene_index + 1}" if scene_index >= 0 else "Scene"]
        if scene_id:
            parts.append(scene_id)
        if summary:
            parts.append(_audio_story_truncate(summary, 80))
        return " • ".join([part for part in parts if part])

    def _scene_override_value(self, key: str, default=None):
        scene_id = self._current_scene_id()
        if not scene_id:
            return default
        return dict(self.scene_overrides.get(key, {}) or {}).get(scene_id, default)

    def _current_scene_character_items(self):
        chunk = self._current_scene_entry()
        characters = []
        for character_id in list(chunk.get("active_character_ids", []) or []):
            entry = dict((self.story_bible.get("characters", {}) or {}).get(character_id) or {})
            label = str(entry.get("label", "") or character_id).strip()
            characters.append((character_id, label))
        return characters

    def _refresh_scene_override_controls(self):
        label = getattr(self, "audio_story_scene_status_label", None)
        if label is not None:
            chunk = self._current_scene_entry()
            if chunk:
                scene_label = self._current_scene_label()
                generation_mode = str(chunk.get("generation_mode", "fresh") or "fresh").strip()
                scene_id = self._current_scene_id()
                forced_mode = str(dict(self.scene_overrides.get("forced_scene_modes", {}) or {}).get(scene_id, "") or "").strip()
                current_anchor = str(dict(self.scene_overrides.get("scene_anchor_overrides", {}) or {}).get(scene_id, "") or "").strip()
                negative_prompt = str(dict(self.scene_overrides.get("scene_negative_prompt_overrides", {}) or {}).get(scene_id, "") or "").strip()
                global_negative_prompt = str(self.scene_overrides.get("global_negative_prompt", "") or "").strip()
                if bool(self.scene_overrides.get("global_negative_prompt_enabled", False)) and global_negative_prompt:
                    negative_prompt = global_negative_prompt if not negative_prompt else f"{global_negative_prompt}; {negative_prompt}"
                if not current_anchor:
                    current_anchor = str(chunk.get("scene_summary", "") or chunk.get("key_action", "") or chunk.get("text", "") or "").strip()
                label.setText(
                    f"{scene_label}\n"
                    f"Mode: {generation_mode}{f' (forced {forced_mode})' if forced_mode else ''}\n"
                    f"Current anchor: {current_anchor[:180]}"
                    + (f"\nNegative prompt: {negative_prompt[:180]}" if negative_prompt else "")
                )
            else:
                label.setText("No scene selected yet.")
        layout = getattr(self, "audio_story_scene_character_button_row", None)
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            chunk = self._current_scene_entry()
            pinned = set(str(item or "").strip() for item in list(self.scene_overrides.get("pinned_character_ids", []) or []))
            character_label = QtWidgets.QLabel("Pin Character:")
            character_label.setStyleSheet("color: #cbd5e1;")
            layout.addWidget(character_label, 0, 0)
            character_items = self._current_scene_character_items()
            if not character_items:
                empty_label = QtWidgets.QLabel("No active characters in this scene.")
                empty_label.setStyleSheet("color: #8ea3b8;")
                layout.addWidget(empty_label, 0, 1)
            for item_index, (character_id, label_text) in enumerate(character_items):
                button = QtWidgets.QPushButton(label_text)
                button.setCheckable(True)
                button.setChecked(character_id in pinned)
                button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                button.setToolTip("Pin or unpin this character across future story images.")
                button.setStyleSheet(
                    "QPushButton { padding: 5px 10px; border-radius: 9px; background: #22344c; border: 1px solid #35506c; color: #f2f5f9; }"
                    "QPushButton:checked { background: #4d8dff; border: 1px solid #6a95ff; }"
                )
                button.toggled.connect(lambda checked, character_id=character_id: self._toggle_pinned_character(character_id, checked))
                button_row = item_index // 3
                button_column = (item_index % 3) + 1
                layout.addWidget(button, button_row, button_column)
            for column in range(4):
                layout.setColumnStretch(column, 1 if column else 0)
        location_button = getattr(self, "audio_story_pin_location_button", None)
        if location_button is not None:
            chunk = self._current_scene_entry()
            location_id = str(chunk.get("location_id", "") or "").strip()
            location_label = str(chunk.get("location_label", "") or "").strip() or self._build_location_anchor_text(self.story_bible, location_id) or "current location"
            pinned_locations = set(str(item or "").strip() for item in list(self.scene_overrides.get("pinned_location_ids", []) or []))
            location_button.blockSignals(True)
            location_button.setText(f"Pin Location: {location_label}")
            location_button.setChecked(location_id in pinned_locations if location_id else False)
            location_button.blockSignals(False)
        for key, button_name, label_text in (
            ("force_fresh_button", "audio_story_force_fresh_button", "Force Fresh Scene"),
            ("force_continuation_button", "audio_story_force_continuation_button", "Force Continuation"),
        ):
            button = getattr(self, button_name, None)
            if button is not None:
                scene_id = self._current_scene_id()
                forced_mode = str(dict(self.scene_overrides.get("forced_scene_modes", {}) or {}).get(scene_id, "") or "").strip()
                desired = label_text.startswith("Force Fresh") and forced_mode == "fresh" or label_text.startswith("Force Continuation") and forced_mode == "continuation"
                button.blockSignals(True)
                button.setChecked(desired)
                button.blockSignals(False)
        anchor_edit = getattr(self, "audio_story_scene_anchor_edit", None)
        if anchor_edit is not None:
            scene_id = self._current_scene_id()
            anchor_text = ""
            if scene_id:
                anchor_text = str(dict(self.scene_overrides.get("scene_anchor_overrides", {}) or {}).get(scene_id, "") or "").strip()
                if not anchor_text:
                    chunk = self._current_scene_entry()
                    anchor_text = str(chunk.get("scene_summary", "") or chunk.get("key_action", "") or chunk.get("text", "") or "").strip()
            anchor_edit.blockSignals(True)
            anchor_edit.setPlainText(anchor_text)
            anchor_edit.blockSignals(False)
        negative_prompt_edit = getattr(self, "audio_story_scene_negative_prompt_edit", None)
        if negative_prompt_edit is not None:
            scene_id = self._current_scene_id()
            negative_prompt_text = ""
            if bool(self.scene_overrides.get("global_negative_prompt_enabled", False)):
                negative_prompt_text = str(self.scene_overrides.get("global_negative_prompt", "") or "").strip()
            elif scene_id:
                negative_prompt_text = str(dict(self.scene_overrides.get("scene_negative_prompt_overrides", {}) or {}).get(scene_id, "") or "").strip()
            negative_prompt_edit.blockSignals(True)
            negative_prompt_edit.setPlainText(negative_prompt_text)
            negative_prompt_edit.blockSignals(False)
        negative_prompt_anchor_button = getattr(self, "audio_story_negative_prompt_anchor_button", None)
        if negative_prompt_anchor_button is not None:
            negative_prompt_anchor_button.blockSignals(True)
            negative_prompt_anchor_button.setChecked(bool(self.scene_overrides.get("global_negative_prompt_enabled", False)))
            negative_prompt_anchor_button.blockSignals(False)
        self.apply_theme_palette()

    def _scene_override_refresh_after_change(self, *, refresh_visuals: bool = True):
        if not self.transcript_chunks:
            self._refresh_scene_override_controls()
            return
        self._apply_scene_prompts()
        self._reconcile_cached_images_for_current_prompts()
        position_seconds = self._player_position_seconds()
        if refresh_visuals:
            self._restart_visual_generation_from_position(position_seconds, force=True)
            self._sync_visual_to_position(position_seconds, force=True)
        else:
            self._refresh_scene_override_controls()

    def _toggle_pinned_character(self, character_id: str, checked: bool):
        character_id = str(character_id or "").strip()
        if not character_id:
            return
        pinned = [str(item or "").strip() for item in list(self.scene_overrides.get("pinned_character_ids", []) or []) if str(item or "").strip()]
        if checked:
            if character_id not in pinned:
                pinned.append(character_id)
        else:
            pinned = [item for item in pinned if item != character_id]
        self.scene_overrides["pinned_character_ids"] = _audio_story_unique_keep_order(pinned)
        self._scene_override_refresh_after_change(refresh_visuals=True)

    def _on_pin_location_toggled(self, checked: bool):
        scene_id = self._current_scene_id()
        if not scene_id:
            self._refresh_scene_override_controls()
            return
        chunk = self._current_scene_entry()
        location_id = str(chunk.get("location_id", "") or "").strip()
        pinned = [str(item or "").strip() for item in list(self.scene_overrides.get("pinned_location_ids", []) or []) if str(item or "").strip()]
        if checked and location_id:
            if location_id not in pinned:
                pinned.append(location_id)
        else:
            pinned = [item for item in pinned if item != location_id]
        self.scene_overrides["pinned_location_ids"] = _audio_story_unique_keep_order(pinned)
        self._scene_override_refresh_after_change(refresh_visuals=True)

    def _on_force_scene_mode_changed(self, mode: str, checked: bool):
        scene_id = self._current_scene_id()
        mode = str(mode or "").strip().lower()
        if not scene_id or mode not in {"fresh", "continuation"}:
            self._refresh_scene_override_controls()
            return
        forced_modes = dict(self.scene_overrides.get("forced_scene_modes", {}) or {})
        if checked:
            forced_modes[scene_id] = mode
        else:
            if str(forced_modes.get(scene_id, "") or "").strip().lower() == mode:
                forced_modes.pop(scene_id, None)
        self.scene_overrides["forced_scene_modes"] = forced_modes
        other_button = getattr(self, "audio_story_force_continuation_button", None) if mode == "fresh" else getattr(self, "audio_story_force_fresh_button", None)
        if checked and other_button is not None:
            other_button.blockSignals(True)
            other_button.setChecked(False)
            other_button.blockSignals(False)
        self._scene_override_refresh_after_change(refresh_visuals=True)

    def _apply_scene_anchor_override(self):
        scene_id = self._current_scene_id()
        anchor_edit = getattr(self, "audio_story_scene_anchor_edit", None)
        if not scene_id or anchor_edit is None:
            self._refresh_scene_override_controls()
            return
        anchor_text = str(anchor_edit.toPlainText() or "").strip()
        anchor_overrides = dict(self.scene_overrides.get("scene_anchor_overrides", {}) or {})
        if anchor_text:
            anchor_overrides[scene_id] = anchor_text
        else:
            anchor_overrides.pop(scene_id, None)
        self.scene_overrides["scene_anchor_overrides"] = anchor_overrides
        self._scene_override_refresh_after_change(refresh_visuals=True)

    def _apply_scene_negative_prompt_override(self):
        scene_id = self._current_scene_id()
        negative_prompt_edit = getattr(self, "audio_story_scene_negative_prompt_edit", None)
        if not scene_id or negative_prompt_edit is None:
            self._refresh_scene_override_controls()
            return
        negative_prompt_text = str(negative_prompt_edit.toPlainText() or "").strip()
        if bool(self.scene_overrides.get("global_negative_prompt_enabled", False)):
            self.scene_overrides["global_negative_prompt"] = negative_prompt_text
            self._scene_override_refresh_after_change(refresh_visuals=True)
            return
        negative_prompt_overrides = dict(self.scene_overrides.get("scene_negative_prompt_overrides", {}) or {})
        if negative_prompt_text:
            negative_prompt_overrides[scene_id] = negative_prompt_text
        else:
            negative_prompt_overrides.pop(scene_id, None)
        self.scene_overrides["scene_negative_prompt_overrides"] = negative_prompt_overrides
        self._scene_override_refresh_after_change(refresh_visuals=True)

    def _on_negative_prompt_anchor_toggled(self, checked: bool):
        negative_prompt_edit = getattr(self, "audio_story_scene_negative_prompt_edit", None)
        negative_prompt_text = str(negative_prompt_edit.toPlainText() or "").strip() if negative_prompt_edit is not None else ""
        self.scene_overrides["global_negative_prompt_enabled"] = bool(checked)
        if checked:
            self.scene_overrides["global_negative_prompt"] = negative_prompt_text
        self._scene_override_refresh_after_change(refresh_visuals=bool(self.transcript_chunks))

    def _scene_entry_for_index(self, index: int):
        if index < 0 or index >= len(self.transcript_chunks):
            return {}
        return dict(self.transcript_chunks[index] or {})

    def load_current_story_image(self, payload=None):
        if not self.transcript_chunks:
            self._set_status("No audio story is loaded.")
            return {"ok": False, "reason": "no_story"}
        position_seconds = self._player_position_seconds()
        if isinstance(payload, dict) and payload.get("position_seconds") is not None:
            try:
                position_seconds = max(0.0, float(payload.get("position_seconds", 0.0) or 0.0))
            except Exception:
                position_seconds = self._player_position_seconds()
        index = self._chunk_index_for_position(position_seconds)
        chunk = dict(self.transcript_chunks[index] or {})
        cached = self._matching_cached_image_entry(index, str(chunk.get("prompt", "") or "").strip(), scene_entry=chunk)
        if cached.get("image_path"):
            self._sync_visual_to_position(position_seconds, force=True)
        else:
            self._restart_visual_generation_from_position(position_seconds)
            self._sync_visual_to_position(position_seconds, force=True)
        return {
            "ok": True,
            "index": index,
            "position_seconds": position_seconds,
            "image_ready": bool(cached.get("image_path")),
        }

    def refresh_master_style_anchor(self, payload=None):
        if not self.transcript_chunks:
            return {"ok": False, "reason": "no_story"}
        position_seconds = self._player_position_seconds()
        self._reconcile_cached_images_for_current_prompts()
        token = self._restart_visual_generation_from_position(position_seconds)
        return {
            "ok": True,
            "token": int(token),
            "position_seconds": position_seconds,
            "current_index": int(self._chunk_index_for_position(position_seconds)),
        }

    def _visual_request_signature(self, prompt_text: str, *, scene_entry=None, generation_mode: str = "", reference_image_paths=None):
        effective_prompt = self._visual_reply_apply_style_anchor(str(prompt_text or "").strip())
        provider = str(str(self._visual_reply_generation_info().get("provider") or "") or "openai").strip().lower()
        scene_entry = dict(scene_entry or {}) if isinstance(scene_entry, dict) else {}
        reference_image_paths = list(reference_image_paths or [])
        payload = {
            "provider": provider,
            "base_url": str(str(self._visual_reply_generation_info().get("base_url") or "") or "").strip(),
            "model": str(str(self._visual_reply_generation_info().get("model") or "") or "").strip(),
            "size": str(str(self._visual_reply_generation_info().get("size") or "") or "").strip(),
            "extra_body": dict(self._visual_reply_generation_info().get("extra_body") or {}) if provider == "xai" else {},
            "response_format": str(self._visual_reply_generation_info().get("response_format") or "b64_json") if provider == "xai" else "",
            "n": 1 if provider == "xai" else "",
            "prompt": effective_prompt,
            "generation_mode": str(generation_mode or "fresh").strip().lower(),
            "scene_id": str(scene_entry.get("scene_id", "") or "").strip(),
            "scene_index": int(scene_entry.get("scene_index", 0) or 0),
            "location_id": str(scene_entry.get("location_id", "") or "").strip(),
            "active_character_ids": list(scene_entry.get("active_character_ids", []) or []),
            "reference_image_signatures": [self._reference_image_signature(path) for path in reference_image_paths if path],
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest(), effective_prompt

    def _matching_cached_image_entry(self, index: int, prompt_text: str, scene_entry=None):
        scene_entry = dict(scene_entry or {}) if isinstance(scene_entry, dict) else {}
        previous_scene = self._scene_entry_for_index(index - 1)
        generation_mode = str(scene_entry.get("generation_mode", "") or "").strip()
        reference_image_paths = self._story_reference_image_paths(scene_entry, previous_scene=previous_scene)
        expected_signature, _effective_prompt = self._visual_request_signature(
            prompt_text,
            scene_entry=scene_entry,
            generation_mode=generation_mode,
            reference_image_paths=reference_image_paths,
        )
        with self._lock:
            entry = dict(self._image_cache.get(int(index)) or {})
            indexed_entry = bool(entry)
            if not entry:
                entry = dict(self._prompt_image_cache.get(expected_signature) or {})
        if not entry:
            return {}
        image_path = str(entry.get("image_path", "") or "").strip()
        if not image_path or not Path(image_path).exists():
            return {}
        if indexed_entry:
            cached_prompt_text = str(entry.get("prompt_text", "") or "").strip()
            if cached_prompt_text == str(prompt_text or "").strip():
                return entry
            if entry.get("image_path") and int(index) < int(self._chunk_index_for_position(self._player_position_seconds())):
                return entry
            if entry.get("image_path") and not bool(self._stored_style_change_live):
                return entry
        entry_signature = str(entry.get("prompt_signature", "") or "").strip()
        if not entry_signature:
            cached_prompt_text = str(entry.get("prompt_text", "") or "").strip()
            if cached_prompt_text:
                entry_signature, _unused = self._visual_request_signature(cached_prompt_text, scene_entry=scene_entry, generation_mode=generation_mode, reference_image_paths=reference_image_paths)
        if entry_signature != expected_signature:
            return {}
        if int(index) >= 0:
            with self._lock:
                self._image_cache[int(index)] = dict(entry)
        return entry

    def _reconcile_cached_images_for_current_prompts(self):
        prompt_cache = {}
        with self._lock:
            existing_entries = list(dict(self._prompt_image_cache or {}).values()) + list(dict(self._image_cache or {}).values())
        for entry in existing_entries:
            item = dict(entry or {})
            image_path = str(item.get("image_path", "") or "").strip()
            if not image_path or not Path(image_path).exists():
                continue
            prompt_signature = str(item.get("prompt_signature", "") or "").strip()
            if not prompt_signature:
                prompt_text = str(item.get("prompt_text", "") or "").strip()
                if not prompt_text:
                    continue
                prompt_signature, _unused = self._visual_request_signature(
                    prompt_text,
                    scene_entry=item.get("scene_context", {}),
                    generation_mode=str(item.get("generation_mode", "") or ""),
                    reference_image_paths=list(item.get("reference_image_paths", []) or []),
                )
                item["prompt_signature"] = prompt_signature
            prompt_cache[prompt_signature] = item
        rebuilt_cache = {}
        with self._lock:
            existing_index_cache = {int(index): dict(item or {}) for index, item in dict(self._image_cache or {}).items()}
        for index, chunk in enumerate(list(self.transcript_chunks or [])):
            prompt_text = str(dict(chunk or {}).get("prompt", "") or "").strip()
            if not prompt_text:
                continue
            previous_scene = self._scene_entry_for_index(index - 1)
            runtime_reference_image_paths = self._story_reference_image_paths(chunk, previous_scene=previous_scene)
            prompt_signature, _unused = self._visual_request_signature(
                prompt_text,
                scene_entry=chunk,
                generation_mode=str(chunk.get("generation_mode", "") or ""),
                reference_image_paths=runtime_reference_image_paths,
            )
            entry = dict(prompt_cache.get(prompt_signature) or {})
            image_path = str(entry.get("image_path", "") or "").strip()
            if image_path and Path(image_path).exists():
                entry["scene_context"] = dict(chunk or {})
                entry["generation_mode"] = str(chunk.get("generation_mode", "") or entry.get("generation_mode", "") or "").strip() or "fresh"
                entry["reference_image_paths"] = list(runtime_reference_image_paths or entry.get("reference_image_paths", []) or [])
                rebuilt_cache[int(index)] = entry
            else:
                existing_entry = dict(existing_index_cache.get(int(index)) or {})
                existing_image_path = str(existing_entry.get("image_path", "") or "").strip()
                if existing_image_path and Path(existing_image_path).exists():
                    rebuilt_cache[int(index)] = existing_entry
        with self._lock:
            self._prompt_image_cache = prompt_cache
            self._image_cache = rebuilt_cache

    def _get_visual_client(self):
        client_kwargs = {"api_key": str(self._visual_reply_generation_info().get("api_key") or "") or "visual-reply"}
        base_url = str(self._visual_reply_generation_info().get("base_url") or "")
        if base_url:
            client_kwargs["base_url"] = base_url
        signature = json.dumps(
            {
                "api_key": str(client_kwargs.get("api_key") or ""),
                "base_url": str(client_kwargs.get("base_url") or ""),
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        if self._visual_client is not None and self._visual_client_signature == signature:
            return self._visual_client
        self._visual_client = self._visual_reply_client()
        self._visual_client_signature = signature
        return self._visual_client

    def _refresh_controls(self):
        multimedia_available = QtMultimedia is not None
        has_audio_path = bool(str(self.imported_audio_path or "").strip())
        has_transcript = bool(self.transcript_chunks)
        mode_value = self._playback_mode_value()
        has_tts_bundle = bool(
            self._tts_bundle
            and str(self._tts_bundle.get("audio_path", "") or "").strip()
            and Path(str(self._tts_bundle.get("audio_path", "") or "").strip()).exists()
        )
        can_prepare_media = has_audio_path and has_transcript and (mode_value == "source" or has_tts_bundle)
        is_rendering_tts = bool(mode_value == "tts" and self._tts_render_in_progress)

        state = None
        if self.audio_player is not None:
            try:
                state = self.audio_player.playbackState()
            except Exception:
                state = None
        playing_state = getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlayingState", None)
        paused_state = getattr(getattr(QtMultimedia, "QMediaPlayer", object), "PausedState", None)
        if hasattr(getattr(QtMultimedia, "QMediaPlayer", object), "PlaybackState"):
            playback_state_enum = getattr(QtMultimedia.QMediaPlayer, "PlaybackState")
            playing_state = getattr(playback_state_enum, "PlayingState", playing_state)
            paused_state = getattr(playback_state_enum, "PausedState", paused_state)
        is_playing = state == playing_state
        is_paused = state == paused_state
        has_position = self._player_position_seconds() > 0.0

        if hasattr(self, "audio_story_import_button"):
            self.audio_story_import_button.setEnabled(True)
        if hasattr(self, "audio_story_path_edit"):
            self.audio_story_path_edit.setEnabled(True)
        if hasattr(self, "audio_story_playback_mode_combo"):
            self.audio_story_playback_mode_combo.setEnabled(has_audio_path)
        if hasattr(self, "audio_story_transcribe_seconds_slider"):
            self.audio_story_transcribe_seconds_slider.setEnabled(has_audio_path and not is_playing and not is_paused)
        if hasattr(self, "audio_story_transcription_start_spin"):
            self.audio_story_transcription_start_spin.setEnabled(has_audio_path and not is_playing and not is_paused)
        if hasattr(self, "audio_story_transcription_end_spin"):
            self.audio_story_transcription_end_spin.setEnabled(has_audio_path and not is_playing and not is_paused)
        if hasattr(self, "audio_story_image_frequency_slider"):
            self.audio_story_image_frequency_slider.setEnabled(has_audio_path and not is_playing and not is_paused)
        if hasattr(self, "audio_story_continuity_slider"):
            self.audio_story_continuity_slider.setEnabled(bool(has_transcript))
        if hasattr(self, "audio_story_generate_ahead_slider"):
            self.audio_story_generate_ahead_slider.setEnabled(bool(has_transcript))
        if hasattr(self, "audio_story_master_prompt_button"):
            self.audio_story_master_prompt_button.setEnabled(bool(has_transcript))
        if hasattr(self, "audio_story_master_prompt_mode_combo"):
            self.audio_story_master_prompt_mode_combo.setEnabled(bool(has_transcript and self._stored_story_master_prompt_enabled))
        if hasattr(self, "audio_story_llm_analysis_checkbox"):
            self.audio_story_llm_analysis_checkbox.setEnabled(has_audio_path and not is_playing and not is_paused)
        if hasattr(self, "audio_story_analysis_mode_combo"):
            self.audio_story_analysis_mode_combo.setEnabled(has_audio_path and not is_playing and not is_paused)
        if hasattr(self, "audio_story_analysis_provider_combo"):
            self.audio_story_analysis_provider_combo.setEnabled(has_audio_path and not is_playing and not is_paused)
        if hasattr(self, "audio_story_analysis_model_combo"):
            self.audio_story_analysis_model_combo.setEnabled(has_audio_path and not is_playing and not is_paused)
        for spin in dict(getattr(self, "audio_story_prompt_limit_spins", {}) or {}).values():
            spin.setEnabled(bool(has_transcript))
        for button in dict(getattr(self, "audio_story_style_buttons", {}) or {}).values():
            button.setEnabled(True)
        for edit in dict(getattr(self, "audio_story_style_edits", {}) or {}).values():
            edit.setEnabled(True)
        if hasattr(self, "audio_story_style_live_checkbox"):
            self.audio_story_style_live_checkbox.setEnabled(True)
        if hasattr(self, "audio_story_transcribe_button"):
            self.audio_story_transcribe_button.setEnabled(has_audio_path and not is_playing and not is_paused)

        if hasattr(self, "audio_story_play_button"):
            self.audio_story_play_button.setEnabled(multimedia_available and has_transcript and not is_rendering_tts)
        if hasattr(self, "audio_story_pause_button"):
            self.audio_story_pause_button.setEnabled(multimedia_available and is_playing)
        if hasattr(self, "audio_story_stop_button"):
            self.audio_story_stop_button.setEnabled(multimedia_available and (is_playing or is_paused or has_position))

        slider_enabled = multimedia_available and can_prepare_media and not is_rendering_tts
        if hasattr(self, "audio_story_position_slider"):
            self.audio_story_position_slider.setEnabled(slider_enabled)
        if hasattr(self, "audio_story_stream_enabled_checkbox"):
            self.audio_story_stream_enabled_checkbox.setEnabled(True)
        if hasattr(self, "audio_story_stream_port_spin"):
            self.audio_story_stream_port_spin.setEnabled(not bool(self._stored_visual_stream_enabled))

        if hasattr(self, "audio_story_status_label"):
            if not multimedia_available:
                self.audio_story_status_label.setText("Qt Multimedia is unavailable in this environment.")
            elif is_rendering_tts:
                self.audio_story_status_label.setText("Rendering TTS narration for timeline-accurate playback...")

    def _format_seconds(self, total_seconds):
        total_seconds = max(0, int(round(float(total_seconds or 0.0))))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _format_slider_seconds(self, total_seconds):
        seconds = max(1, int(round(float(total_seconds or 0.0))))
        return f"{seconds} second" if seconds == 1 else f"{seconds} seconds"
