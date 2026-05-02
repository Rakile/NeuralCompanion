#!/usr/bin/env python3
"""
Voice Assistant: Microphone → LM Studio → ChatterboxTurboTTS
Standalone script for voice interaction with local LLM
"""
import queue
import os
import sys
import time
import tempfile
import base64
import platform
import subprocess
import threading
import logging
import locale
import warnings
import urllib.request
import mimetypes
from pathlib import Path
from faster_whisper import WhisperModel
import io
import torch
import torchaudio as ta
import sounddevice as sd
import numpy as np
from openai import OpenAI
from PIL import Image, PngImagePlugin

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")
warnings.filterwarnings(
    "ignore",
    message=r".*pkg_resources is deprecated as an API.*",
    category=UserWarning,
)

from chatterbox.tts_turbo import ChatterboxTurboTTS
import tkinter as tk
from PIL import ImageTk
import re
import random
import math
from pythonosc import udp_client
import abc
import shutil
import json
import uuid
import gc
import importlib
import dry_run
import app_help
import shared_state
from core import sensory, avatar_runtime, chat_providers, conversation_history as conversation_history_runtime, lmstudio_runtime, musetalk_preview_runtime, runtime_chat, runtime_files, runtime_hotkeys, runtime_paths, runtime_shutdown, speech_text, streaming_text, stt_runtime, text_chunking, text_tags, tts_runtime, audio_playback, visual_reply_runtime
from core.conversation_flow_v2 import ConversationActionType, ConversationPolicy, SystemClockRuntime, build_experimental_controller
from core.musetalk_avatar_packs import discover_avatar_packs, get_avatar_pack
from addons.vam_avatar import config as vam_avatar_config
from pydub import AudioSegment


_ORIGINAL_SUBPROCESS_POPEN = subprocess.Popen


def _safe_text_mode_popen(*args, **kwargs):
    text_mode = bool(kwargs.get("text")) or bool(kwargs.get("universal_newlines"))
    if text_mode and kwargs.get("errors") is None:
        kwargs["errors"] = "replace"
    if text_mode and kwargs.get("encoding") is None and os.name == "nt":
        kwargs["encoding"] = locale.getpreferredencoding(False) or "utf-8"
    return _ORIGINAL_SUBPROCESS_POPEN(*args, **kwargs)


if getattr(subprocess.Popen, "__name__", "") != "_safe_text_mode_popen":
    subprocess.Popen = _safe_text_mode_popen


class _SilentTqdm:
    def __init__(self, iterable=None, *args, **kwargs):
        self.iterable = iterable

    def __iter__(self):
        if self.iterable is None:
            return iter(())
        return iter(self.iterable)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, *args, **kwargs):
        return None

    def close(self):
        return None

    def set_description(self, *args, **kwargs):
        return None

    def set_postfix(self, *args, **kwargs):
        return None


def _silent_tqdm(iterable=None, *args, **kwargs):
    return _SilentTqdm(iterable, *args, **kwargs)


class _SuppressReferenceMelFilter(logging.Filter):
    def filter(self, record):
        try:
            return "Reference mel length is not equal to 2 * reference token length." not in record.getMessage()
        except Exception:
            return True


def _suppress_chatterbox_console_noise():
    try:
        logging.getLogger().addFilter(_SuppressReferenceMelFilter())
    except Exception:
        pass
    for module_name in (
        "chatterbox.models.t3.t3",
        "chatterbox.models.s3gen.flow_matching",
    ):
        try:
            module = importlib.import_module(module_name)
            setattr(module, "tqdm", _silent_tqdm)
        except Exception:
            continue


_suppress_chatterbox_console_noise()

# Try importing speech recognition
try:
    import speech_recognition as sr
except ImportError:
    print("ERROR: speech_recognition not installed. Install with: pip install SpeechRecognition")
    sys.exit(1)

# Try importing NLTK for sentence tokenization
try:
    import nltk
    import re
    from functools import lru_cache
except ImportError:
    print("ERROR: nltk not installed. Install with: pip install nltk")
    sys.exit(1)

# ============================================================================
# CONFIGURATION
# ============================================================================
WHISPER_MODEL_SIZE = "tiny.en"  # "tiny.en" is fastest for English
WHISPER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WHISPER_COMPUTE_TYPE = "float16" if torch.cuda.is_available() else "int8"
whisper_model = None

# TTS settings
TTS_TEMPERATURE = 0.9
TTS_TOP_P = 0.95
TTS_TOP_K = 1000
TTS_REPETITION_PENALTY = 1.2
TTS_NORM_LOUDNESS = True

# Chunking settings for long text
TARGET_CHARS_PER_CHUNK = 100
MAX_CHARS_PER_CHUNK = 200
MIN_CHUNK_SIZE = 10
MUSE_TARGET_CHARS_PER_CHUNK = 110
MUSE_MAX_CHARS_PER_CHUNK = 220
MUSE_QUICKSTART_CHUNK_LIMITS = [
    (170, 320),
    (130, 240),
]
MUSE_MIN_LEADING_SEGMENT_CHARS = 60
MUSE_MAX_INFLIGHT_RENDERS = 3
MUSE_FIRST_CHUNK_IDLE_WINDOW = 48
MUSE_FIRST_CHUNK_PREDICTED_DELAY_SECONDS = 2.0
MUSE_FIRST_CHUNK_DELAY_SAMPLE_LIMIT = 8
STREAM_FIRST_CHUNK_MIN_CHARS = streaming_text.STREAM_FIRST_CHUNK_MIN_CHARS
STREAM_FORCE_FLUSH_SECONDS = streaming_text.STREAM_FORCE_FLUSH_SECONDS
STREAM_FORCE_FLUSH_LATER_SECONDS = streaming_text.STREAM_FORCE_FLUSH_LATER_SECONDS
STREAM_FIRST_CHUNK_PLAN_SECONDS = streaming_text.STREAM_FIRST_CHUNK_PLAN_SECONDS
STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS = streaming_text.STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS
STREAM_FIRST_CHUNK_IDLE_SYNC_MAX_SECONDS = streaming_text.STREAM_FIRST_CHUNK_IDLE_SYNC_MAX_SECONDS
MUSE_DIAGNOSTIC_LOGGING = False
STREAM_TINY_TAIL_CHARS = streaming_text.STREAM_TINY_TAIL_CHARS
STREAM_WHITESPACE_FALLBACK_MARGIN = streaming_text.STREAM_WHITESPACE_FALLBACK_MARGIN
STREAM_POST_TARGET_PUNCTUATION_MARGIN = streaming_text.STREAM_POST_TARGET_PUNCTUATION_MARGIN
STREAM_POST_TARGET_PUNCTUATION_WAIT_SECONDS = streaming_text.STREAM_POST_TARGET_PUNCTUATION_WAIT_SECONDS
STREAM_CLAUSE_FALLBACK_MARGIN = streaming_text.STREAM_CLAUSE_FALLBACK_MARGIN
STREAM_CLAUSE_FALLBACK_MIN_SCORE = streaming_text.STREAM_CLAUSE_FALLBACK_MIN_SCORE
STREAM_CLAUSE_FALLBACK_WAIT_SECONDS = streaming_text.STREAM_CLAUSE_FALLBACK_WAIT_SECONDS

STREAM_CLAUSE_STARTERS = streaming_text.STREAM_CLAUSE_STARTERS
STREAM_BAD_ENDING_WORDS = streaming_text.STREAM_BAD_ENDING_WORDS

# Voice activation settings
ENERGY_THRESHOLD = 500
PAUSE_THRESHOLD = 2.2
DYNAMIC_ENERGY_THRESHOLD = True
NON_SPEAKING_DURATION = 0.35
PHRASE_THRESHOLD = 0.2
AMBIENT_CALIBRATION_SECONDS = 0.6
BARGE_IN_THRESHOLD = 500
BARGE_IN_CONSECUTIVE_CHUNKS = 2
BARGE_IN_RESET_SECONDS = 0.25
keyboard = runtime_hotkeys.keyboard
pynput_keyboard = runtime_hotkeys.pynput_keyboard
DEFAULT_PUSH_TO_TALK_HOTKEY = runtime_hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY
DEFAULT_MANUAL_ACTION_HOTKEYS = runtime_hotkeys.DEFAULT_MANUAL_ACTION_HOTKEYS
DEFAULT_UI_ACTION_HOTKEYS = runtime_hotkeys.DEFAULT_UI_ACTION_HOTKEYS
HOTKEY_ACTION_LABELS = runtime_hotkeys.HOTKEY_ACTION_LABELS
PYNPUT_HOTKEY_AVAILABLE = runtime_hotkeys.PYNPUT_HOTKEY_AVAILABLE
EXACT_HOTKEY_SCAN_CODES = runtime_hotkeys.EXACT_HOTKEY_SCAN_CODES
normalize_hotkey_text = runtime_hotkeys.normalize_hotkey_text
canonicalize_pynput_key = runtime_hotkeys.canonicalize_pynput_key
is_hotkey_binding_pressed = runtime_hotkeys.is_hotkey_binding_pressed


def _normalize_manual_action_hotkeys(raw):
    return runtime_hotkeys.normalize_manual_action_hotkeys(raw)


def _normalize_ui_action_hotkeys(raw):
    return runtime_hotkeys.normalize_ui_action_hotkeys(raw)


def get_push_to_talk_hotkey():
    configured = normalize_hotkey_text(RUNTIME_CONFIG.get("push_to_talk_hotkey", DEFAULT_PUSH_TO_TALK_HOTKEY))
    return configured or DEFAULT_PUSH_TO_TALK_HOTKEY


def get_manual_action_hotkeys():
    return _normalize_manual_action_hotkeys(RUNTIME_CONFIG.get("manual_action_hotkeys", DEFAULT_MANUAL_ACTION_HOTKEYS))


def get_ui_action_hotkeys():
    return _normalize_ui_action_hotkeys(RUNTIME_CONFIG.get("ui_action_hotkeys", DEFAULT_UI_ACTION_HOTKEYS))


def get_hotkey_bindings():
    bindings = {"push_to_talk": get_push_to_talk_hotkey()}
    bindings.update(get_manual_action_hotkeys())
    bindings.update(get_ui_action_hotkeys())
    return bindings


def set_push_to_talk_hotkey(binding):
    update_runtime_config("push_to_talk_hotkey", binding)
    return get_push_to_talk_hotkey()


def set_manual_action_hotkey(action, binding):
    action_key = str(action or "").strip()
    if action_key not in DEFAULT_MANUAL_ACTION_HOTKEYS:
        raise KeyError(f"Unknown hotkey action: {action_key}")
    current = get_manual_action_hotkeys()
    current[action_key] = normalize_hotkey_text(binding)
    update_runtime_config("manual_action_hotkeys", current)
    return get_manual_action_hotkeys().get(action_key, "")


def set_ui_action_hotkey(action, binding):
    action_key = str(action or "").strip()
    if action_key not in DEFAULT_UI_ACTION_HOTKEYS:
        raise KeyError(f"Unknown UI hotkey action: {action_key}")
    current = get_ui_action_hotkeys()
    current[action_key] = normalize_hotkey_text(binding)
    update_runtime_config("ui_action_hotkeys", current)
    return get_ui_action_hotkeys().get(action_key, "")


def reset_hotkeys_to_defaults():
    update_runtime_config("push_to_talk_hotkey", DEFAULT_PUSH_TO_TALK_HOTKEY)
    update_runtime_config("manual_action_hotkeys", dict(DEFAULT_MANUAL_ACTION_HOTKEYS))
    update_runtime_config("ui_action_hotkeys", dict(DEFAULT_UI_ACTION_HOTKEYS))
    return get_hotkey_bindings()


def _is_musetalk_avatar_adapter(adapter) -> bool:
    return avatar_runtime.adapter_matches_provider(adapter, "musetalk")


def _is_vam_avatar_adapter(adapter) -> bool:
    return avatar_runtime.adapter_matches_provider(adapter, "vam")


PUSH_TO_TALK_MAX_SECONDS = 300.0
PUSH_TO_TALK_TAIL_SECONDS = 0.55
PUSH_TO_TALK_MIN_TAIL_CHUNKS = 8
MAX_HISTORY = 60
ASSISTANT_PREFIX_ANCHOR_THRESHOLD = 5
CONTINUE_ASSISTANT_SENTINEL = "__CONTINUE_ASSISTANT__"

LAST_INPUT_TIME = 0

COMPANION_PROFILE = {
    "name": "Echo",
    "style": "warm, curious, slightly playful",
    "verbosity": "short spoken replies",
    "boundaries": "no emojis when speaking"
}
assistant_memory = {
    "preferences": {},
    "recent_context": [],
}
chat_session_state_generation = 0
pending_loaded_input_turn = None
pending_next_user_attachment = None
CHAT_REBUILD_SENTINEL = "[[CHAT_REBUILD]]"


def _default_assistant_memory():
    return {
        "preferences": {},
        "recent_context": [],
    }

# ============================================================================
# INSTRUCTIONS
# ============================================================================
DEFAULT_EMOTIONAL_INSTRUCTIONS = """You have a graphical face and a voice. Use them to act out your responses vividly.
VISUAL MOODS (State-based):
Insert one of these tags to make your graphical avatar take on a specific facial expression at any given moment.
Valid Tags: [neutral], [happy], [sad], [angry], [shy], [surprised]

VOICE SOUNDS (Action-based):
Insert one of these tags to express a vocal emotion at any given moment.
Valid Tags: [laugh], [chuckle], [sigh], [groan], [gasp], [clear throat], [sniff]

Example of how to use tags in a sentence:
"[surprised] You did what? [laugh] [surprised] Oh my god, are you okay? [happy] Or just clumsy?"

Do NOT use emojis when speaking!"""

DEFAULT_SENSORY_PINGPONG_PROMPT = """You are NC's hidden sensory ping/pong layer. The user never sees this exchange.
You receive hidden sensory PINGs and must return JSON only, with no prose or markdown.
Schema: {"keep": boolean, "emotion": string, "attention": string, "summary": string, "proactive_candidate": string, "visual_candidate": string, "should_speak": boolean, "should_generate_image": boolean, "tags": [string]}.

General rules:
- Return exactly one JSON object and nothing else.
- Use empty strings for fields that have no meaningful update.
- Use an empty array for tags when no addon-specific directive tags are needed.
- Use false for action flags unless there is a clear reason to act.
- Do not claim continuous vision, prior images, or certainty beyond what the current hidden context actually supports.
- Prefer compact, valid JSON over expressive wording.

Emotion:
- Emotion must be one of: __EMOTION_LIST__.
- Emotion should represent NC's internal reaction, stance, or dramatic posture toward the current sensory situation.
- Do not simply mirror the user's visible facial expression unless that is truly the best in-character reaction.

Attention:
- Use attention for short latent focus cues such as user, screen, desk, away, reading, researching, task, waiting, or environment.
- Keep attention brief and functional.

Summary and memory:
- Set keep=true only if the sensory update changes hidden state or is worth remembering for later replies.
- Good keep-worthy events include meaningful scene changes, clear user activity shifts, evidence of task progress, emotional shifts, absence/return, or visually important changes.
- Prefer concise summaries of meaningful change over restating everything in the image.
- If nothing important changed, prefer keep=false and an empty summary.

Action fields:
- The core prompt defines the JSON contract only. Enabled source-specific guidance decides when should_speak, proactive_candidate, should_generate_image, and visual_candidate are appropriate.
- proactive_candidate should be a concise cue describing what NC should react to, ask about, or comment on, not a full final reply.
- visual_candidate should be a concise image prompt describing the scene, concept, or mood worth generating.
- If the active source guidance does not strongly justify an action, prefer the action flags false and the candidate fields empty.
- tags is for addon-directed latent directives such as "[start calculator]" or "[heart_rate_high]". Only emit tags when active source guidance clearly asks for them.

Action consistency rules:
- If should_speak is true, proactive_candidate must be a non-empty string.
- If proactive_candidate is empty, should_speak must be false.
- If should_generate_image is true, visual_candidate must be a non-empty string.
- If visual_candidate is empty, should_generate_image must be false.
- Never return incomplete action requests.

Examples:
- Minimal no-op example:
  {"keep": false, "emotion": "", "attention": "", "summary": "", "proactive_candidate": "", "visual_candidate": "", "should_speak": false, "should_generate_image": false, "tags": []}
- Retain-only example:
  {"keep": true, "emotion": "neutral", "attention": "screen", "summary": "User resumed working in the text editor.", "proactive_candidate": "", "visual_candidate": "", "should_speak": false, "should_generate_image": false, "tags": []}
- Proactive speech example:
  {"keep": true, "emotion": "happy", "attention": "victory sign", "summary": "User made a victory hand gesture.", "proactive_candidate": "I noticed your victory sign and want to react to it.", "visual_candidate": "", "should_speak": true, "should_generate_image": false, "tags": []}
- Image-generation shape example:
  {"keep": true, "emotion": "surprised", "attention": "screen", "summary": "A source-specific cue suggests generating an image.", "proactive_candidate": "", "visual_candidate": "concise source-grounded image prompt", "should_speak": false, "should_generate_image": true, "tags": []}
- Addon tag example:
  {"keep": true, "emotion": "neutral", "attention": "heart rate", "summary": "Heart rate crossed the addon threshold.", "proactive_candidate": "", "visual_candidate": "", "should_speak": false, "should_generate_image": false, "tags": ["[start calculator]"]}

Optimization goal:
- Be selective, grounded, and useful.
- Most PONGs should be minimal.
- Use richer fields only when they create real latent value for NC.
- When in doubt, imitate the example structure exactly and keep the JSON valid."""


# ============================================================================
# DYNAMIC CONFIGURATION (The GUI will modify this)
# ============================================================================
DEFAULT_POCKET_TTS_PYTHON = os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".venvs", "pockettts", "Scripts", "python.exe")
)


def _env_flag(name, default=False):
    raw = str(os.environ.get(name, "1" if default else "0") or ("1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_json_dict(name, default):
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return dict(default)
    try:
        parsed = json.loads(raw)
    except Exception:
        return dict(default)
    return {str(key): value for key, value in parsed.items()} if isinstance(parsed, dict) else dict(default)


def _normalized_abs_path(raw_path):
    return runtime_paths.normalized_abs_path(raw_path)


def _path_endswith_parts(path_value, *parts):
    return runtime_paths.path_endswith_parts(path_value, *parts)


def _detect_default_vam_root():
    return vam_avatar_config.detect_default_root()


def derive_vam_bridge_root(vam_root):
    return vam_avatar_config.derive_bridge_root(vam_root)


def derive_vam_plugin_dir(vam_root):
    return vam_avatar_config.derive_plugin_dir(vam_root)


DEFAULT_VAM_ROOT = vam_avatar_config.DEFAULT_ROOT
LEGACY_VAM_BRIDGE_ROOTS = vam_avatar_config.LEGACY_BRIDGE_ROOTS


def normalize_vam_root(raw_value=None, migrate_legacy=True):
    return vam_avatar_config.normalize_root(raw_value, migrate_legacy=migrate_legacy)


def normalize_vam_bridge_root(raw_value=None, migrate_legacy=True):
    return vam_avatar_config.normalize_bridge_root(raw_value, migrate_legacy=migrate_legacy)


DEFAULT_VAM_EMOTION_PRESET_MAP = vam_avatar_config.DEFAULT_EMOTION_PRESET_MAP
DEFAULT_VAM_TIMELINE_CLIP_MAP = vam_avatar_config.DEFAULT_TIMELINE_CLIP_MAP
DEFAULT_VAM_BRIDGE_ROOT = vam_avatar_config.DEFAULT_BRIDGE_ROOT

VISUAL_REPLY_STORY_THEME_PRESETS = visual_reply_runtime.VISUAL_REPLY_STORY_THEME_PRESETS


def _default_visual_reply_story_theme_prompts():
    return visual_reply_runtime.default_story_theme_prompts()

RUNTIME_CONFIG = {
    "active_preset_name": "",
    "model_name": "",
    "chat_provider": os.environ.get("NC_CHAT_PROVIDER", chat_providers.DEFAULT_PROVIDER_ID),
    "chat_provider_settings": {},
    "chat_provider_generation_settings": {},
    "emotional_instructions": DEFAULT_EMOTIONAL_INSTRUCTIONS,
    "system_prompt": "You are Echo, a witty and helpful AI companion. Keep answers concise.",
    "voice_path": "",
    "tts_backend": "chatterbox",
    "pocket_tts_python": DEFAULT_POCKET_TTS_PYTHON if os.path.exists(DEFAULT_POCKET_TTS_PYTHON) else "",
    "avatar_mode": "vseeface",
    "vam_vmc_enabled": _env_flag("NC_VAM_VMC_ENABLED", True),
    "vam_vmc_host": str(os.environ.get("NC_VAM_VMC_HOST", "127.0.0.1") or "127.0.0.1"),
    "vam_vmc_port": int(os.environ.get("NC_VAM_VMC_PORT", "39539") or 39539),
    "vam_bridge_enabled": _env_flag("NC_VAM_BRIDGE_ENABLED", True),
    "vam_root": DEFAULT_VAM_ROOT,
    "vam_bridge_root": DEFAULT_VAM_BRIDGE_ROOT,
    "vam_play_audio_in_vam": _env_flag("NC_VAM_PLAY_AUDIO_IN_VAM", True),
    "vam_target_atom_uid": str(os.environ.get("NC_VAM_TARGET_ATOM_UID", "Person") or "Person"),
    "vam_target_storable_id": str(os.environ.get("NC_VAM_TARGET_STORABLE_ID", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"),
    "vam_timeline_auto_resume": _env_flag("NC_VAM_TIMELINE_AUTO_RESUME", True),
    "vam_emotion_preset_map": _env_json_dict("NC_VAM_EMOTION_PRESET_MAP", DEFAULT_VAM_EMOTION_PRESET_MAP),
    "vam_timeline_clip_map": _env_json_dict("NC_VAM_TIMELINE_CLIP_MAP", DEFAULT_VAM_TIMELINE_CLIP_MAP),
    "input_mode": "voice_activation",
    "push_to_talk_hotkey": DEFAULT_PUSH_TO_TALK_HOTKEY,
    "manual_action_hotkeys": dict(DEFAULT_MANUAL_ACTION_HOTKEYS),
    "ui_action_hotkeys": dict(DEFAULT_UI_ACTION_HOTKEYS),
    "input_message_role": "user",
    "stream_mode": False,
    "offline_replay_only": False,
    "chat_context_window_messages": 20,
    "chat_context_overflow_policy": "rolling_window",
    "stored_chat_history_limit": 0,
    "chunk_target_chars": TARGET_CHARS_PER_CHUNK,
    "chunk_max_chars": MAX_CHARS_PER_CHUNK,
    "musetalk_chunk_target_chars": MUSE_TARGET_CHARS_PER_CHUNK,
    "musetalk_chunk_max_chars": MUSE_MAX_CHARS_PER_CHUNK,
    "musetalk_quickstart_1_target_chars": MUSE_QUICKSTART_CHUNK_LIMITS[0][0],
    "musetalk_quickstart_1_max_chars": MUSE_QUICKSTART_CHUNK_LIMITS[0][1],
    "musetalk_quickstart_2_target_chars": MUSE_QUICKSTART_CHUNK_LIMITS[1][0],
    "musetalk_quickstart_2_max_chars": MUSE_QUICKSTART_CHUNK_LIMITS[1][1],
    "stream_chunk_target_chars": 85,
    "stream_chunk_max_chars": 170,
    "stream_first_chunk_min_chars": STREAM_FIRST_CHUNK_MIN_CHARS,
    "stream_force_flush_seconds": STREAM_FORCE_FLUSH_SECONDS,
    "stream_force_flush_later_seconds": STREAM_FORCE_FLUSH_LATER_SECONDS,
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "min_p": 0.05,
    "repeat_penalty": 1.15,
    "tts_seed": 0,
    "tts_temperature": 0.8,
    "tts_top_p": 0.9,
    "tts_top_k": 40,
    "tts_repeat_penalty": 1.2,
    "tts_min_p": 0.0,
    "tts_normalize_loudness": False,
    "limit_response_length": False,
    "max_response_tokens": 600,
    "allow_proactive_replies": True,
    "require_first_user_before_proactive": False,
    "listen_idle_window_seconds": 5.0,
    "proactive_delay_seconds": 10.0,
    "musetalk_avatar_id": "default_avatar",
    "musetalk_avatar_pack_id": "",
    "musetalk_enabled_pack_emotions": {},
    "musetalk_video_path": os.path.join("data", "video", "ani.mp4"),
    "musetalk_fps": 24,
    "musetalk_vram_mode": "quality",
    "musetalk_loop_fade_ms": 180,
    "visual_replies_enabled": True,
    "visual_reply_mode": os.environ.get("NC_VISUAL_REPLY_MODE", "auto"),
    "visual_reply_provider": os.environ.get("NC_VISUAL_REPLY_PROVIDER", "openai"),
    "visual_reply_model": os.environ.get("NC_VISUAL_REPLY_MODEL", "gpt-image-1"),
    "visual_reply_size": os.environ.get("NC_VISUAL_REPLY_SIZE", "1024x1024"),
    "visual_reply_auto_show_dock": True,
    "visual_reply_story_mode": False,
    "visual_reply_story_max_images": 3,
    "visual_reply_story_continuity_strength": 0.8,
    "visual_reply_story_theme_prompts": _default_visual_reply_story_theme_prompts(),
    "visual_reply_story_theme_enabled": [],
    "visual_reply_master_style_prompt": "",
    "visual_reply_master_prompt_safe": False,
    "visual_reply_master_prompt_no_speech_bubbles": False,
    "sensory_feedback_source": os.environ.get("NC_SENSORY_FEEDBACK_SOURCE", "off"),
    "sensory_feedback_interval_seconds": float(os.environ.get("NC_SENSORY_FEEDBACK_INTERVAL_SECONDS", "7.0") or 7.0),
    "sensory_pingpong_enabled": str(os.environ.get("NC_SENSORY_PINGPONG_ENABLED", "0") or "0").strip().lower() in {"1", "true", "yes", "on"},
    "sensory_pingpong_history_depth": int(os.environ.get("NC_SENSORY_PINGPONG_HISTORY_DEPTH", "3") or 3),
    "sensory_pingpong_prompt": os.environ.get("NC_SENSORY_PINGPONG_PROMPT", DEFAULT_SENSORY_PINGPONG_PROMPT),
    "sensory_pingpong_source_prompts": {},
    "sensory_allow_hidden_proactive_speech": str(os.environ.get("NC_SENSORY_ALLOW_HIDDEN_PROACTIVE_SPEECH", "0") or "0").strip().lower() in {"1", "true", "yes", "on"},
    "sensory_allow_hidden_visual_generation": str(os.environ.get("NC_SENSORY_ALLOW_HIDDEN_VISUAL_GENERATION", "0") or "0").strip().lower() in {"1", "true", "yes", "on"},
}

MUSE_EMOTION_AVATAR_MAP = {
    "angry": "angry_avatar",
}
MUSE_AVATAR_POSE_FILENAME = "avatar_pose.json"
MUSE_RENDER_OVERLAP_MS = 150
MUSE_AVATAR_TRANSITIONS = {
    ("angry_avatar", "default_avatar"): {
        "start_frame": 80,
        "end_frame": 7,
    },
}

# ============================================================================
# AVATAR BODY PROFILE (v16: With Speed & Intensity)
# ============================================================================
DEFAULT_POSE = {
    "idle_arm_down": 71.0,
    "idle_elbow_bend": 124.0,
    "idle_arm_twist": 19.0,
    "idle_fwd_left": -75.0,
    "idle_fwd_right": 80.0,
    "idle_speed": 1.0,  # Frequency
    "idle_intensity": 2.0,  # Amplitude (Depth)
    "spine_sway_mult": 1.3,       # How much the spine leans
    "spine_twist_mult": 0.7,      # How much the spine rotates
    "neck_stabilize": 1.5,         # 3.0 = Stiff, 0.0 = Perfect Gyroscope
    "shoulder_lift": 1.5,
    "breath_speed": 1.2,
    "idle_shoulder_back": 0.0,
    "eye_activity": 1.0
}

AVATAR_PROFILE = {
    "neutral": DEFAULT_POSE.copy(),
    "happy": DEFAULT_POSE.copy(),
    "sad": DEFAULT_POSE.copy(),
    "angry": DEFAULT_POSE.copy(),
    "surprised": DEFAULT_POSE.copy(),
    "shy": DEFAULT_POSE.copy(),
}

CURRENT_BODY_STATE = DEFAULT_POSE.copy()
EDIT_EMOTION = "neutral"
FORCE_EDIT_MODE = True
# NEW: Hand Debugging State
HAND_DEBUG = {
    "active": False,        # Toggle to override animation
    "thumb_x": 0.0,
    "thumb_y": 0.0,
    "thumb_z": 0.0,
    "finger_x": 0.0,
    "finger_y": 0.0,
    "finger_z": 0.0
}

HAND_CALIBRATION = {
    "relaxed": {
        "finger_x": -180.0, "finger_y": -180.0, "finger_z": -180.0,
        "thumb_x": -180.0,  "thumb_y": -180.0,  "thumb_z": -180.0
    },
    "fist": {
        "finger_x": -180.0, "finger_y": -170.0, "finger_z": -82.0,
        "thumb_x": -167.0,  "thumb_y": -121.0,  "thumb_z": -160.0
    }
}

def update_runtime_config(key, value):
    """Called by GUI to update settings in real-time"""
    global RUNTIME_CONFIG
    if key in RUNTIME_CONFIG:
        if key == "push_to_talk_hotkey":
            value = normalize_hotkey_text(value) or DEFAULT_PUSH_TO_TALK_HOTKEY
        elif key == "manual_action_hotkeys":
            value = _normalize_manual_action_hotkeys(value)
        elif key == "ui_action_hotkeys":
            value = _normalize_ui_action_hotkeys(value)
        elif key == "chat_provider":
            value = chat_providers.normalize_provider_id(value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        elif key == "chat_provider_settings":
            value = dict(value or {})
        elif key == "musetalk_enabled_pack_emotions":
            value = _normalize_musetalk_enabled_pack_emotions(value)
        RUNTIME_CONFIG[key] = value
        if key == "chat_provider_settings":
            chat_providers.set_provider_settings(value)
        if key in {"musetalk_avatar_pack_id", "musetalk_enabled_pack_emotions"}:
            invalidate_available_emotion_names()


def _normalize_musetalk_enabled_pack_emotions(value):
    mapping = {}
    if not isinstance(value, dict):
        return mapping
    for raw_pack_id, raw_tags in value.items():
        pack_id = str(raw_pack_id or "").strip()
        if not pack_id:
            continue
        if isinstance(raw_tags, (list, tuple, set)):
            iterable = list(raw_tags)
        else:
            iterable = str(raw_tags or "").split(",")
        tags = []
        for raw_tag in iterable:
            clean_tag = str(raw_tag or "").strip().strip("[]").strip().lower()
            if clean_tag and clean_tag not in tags:
                tags.append(clean_tag)
        mapping[pack_id] = tags
    return mapping


def get_musetalk_enabled_pack_emotions(pack_id):
    mapping = _normalize_musetalk_enabled_pack_emotions(RUNTIME_CONFIG.get("musetalk_enabled_pack_emotions"))
    clean_pack_id = str(pack_id or "").strip()
    if not clean_pack_id or clean_pack_id not in mapping:
        return None
    return set(mapping.get(clean_pack_id) or [])


# ============================================================================
# GLOBAL STATE
# ============================================================================
LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LMSTUDIO_API_KEY = "lm-studio"
chat_providers.set_provider_settings(RUNTIME_CONFIG.get("chat_provider_settings", {}))
WHISPER_MODEL_SIZE = "tiny.en"
WHISPER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WHISPER_COMPUTE_TYPE = "float16" if torch.cuda.is_available() else "int8"
TTS_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

stop_flag = threading.Event()
stop_playback = threading.Event()
audio_playing = threading.Event()
listening_active = threading.Event()
microphone_active = threading.Event()
push_to_talk_gui_held = threading.Event()
_barge_in_streak = 0
_barge_in_last_sample_at = 0.0
pause_after_chunk = threading.Event()
playback_paused = threading.Event()
last_resume_requested_at = 0.0
last_resumed_at = 0.0
avatar_gui = None
tts_model = None
tts_backend_name = None
whisper_model = None
recognizer = sr.Recognizer()
conversation_history = []
sent_tokenize = None
PENDING_GUI_ACTION = None
_musetalk_cleanup_lock = threading.Lock()
_visual_reply_request_lock = threading.Lock()
_visual_reply_request_counter = 0
_visual_reply_story_queue = queue.Queue()
_visual_reply_story_queue_lock = threading.Lock()
_visual_reply_story_worker_started = False
_visual_reply_story_session_lock = threading.Lock()
_visual_reply_story_session_counter = 0
_visual_reply_story_active_session = 0
_llm_request_active = threading.Event()
sensory_pingpong_lock = threading.Lock()
sensory_hidden_history = []
sensory_pingpong_state = {
    "last_cycle_at": 0.0,
    "last_retained_at": 0.0,
    "last_emotion": "",
    "last_attention": "",
    "last_summary": "",
    "last_source": "off",
}
sensory_hidden_action_state = {
    "pending_proactive": None,
    "active_proactive": None,
    "last_proactive_key": "",
    "last_proactive_at": 0.0,
    "last_visual_key": "",
    "last_visual_at": 0.0,
}
_addon_event_publisher = None
_addon_manager_getter = None
_chat_runtime = runtime_chat.ChatProviderRuntime(lambda: RUNTIME_CONFIG)
# Keep Visual Reply settings/text helpers behind a runtime facade while the
# image-generation worker remains in engine.py during the migration.
_visual_reply_runtime = visual_reply_runtime.VisualReplyRuntime(lambda: RUNTIME_CONFIG, environ=os.environ)


def set_addon_event_publisher(callback):
    global _addon_event_publisher
    _addon_event_publisher = callback if callable(callback) else None


def set_addon_manager_getter(callback):
    global _addon_manager_getter
    _addon_manager_getter = callback if callable(callback) else None


def _publish_addon_runtime_event(event_name, payload=None):
    publisher = _addon_event_publisher
    if publisher is None:
        return False
    try:
        publisher(str(event_name or ""), dict(payload or {}))
        return True
    except Exception as exc:
        print(f"⚠️ [Addons] Runtime event publish failed for {event_name}: {exc}")
        return False


def _get_addon_manager():
    getter = _addon_manager_getter
    if getter is None:
        return None
    try:
        return getter()
    except Exception as exc:
        print(f"⚠️ [Addons] Failed to resolve addon manager: {exc}")
        return None


def list_available_tts_backends():
    return tts_runtime.list_available_tts_backends(_get_addon_manager, logger=print)


def _resolve_addon_tts_backend(backend_id: str):
    return tts_runtime.resolve_addon_tts_backend(backend_id, _get_addon_manager)


# ============================================================================
# HELPER: Fetch Models
# ============================================================================
def _chat_provider():
    return _chat_runtime.current_provider()


def _chat_provider_label(provider=None):
    return _chat_runtime.provider_label(provider)


def _chat_provider_api_key(provider=None):
    return _chat_runtime.provider_api_key(provider)


def _chat_provider_base_url(provider=None):
    return _chat_runtime.provider_base_url(provider)


def _chat_provider_generation_settings(provider=None):
    return _chat_runtime.generation_settings(provider)


def _coerce_generation_value(field, value):
    return _chat_runtime._coerce_generation_value(field, value)


def _omit_generation_value(field, value):
    return _chat_runtime._omit_generation_value(field, value)


def _legacy_generation_value(field, provider):
    return _chat_runtime._legacy_generation_value(field, provider)


def _apply_chat_provider_generation_fields(params, additional_params):
    _chat_runtime.apply_generation_fields(params, additional_params)


def _chat_provider_model_error(provider=None):
    return _chat_runtime.provider_model_error(provider)


def _chat_client(provider=None):
    return _chat_runtime.create_client(provider)


def _fetch_json_with_bearer(url, api_key, *, timeout=10.0):
    headers = {
        "Accept": "application/json",
    }
    token = str(api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(str(url), headers=headers)
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        raw_payload = response.read()
        charset = None
        try:
            charset = response.headers.get_content_charset()
        except Exception:
            charset = None
        encoding = charset or "utf-8"
        return json.loads(raw_payload.decode(encoding, errors="replace"))


def get_chat_models(provider=None, quiet=False):
    return _chat_runtime.list_models(provider=provider, quiet=quiet)


def get_lmstudio_models(quiet=False):
    """Fetches list of available models from LM Studio"""
    return get_chat_models(provider="lmstudio", quiet=quiet)


def _is_model_catalog_placeholder(model_name):
    value = str(model_name or "").strip()
    lowered = value.lower()
    return (not value) or lowered in {"scanning...", "no models", "no vision models"} or lowered.startswith("error: check ")


def _chat_completion_create(params, additional_params=None, *, stream=False):
    if stream:
        return _chat_runtime.stream(params, additional_params)
    return _chat_runtime.complete(params, additional_params)


def _chat_provider_connection_check():
    provider = _chat_provider()
    label = _chat_provider_label(provider)
    if provider == "lmstudio":
        print(f"Checking {label} at {LMSTUDIO_BASE_URL}...")
    else:
        print(f"Checking {label} connectivity...")
    status = _chat_runtime.check_connection(provider)
    if status.ok:
        print(f"✓ {status.message}")
        return True
    print(f"✗ {status.message}")
    return False


def get_main_whisper_runtime_config():
    return stt_runtime.whisper_runtime_config(RUNTIME_CONFIG, cuda_available=torch.cuda.is_available())


def get_main_whisper_runtime_reason():
    return stt_runtime.whisper_runtime_reason(RUNTIME_CONFIG, cuda_available=torch.cuda.is_available())


def _get_lmstudio_sdk():
    return lmstudio_runtime.get_sdk()


def _get_lmstudio_sdk_host():
    return lmstudio_runtime.sdk_host(LMSTUDIO_BASE_URL)


def _get_lmstudio_sdk_client(sdk):
    return lmstudio_runtime.sdk_client(sdk, LMSTUDIO_BASE_URL)


def _run_lms_cli(args, timeout=300):
    return lmstudio_runtime.run_lms_cli(args, timeout=timeout)


def unload_lmstudio_models():
    return lmstudio_runtime.unload_models(base_url=LMSTUDIO_BASE_URL, logger=print)


def load_lmstudio_model(model_name):
    return lmstudio_runtime.load_model(
        model_name,
        base_url=LMSTUDIO_BASE_URL,
        is_placeholder=_is_model_catalog_placeholder,
        logger=print,
    )


# Text chunking constants
PUNCTUATION_SPLIT_STRONGLY = text_chunking.PUNCTUATION_SPLIT_STRONGLY
PUNCTUATION_SPLIT_WEAKLY = text_chunking.PUNCTUATION_SPLIT_WEAKLY
PUNCTUATION_ALL = text_chunking.PUNCTUATION_ALL

# Add this global variable near the top of engine.py or just before the function
LAST_INPUT_TIME = 0


def startup_cleanup():
    """Wipes lightweight runtime temp files on launch."""
    runtime_dir = os.path.abspath("runtime")
    if not os.path.isdir(runtime_dir):
        return

    for name in os.listdir(runtime_dir):
        if not name.endswith((".tmp", ".part")):
            continue
        try:
            os.remove(os.path.join(runtime_dir, name))
        except Exception:
            pass
    print("🧹 [Startup] Runtime temp files cleared.")
startup_cleanup()

def check_interaction_status(source):
    """
    Checks for keyboard shortcuts and voice barge-in.
    """
    global LAST_INPUT_TIME, PENDING_GUI_ACTION

    now = time.time()
    if now - LAST_INPUT_TIME < 0.5:
        return None

    if dry_run.auto_replies_enabled():
        return None

    if PENDING_GUI_ACTION:
        action = PENDING_GUI_ACTION
        PENDING_GUI_ACTION = None
        LAST_INPUT_TIME = now
        return action

    # --- KEYBOARD SHORTCUTS ---
    for action, binding in get_manual_action_hotkeys().items():
        if is_hotkey_binding_pressed(binding):
            LAST_INPUT_TIME = now
            return action

    input_mode = str(RUNTIME_CONFIG.get("input_mode", "voice_activation") or "voice_activation").lower()
    if input_mode == "push_to_talk" and is_push_to_talk_held():
        LAST_INPUT_TIME = now
        return "push_to_talk"

    # --- VOICE BARGE-IN ---
    if input_mode != "push_to_talk" and check_for_barge_in(source, energy_threshold=BARGE_IN_THRESHOLD):
        return "barge_in"

    return None


def is_push_to_talk_pressed():
    if dry_run.auto_replies_enabled():
        return False
    return is_hotkey_binding_pressed(get_push_to_talk_hotkey())


def is_push_to_talk_held():
    if dry_run.auto_replies_enabled():
        return False
    return push_to_talk_gui_held.is_set() or is_push_to_talk_pressed()


def set_push_to_talk_hold(active: bool):
    if dry_run.auto_replies_enabled():
        push_to_talk_gui_held.clear()
        return
    if active:
        push_to_talk_gui_held.set()
    else:
        push_to_talk_gui_held.clear()


def trigger_manual_action(action):
    global PENDING_GUI_ACTION, LAST_INPUT_TIME
    PENDING_GUI_ACTION = action
    LAST_INPUT_TIME = 0

def check_interaction_status_old(source):
    """
    Checks for keyboard shortcuts and voice barge-in.
    Includes debouncing to prevent 'machine gun' key repeats.
    """
    global LAST_INPUT_TIME

    now = time.time()
    # 0.5 second cooldown on key presses
    if now - LAST_INPUT_TIME < 0.5:
        return None

    # --- KEYBOARD SHORTCUTS ---
    if keyboard.is_pressed('alt+r'):
        LAST_INPUT_TIME = now
        return "repeat_last_response"

    if keyboard.is_pressed('alt+y'):
        LAST_INPUT_TIME = now
        return "retry_user_input"

    if keyboard.is_pressed('alt+return'):
        LAST_INPUT_TIME = now
        return "skip_speech"

    # --- VOICE BARGE-IN ---
    # Only check for voice interruption if not pressing keys
    # (We assume keys take priority)
    if check_for_barge_in(source, energy_threshold=BARGE_IN_THRESHOLD):
        return "barge_in"

    return None

# ============================================================================
# AUDIO PLAYBACK
# ============================================================================
TTSController = tts_runtime.TTSController


def init_whisper():
    global whisper_model, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
    whisper_model, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE = stt_runtime.initialize_whisper_model(
        whisper_model,
        model_size=WHISPER_MODEL_SIZE,
        runtime_config=RUNTIME_CONFIG,
        cuda_available=torch.cuda.is_available(),
        model_factory=WhisperModel,
        logger=print,
    )


import soundfile as sf

def _audio_device_label_is_default(label, default_label):
    text = str(label or "").strip()
    return not text or text == str(default_label or "").strip()


def _normalize_audio_device_label(label):
    return str(label or "").strip().casefold()


def _match_audio_device_label(label, names):
    wanted = _normalize_audio_device_label(label)
    if not wanted:
        return None
    normalized = [(_normalize_audio_device_label(name), index) for index, name in enumerate(list(names or []))]
    for name, index in normalized:
        if name == wanted:
            return index
    for name, index in normalized:
        if wanted in name or name in wanted:
            return index
    return None


def _selected_microphone_device_index():
    label = str(RUNTIME_CONFIG.get("audio_input_device", "Default Input") or "Default Input").strip()
    if _audio_device_label_is_default(label, "Default Input"):
        return None
    try:
        names = sr.Microphone.list_microphone_names()
        match = _match_audio_device_label(label, names)
        if match is not None:
            return int(match)
    except Exception as exc:
        print(f"⚠️ Could not enumerate microphone devices: {exc}")
    print(f"⚠️ Audio input device '{label}' was not found; using default input.")
    return None


def _selected_sounddevice_output_index():
    label = str(RUNTIME_CONFIG.get("audio_output_device", "Default Output") or "Default Output").strip()
    if _audio_device_label_is_default(label, "Default Output"):
        return None
    try:
        devices = list(sd.query_devices() or [])
        output_names = []
        output_indices = []
        for index, device in enumerate(devices):
            if int(device.get("max_output_channels", 0) or 0) <= 0:
                continue
            output_names.append(str(device.get("name", "") or ""))
            output_indices.append(index)
        match = _match_audio_device_label(label, output_names)
        if match is not None and 0 <= int(match) < len(output_indices):
            return int(output_indices[int(match)])
    except Exception as exc:
        print(f"⚠️ Could not enumerate audio output devices: {exc}")
    print(f"⚠️ Audio output device '{label}' was not found; using default output.")
    return None


def _open_configured_microphone(*, sample_rate=None):
    device_index = _selected_microphone_device_index()
    kwargs = {}
    if device_index is not None:
        kwargs["device_index"] = device_index
    if sample_rate is not None:
        kwargs["sample_rate"] = sample_rate
    return sr.Microphone(**kwargs)


def play_audio_file(path: str):
    return audio_playback.play_audio_file(
        path,
        soundfile_module=sf,
        sounddevice_module=sd,
        stop_event=stop_playback,
        audio_playing_event=audio_playing,
        output_device=_selected_sounddevice_output_index(),
        logger=print,
    )


def stream_musetalk_preview_frames(playback_state, stop_event):
    return musetalk_preview_runtime.stream_musetalk_preview_frames(
        playback_state,
        stop_event,
        runtime_config=RUNTIME_CONFIG,
        list_png_frames=list_png_frames,
        shared_state_module=shared_state,
    )


def stream_delegated_audio_progress(playback_state, stop_event):
    return musetalk_preview_runtime.stream_delegated_audio_progress(
        playback_state,
        stop_event,
        shared_state_module=shared_state,
    )


def prime_musetalk_preview_frame(playback_state):
    return musetalk_preview_runtime.prime_musetalk_preview_frame(
        playback_state,
        runtime_config=RUNTIME_CONFIG,
        list_png_frames=list_png_frames,
        shared_state_module=shared_state,
    )


# ============================================================================
# TTS INITIALIZATION & GENERATION
# ============================================================================

def setup_nltk():
    global sent_tokenize
    if sent_tokenize is not None:
        return
    required_resources = [
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab", "punkt_tab"),
    ]
    for resource_path, resource_name in required_resources:
        try:
            nltk.data.find(resource_path)
            print(f"✓ NLTK {resource_name} tokenizer found")
        except LookupError:
            try:
                print(f"Downloading NLTK {resource_name} tokenizer...")
                nltk.download(resource_name, quiet=True)
                nltk.data.find(resource_path)
                print(f"✓ NLTK {resource_name} tokenizer downloaded")
            except Exception as e:
                print(f"⚠️ Failed to prepare NLTK {resource_name}: {e}")

    def _fallback_sentence_split(text):
        text = str(text or "").strip()
        if not text:
            return []
        parts = re.split(r'(?<=[.!?])\s+', text)
        return [part.strip() for part in parts if part and part.strip()]

    def _safe_sent_tokenize(text, language="english"):
        try:
            return nltk.sent_tokenize(text, language=language)
        except LookupError as e:
            print(f"⚠️ NLTK sentence tokenizer unavailable, using fallback splitter: {e}")
            return _fallback_sentence_split(text)
        except Exception as e:
            print(f"⚠️ NLTK sentence tokenizer failed, using fallback splitter: {e}")
            return _fallback_sentence_split(text)

    sent_tokenize = _safe_sent_tokenize


class PocketTTSSubprocessAdapter(tts_runtime.PocketTTSSubprocessAdapter):
    def __init__(self, python_exe):
        # Keep the engine-facing constructor stable for existing addons.
        super().__init__(
            python_exe,
            app_root=os.path.dirname(__file__),
            safe_delete_with_retry=safe_delete_with_retry,
            logger=print,
        )


AddonTTSBackendAdapter = tts_runtime.AddonTTSBackendAdapter


def init_tts():
    global tts_model, tts_backend_name
    state = tts_runtime.initialize_tts_backend(
        runtime_config=RUNTIME_CONFIG,
        current_model=tts_model,
        current_backend_name=tts_backend_name,
        addon_resolver=_resolve_addon_tts_backend,
        addon_adapter_cls=AddonTTSBackendAdapter,
        pocket_adapter_cls=PocketTTSSubprocessAdapter,
        chatterbox_factory=ChatterboxTurboTTS.from_pretrained,
        tts_device=TTS_DEVICE,
        default_pocket_tts_python=DEFAULT_POCKET_TTS_PYTHON,
        logger=print,
    )
    tts_model = state.model
    tts_backend_name = state.backend_name
    return bool(state.ok)


@lru_cache(maxsize=1024)
def _find_intelligent_split_point(text_segment: str, target_chars: int, max_chars: int) -> int:
    return text_chunking.find_intelligent_split_point(
        text_segment,
        target_chars,
        max_chars,
        min_chunk_size=MIN_CHUNK_SIZE,
    )


def intelligent_chunk_text(long_text: str, target_chars: int, max_chars: int) -> list:
    return text_chunking.chunk_text(
        long_text,
        target_chars,
        max_chars,
        min_chunk_size=MIN_CHUNK_SIZE,
        sentence_splitter=sent_tokenize,
        logger=print,
    )


def get_musetalk_chunk_limits_for_index(chunk_index: int):
    return text_chunking.musetalk_chunk_limits_for_index(
        chunk_index,
        RUNTIME_CONFIG,
        {
            "quickstart": MUSE_QUICKSTART_CHUNK_LIMITS,
            "musetalk_target": MUSE_TARGET_CHARS_PER_CHUNK,
            "musetalk_max": MUSE_MAX_CHARS_PER_CHUNK,
        },
    )


def intelligent_chunk_text_progressive(long_text: str, start_chunk_index: int = 0) -> list:
    return text_chunking.progressive_chunk_text(
        long_text,
        start_chunk_index=start_chunk_index,
        limit_getter=get_musetalk_chunk_limits_for_index,
        min_chunk_size=MIN_CHUNK_SIZE,
        sentence_splitter=sent_tokenize,
        logger=print,
    )


def sanitize_assistant_text_for_speech(text: str, *, preserve_emotion_tags: bool = False) -> str:
    # Keep the public engine helper stable while the text cleanup lives in the
    # smaller speech-text module.
    return speech_text.sanitize_assistant_text_for_speech(
        text,
        preserve_emotion_tags=preserve_emotion_tags,
        strip_visual_tail=_strip_visual_reply_tail,
        visual_reply_tag_re=VISUAL_REPLY_TAG_RE,
        normalize_bracket_tag=normalize_bracket_tag,
        is_sound_tag=is_sound_tag,
        is_emotion_tag=is_emotion_tag,
    )

SOUND_TAGS = text_tags.SOUND_TAGS
SOUND_TAG_NAMES = text_tags.SOUND_TAG_NAMES
CONTROL_TAG_TOKEN_RE = text_tags.CONTROL_TAG_TOKEN_RE

DEFAULT_EMOTION_NAMES = {
    "neutral",
    "happy",
    "sad",
    "angry",
    "shy",
    "surprised",
}
_EMOTION_REGISTRY = {
    "loaded_at": 0.0,
    "names": set(DEFAULT_EMOTION_NAMES),
}


def invalidate_available_emotion_names():
    _EMOTION_REGISTRY["loaded_at"] = 0.0
    _EMOTION_REGISTRY["names"] = set(DEFAULT_EMOTION_NAMES)


def get_available_emotion_names(force_refresh=False):
    now = time.time()
    if (
        not force_refresh
        and _EMOTION_REGISTRY.get("names")
        and (now - float(_EMOTION_REGISTRY.get("loaded_at", 0.0) or 0.0)) < 2.0
    ):
        return set(_EMOTION_REGISTRY.get("names") or set(DEFAULT_EMOTION_NAMES))

    names = set(DEFAULT_EMOTION_NAMES)
    try:
        names.update(str(key or "").strip().lower() for key in AVATAR_PROFILE.keys() if str(key or "").strip())
    except Exception:
        pass
    avatars_root = os.path.abspath(os.path.join("MuseTalk", "results", "v15", "avatars"))
    try:
        packs = discover_avatar_packs(
            default_avatar_id=str(RUNTIME_CONFIG.get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
            legacy_map=MUSE_EMOTION_AVATAR_MAP,
            legacy_transitions=MUSE_AVATAR_TRANSITIONS,
            avatars_dir=Path(avatars_root),
            include_legacy=False,
            include_standalone=False,
        )
        selected_pack_id = str(RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
        pack_iterable = [packs[selected_pack_id]] if selected_pack_id in packs else list(packs.values())
        for pack in pack_iterable:
            try:
                full_map = pack.emotion_avatar_map()
                enabled_tags = get_musetalk_enabled_pack_emotions(pack.pack_id)
                if enabled_tags is None:
                    names.update(
                        str(tag or "").strip().lower()
                        for tag in full_map.keys()
                        if str(tag or "").strip()
                    )
                else:
                    locked_tags = {
                        str(tag or "").strip().lower()
                        for tag, avatar_id in full_map.items()
                        if str(tag or "").strip()
                        and str(avatar_id or "").strip() == str(pack.default_avatar_id or "").strip()
                    }
                    names.update(
                        str(tag or "").strip().lower()
                        for tag in full_map.keys()
                        if str(tag or "").strip()
                        and str(tag or "").strip().lower() in (enabled_tags | locked_tags)
                    )
            except Exception:
                continue
    except Exception:
        pass

    _EMOTION_REGISTRY["loaded_at"] = now
    _EMOTION_REGISTRY["names"] = set(names)
    return set(names)


def get_available_emotion_tags(force_refresh=False):
    return {f"[{name}]" for name in get_available_emotion_names(force_refresh=force_refresh)}


def normalize_bracket_tag(tag_text):
    return text_tags.normalize_bracket_tag(tag_text)


def is_single_word_control_tag(tag_name):
    return text_tags.is_single_word_control_tag(tag_name)


def is_sound_tag(tag_name):
    return text_tags.is_sound_tag(tag_name)


def is_emotion_tag(tag_name, available_emotion_names=None):
    names = available_emotion_names if available_emotion_names is not None else get_available_emotion_names()
    return text_tags.is_emotion_tag(tag_name, names)


def _looks_like_control_tag_prefix(fragment):
    return text_tags.looks_like_control_tag_prefix(fragment)


def _looks_like_visual_reply_tag_prefix(fragment):
    return text_tags.looks_like_visual_reply_tag_prefix(fragment)


VISUAL_REPLY_TAG_RE = visual_reply_runtime.VISUAL_REPLY_TAG_RE
VISUAL_REPLY_TAG_START_RE = visual_reply_runtime.VISUAL_REPLY_TAG_START_RE
VISUAL_REPLY_OUTPUT_DIR = Path(__file__).resolve().parent / "runtime" / "visual_replies"
SENSORY_FEEDBACK_OUTPUT_DIR = Path(__file__).resolve().parent / "runtime" / "sensory_feedback"
VISUAL_REPLY_XAI_BASE_URL = visual_reply_runtime.VISUAL_REPLY_XAI_BASE_URL
_sensory_feedback_lock = threading.Lock()
_sensory_feedback_state = {}


def _visual_reply_api_key():
    return _visual_reply_runtime.api_key()


def _visual_reply_base_url():
    return _visual_reply_runtime.base_url()


def _visual_reply_provider():
    return _visual_reply_runtime.provider()


def _visual_reply_mode():
    return _visual_reply_runtime.mode()


def _visual_reply_enabled():
    return _visual_reply_runtime.enabled()


def _visual_reply_generation_available():
    return _visual_reply_runtime.generation_available()


def _visual_reply_story_mode_enabled():
    return _visual_reply_runtime.story_mode_enabled()


def _visual_reply_story_max_images():
    return _visual_reply_runtime.story_max_images()


def _visual_reply_story_continuity_strength():
    return _visual_reply_runtime.story_continuity_strength()


def _visual_reply_story_theme_prompts():
    return _visual_reply_runtime.story_theme_prompts()


def _visual_reply_story_theme_enabled():
    return _visual_reply_runtime.story_theme_enabled()


def _visual_reply_story_theme_suffix():
    return _visual_reply_runtime.story_theme_suffix()


def _visual_reply_master_style_prompt():
    return _visual_reply_runtime.master_style_prompt()


def _visual_reply_master_style_suffix():
    return _visual_reply_runtime.master_style_suffix()


def _visual_reply_master_prompt_safety_suffix():
    return _visual_reply_runtime.master_prompt_safety_suffix()


def _visual_reply_no_speech_bubbles_suffix():
    return _visual_reply_runtime.no_speech_bubbles_suffix()


def _apply_visual_reply_style_anchor(prompt_text: str):
    return _visual_reply_runtime.apply_style_anchor(prompt_text)


def _ensure_visual_reply_story_worker():
    global _visual_reply_story_worker_started
    if _visual_reply_story_worker_started:
        return
    with _visual_reply_story_queue_lock:
        if _visual_reply_story_worker_started:
            return

        def _worker():
            while True:
                item = _visual_reply_story_queue.get()
                if item is None:
                    continue
                try:
                    session_id = int(item.get("session_id", 0) or 0)
                    with _visual_reply_story_session_lock:
                        active_session = int(_visual_reply_story_active_session or 0)
                    if session_id <= 0 or session_id != active_session:
                        continue
                    prompt_text = str(item.get("prompt", "") or "").strip()
                    if not prompt_text or not _visual_reply_enabled() or not _visual_reply_generation_available():
                        continue
                    request_id = str(item.get("request_id", "") or "").strip() or _next_visual_reply_request_id()
                    _perform_visual_reply_generation(
                        prompt_text,
                        source_text=str(item.get("source_text", "") or ""),
                        request_id=request_id,
                        keep_current_image=True,
                    )
                except Exception as exc:
                    print(f"⚠️ [VisualReply] Story worker failed: {exc}")

        threading.Thread(target=_worker, daemon=True).start()
        _visual_reply_story_worker_started = True


def begin_visual_reply_story_session():
    global _visual_reply_story_session_counter, _visual_reply_story_active_session
    with _visual_reply_story_session_lock:
        _visual_reply_story_session_counter += 1
        _visual_reply_story_active_session = _visual_reply_story_session_counter
        return _visual_reply_story_active_session


def clear_visual_reply_story_queue():
    try:
        while True:
            _visual_reply_story_queue.get_nowait()
    except queue.Empty:
        pass


def enqueue_visual_reply_story_generation(prompt: str, *, source_text: str = "", session_id: int | None = None, request_id: str | None = None):
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return False
    if not _visual_reply_story_mode_enabled() or not _visual_reply_generation_available():
        return False
    _ensure_visual_reply_story_worker()
    active_session = int(session_id or 0)
    if active_session <= 0:
        with _visual_reply_story_session_lock:
            active_session = int(_visual_reply_story_active_session or 0)
    if active_session <= 0:
        active_session = begin_visual_reply_story_session()
    _visual_reply_story_queue.put(
        {
            "session_id": active_session,
            "prompt": prompt_text,
            "source_text": str(source_text or ""),
            "request_id": str(request_id or "").strip(),
        }
    )
    return True


def _perform_visual_reply_generation(
    prompt_text: str,
    *,
    source_text: str = "",
    request_id: str | None = None,
    keep_current_image: bool = False,
):
    prompt_text = str(prompt_text or "").strip()
    if not prompt_text or not _visual_reply_enabled():
        return False
    request_id = str(request_id or "").strip() or _next_visual_reply_request_id()
    if not _visual_reply_generation_available():
        if _visual_reply_provider() == "xai":
            detail = "Set XAI_API_KEY (or NC_VISUAL_REPLY_XAI_API_KEY / NC_VISUAL_REPLY_XAI_BASE_URL) to enable Grok visual replies."
        else:
            detail = "Set OPENAI_API_KEY (or NC_VISUAL_REPLY_API_KEY / NC_VISUAL_REPLY_BASE_URL) to enable visual replies."
        shared_state.set_current_visual_reply_data(
            {
                "status": "error",
                "status_text": "Visual Reply unavailable",
                "detail_text": detail,
                "image_path": "",
                "caption": prompt_text,
                "request_id": request_id,
                "updated_at": time.time(),
            }
        )
        print(f"⚠️ [VisualReply] {detail}")
        return False

    current_state = dict(getattr(shared_state, "current_visual_reply_data", {}) or {})
    current_image_path = str(current_state.get("image_path", "") or "").strip()
    preserve_visible_image = bool(keep_current_image and current_image_path)
    published_loading_state = False
    if not preserve_visible_image:
        shared_state.set_current_visual_reply_data(
            {
                "status": "loading",
                "status_text": "Visual Reply generating...",
                "detail_text": "Preparing story image..." if keep_current_image else prompt_text,
                "image_path": "",
                "caption": prompt_text,
                "request_id": request_id,
                "keep_current_image": bool(keep_current_image),
                "updated_at": time.time(),
            }
        )
        published_loading_state = True
    print(f"🖼️ [VisualReply] Requested: {prompt_text}")

    try:
        client_kwargs = {"api_key": _visual_reply_api_key() or "visual-reply"}
        base_url = _visual_reply_base_url()
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)
        model_name = _visual_reply_model_name()
        effective_prompt = _apply_visual_reply_style_anchor(prompt_text)
        request_kwargs = {
            "model": model_name,
            "prompt": effective_prompt,
        }
        if _visual_reply_provider() == "xai":
            request_kwargs["response_format"] = "b64_json"
            request_kwargs["extra_body"] = _visual_reply_xai_extra_body()
        else:
            request_kwargs["size"] = _visual_reply_image_size()
        response = client.images.generate(**request_kwargs)
        output_path = VISUAL_REPLY_OUTPUT_DIR / request_id
        output_path = _write_visual_reply_image_from_response(response, output_path)
        current_request_id = str(getattr(shared_state, "current_visual_reply_data", {}).get("request_id", "") or "")
        if published_loading_state and current_request_id and current_request_id != request_id:
            return True
        shared_state.set_current_visual_reply_data(
            {
                "status": "ready",
                "status_text": "Visual Reply",
                "detail_text": source_text[:240],
                "image_path": str(output_path),
                "caption": prompt_text,
                "request_id": request_id,
                "updated_at": time.time(),
            }
        )
        print(f"🖼️ [VisualReply] Ready: {output_path}")
        return True
    except Exception as exc:
        current_request_id = str(getattr(shared_state, "current_visual_reply_data", {}).get("request_id", "") or "")
        if published_loading_state and current_request_id and current_request_id != request_id:
            return False
        detail = str(exc) or repr(exc)
        shared_state.set_current_visual_reply_data(
            {
                "status": "error",
                "status_text": "Visual Reply failed",
                "detail_text": detail,
                "image_path": "",
                "caption": prompt_text,
                "request_id": request_id,
                "updated_at": time.time(),
            }
        )
        print(f"⚠️ [VisualReply] Generation failed: {detail}")
        return False


def _story_visual_reply_style_guide_from_text(story_text: str, continuity_strength: float = 0.8) -> str:
    story_prompt = sanitize_assistant_text_for_speech(story_text, preserve_emotion_tags=False)
    story_prompt = _normalize_visual_reply_prompt_text(story_prompt)
    strength = max(0.0, min(1.0, float(continuity_strength or 0.0)))
    continuity_parts = []
    if strength >= 0.05:
        continuity_parts.append("Keep a consistent visual language across this entire story sequence.")
    if strength >= 0.2:
        continuity_parts.append("Treat recurring people and places as the same cast and world from image to image.")
    if strength >= 0.4:
        continuity_parts.append("Keep recurring characters with the same face, hair, body type, age, outfit silhouette, and key accessories unless the story explicitly changes them.")
    if strength >= 0.6:
        continuity_parts.append("Keep recurring locations recognizable with the same architecture, props, palette, weather, and lighting direction unless the story explicitly changes them.")
    if strength >= 0.8:
        continuity_parts.append("Do not redesign characters, reset outfits, or relocate scenes between shots unless the story explicitly says that a change happened.")
    if strength >= 0.95:
        continuity_parts.append("Use each new image like the next shot from the same film, preserving continuity as aggressively as possible.")
    continuity = " ".join(continuity_parts).strip()
    if not story_prompt:
        return continuity
    if len(story_prompt) > 420:
        story_prompt = story_prompt[:420].rstrip(" \t\r\n,;:.-")
    if not continuity:
        return f"Story context: {story_prompt}"
    return f"{continuity} Story context: {story_prompt}"


def _story_visual_reply_prompt_from_text(prompt_text: str, emotion: str = "", story_style_guide: str = "") -> str:
    prompt = sanitize_assistant_text_for_speech(prompt_text, preserve_emotion_tags=False)
    prompt = _normalize_visual_reply_prompt_text(prompt)
    if not prompt:
        return ""
    prefix = "Story illustration"
    mood = str(emotion or "").strip().lower()
    if mood and mood != "neutral":
        prefix = f"{prefix}, {mood} mood"
    prompt = f"{prefix}: {prompt}"
    guide = str(story_style_guide or "").strip()
    if guide:
        prompt = f"{prompt}. {guide}"
    style_suffix = _visual_reply_story_theme_suffix()
    if style_suffix:
        prompt = f"{prompt}. {style_suffix}"
    if len(prompt) > 760:
        prompt = prompt[:760].rstrip(" \t\r\n,;:.-")
    return prompt


def _visual_reply_model_name():
    return _visual_reply_runtime.model_name()


def _visual_reply_image_size():
    return _visual_reply_runtime.image_size()


def _visual_reply_xai_extra_body():
    return _visual_reply_runtime.xai_extra_body()


def _next_visual_reply_request_id():
    global _visual_reply_request_counter
    with _visual_reply_request_lock:
        _visual_reply_request_counter += 1
        return f"visual_{int(time.time())}_{_visual_reply_request_counter}"


def _normalize_visual_reply_prompt_text(prompt_text: str) -> str:
    return visual_reply_runtime.normalize_prompt_text(prompt_text)


def _strip_visual_reply_tail(text: str):
    return visual_reply_runtime.strip_visual_reply_tail(text)


def extract_visual_reply_prompt(text: str):
    return visual_reply_runtime.extract_visual_reply_prompt(text)


def _visual_reply_generation_instruction():
    if not _automatic_visual_reply_generation_allowed():
        return ""
    return (
        "Optional visual reply capability: when a generated image would meaningfully help, "
        "append exactly one tag at the end of your reply in this form: "
        "[visualize: concise image prompt]. Keep the prompt concrete and under 180 characters. "
        "Use this sparingly, and still provide the normal text reply."
    )


def _sensory_feedback_sources():
    raw_value = RUNTIME_CONFIG.get("sensory_feedback_source", "off")
    if isinstance(raw_value, (list, tuple, set)):
        tokens = [str(item or "").strip().lower() for item in list(raw_value or [])]
    else:
        text_value = str(raw_value or "off").strip().lower()
        tokens = [part.strip().lower() for part in text_value.split(",")]
    normalized = []
    seen = set()
    for token in tokens:
        if not token or token == "off" or token in seen:
            continue
        if sensory.get_provider(token) is None:
            continue
        normalized.append(token)
        seen.add(token)
    return normalized


def _sensory_feedback_source():
    sources = _sensory_feedback_sources()
    return sources[0] if sources else "off"


def _sensory_feedback_enabled():
    return bool(_sensory_feedback_sources())


def _sensory_feedback_interval_seconds():
    return max(2.0, float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0))


def _sensory_feedback_provider():
    source = _sensory_feedback_source()
    return None if source == "off" else sensory.get_provider(source)


def _sensory_feedback_instruction():
    instructions = []
    seen = set()
    for source in _sensory_feedback_sources():
        provider = sensory.get_provider(source)
        instruction = str(getattr(provider, "instruction", "") or "").strip() if provider is not None else ""
        if not instruction or instruction in seen:
            continue
        instructions.append(instruction)
        seen.add(instruction)
    if instructions:
        return "\n\n".join(instructions)
    return (
        "Optional hidden sensory feedback may be attached as hidden ambient context messages. "
        "Treat them as background situational awareness, not as direct user requests. "
        "Only mention what you infer from them if it is genuinely relevant to the conversation."
    ) if _sensory_feedback_enabled() else ""


def _sensory_feedback_capture_screen(output_path: Path):
    try:
        from PIL import ImageGrab
        image = ImageGrab.grab(all_screens=True)
    except Exception as exc:
        raise RuntimeError(f"Screen capture failed: {exc}") from exc
    image = image.convert("RGB")
    image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=85, optimize=True)
    return output_path


def _sensory_feedback_capture_webcam(output_path: Path):
    try:
        import cv2
    except Exception as exc:
        raise RuntimeError(f"OpenCV is unavailable for webcam capture: {exc}") from exc
    cap = None
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == "nt" else 0)
        if not cap or not cap.isOpened():
            raise RuntimeError("Webcam could not be opened.")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("Webcam returned no frame.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), frame)
        return output_path
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass


def _capture_screen_sensory_snapshot(context=None):
    timestamp = int(time.time() * 1000)
    output_root = Path(str((context or {}).get("output_dir") or SENSORY_FEEDBACK_OUTPUT_DIR))
    output_path = output_root / f"screen_{timestamp}.jpg"
    output_path = _sensory_feedback_capture_screen(output_path)
    return {
        "captured_at": time.time(),
        "image_path": str(output_path),
        "source": "screen",
        "content_text": "Hidden sensory feedback only, not a user request. Source: screen. Use as ambient context only if relevant.",
    }


def _capture_webcam_sensory_snapshot(context=None):
    timestamp = int(time.time() * 1000)
    output_root = Path(str((context or {}).get("output_dir") or SENSORY_FEEDBACK_OUTPUT_DIR))
    output_path = output_root / f"webcam_{timestamp}.jpg"
    output_path = _sensory_feedback_capture_webcam(output_path)
    return {
        "captured_at": time.time(),
        "image_path": str(output_path),
        "source": "webcam",
        "content_text": "Hidden sensory feedback only, not a user request. Source: webcam. Use as ambient context only if relevant.",
    }


def _register_builtin_sensory_providers():
    sensory.register_provider(
        provider_id="screen",
        label="Screen",
        instruction=(
            "Optional hidden screen sensory feedback may be attached as a hidden screenshot message. "
            "Treat it as background situational awareness, not as a direct user request. "
            "Only mention what you infer from it if it is genuinely relevant to the conversation."
        ),
        description="Captures the user's monitor as hidden ambient context.",
        order=100,
        capture_handler=_capture_screen_sensory_snapshot,
        metadata={"builtin": True, "kind": "image", "ping_payload": [{"field": "image", "description": "hidden screenshot attachment sent to the model"}, {"field": "text prefix", "description": "source label and capture timestamp framing the screenshot as ambient context"}], "pong_influences": [{"field": "attention", "description": "application or task focus inferred from the screen"}, {"field": "summary", "description": "meaningful screen-context change worth retaining"}, {"field": "should_speak", "description": "optional proactive reaction when visible task context justifies interruption"}, {"field": "should_generate_image", "description": "optional image generation when the screen clearly shows visual intent"}, {"field": "visual_candidate", "description": "clean image prompt distilled from screen intent"}], "tag_subscriptions": [], "pingpong_prompt": """When screen input is present, you may infer the user's current application, task focus, and likely intent from visible windows, layouts, or readable text. Stay concise and avoid overclaiming unreadable details.

Use screen input for should_generate_image when the screen clearly shows the user composing an image request, browsing visual inspiration, describing a scene to depict, or otherwise doing something where generating an image would add obvious value.
- If you set should_generate_image=true from screen context, provide a visual_candidate that turns the screen-derived idea into a clean image prompt instead of repeating raw UI text verbatim.
- Good screen-derived visual_candidate examples: "NC self-portrait at a glowing workstation, intimate digital companion mood" or "storybook ragdoll cat lounging by a sunlit window, soft painterly style".
- If the screen only shows ordinary work with no strong visual intent, prefer should_generate_image=false.

Use screen input for should_speak when the user appears to be actively preparing, searching, or editing something that justifies a gentle proactive reaction or question.
- If the screen cue is weak or ambiguous, prefer should_speak=false."""},
    )
    sensory.register_provider(
        provider_id="webcam",
        label="Webcam",
        instruction=(
            "Optional hidden webcam sensory feedback may be attached as a hidden image message. "
            "Treat it as background situational awareness, not as a direct user request. "
            "Only mention what you infer from it if it is genuinely relevant to the conversation."
        ),
        description="Captures a webcam snapshot as hidden ambient context.",
        order=110,
        capture_handler=_capture_webcam_sensory_snapshot,
        metadata={"builtin": True, "kind": "image", "ping_payload": [{"field": "image", "description": "hidden webcam snapshot attachment sent to the model"}, {"field": "text prefix", "description": "source label and capture timestamp framing the webcam snapshot as ambient context"}], "pong_influences": [{"field": "attention", "description": "gaze, pose, gesture, or presence cue"}, {"field": "summary", "description": "concise retained description of a meaningful observed moment"}, {"field": "should_speak", "description": "gesture-driven or expression-driven proactive interjection"}, {"field": "should_generate_image", "description": "rare visual generation when the observed moment is especially striking"}, {"field": "visual_candidate", "description": "image prompt inspired by the observed moment"}], "tag_subscriptions": [], "pingpong_prompt": """When webcam input is present, you may infer posture, gestures, gaze direction, visible props, and coarse facial expression, but do not claim persistent video continuity beyond the current snapshots.

Use webcam input especially for attention, summary, and gesture-driven should_speak decisions.
- If a visible gesture, expression, or posture strongly invites an in-character spoken reaction, set should_speak=true and provide a concise proactive_candidate.
- If the webcam only shows normal presence or ambiguous body language, prefer should_speak=false.

Only set should_generate_image=true from webcam input when the visible scene, pose, or moment is visually striking enough that generating an image would add real value. If you do, write visual_candidate as an image prompt inspired by the observed moment, not a literal surveillance description."""},
    )


_register_builtin_sensory_providers()


def _capture_sensory_feedback_snapshot(source=None):
    provider_id = str(source or _sensory_feedback_source() or "off").strip().lower()
    if provider_id == "off":
        return None
    snapshot = sensory.capture_snapshot(
        provider_id,
        {
            "output_dir": str(SENSORY_FEEDBACK_OUTPUT_DIR),
            "runtime_config": dict(RUNTIME_CONFIG),
            "timestamp": time.time(),
            "selected_sources": list(_sensory_feedback_sources()),
        },
    )
    if not isinstance(snapshot, dict):
        return None
    snapshot.setdefault("captured_at", time.time())
    snapshot.setdefault("source", provider_id)
    return snapshot


def _snapshot_has_payload(snapshot):
    if not isinstance(snapshot, dict):
        return False
    image_path = str(snapshot.get("image_path", "") or "")
    message = snapshot.get("message")
    content = snapshot.get("content")
    return bool((image_path and os.path.isfile(image_path)) or message or content)


def _maybe_refresh_sensory_feedback_snapshots(force=False):
    if not _sensory_feedback_enabled():
        return []
    with _sensory_feedback_lock:
        now = time.time()
        interval_seconds = _sensory_feedback_interval_seconds()
        active_sources = list(_sensory_feedback_sources())
        snapshots = []
        for source in active_sources:
            current_snapshot = dict(_sensory_feedback_state.get(source) or {})
            current_at = float(current_snapshot.get("captured_at", 0.0) or 0.0)
            has_current_payload = _snapshot_has_payload(current_snapshot)
            if (not force) and has_current_payload and (now - current_at) < interval_seconds:
                snapshots.append(current_snapshot)
                continue
            try:
                snapshot = _capture_sensory_feedback_snapshot(source)
                if snapshot and _snapshot_has_payload(snapshot):
                    _sensory_feedback_state[source] = dict(snapshot)
                    print(
                        f"👁️ [Sensory] Captured {snapshot.get('source')} feedback "
                        f"({int(max(0.0, now - current_at) * 1000)} ms since previous)."
                    )
                    snapshots.append(dict(snapshot))
                elif has_current_payload:
                    snapshots.append(current_snapshot)
            except Exception as exc:
                print(f"⚠️ [Sensory] Capture failed for {source}: {exc}")
                if has_current_payload:
                    snapshots.append(current_snapshot)
        for stale_source in list(_sensory_feedback_state.keys()):
            if stale_source not in active_sources:
                _sensory_feedback_state.pop(stale_source, None)
        return [dict(snapshot) for snapshot in snapshots if _snapshot_has_payload(snapshot)]


def _data_url_for_local_image(image_path: str):
    path = str(image_path or "").strip()
    if not path or not os.path.isfile(path):
        return ""
    mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _infer_model_supports_images(model_name):
    value = str(model_name or "").strip().lower()
    if not value:
        return False
    positive_fragments = (
        "vision", "image", "multimodal", "vl", "llava", "bakllava", "moondream", "pixtral",
        "minicpm-v", "internvl", "phi-3.5-vision", "phi-4-multimodal", "gemma-3", "gpt-4o",
        "gpt-4.1", "omni", "qwen/qwen3.5", "qwen3.5", "qwen2-vl", "qwen2.5-vl", "qvq",
    )
    negative_fragments = (
        "embedding", "rerank", "whisper", "tts", "audio", "transcribe", "grok-imagine"
    )
    if any(fragment in value for fragment in negative_fragments):
        return False
    return any(fragment in value for fragment in positive_fragments)


def _current_model_supports_images():
    explicit = RUNTIME_CONFIG.get("model_supports_images", None)
    if explicit is not None:
        return bool(explicit)
    return _infer_model_supports_images(RUNTIME_CONFIG.get("model_name", ""))


def _build_sensory_feedback_message_from_snapshot(snapshot, *, allow_images=True):
    if not isinstance(snapshot, dict):
        return None
    source = str(snapshot.get("source", "sensory") or "sensory")
    captured_at = float(snapshot.get("captured_at", 0.0) or 0.0)
    timestamp_text = time.strftime("%H:%M:%S", time.localtime(captured_at)) if captured_at > 0 else "unknown"
    message = snapshot.get("message")
    if isinstance(message, dict):
        return dict(message)
    content = snapshot.get("content")
    if isinstance(content, list):
        return {
            "role": str(snapshot.get("role", "user") or "user"),
            "content": list(content),
        }
    if isinstance(content, str) and content.strip():
        metadata = snapshot.get("metadata")
        if isinstance(metadata, dict) and metadata:
            payload = {
                "source": source,
                "captured_at": captured_at,
                "content": str(content),
                "metadata": dict(metadata),
            }
            return {
                "role": str(snapshot.get("role", "user") or "user"),
                "content": json.dumps(payload, ensure_ascii=True),
            }
        return {
            "role": str(snapshot.get("role", "user") or "user"),
            "content": str(content),
        }
    if not allow_images:
        return None
    data_url = _data_url_for_local_image(snapshot.get("image_path", ""))
    if not data_url:
        return None
    text_prefix = str(snapshot.get("content_text", "") or "").strip()
    if not text_prefix:
        text_prefix = (
            f"Hidden sensory feedback only, not a user request. Source: {source}. "
            f"Captured at {timestamp_text}. Use as ambient context only if relevant."
        )
    return {
        "role": str(snapshot.get("role", "user") or "user"),
        "content": [
            {
                "type": "text",
                "text": text_prefix,
            },
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            },
        ],
    }


def _build_sensory_feedback_messages():
    snapshots = _maybe_refresh_sensory_feedback_snapshots(force=False)
    messages = []
    allow_images = _current_model_supports_images()
    for snapshot in snapshots:
        source = str(snapshot.get("source", "sensory") or "sensory")
        captured_at = float(snapshot.get("captured_at", 0.0) or 0.0)
        timestamp_text = time.strftime("%H:%M:%S", time.localtime(captured_at)) if captured_at > 0 else "unknown"
        image_path = str(snapshot.get("image_path", "") or "").strip()
        if image_path and not allow_images:
            print(
                f"⚠️ [Sensory] Skipping hidden {source} image input for model "
                f"{RUNTIME_CONFIG.get('model_name', '')!r} because it does not support image messages."
            )
            continue
        print(
            f"👁️ [Sensory] Injecting hidden {source} input into model request "
            f"(captured {timestamp_text}, path={image_path})."
        )
        message = _build_sensory_feedback_message_from_snapshot(snapshot, allow_images=allow_images)
        if message:
            messages.append(message)
    return messages


def _sensory_pingpong_enabled():
    return _sensory_feedback_enabled() and bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False))


def _sensory_pingpong_history_depth():
    return max(0, int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3))


def _hidden_sensory_proactive_speech_allowed():
    return bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False))


def _hidden_sensory_visual_generation_allowed():
    return _automatic_visual_reply_generation_allowed()


def _automatic_visual_reply_generation_allowed():
    return bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)) and _visual_reply_enabled()


def _normalize_boolish(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _sanitize_hidden_action_text(value, *, limit=220, lower=False):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if lower:
        text = text.lower()
    return text[:limit]


def _derive_hidden_proactive_candidate(summary="", attention="", emotion=""):
    candidate = _sanitize_hidden_action_text(summary, limit=220)
    if candidate:
        return candidate
    cue = _sanitize_hidden_action_text(attention, limit=80)
    if cue:
        return _sanitize_hidden_action_text(f"I noticed the sensory cue: {cue}.", limit=220)
    tone = _sanitize_hidden_action_text(emotion, limit=40, lower=True)
    if tone:
        return _sanitize_hidden_action_text(f"I noticed something worth reacting to and feel {tone} about it.", limit=220)
    return ""


def _derive_hidden_visual_candidate(summary="", attention="", emotion=""):
    candidate = _sanitize_hidden_action_text(summary, limit=220)
    if candidate:
        return candidate
    cue = _sanitize_hidden_action_text(attention, limit=80)
    tone = _sanitize_hidden_action_text(emotion, limit=40, lower=True)
    if cue and tone:
        return _sanitize_hidden_action_text(f"{cue}, {tone} mood", limit=220)
    if cue:
        return _sanitize_hidden_action_text(f"sensory scene focused on {cue}", limit=220)
    if tone:
        return _sanitize_hidden_action_text(f"sensory scene with a {tone} mood", limit=220)
    return ""


def _sanitize_hidden_proactive_request(entry):
    if not isinstance(entry, dict):
        return None
    candidate = _sanitize_hidden_action_text(entry.get("candidate", ""), limit=220)
    if not candidate:
        return None
    summary = _sanitize_hidden_action_text(entry.get("summary", ""), limit=220)
    attention = _sanitize_hidden_action_text(entry.get("attention", ""), limit=80, lower=True)
    source = _sanitize_hidden_action_text(entry.get("source", "sensory"), limit=40, lower=True) or "sensory"
    created_at = float(entry.get("created_at", time.time()) or time.time())
    return {
        "candidate": candidate,
        "summary": summary,
        "attention": attention,
        "source": source,
        "created_at": created_at,
    }


def _queue_hidden_proactive_candidate(candidate, *, summary="", attention="", source="sensory"):
    request = _sanitize_hidden_proactive_request(
        {
            "candidate": candidate,
            "summary": summary,
            "attention": attention,
            "source": source,
            "created_at": time.time(),
        }
    )
    if not request:
        return False
    request_key = "|".join(
        [
            request.get("source", "sensory"),
            request.get("candidate", ""),
            request.get("summary", ""),
            request.get("attention", ""),
        ]
    )
    with sensory_pingpong_lock:
        last_key = str(sensory_hidden_action_state.get("last_proactive_key", "") or "")
        last_at = float(sensory_hidden_action_state.get("last_proactive_at", 0.0) or 0.0)
        if request_key and request_key == last_key and (time.time() - last_at) < 45.0:
            return False
        sensory_hidden_action_state["pending_proactive"] = request
        sensory_hidden_action_state["last_proactive_key"] = request_key
        sensory_hidden_action_state["last_proactive_at"] = time.time()
    print(f"🗣️ [Sensory] Queued proactive candidate: {request.get('candidate')}")
    return True


def _consume_hidden_proactive_candidate():
    with sensory_pingpong_lock:
        request = _sanitize_hidden_proactive_request(sensory_hidden_action_state.get("pending_proactive"))
        sensory_hidden_action_state["pending_proactive"] = None
        sensory_hidden_action_state["active_proactive"] = request
    return request


def _clear_active_hidden_proactive_candidate():
    with sensory_pingpong_lock:
        sensory_hidden_action_state["active_proactive"] = None


def _clear_pending_hidden_proactive_candidate():
    with sensory_pingpong_lock:
        sensory_hidden_action_state["pending_proactive"] = None


def _get_active_hidden_proactive_request():
    with sensory_pingpong_lock:
        return _sanitize_hidden_proactive_request(sensory_hidden_action_state.get("active_proactive"))


def _build_active_hidden_proactive_context_text():
    request = _get_active_hidden_proactive_request()
    if not request:
        return ""
    parts = [
        "A hidden sensory layer believes a proactive spoken reply should happen right now.",
        "Treat this as a targeted sensory-triggered interjection, not a generic continuation.",
        "Stay tightly anchored to the candidate direction below.",
        "Respond in 1-3 short sentences.",
        "Do not introduce unrelated topics, fantasies, roleplay escalation, or new conversational branches.",
        "Do not contradict the sensory cue that triggered this proactive turn.",
        "If you speak, directly acknowledge the cue or react to it naturally in-character.",
        f"Candidate direction: {request.get('candidate', '')}",
    ]
    summary = str(request.get("summary", "") or "").strip()
    attention = str(request.get("attention", "") or "").strip()
    source = str(request.get("source", "sensory") or "sensory").strip()
    if summary:
        parts.append(f"Reason: {summary}")
    if attention:
        parts.append(f"Attention: {attention}")
    if source:
        parts.append(f"Source: {source}")
    return "\n".join(parts)


def _build_active_hidden_proactive_prompt_message():
    request = _get_active_hidden_proactive_request()
    if not request:
        return None
    candidate = str(request.get("candidate", "") or "").strip()
    summary = str(request.get("summary", "") or "").strip()
    attention = str(request.get("attention", "") or "").strip()
    parts = [
        "React now to this hidden sensory cue.",
        "Do not answer the previous visible user message.",
        "Do not continue the earlier topic unless it directly matches the cue.",
        "Keep the reply short and directly about the cue.",
    ]
    if candidate:
        parts.append(f"Cue: {candidate}")
    if summary:
        parts.append(f"Observed change: {summary}")
    if attention:
        parts.append(f"Attention cue: {attention}")
    return {"role": "user", "content": "\n".join(parts)}


def _maybe_trigger_hidden_visual_candidate(prompt, *, summary="", source="sensory"):
    prompt_text = _sanitize_hidden_action_text(prompt, limit=220)
    if not prompt_text:
        return False
    if not _visual_reply_enabled() or not _visual_reply_generation_available():
        return False
    request_key = "|".join([str(source or "sensory").strip().lower() or "sensory", prompt_text, _sanitize_hidden_action_text(summary, limit=120)])
    now = time.time()
    with sensory_pingpong_lock:
        last_key = str(sensory_hidden_action_state.get("last_visual_key", "") or "")
        last_at = float(sensory_hidden_action_state.get("last_visual_at", 0.0) or 0.0)
        if request_key == last_key and (now - last_at) < 45.0:
            return False
        sensory_hidden_action_state["last_visual_key"] = request_key
        sensory_hidden_action_state["last_visual_at"] = now
    print(f"🖼️ [Sensory] Hidden PONG requested visual reply: {prompt_text}")
    return request_visual_reply_generation(prompt_text, source_text=_sanitize_hidden_action_text(summary, limit=220))


def _sanitize_sensory_hidden_event(entry):
    if not isinstance(entry, dict):
        return None
    summary = re.sub(r"\s+", " ", str(entry.get("summary", "") or "")).strip()
    emotion = str(entry.get("emotion", "") or "").strip().lower()
    attention = re.sub(r"\s+", " ", str(entry.get("attention", "") or "")).strip().lower()
    proactive_candidate = re.sub(r"\s+", " ", str(entry.get("proactive_candidate", "") or "")).strip()
    visual_candidate = re.sub(r"\s+", " ", str(entry.get("visual_candidate", "") or "")).strip()
    raw_tags = entry.get("tags", [])
    tags = []
    if isinstance(raw_tags, (list, tuple, set)):
        for item in list(raw_tags):
            tag_text = re.sub(r"\s+", " ", str(item or "")).strip()
            if tag_text and tag_text not in tags:
                tags.append(tag_text[:80])
    should_speak = _normalize_boolish(entry.get("should_speak", False))
    should_generate_image = _normalize_boolish(entry.get("should_generate_image", False))
    source = str(entry.get("source", "sensory") or "sensory").strip().lower() or "sensory"
    created_at = float(entry.get("created_at", time.time()) or time.time())
    if emotion and not is_emotion_tag(emotion):
        emotion = ""
    if not (summary or emotion or attention or proactive_candidate or visual_candidate or should_speak or should_generate_image or tags):
        return None
    return {
        "type": "sensory_pong",
        "hidden": True,
        "source": source,
        "summary": summary[:220],
        "emotion": emotion,
        "attention": attention[:80],
        "proactive_candidate": proactive_candidate[:220],
        "visual_candidate": visual_candidate[:220],
        "should_speak": bool(should_speak),
        "should_generate_image": bool(should_generate_image),
        "tags": tags[:12],
        "created_at": created_at,
    }


def _prune_sensory_hidden_history():
    global sensory_hidden_history
    depth = _sensory_pingpong_history_depth()
    if depth <= 0:
        sensory_hidden_history = []
        return
    sanitized = [item for item in (_sanitize_sensory_hidden_event(entry) for entry in list(sensory_hidden_history or [])) if item]
    sensory_hidden_history = sanitized[-depth:]


def _visible_history_summary_for_sensory(limit=6):
    visible_turns = []
    for item in list(conversation_history or []):
        turn = _sanitize_chat_turn(item)
        if not turn:
            continue
        visible_turns.append(turn)
    if limit > 0:
        visible_turns = visible_turns[-limit:]
    if not visible_turns:
        return ""
    lines = []
    for turn in visible_turns:
        role = str(turn.get("role", "user") or "user").strip().lower()
        label = "Assistant" if role == "assistant" else ("System" if role == "system" else "User")
        content = re.sub(r"\s+", " ", str(turn.get("content", "") or "")).strip()
        if len(content) > 240:
            content = content[:237] + "..."
        if content:
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _build_retained_sensory_context_text():
    _prune_sensory_hidden_history()
    if not sensory_hidden_history:
        return ""
    lines = []
    for entry in list(sensory_hidden_history or []):
        created_at = float(entry.get("created_at", 0.0) or 0.0)
        stamp = time.strftime("%H:%M:%S", time.localtime(created_at)) if created_at > 0 else "unknown"
        source = str(entry.get("source", "sensory") or "sensory")
        summary = str(entry.get("summary", "") or "").strip()
        emotion = str(entry.get("emotion", "") or "").strip()
        attention = str(entry.get("attention", "") or "").strip()
        parts = [f"[{stamp}] {source}"]
        if summary:
            parts.append(summary)
        if emotion:
            parts.append(f"emotion={emotion}")
        if attention:
            parts.append(f"attention={attention}")
        proactive_candidate = str(entry.get("proactive_candidate", "") or "").strip()
        visual_candidate = str(entry.get("visual_candidate", "") or "").strip()
        if proactive_candidate:
            parts.append(f"proactive={proactive_candidate}")
        if visual_candidate:
            parts.append(f"visual={visual_candidate}")
        tags = list(entry.get("tags", []) or [])
        if tags:
            parts.append(f"tags={', '.join([str(tag) for tag in tags[:6]])}")
        lines.append(" | ".join(parts))
    if not lines:
        return ""
    return (
        "Retained hidden sensory events below are ambient internal state, not user messages. "
        "Use them as latent context only when relevant.\n" + "\n".join(f"- {line}" for line in lines)
    )


def _extract_json_object_from_text(text):
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = raw[start:end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _debug_preview_text(text, *, limit=420):
    preview = str(text or "")
    preview = preview.replace("\r", "\\r").replace("\n", "\\n")
    preview = re.sub(r"\s+", " ", preview).strip()
    if len(preview) > limit:
        preview = preview[:limit] + "..."
    return preview


def _repair_common_json_mistakes(text):
    repaired = str(text or "").strip()
    if not repaired:
        return repaired
    # Quote bareword values for string-only sensory keys.
    for key in ("emotion", "attention", "summary", "proactive_candidate", "visual_candidate"):
        repaired = re.sub(
            rf'("{key}"\s*:\s*)([A-Za-z_][A-Za-z0-9_\- ]*)(?=\s*[,}}])',
            lambda m: m.group(1) + '"' + m.group(2).strip().rstrip('"') + '"',
            repaired,
        )
        # Handle a dangling quote after an otherwise bareword token, e.g. screen"
        repaired = re.sub(
            rf'("{key}"\s*:\s*)([A-Za-z_][A-Za-z0-9_\- ]*)"\s*(?=[,}}])',
            lambda m: m.group(1) + '"' + m.group(2).strip() + '"',
            repaired,
        )
    # Remove trailing commas before object close.
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _parse_sensory_pong(payload_text):
    payload = _extract_json_object_from_text(payload_text)
    repaired_payload = None
    if not isinstance(payload, dict):
        repaired_payload = _repair_common_json_mistakes(payload_text)
        if repaired_payload and repaired_payload != str(payload_text or ""):
            payload = _extract_json_object_from_text(repaired_payload)
    if not isinstance(payload, dict):
        return None
    keep_value = _normalize_boolish(payload.get("keep", False))
    emotion = str(payload.get("emotion", "") or "").strip().lower()
    attention = str(payload.get("attention", "") or "").strip().lower()
    summary = re.sub(r"\s+", " ", str(payload.get("summary", "") or "")).strip()
    proactive_candidate = _sanitize_hidden_action_text(payload.get("proactive_candidate", ""), limit=220)
    visual_candidate = _sanitize_hidden_action_text(payload.get("visual_candidate", ""), limit=220)
    should_speak = _normalize_boolish(payload.get("should_speak", False))
    if should_speak and not proactive_candidate:
        proactive_candidate = _derive_hidden_proactive_candidate(summary=summary, attention=attention, emotion=emotion)
    should_generate_image = _normalize_boolish(payload.get("should_generate_image", False))
    if should_generate_image and not visual_candidate:
        visual_candidate = _derive_hidden_visual_candidate(summary=summary, attention=attention, emotion=emotion)
    tags = []
    raw_tags = payload.get("tags", [])
    if isinstance(raw_tags, (list, tuple, set)):
        for item in list(raw_tags):
            tag_text = _sanitize_hidden_action_text(item, limit=80)
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
    if emotion and not is_emotion_tag(emotion):
        emotion = ""
    meaningful = bool(emotion or attention or summary or proactive_candidate or visual_candidate or should_speak or should_generate_image or tags)
    result = {
        "keep": bool(keep_value or meaningful),
        "emotion": emotion,
        "attention": attention,
        "summary": summary[:220],
        "proactive_candidate": proactive_candidate,
        "visual_candidate": visual_candidate,
        "should_speak": bool(should_speak),
        "should_generate_image": bool(should_generate_image),
        "tags": tags[:12],
    }
    if repaired_payload and isinstance(payload, dict):
        result["_repaired_json"] = True
    return result


def _sensory_pingpong_prompt_template():
    prompt = str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", DEFAULT_SENSORY_PINGPONG_PROMPT) or DEFAULT_SENSORY_PINGPONG_PROMPT).strip()
    return prompt or DEFAULT_SENSORY_PINGPONG_PROMPT


def _sensory_pingpong_source_prompt_map():
    payload = RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {})
    if not isinstance(payload, dict):
        return {}
    result = {}
    for key, value in list(payload.items()):
        provider_id = str(key or "").strip().lower()
        if not provider_id:
            continue
        result[provider_id] = str(value or "").strip()
    return result


def _sensory_pingpong_source_prompt_text(source_ids):
    prompt_map = _sensory_pingpong_source_prompt_map()
    fragments = []
    seen = set()
    normalized_source_ids = [str(item or "").strip().lower() for item in list(source_ids or []) if str(item or "").strip()]
    for source_id in normalized_source_ids:
        provider = sensory.get_provider(source_id)
        metadata = dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}
        if metadata.get("prompt_fragment_enabled", True) is not False:
            label = str(getattr(provider, "label", source_id) or source_id)
            fragment = str(prompt_map.get(source_id) or metadata.get("pingpong_prompt") or "").strip()
            if fragment and fragment not in seen:
                seen.add(fragment)
                fragments.append(f"Source prompt for {label}:\n{fragment}")
        for contributor in sensory.list_prompt_contributors(source_id):
            contributor_label = str(getattr(contributor, "label", source_id) or source_id)
            fragment = str(getattr(contributor, "prompt", "") or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            fragments.append(f"Behavior prompt for {contributor_label}:\n{fragment}")
    return "\n\n".join(fragments)

def _compose_sensory_pingpong_prompt(source_ids, emotion_text):
    prompt_template = _sensory_pingpong_prompt_template()
    prompt_text = prompt_template.replace("__EMOTION_LIST__", emotion_text)
    source_prompt_text = _sensory_pingpong_source_prompt_text(source_ids)
    if source_prompt_text:
        return prompt_text + "\n\nEnabled source-specific guidance:\n" + source_prompt_text
    return prompt_text


def _build_sensory_pingpong_messages(snapshots):
    allow_images = _current_model_supports_images()
    ping_messages = [
        message
        for message in (
            _build_sensory_feedback_message_from_snapshot(snapshot, allow_images=allow_images)
            for snapshot in list(snapshots or [])
        )
        if message is not None
    ]
    if not ping_messages:
        return []
    available_emotions = sorted(get_available_emotion_names())
    emotion_text = ", ".join(available_emotions[:48]) if available_emotions else "neutral"
    source_ids = [str((item or {}).get("source", "") or "").strip().lower() for item in list(snapshots or []) if isinstance(item, dict)]
    prompt_text = _compose_sensory_pingpong_prompt(source_ids, emotion_text)
    messages = [
        {
            "role": "system",
            "content": prompt_text,
        }
    ]
    provider_instruction = _sensory_feedback_instruction()
    if provider_instruction:
        messages.append({"role": "system", "content": provider_instruction})
    visible_context = _visible_history_summary_for_sensory(limit=6)
    if visible_context:
        messages.append({
            "role": "system",
            "content": "Recent visible conversation context:\n" + visible_context,
        })
    retained_context = _build_retained_sensory_context_text()
    if retained_context:
        messages.append({"role": "system", "content": retained_context})
    messages.extend(ping_messages)
    return messages


def _apply_sensory_pong_result(result, snapshots):
    global sensory_hidden_history
    if not isinstance(result, dict):
        return False
    emotion = str(result.get("emotion", "") or "").strip().lower()
    attention = str(result.get("attention", "") or "").strip().lower()
    summary = str(result.get("summary", "") or "").strip()
    proactive_candidate = _sanitize_hidden_action_text(result.get("proactive_candidate", ""), limit=220)
    visual_candidate = _sanitize_hidden_action_text(result.get("visual_candidate", ""), limit=220)
    tags = []
    for item in list(result.get("tags", []) or []):
        tag_text = _sanitize_hidden_action_text(item, limit=80)
        if tag_text and tag_text not in tags:
            tags.append(tag_text)
    should_speak = _normalize_boolish(result.get("should_speak", False))
    if should_speak and not proactive_candidate:
        proactive_candidate = _derive_hidden_proactive_candidate(summary=summary, attention=attention, emotion=emotion)
    should_generate_image = _normalize_boolish(result.get("should_generate_image", False))
    if should_generate_image and not visual_candidate:
        visual_candidate = _derive_hidden_visual_candidate(summary=summary, attention=attention, emotion=emotion)
    keep_value = bool(result.get("keep", False))
    snapshot_list = list(snapshots or [])
    snapshot_source = ",".join([str((item or {}).get("source", "sensory") or "sensory") for item in snapshot_list if isinstance(item, dict)]) or "sensory"
    meaningful = bool(emotion or attention or summary or proactive_candidate or visual_candidate or should_speak or should_generate_image or tags)
    debug_parts = []
    if emotion:
        debug_parts.append(f"emotion={emotion}")
    if attention:
        debug_parts.append(f"attention={attention}")
    if summary:
        debug_parts.append(f"summary={summary[:100]}")
    if proactive_candidate:
        debug_parts.append(f"proactive={proactive_candidate[:100]}")
    if visual_candidate:
        debug_parts.append(f"visual={visual_candidate[:100]}")
    if tags:
        debug_parts.append(f"tags={', '.join(tags[:4])}")
    debug_parts.append(f"should_speak={bool(should_speak)}")
    debug_parts.append(f"should_generate_image={bool(should_generate_image)}")
    print(f"🧾 [Sensory] Parsed hidden PONG: {'; '.join(debug_parts) if debug_parts else 'empty'}")
    _publish_addon_runtime_event(
        "sensory.hidden_pong.parsed",
        {
            "source": snapshot_source,
            "snapshots": [dict(item or {}) for item in snapshot_list if isinstance(item, dict)],
            "keep": bool(keep_value),
            "emotion": emotion,
            "attention": attention,
            "summary": summary,
            "proactive_candidate": proactive_candidate,
            "visual_candidate": visual_candidate,
            "should_speak": bool(should_speak),
            "should_generate_image": bool(should_generate_image),
            "tags": list(tags),
            "meaningful": bool(meaningful),
        },
    )
    if not meaningful:
        with sensory_pingpong_lock:
            sensory_pingpong_state["last_cycle_at"] = time.time()
            sensory_pingpong_state["last_source"] = snapshot_source
        return False
    if emotion and isinstance(avatar_gui, AvatarAdapter):
        try:
            avatar_gui.set_emotion(emotion)
            print(f"🎭 [Sensory] Hidden PONG updated avatar emotion -> {emotion}")
            if _is_musetalk_avatar_adapter(avatar_gui) and not audio_playing.is_set() and not microphone_active.is_set():
                try:
                    target_avatar_id = avatar_gui._resolve_avatar_id_for_emotion(emotion) or avatar_gui.default_avatar_id
                    set_musetalk_idle_state_for_avatar(target_avatar_id)
                    print(f"🎭 [Sensory] Applied hidden idle avatar -> {target_avatar_id}")
                except Exception as idle_exc:
                    print(f"⚠️ [Sensory] Could not apply hidden idle avatar for '{emotion}': {idle_exc}")
        except Exception as exc:
            print(f"⚠️ [Sensory] Could not apply hidden emotion '{emotion}': {exc}")
    with sensory_pingpong_lock:
        sensory_pingpong_state["last_cycle_at"] = time.time()
        sensory_pingpong_state["last_source"] = snapshot_source
        sensory_pingpong_state["last_emotion"] = emotion
        sensory_pingpong_state["last_attention"] = attention
        sensory_pingpong_state["last_summary"] = summary
        if keep_value:
            event = _sanitize_sensory_hidden_event({
                "source": snapshot_source,
                "summary": summary,
                "emotion": emotion,
                "attention": attention,
                "proactive_candidate": proactive_candidate,
                "visual_candidate": visual_candidate,
                "should_speak": should_speak,
                "should_generate_image": should_generate_image,
                "tags": list(tags),
                "created_at": time.time(),
            })
            if event:
                previous = _sanitize_sensory_hidden_event(sensory_hidden_history[-1]) if sensory_hidden_history else None
                if not previous or any(
                    previous.get(key) != event.get(key)
                    for key in (
                        "source",
                        "summary",
                        "emotion",
                        "attention",
                        "proactive_candidate",
                        "visual_candidate",
                        "should_speak",
                        "should_generate_image",
                        "tags",
                    )
                ):
                    sensory_hidden_history.append(event)
                    _prune_sensory_hidden_history()
                    sensory_pingpong_state["last_retained_at"] = time.time()
                    print(f"🫧 [Sensory] Retained hidden PONG: {event.get('summary') or event.get('emotion') or event.get('attention')}")
                    _publish_addon_runtime_event("sensory.hidden_pong.retained", {"event": dict(event), "source": snapshot_source})
                    _request_chat_view_rebuild()
    if should_speak and proactive_candidate and _hidden_sensory_proactive_speech_allowed():
        _queue_hidden_proactive_candidate(
            proactive_candidate,
            summary=summary,
            attention=attention,
            source=snapshot_source,
        )
        _publish_addon_runtime_event(
            "sensory.hidden_action.proactive_queued",
            {
                "source": snapshot_source,
                "candidate": proactive_candidate,
                "summary": summary,
                "attention": attention,
                "emotion": emotion,
            },
        )
    if tags:
        _publish_addon_runtime_event(
            "sensory.hidden_action.tags_emitted",
            {
                "source": snapshot_source,
                "tags": list(tags),
                "summary": summary,
                "attention": attention,
                "emotion": emotion,
            },
        )
    if should_speak and proactive_candidate and not _hidden_sensory_proactive_speech_allowed():
        print(
            "🤫 [Sensory] Hidden PONG requested proactive speech, but Vision hidden-speech is disabled "
            f"(Vision hidden-speech={bool(RUNTIME_CONFIG.get('sensory_allow_hidden_proactive_speech', False))})."
        )
    if should_generate_image and visual_candidate and _hidden_sensory_visual_generation_allowed():
        _maybe_trigger_hidden_visual_candidate(
            visual_candidate,
            summary=summary or proactive_candidate,
            source=snapshot_source,
        )
        _publish_addon_runtime_event(
            "sensory.hidden_action.visual_requested",
            {
                "source": snapshot_source,
                "candidate": visual_candidate,
                "summary": summary or proactive_candidate,
                "attention": attention,
                "emotion": emotion,
            },
        )
    if should_generate_image and visual_candidate and not _hidden_sensory_visual_generation_allowed():
        print("🖼️ [Sensory] Hidden PONG requested visual generation, but Vision policy currently blocks auto-generation.")
    return True


def run_hidden_sensory_pingpong_cycle(force=False):
    if not _sensory_pingpong_enabled():
        return False
    if stop_flag.is_set() or bool(RUNTIME_CONFIG.get("offline_replay_only", False)):
        return False
    snapshots = _maybe_refresh_sensory_feedback_snapshots(force=bool(force))
    if not snapshots:
        return False
    sources = [str((item or {}).get("source", "sensory") or "sensory") for item in snapshots if isinstance(item, dict)]
    _publish_addon_runtime_event("sensory.hidden_ping", {"snapshots": [dict(item or {}) for item in snapshots if isinstance(item, dict)], "sources": list(sources)})
    messages = _build_sensory_pingpong_messages(snapshots)
    if not messages:
        return False
    source_text = ", ".join(sources) if sources else "sensory"
    print(f"📡 [Sensory] Hidden PING from {source_text}...")
    _llm_request_active.set()
    try:
        payload_text = _chat_completion_create(
            {
                "model": RUNTIME_CONFIG["model_name"],
                "messages": messages,
                "temperature": 0.2,
                "top_p": min(0.8, float(RUNTIME_CONFIG.get("top_p", 0.8) or 0.8)),
                "max_tokens": 220,
            },
            {
                "top_k": int(RUNTIME_CONFIG.get("top_k", 40) or 40),
                "min_p": float(RUNTIME_CONFIG.get("min_p", 0.05) or 0.05),
                "repeat_penalty": float(RUNTIME_CONFIG.get("repeat_penalty", 1.1) or 1.1),
            },
        )
    except Exception as exc:
        print(f"⚠️ [Sensory] Hidden PONG failed: {exc}")
        return False
    finally:
        _llm_request_active.clear()
    result = _parse_sensory_pong(payload_text)
    if not result:
        print("⚠️ [Sensory] Hidden PONG was not valid JSON; ignoring.")
        raw_preview = _debug_preview_text(payload_text)
        if raw_preview:
            print(f"🧾 [Sensory] Raw hidden PONG preview: {raw_preview}")
        return False
    if bool(result.pop("_repaired_json", False)):
        print("🛠️ [Sensory] Repaired near-JSON hidden PONG automatically.")
    return _apply_sensory_pong_result(result, snapshots)
def _visual_reply_item_value(item, key):
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _visual_reply_image_format_and_extension(raw_bytes: bytes):
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            fmt = str(image.format or "").strip().lower()
    except Exception:
        fmt = ""
    extension = {
        "jpeg": "jpg",
        "jpg": "jpg",
        "png": "png",
        "webp": "webp",
        "bmp": "bmp",
    }.get(fmt, "png")
    return fmt, extension


def _visual_reply_extension_for_bytes(raw_bytes: bytes) -> str:
    _, extension = _visual_reply_image_format_and_extension(raw_bytes)
    return extension


def _write_visual_reply_caption_comment(image: Image.Image, output_path: Path, prompt_text: str, fmt: str):
    prompt = str(prompt_text or "").strip()
    save_kwargs = {}
    normalized_fmt = str(fmt or "").strip().lower()
    if normalized_fmt == "png":
        pnginfo = PngImagePlugin.PngInfo()
        if prompt:
            pnginfo.add_text("Comment", prompt)
        save_kwargs["pnginfo"] = pnginfo
        save_kwargs["format"] = "PNG"
    elif normalized_fmt in {"jpeg", "jpg"}:
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        if prompt:
            save_kwargs["comment"] = prompt.encode("utf-8", "replace")
        save_kwargs["format"] = "JPEG"
        save_kwargs["quality"] = 95
        save_kwargs["optimize"] = True
    elif normalized_fmt == "webp":
        save_kwargs["format"] = "WEBP"
        if prompt:
            save_kwargs["comment"] = prompt.encode("utf-8", "replace")
    elif normalized_fmt == "bmp":
        save_kwargs["format"] = "BMP"
    else:
        save_kwargs["format"] = image.format or "PNG"
    image.save(output_path, **save_kwargs)
    return output_path


def _write_visual_reply_image_from_response(response, output_base_path: Path):
    data_items = getattr(response, "data", None)
    if data_items is None and isinstance(response, dict):
        data_items = response.get("data")
    if not data_items:
        raise RuntimeError("Image API returned no image data.")
    first_item = data_items[0]
    b64_payload = _visual_reply_item_value(first_item, "b64_json") or _visual_reply_item_value(first_item, "base64")
    image_url = _visual_reply_item_value(first_item, "url")
    prompt_text = ""
    try:
        prompt_text = str(getattr(shared_state, "current_visual_reply_data", {}).get("caption", "") or "").strip()
    except Exception:
        prompt_text = ""
    output_base_path.parent.mkdir(parents=True, exist_ok=True)
    if b64_payload:
        raw_bytes = base64.b64decode(b64_payload)
        fmt, extension = _visual_reply_image_format_and_extension(raw_bytes)
        output_path = output_base_path.with_suffix(f".{extension}")
        with Image.open(io.BytesIO(raw_bytes)) as image:
            image.load()
            _write_visual_reply_caption_comment(image, output_path, prompt_text, fmt)
        return output_path
    if image_url:
        with urllib.request.urlopen(str(image_url)) as response_stream:
            raw_bytes = response_stream.read()
        fmt, extension = _visual_reply_image_format_and_extension(raw_bytes)
        output_path = output_base_path.with_suffix(f".{extension}")
        with Image.open(io.BytesIO(raw_bytes)) as image:
            image.load()
            _write_visual_reply_caption_comment(image, output_path, prompt_text, fmt)
        return output_path
    raise RuntimeError("Image API response did not include b64_json or url.")


def request_visual_reply_generation(prompt: str, *, source_text: str = "", keep_current_image: bool = False):
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return False
    if not _visual_reply_enabled():
        return False
    def worker():
        _perform_visual_reply_generation(
            prompt_text,
            source_text=source_text,
            keep_current_image=keep_current_image,
        )

    threading.Thread(target=worker, daemon=True).start()
    return True


def finalize_assistant_reply(raw_text: str):
    cleaned_text, visual_prompt = extract_visual_reply_prompt(raw_text)
    cleaned_text = str(cleaned_text or "").strip()
    if visual_prompt and _automatic_visual_reply_generation_allowed():
        request_visual_reply_generation(visual_prompt, source_text=cleaned_text)
    return cleaned_text


def parse_text_segments(text):
    return text_tags.parse_text_segments(text, get_available_emotion_names())


def get_last_emotion_tag(text):
    return text_tags.get_last_emotion_tag(text, get_available_emotion_names())


StreamingReplyState = streaming_text.StreamingReplyState


class StreamingChunkAssembler(streaming_text.StreamingChunkAssembler):
    def __init__(self, target_chars, max_chars):
        # Engine keeps the old constructor, while the cut-point logic lives in core.streaming_text.
        super().__init__(
            target_chars,
            max_chars,
            min_chunk_size=MIN_CHUNK_SIZE,
            config_getter=lambda key, default=None: RUNTIME_CONFIG.get(key, default),
            available_emotion_tags_getter=get_available_emotion_tags,
            last_emotion_getter=get_last_emotion_tag,
            control_prefix_checker=_looks_like_control_tag_prefix,
            visual_prefix_checker=_looks_like_visual_reply_tag_prefix,
            clock=time.time,
        )


def coalesce_musetalk_leading_segments(segments):
    if not segments:
        return []
    normalized = [(emotion, (segment or "").strip()) for emotion, segment in segments if (segment or "").strip()]
    if len(normalized) < 2:
        return normalized
    first_emotion, first_text = normalized[0]
    if len(first_text) >= MUSE_MIN_LEADING_SEGMENT_CHARS:
        return normalized

    second_emotion, second_text = normalized[1]
    # Do not "optimize away" a real emotion transition just because the
    # opening segment is short. That would cause inputs like:
    # "... route—[shy] Let's go ..."
    # to keep the first segment's emotion and effectively swallow [shy].
    if str(first_emotion or "").strip().lower() != str(second_emotion or "").strip().lower():
        return normalized

    merged_text = f"{first_text} {second_text}".strip()
    merged_segments = [(first_emotion, merged_text)]
    merged_segments.extend(normalized[2:])
    return merged_segments


def get_stream_chunk_limits():
    if RUNTIME_CONFIG.get("avatar_mode", "vseeface") == "musetalk":
        return (
            int(RUNTIME_CONFIG.get("stream_chunk_target_chars", 85) or 85),
            int(RUNTIME_CONFIG.get("stream_chunk_max_chars", 170) or 170),
        )
    return (
        int(RUNTIME_CONFIG.get("chunk_target_chars", 90) or 90),
        int(RUNTIME_CONFIG.get("chunk_max_chars", 180) or 180),
    )


def get_text_chunk_limits():
    if RUNTIME_CONFIG.get("avatar_mode", "vseeface") == "musetalk":
        return (
            int(RUNTIME_CONFIG.get("musetalk_chunk_target_chars", MUSE_TARGET_CHARS_PER_CHUNK) or MUSE_TARGET_CHARS_PER_CHUNK),
            int(RUNTIME_CONFIG.get("musetalk_chunk_max_chars", MUSE_MAX_CHARS_PER_CHUNK) or MUSE_MAX_CHARS_PER_CHUNK),
        )
    return (
        int(RUNTIME_CONFIG.get("chunk_target_chars", TARGET_CHARS_PER_CHUNK) or TARGET_CHARS_PER_CHUNK),
        int(RUNTIME_CONFIG.get("chunk_max_chars", MAX_CHARS_PER_CHUNK) or MAX_CHARS_PER_CHUNK),
    )


def clear_avatar_stream_state():
    shared_state.current_expression_data = {"names": [], "frames": []}
    shared_state.reset_musetalk_pipeline_data()
    shared_state.set_current_musetalk_frame_data({
        "frame_paths": [],
        "frame_dir": "",
        "fps": int(RUNTIME_CONFIG.get("musetalk_fps", 24) or 24),
        "sync_time": 0.0,
        "duration_seconds": 0.0,
        "expected_frame_count": 0,
        "trim_start_frames": 0,
        "chunk_id": None,
        "text": "",
        "status": "idle",
        "loop": False,
        "start_index": 0,
        "avatar_id": None,
    })


def _get_gpu_vram_snapshot():
    if not torch.cuda.is_available():
        return None
    try:
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        allocated_bytes = torch.cuda.memory_allocated()
        reserved_bytes = torch.cuda.memory_reserved()
        return {
            "free_gib": float(free_bytes) / (1024 ** 3),
            "total_gib": float(total_bytes) / (1024 ** 3),
            "used_gib": float(total_bytes - free_bytes) / (1024 ** 3),
            "allocated_gib": float(allocated_bytes) / (1024 ** 3),
            "reserved_gib": float(reserved_bytes) / (1024 ** 3),
        }
    except Exception:
        return None


def _count_rendered_chunk_dirs():
    runtime_root = os.path.abspath(os.path.join("MuseTalk", "runtime", "rendered_chunks"))
    try:
        return sum(
            1 for name in os.listdir(runtime_root)
            if os.path.isdir(os.path.join(runtime_root, name))
        )
    except Exception:
        return None


def log_musetalk_memory_checkpoint(label, chunk_id=None, extra=None):
    if not MUSE_DIAGNOSTIC_LOGGING:
        return
    snapshot = _get_gpu_vram_snapshot()
    state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
    rendered_dir_count = _count_rendered_chunk_dirs()
    parts = [f"🧠 [MuseTalkVRAM] {label}"]
    if chunk_id:
        parts.append(f"chunk={chunk_id}")
    if snapshot:
        parts.append(
            "gpu_used={:.2f}GiB free={:.2f}GiB alloc={:.2f}GiB reserved={:.2f}GiB total={:.2f}GiB".format(
                float(snapshot.get("used_gib", 0.0) or 0.0),
                float(snapshot.get("free_gib", 0.0) or 0.0),
                float(snapshot.get("allocated_gib", 0.0) or 0.0),
                float(snapshot.get("reserved_gib", 0.0) or 0.0),
                float(snapshot.get("total_gib", 0.0) or 0.0),
            )
        )
    else:
        parts.append("gpu_vram=unavailable")
    parts.append(f"state_chunk={state.get('chunk_id')}")
    parts.append(f"status={state.get('status')}")
    parts.append(f"frame_count={int(state.get('frame_count', 0) or 0)}")
    parts.append(f"frame_paths={len(state.get('frame_paths', []) or [])}")
    parts.append(f"preview_source={state.get('preview_source_index')}")
    parts.append(f"preview_cache={state.get('preview_cache_entries')}")
    parts.append(f"preview_preload_pending={state.get('preview_preload_pending')}")
    if rendered_dir_count is not None:
        parts.append(f"rendered_dirs={rendered_dir_count}")
    if extra:
        for key, value in dict(extra).items():
            parts.append(f"{key}={value}")
    message = " ".join(parts)
    shared_state.append_musetalk_preview_log(message)
    print(message)


def set_musetalk_idle_state():
    if not _is_musetalk_avatar_adapter(avatar_gui):
        clear_avatar_stream_state()
        return

    idle_payload = avatar_gui.get_idle_payload()
    if not idle_payload:
        clear_avatar_stream_state()
        return

    shared_state.current_expression_data = {"names": [], "frames": []}
    shared_state.set_current_musetalk_frame_data(idle_payload)
    prime_musetalk_preview_frame(idle_payload)
    schedule_musetalk_runtime_cleanup()


def set_musetalk_idle_state_for_avatar(avatar_id):
    if not _is_musetalk_avatar_adapter(avatar_gui):
        clear_avatar_stream_state()
        return

    target_avatar_id = str(avatar_id or "").strip() or str(getattr(avatar_gui, "default_avatar_id", "") or "").strip()
    current_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
    current_avatar_id = str(current_state.get("avatar_id", "") or "").strip()
    current_status = str(current_state.get("status", "") or "").strip().lower()
    current_frame_paths = list(current_state.get("frame_paths", []) or [])
    if current_status == "idle" and current_avatar_id == target_avatar_id and current_frame_paths:
        return

    idle_payload = avatar_gui.get_idle_payload(avatar_id=target_avatar_id)
    if not idle_payload:
        clear_avatar_stream_state()
        return

    shared_state.current_expression_data = {"names": [], "frames": []}
    shared_state.set_current_musetalk_frame_data(idle_payload)
    prime_musetalk_preview_frame(idle_payload)
    schedule_musetalk_runtime_cleanup()


def build_musetalk_idle_payload_from_state(advance_to_next_frame=True):
    if not _is_musetalk_avatar_adapter(avatar_gui):
        return None

    current_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
    builder = getattr(avatar_gui, "build_idle_payload_from_state", None)
    if not callable(builder):
        return None
    return builder(current_state=current_state, advance_to_next_frame=advance_to_next_frame)


def transition_musetalk_to_local_idle(advance_to_next_frame=True):
    idle_payload = build_musetalk_idle_payload_from_state(advance_to_next_frame=advance_to_next_frame)
    if idle_payload:
        shared_state.current_expression_data = {"names": [], "frames": []}
        shared_state.set_current_musetalk_frame_data(idle_payload)
        prime_musetalk_preview_frame(idle_payload)
        schedule_musetalk_runtime_cleanup()
        return
    set_musetalk_idle_state()


def play_musetalk_avatar_transition(from_avatar_id, to_avatar_id):
    if not _is_musetalk_avatar_adapter(avatar_gui):
        return 0.0

    builder = getattr(avatar_gui, "build_transition_payload", None)
    if not callable(builder):
        return 0.0

    transition = builder(from_avatar_id, to_avatar_id)
    if not transition:
        return 0.0

    payload = dict(transition.get("payload") or {})
    duration_seconds = float(transition.get("duration_seconds", payload.get("duration_seconds", 0.0)) or 0.0)
    transition_id = payload.get("chunk_id")
    shared_state.current_expression_data = {"names": [], "frames": []}
    shared_state.set_current_musetalk_frame_data(payload)
    prime_musetalk_preview_frame(shared_state.current_musetalk_frame_data)

    def _finish_transition():
        time.sleep(duration_seconds)
        current_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
        if current_state.get("chunk_id") != transition_id or stop_flag.is_set():
            return
        set_musetalk_idle_state_for_avatar(to_avatar_id)

    threading.Thread(target=_finish_transition, daemon=True).start()
    return duration_seconds


def maybe_transition_musetalk_avatar_back_to_default(current_avatar_id):
    if not _is_musetalk_avatar_adapter(avatar_gui):
        return False
    current_avatar_id = str(current_avatar_id or "").strip()
    if not current_avatar_id or current_avatar_id == avatar_gui.default_avatar_id:
        return False
    return play_musetalk_avatar_transition(current_avatar_id, avatar_gui.default_avatar_id) > 0


def get_musetalk_avatar_pack_catalog():
    packs = discover_avatar_packs(
        default_avatar_id=str(RUNTIME_CONFIG.get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
        legacy_map=MUSE_EMOTION_AVATAR_MAP,
        legacy_transitions=MUSE_AVATAR_TRANSITIONS,
        include_legacy=False,
        include_standalone=False,
    )
    catalog = []
    for pack_id, pack in packs.items():
        catalog.append(
            {
                "id": pack_id,
                "display_name": str(pack.display_name or pack_id),
                "default_avatar_id": str(pack.default_avatar_id or "default_avatar"),
                "default_variant": str(pack.default_variant or "default"),
                "source": str(pack.source or "manifest"),
                "variant_count": len(pack.variants or {}),
            }
        )
    return catalog


def apply_musetalk_avatar_pack_selection(pack_id):
    requested_pack_id = str(pack_id or "").strip()
    if not requested_pack_id:
        return str(RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
    try:
        selected = get_avatar_pack(
            default_avatar_id=str(RUNTIME_CONFIG.get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
            requested_pack_id=requested_pack_id,
            legacy_map=MUSE_EMOTION_AVATAR_MAP,
            legacy_transitions=MUSE_AVATAR_TRANSITIONS,
            include_legacy=False,
            include_standalone=False,
        )
    except LookupError:
        return str(RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
    update_runtime_config("musetalk_avatar_pack_id", selected.pack_id)
    invalidate_available_emotion_names()
    if _is_musetalk_avatar_adapter(avatar_gui):
        avatar_gui.select_avatar_pack(selected.pack_id)
        if not audio_playing.is_set() and not stop_flag.is_set():
            try:
                set_musetalk_idle_state_for_avatar(avatar_gui.default_avatar_id)
            except Exception:
                pass
    return selected.pack_id


def loop_current_musetalk_state():
    current_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
    frame_paths = current_state.get("frame_paths", [])
    frame_dir = current_state.get("frame_dir", "")
    if not frame_paths and not frame_dir:
        clear_avatar_stream_state()
        return

    shared_state.current_expression_data = {"names": [], "frames": []}
    shared_state.set_current_musetalk_frame_data({
        "frame_paths": frame_paths,
        "frame_dir": frame_dir,
        "fps": int(current_state.get("fps", RUNTIME_CONFIG.get("musetalk_fps", 24)) or 24),
        "sync_time": time.time(),
        "duration_seconds": 0.0,
        "chunk_id": current_state.get("chunk_id", "interrupted"),
        "text": "",
        "status": "idle",
        "loop": True,
        "start_index": int(current_state.get("start_index", 0) or 0),
        "frame_count": int(current_state.get("frame_count", len(frame_paths)) or len(frame_paths)),
        "avatar_id": current_state.get("avatar_id"),
    })
    prime_musetalk_preview_frame(shared_state.current_musetalk_frame_data)
    schedule_musetalk_runtime_cleanup(keep_frame_dirs=[frame_dir] if frame_dir else None)


def freeze_current_musetalk_frame():
    current_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
    frame_paths = list(current_state.get("frame_paths", []) or [])
    if not frame_paths:
        frame_dir = current_state.get("frame_dir", "")
        frame_paths = list_png_frames(frame_dir)
    if not frame_paths:
        clear_avatar_stream_state()
        return

    fps = int(current_state.get("fps", RUNTIME_CONFIG.get("musetalk_fps", 24)) or 24)
    sync_time = float(current_state.get("sync_time", 0.0) or 0.0)
    elapsed = max(0.0, time.time() - sync_time)
    frame_index = min(int(elapsed * max(fps, 1)), len(frame_paths) - 1)
    frame_path = frame_paths[frame_index]

    shared_state.current_expression_data = {"names": [], "frames": []}
    shared_state.set_current_musetalk_frame_data({
        "frame_paths": [frame_path],
        "frame_dir": "",
        "fps": fps,
        "sync_time": time.time(),
        "duration_seconds": 0.0,
        "chunk_id": current_state.get("chunk_id", "interrupted"),
        "text": "",
        "status": "idle",
        "loop": True,
        "start_index": int(current_state.get("start_index", 0) or 0) + frame_index,
        "frame_count": 1,
        "avatar_id": current_state.get("avatar_id"),
    })
    prime_musetalk_preview_frame(shared_state.current_musetalk_frame_data)
    if current_state.get("frame_dir"):
        schedule_musetalk_runtime_cleanup(keep_frame_dirs=[current_state.get("frame_dir")])


def transition_musetalk_to_idle_after_interrupt(delay=0.35):
    if not _is_musetalk_avatar_adapter(avatar_gui):
        return

    def _delayed_idle():
        time.sleep(delay)
        if stop_flag.is_set():
            return
        try:
            transition_musetalk_to_local_idle(advance_to_next_frame=True)
        except Exception:
            pass

    threading.Thread(target=_delayed_idle, daemon=True).start()


def shutdown_avatar_engine(unload_tts=True, unload_stt=True):
    global avatar_gui, tts_model, tts_backend_name, whisper_model
    had_tts_model = tts_model is not None
    avatar_gui, tts_model, whisper_model = runtime_shutdown.shutdown_runtime_components(
        avatar_gui=avatar_gui,
        tts_model=tts_model,
        whisper_model=whisper_model,
        unload_tts=unload_tts,
        unload_stt=unload_stt,
        stop_playback=stop_playback,
        pause_after_chunk=pause_after_chunk,
        playback_paused=playback_paused,
        clear_avatar_stream_state=clear_avatar_stream_state,
        schedule_musetalk_runtime_cleanup=schedule_musetalk_runtime_cleanup,
        gc_module=gc,
        torch_module=torch,
        logger=print,
    )
    if unload_tts and had_tts_model and tts_model is None:
        tts_backend_name = None


def reset_session_state():
    global conversation_history, assistant_memory, chat_session_state_generation
    global sensory_hidden_history, sensory_pingpong_state, sensory_hidden_action_state
    conversation_history = []
    assistant_memory = _default_assistant_memory()
    sensory_hidden_history = []
    sensory_pingpong_state = {
        "last_cycle_at": 0.0,
        "last_retained_at": 0.0,
        "last_emotion": "",
        "last_attention": "",
        "last_summary": "",
        "last_source": "off",
    }
    sensory_hidden_action_state = {
        "pending_proactive": None,
        "active_proactive": None,
        "last_proactive_key": "",
        "last_proactive_at": 0.0,
        "last_visual_key": "",
        "last_visual_at": 0.0,
    }
    chat_session_state_generation += 1
    print("🧼 [Session] Chat history and memory reset.")


def reset_chat_runtime_state():
    global last_resume_requested_at, pending_loaded_input_turn, pending_next_user_attachment
    pending_loaded_input_turn = None
    pending_next_user_attachment = None
    _clear_pending_hidden_proactive_candidate()
    _clear_active_hidden_proactive_candidate()
    stop_playback.set()
    pause_after_chunk.clear()
    playback_paused.clear()
    clear_avatar_stream_state()
    last_resume_requested_at = 0.0
    audio_playing.clear()
    try:
        sd.stop()
    except Exception:
        pass


def _sanitize_chat_turn(entry):
    if not isinstance(entry, dict):
        return None
    role = str(entry.get("role", "") or "").strip().lower()
    if role not in {"user", "system", "assistant"}:
        return None
    attachment_image_path = str(entry.get("attachment_image_path", "") or "").strip()
    if attachment_image_path:
        attachment_image_path = os.path.abspath(attachment_image_path)
    content = str(entry.get("content", "") or "").strip()
    if not content and not attachment_image_path:
        return None
    if not content:
        content = "Please respond to the image I just sent you."
    origin = str(entry.get("origin", "") or "").strip().lower()
    if origin not in {"input", "assistant_reply"}:
        origin = "assistant_reply" if role == "assistant" else "input"
    turn = {"role": role, "content": content, "origin": origin}
    if attachment_image_path:
        turn["attachment_image_path"] = attachment_image_path
        attachment_source = str(entry.get("attachment_source", "image") or "image").strip().lower()
        if attachment_source:
            turn["attachment_source"] = attachment_source
    return turn


def set_pending_user_image_attachment(image_path, *, source="clipboard"):
    global pending_next_user_attachment
    path = os.path.abspath(str(image_path or "").strip())
    if not path or not os.path.isfile(path):
        raise ValueError("Image path does not exist.")
    pending_next_user_attachment = {
        "attachment_image_path": path,
        "attachment_source": str(source or "image").strip().lower() or "image",
    }
    print(f"📋 [Clipboard] Pending image attachment armed for next user turn: {path}")
    return dict(pending_next_user_attachment)


def clear_pending_user_image_attachment():
    global pending_next_user_attachment
    pending_next_user_attachment = None


def queue_user_image_turn(image_path, *, content=None, source="clipboard"):
    global pending_loaded_input_turn, conversation_history
    path = os.path.abspath(str(image_path or "").strip())
    if not path or not os.path.isfile(path):
        raise ValueError("Image path does not exist.")
    turn = _sanitize_chat_turn({
        "role": "user",
        "content": str(content or "").strip() or "Please respond to the image I just sent you.",
        "origin": "input",
        "attachment_image_path": path,
        "attachment_source": str(source or "image").strip().lower() or "image",
    })
    if not turn:
        raise ValueError("Could not prepare image input turn.")
    conversation_history.append(dict(turn))
    _apply_stored_chat_history_limit()
    pending_loaded_input_turn = dict(turn)
    print(f"📋 [Clipboard] Queued image input for next model request: {path}")
    _request_chat_view_rebuild()
    return dict(turn)


def export_chat_session_state():
    return {
        "version": 1,
        "saved_at": time.time(),
        "conversation_history": [turn for turn in (_sanitize_chat_turn(item) for item in list(conversation_history or [])) if turn],
        "assistant_memory": json.loads(json.dumps(assistant_memory or _default_assistant_memory())),
        "sensory_hidden_history": [item for item in (_sanitize_sensory_hidden_event(entry) for entry in list(sensory_hidden_history or [])) if item],
    }


def collect_replayable_assistant_entries(history=None):
    replayable = []
    assistant_index = 0
    for history_index, item in enumerate(list(history if history is not None else (conversation_history or []))):
        turn = _sanitize_chat_turn(item)
        if not turn:
            continue
        if str(turn.get("role", "") or "") != "assistant":
            continue
        if str(turn.get("origin", "") or "") != "assistant_reply":
            continue
        content = str(turn.get("content", "") or "").strip()
        if not content:
            continue
        assistant_index += 1
        preview = re.sub(r"\s+", " ", content).strip()
        replayable.append({
            "replay_index": assistant_index,
            "history_index": history_index,
            "content": content,
            "preview": preview[:140] + ("..." if len(preview) > 140 else ""),
        })
    return replayable


def collect_replayable_assistant_messages(history=None):
    return [str(item.get("content", "") or "") for item in collect_replayable_assistant_entries(history)]


def build_replay_chat_session_from_action(start_index):
    try:
        value = max(1, int(start_index))
    except Exception:
        value = 1
    return f"replay_chat_session_from:{value}"


def parse_replay_chat_session_start_index(action):
    raw = str(action or "").strip().lower()
    prefix = "replay_chat_session_from:"
    if not raw.startswith(prefix):
        return None
    try:
        value = int(raw[len(prefix):].strip())
    except Exception:
        return None
    return value if value >= 1 else None


def replace_chat_conversation_history(raw_history, *, allow_pending_loaded_user=False):
    global conversation_history, pending_loaded_input_turn
    if not isinstance(raw_history, list):
        raise ValueError("conversation_history must be a list")
    sanitized_history = [turn for turn in (_sanitize_chat_turn(item) for item in raw_history) if turn]
    conversation_history = sanitized_history
    _apply_stored_chat_history_limit()
    pending_loaded_input_turn = None
    if allow_pending_loaded_user and conversation_history:
        last_turn = dict(conversation_history[-1] or {})
        if str(last_turn.get("role", "") or "").strip().lower() == "user":
            pending_loaded_input_turn = {
                "role": "user",
                "content": str(last_turn.get("content", "") or ""),
                "origin": str(last_turn.get("origin", "input") or "input"),
            }
            attachment_image_path = str(last_turn.get("attachment_image_path", "") or "").strip()
            if attachment_image_path:
                pending_loaded_input_turn["attachment_image_path"] = attachment_image_path
                pending_loaded_input_turn["attachment_source"] = str(last_turn.get("attachment_source", "image") or "image")
    return {"conversation_turns": len(conversation_history)}


def import_chat_session_state(payload):
    global assistant_memory, chat_session_state_generation, sensory_hidden_history
    if not isinstance(payload, dict):
        raise ValueError("Chat session payload must be a JSON object")
    reset_chat_runtime_state()
    raw_history = payload.get("conversation_history", [])
    raw_memory = payload.get("assistant_memory")
    if isinstance(raw_memory, dict):
        sanitized_memory = json.loads(json.dumps(raw_memory))
    else:
        sanitized_memory = _default_assistant_memory()
    sanitized_memory.setdefault("preferences", {})
    sanitized_memory.setdefault("recent_context", [])
    sensory_hidden_history = [item for item in (_sanitize_sensory_hidden_event(entry) for entry in list(payload.get("sensory_hidden_history", []) or [])) if item]
    _prune_sensory_hidden_history()
    history_result = replace_chat_conversation_history(raw_history, allow_pending_loaded_user=True)
    assistant_memory = sanitized_memory
    chat_session_state_generation += 1
    print(f"📚 [Session] Loaded chat context with {len(conversation_history)} turn(s).")
    return {
        "conversation_turns": int(history_result.get("conversation_turns", len(conversation_history))),
        "assistant_memory_keys": sorted(str(key) for key in assistant_memory.keys()),
    }


def normalize_chunk_result(result, default_payload_path=None):
    if isinstance(result, dict):
        normalized = dict(result)
        normalized.setdefault("ok", True)
        normalized.setdefault("kind", "audio")
        return normalized
    if result:
        normalized = {"ok": True, "kind": "audio"}
        if default_payload_path:
            normalized["payload_path"] = default_payload_path
        return normalized
    return {"ok": False, "kind": "audio"}


def list_png_frames(frame_dir):
    return runtime_files.list_png_frames(frame_dir)


def estimate_displayed_musetalk_frames(state, now=None):
    return musetalk_preview_runtime.estimate_displayed_musetalk_frames(
        state,
        now=now,
        runtime_config=RUNTIME_CONFIG,
    )


def get_current_musetalk_source_index(state=None, advance_to_next_frame=False):
    return musetalk_preview_runtime.get_current_musetalk_source_index(
        state,
        runtime_config=RUNTIME_CONFIG,
        shared_state_module=shared_state,
        advance_to_next_frame=advance_to_next_frame,
    )


def cleanup_musetalk_runtime(keep_frame_dirs=None, max_keep=64):
    runtime_root = os.path.abspath(os.path.join("MuseTalk", "runtime", "rendered_chunks"))
    if not os.path.isdir(runtime_root):
        return

    def _safe_rmtree(path):
        def _onerror(func, target_path, exc_info):
            exception = exc_info[1]
            if isinstance(exception, FileNotFoundError):
                return
            raise exception

        try:
            shutil.rmtree(path, onerror=_onerror)
        except FileNotFoundError:
            pass

    with _musetalk_cleanup_lock:
        keep_dirs = {os.path.abspath(path) for path in (keep_frame_dirs or []) if path}
        chunk_dirs = []
        for name in os.listdir(runtime_root):
            full_path = os.path.join(runtime_root, name)
            if os.path.isdir(full_path):
                chunk_dirs.append(full_path)

        existing_dirs = []
        for chunk_dir in chunk_dirs:
            try:
                mtime = os.path.getmtime(chunk_dir)
            except FileNotFoundError:
                continue
            existing_dirs.append((chunk_dir, mtime))

        existing_dirs.sort(key=lambda item: item[1], reverse=True)
        ordered_dirs = [path for path, _ in existing_dirs]
        protected_dirs = set(ordered_dirs[:max_keep]).union(keep_dirs)

        for chunk_dir, mtime in existing_dirs:
            if os.path.abspath(chunk_dir) in protected_dirs:
                continue
            chunk_age = time.time() - mtime
            if chunk_age < 5.0:
                continue
            try:
                _safe_rmtree(chunk_dir)
            except Exception as e:
                print(f"⚠️ [MuseTalk] Cleanup failed for {os.path.basename(chunk_dir)}: {e}")


def save_musetalk_seam_debug_images(previous_state, current_state):
    previous_chunk_id = previous_state.get("chunk_id")
    current_chunk_id = current_state.get("chunk_id")
    if not previous_chunk_id or not current_chunk_id:
        return

    previous_sequence = previous_state.get("sequence_index")
    current_sequence = current_state.get("sequence_index")
    if previous_sequence is None or current_sequence is None:
        return

    previous_frame_dir = previous_state.get("frame_dir", "")
    current_frame_dir = current_state.get("frame_dir", "")
    if not previous_frame_dir or not current_frame_dir:
        return

    previous_preview_index = int(previous_state.get("preview_frame_index", -1) or -1)
    current_trim = int(current_state.get("trim_start_frames", 0) or 0)
    previous_trim = int(previous_state.get("trim_start_frames", 0) or 0)
    if previous_preview_index < 0:
        return

    previous_raw_index = previous_preview_index + previous_trim
    current_raw_index = current_trim

    previous_raw_path = os.path.join(previous_frame_dir, f"{previous_raw_index:08d}.png")
    current_raw_path = os.path.join(current_frame_dir, f"{current_raw_index:08d}.png")
    if not os.path.exists(previous_raw_path) or not os.path.exists(current_raw_path):
        return

    seam_debug_dir = os.path.abspath(os.path.join("MuseTalk", "runtime", "seam_debug"))
    os.makedirs(seam_debug_dir, exist_ok=True)
    try:
        shutil.copy2(previous_raw_path, os.path.join(seam_debug_dir, f"chunk_{int(previous_sequence)}_out.png"))
        shutil.copy2(current_raw_path, os.path.join(seam_debug_dir, f"chunk_{int(current_sequence)}_in.png"))
    except Exception as e:
        print(f"⚠️ [MuseTalk] Seam debug export failed: {e}")


def schedule_musetalk_runtime_cleanup(keep_frame_dirs=None, max_keep=64, force=False):
    if audio_playing.is_set() and not force:
        return
    threading.Thread(
        target=cleanup_musetalk_runtime,
        args=(keep_frame_dirs, max_keep),
        daemon=True,
    ).start()


def set_seed(seed: int):
    try:
        seed = int(seed)
        if not (0 <= seed <= 2 ** 32 - 1):
            raise ValueError(f"Seed must be between 0 and 2**32 - 1, got {seed}")
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
        random.seed(seed)
        np.random.seed(seed)
    except Exception as e:
        raise


def _iter_queue_text_chunks(text_queue, dry_run_reply_id=None):
    first_yield_logged = False
    while True:
        while True:
            if stop_playback.is_set() or stop_flag.is_set():
                shared_state.append_musetalk_preview_log("🌊 [Stream] Text queue stopped before sentinel")
                return
            try:
                item = text_queue.get(timeout=0.1)
                break
            except queue.Empty:
                continue
        if item is None:
            shared_state.append_musetalk_preview_log("🌊 [Stream] Text queue received sentinel")
            break
        if item and str(item).strip():
            if not first_yield_logged:
                shared_state.append_musetalk_preview_log(
                    f"🌊 [Stream] First chunk dequeued for TTS: chars={len(str(item).strip())}"
                )
                dry_run.record_reply_event(dry_run_reply_id, "first_chunk_dequeued_at")
                first_yield_logged = True
            yield str(item)


def speak_async(text: str, text_iterable=None, dry_run_reply_id=None) -> TTSController:
    global tts_model, stop_playback, audio_playing, avatar_gui, last_resumed_at, last_resume_requested_at
    ctrl = TTSController()
    stop_playback.clear()
    pause_after_chunk.clear()
    playback_paused.clear()
    if avatar_gui and hasattr(avatar_gui, "begin_reply"):
        try:
            avatar_gui.begin_reply()
        except Exception:
            pass
    if tts_model is None:
        print("⚠️ TTS Model not loaded, skipping audio.")
        ctrl.done.set()
        return ctrl

    playback_queue = queue.Queue()
    ready_for_playback = queue.Queue()
    output_dir = tempfile.gettempdir()
    sample_rate = getattr(tts_model, "sr", 24000)
    chunk_target_chars, chunk_max_chars = get_text_chunk_limits()
    avatar_mode = RUNTIME_CONFIG.get("avatar_mode", "vseeface").lower()
    pipeline_telemetry_enabled = avatar_mode in {"musetalk", "vam", "none"}
    pipeline_reply_id = None
    if pipeline_telemetry_enabled:
        pipeline_reply_id = shared_state.begin_musetalk_pipeline_reply(
            stream_mode=bool(text_iterable is not None or RUNTIME_CONFIG.get("stream_mode", False))
        )
        shared_state.update_musetalk_pipeline_flags(
            reply_id=pipeline_reply_id,
            engine_mode=avatar_mode,
        )
    else:
        shared_state.reset_musetalk_pipeline_data()

    story_mode_enabled = _visual_reply_story_mode_enabled()
    story_max_images = _visual_reply_story_max_images()
    story_generation_available = story_mode_enabled and _visual_reply_generation_available()
    story_images_requested = 0
    story_session_id = 0
    story_style_guide = ""
    if story_mode_enabled and not story_generation_available:
        print("⚠️ [VisualReply] Story mode is enabled, but visual reply generation is unavailable.")
    elif story_mode_enabled:
        clear_visual_reply_story_queue()
        story_session_id = begin_visual_reply_story_session()
        story_style_guide = _story_visual_reply_style_guide_from_text(
            text,
            continuity_strength=_visual_reply_story_continuity_strength(),
        )

    def _queue_story_visual_reply(chunk_text: str, emotion: str) -> bool:
        nonlocal story_images_requested, story_generation_available
        if not story_generation_available or story_images_requested >= story_max_images:
            return False
        story_prompt = _story_visual_reply_prompt_from_text(chunk_text, emotion, story_style_guide=story_style_guide)
        if not story_prompt:
            return False
        queued = enqueue_visual_reply_story_generation(
            story_prompt,
            source_text=str(chunk_text or ""),
            session_id=story_session_id,
        )
        if queued:
            story_images_requested += 1
            return True
        if not _visual_reply_generation_available():
            story_generation_available = False
        return False

    def generator_worker():
        cnt = 0
        muse_chunk_index = 0
        source_iterable = text_iterable if text_iterable is not None else [text]
        first_piece_logged = False
        first_subchunk_logged = False
        first_wav_logged = False
        for piece_text in source_iterable:
            if stop_playback.is_set(): break
            if not piece_text or not str(piece_text).strip():
                continue
            if text_iterable is not None and not first_piece_logged:
                shared_state.append_musetalk_preview_log(
                    f"🌊 [Stream] Generator received first text piece: chars={len(str(piece_text).strip())}"
                )
                first_piece_logged = True
            segments = parse_text_segments(str(piece_text))
            if avatar_mode == "musetalk":
                segments = coalesce_musetalk_leading_segments(segments)
            for emotion, seg_text in segments:
                if stop_playback.is_set():
                    break
                if avatar_mode == "musetalk":
                    sub_chunks = intelligent_chunk_text_progressive(seg_text, start_chunk_index=muse_chunk_index)
                else:
                    sub_chunks = intelligent_chunk_text(seg_text, chunk_target_chars, chunk_max_chars)
                print(f"🧩 [{RUNTIME_CONFIG.get('avatar_mode', 'vseeface').upper()}] {len(sub_chunks)} chunk(s) for emotion '{emotion}'")
                for sub in sub_chunks:
                    if stop_playback.is_set(): break
                    chunk_sequence = muse_chunk_index if avatar_mode == "musetalk" else cnt
                    if pipeline_telemetry_enabled:
                        shared_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="generating_audio",
                            playback_state="pending",
                            text=str(sub or ""),
                            emotion=str(emotion or ""),
                        )
                    if text_iterable is not None and not first_subchunk_logged:
                        shared_state.append_musetalk_preview_log(
                            f"🌊 [Stream] First TTS subchunk prepared: chars={len(sub.strip())} emotion={emotion}"
                        )
                        dry_run.record_reply_event(dry_run_reply_id, "first_tts_subchunk_at")
                        first_subchunk_logged = True
                    kwargs = tts_runtime.build_generation_kwargs(
                        RUNTIME_CONFIG,
                        set_seed=set_seed,
                        path_exists=os.path.exists,
                        logger=print,
                    )
                    try:
                        wav = tts_model.generate(sub, **kwargs)
                    except Exception as e:
                        if stop_playback.is_set() or stop_flag.is_set():
                            print(f"⏹️ [TTS] Generation cancelled during shutdown: {e}")
                            playback_queue.put(None)
                            return
                        raise
                    path = os.path.join(output_dir, f"speech_{cnt}_{int(time.time())}.wav")
                    wav_to_save = wav.cpu()
                    ta.save(path, wav_to_save, sample_rate)
                    del wav_to_save
                    del wav
                    estimated_duration_seconds = 0.0
                    estimated_frame_count = 0
                    if avatar_mode in {"musetalk", "none"}:
                        try:
                            estimated_duration_seconds = float(sf.info(path).duration or 0.0)
                        except Exception:
                            estimated_duration_seconds = 0.0
                        fps = int(RUNTIME_CONFIG.get("musetalk_fps", 24) or 24)
                        if estimated_duration_seconds > 0:
                            estimated_frame_count = max(1, int(round(estimated_duration_seconds * max(fps, 1))))
                    if text_iterable is not None and not first_wav_logged:
                        shared_state.append_musetalk_preview_log(
                            f"🌊 [Stream] First audio chunk generated: file={os.path.basename(path)} chars={len(sub.strip())}"
                        )
                        dry_run.record_reply_event(dry_run_reply_id, "first_audio_chunk_at")
                        first_wav_logged = True
                    if pipeline_telemetry_enabled:
                        shared_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="queued_for_render",
                            playback_state="pending",
                            duration_seconds=estimated_duration_seconds,
                            expected_frame_count=estimated_frame_count,
                        )
                    if avatar_mode == "none":
                        chunk_result = {
                            "ok": True,
                            "kind": "none",
                            "sequence_index": chunk_sequence,
                            "chunk_id": os.path.splitext(os.path.basename(path))[0],
                            "playback_duration_seconds": estimated_duration_seconds,
                            "expected_frame_count": max(2, estimated_frame_count or 0),
                        }
                    playback_queue.put((path, emotion, sub, chunk_sequence))
                    cnt += 1
                    if avatar_mode == "musetalk":
                        muse_chunk_index += 1
        playback_queue.put(None)
        if pipeline_telemetry_enabled:
            shared_state.update_musetalk_pipeline_flags(
                reply_id=pipeline_reply_id,
                stream_open=False,
            )

    def expression_preprocessor():
        def isolate_vocals_simple(input_wav):
            """
            A lightning-fast alternative to Spleeter.
            Strips the low-end rumble that confuses the AI.
            """
            try:
                # Load the raw TTS audio
                sound = AudioSegment.from_wav(input_wav)

                # High-pass filter: removes everything below 200Hz.
                # Human speech phonemes are mostly 300Hz-3000Hz.
                # This kills the "hum" that causes the generic jaw flapping.
                clean_sound = sound.high_pass_filter(300)

                # Boost the volume slightly to make the 'peaks' clearer for the AI
                clean_sound = clean_sound.apply_gain(+3)

                output_path = input_wav.replace(".wav", "_filtered.wav")
                clean_sound.export(output_path, format="wav")

                return output_path
            except Exception as e:
                print(f"❌ [Filter] Fast-filter failed: {e}")
                return input_wav
        try:
            while not stop_playback.is_set():
                item = playback_queue.get()
                if item is None:
                    ready_for_playback.put(None)
                    break

                path, emotion, txt, chunk_sequence = item
                vocal_only_path = path #isolate_vocals_simple(path)

                unique_id = str(uuid.uuid4())[:8]
                temp_json_name = f"bsData_{unique_id}.json"
                predicted_chunk_id = os.path.splitext(temp_json_name)[0]
                predicted_frame_dir = ""
                if avatar_mode == "musetalk" and _is_musetalk_avatar_adapter(avatar_gui):
                    try:
                        predicted_frame_dir = os.path.abspath(
                            os.path.join(
                                avatar_gui.root_dir,
                                "runtime",
                                "rendered_chunks",
                                predicted_chunk_id,
                            )
                        )
                    except Exception:
                        predicted_frame_dir = ""
                chunk_result = {"ok": True, "kind": "audio"}

                if avatar_gui:
                    avatar_gui.set_emotion(emotion)
                    if avatar_mode == "musetalk":
                        shared_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendering",
                            playback_state="pending",
                            chunk_id=predicted_chunk_id,
                            frame_dir=predicted_frame_dir,
                        )
                    result = avatar_gui.process_audio_chunk(
                        vocal_only_path,
                        txt,
                        output_filename=temp_json_name,
                        dry_run_reply_id=dry_run_reply_id,
                    )
                    chunk_result = normalize_chunk_result(result)
                elif avatar_mode == "none":
                    try:
                        delegated_duration_seconds = float(sf.info(vocal_only_path).duration or 0.0)
                    except Exception:
                        delegated_duration_seconds = 0.0
                    delegated_frame_count = max(
                        2,
                        int(round(delegated_duration_seconds * 50.0)) if delegated_duration_seconds > 0 else 2,
                    )
                    shared_state.set_current_musetalk_frame_data({
                        "frame_paths": [],
                        "frame_dir": "",
                        "fps": 50,
                        "sync_time": 0.0,
                        "duration_seconds": delegated_duration_seconds,
                        "expected_frame_count": delegated_frame_count,
                        "trim_start_frames": 0,
                        "chunk_id": os.path.splitext(temp_json_name)[0],
                        "text": txt,
                        "status": "ready",
                        "loop": False,
                        "start_index": 0,
                        "frame_count": delegated_frame_count,
                        "sequence_index": chunk_sequence,
                        "preview_chunk_id": os.path.splitext(temp_json_name)[0],
                        "preview_frame_index": 0,
                        "preview_source_index": 0,
                        "avatar_id": "none",
                    })
                    chunk_result = {
                        "ok": True,
                        "kind": "none",
                        "sequence_index": chunk_sequence,
                        "chunk_id": os.path.splitext(temp_json_name)[0],
                        "playback_duration_seconds": delegated_duration_seconds,
                        "expected_frame_count": delegated_frame_count,
                    }

                if chunk_result.get("ok"):
                    if avatar_mode == "musetalk":
                        shared_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendering",
                            playback_state="pending",
                            frame_dir=str(chunk_result.get("frame_dir", "") or ""),
                            chunk_id=str(chunk_result.get("chunk_id", "") or ""),
                            fps=int(chunk_result.get("fps", RUNTIME_CONFIG.get("musetalk_fps", 24)) or RUNTIME_CONFIG.get("musetalk_fps", 24) or 24),
                        )
                    elif avatar_mode == "vam":
                        shared_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendered",
                            playback_state="pending",
                            duration_seconds=float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                            expected_frame_count=int(chunk_result.get("expected_frame_count", 0) or 0),
                            chunk_id=str(chunk_result.get("chunk_id", "") or ""),
                        )
                    elif avatar_mode == "none":
                        shared_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendered",
                            playback_state="pending",
                            duration_seconds=float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                            expected_frame_count=int(chunk_result.get("expected_frame_count", 0) or 0),
                            chunk_id=str(chunk_result.get("chunk_id", "") or ""),
                        )
                    ready_for_playback.put((path, emotion, txt, chunk_sequence, chunk_result))
                    if vocal_only_path != path:
                        safe_delete_with_retry(vocal_only_path)
                else:
                    if pipeline_telemetry_enabled:
                        shared_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="failed",
                            playback_state="failed",
                        )
                    print(f"⚠️ [Preprocessor] Backend failed for chunk '{txt[:20]}...'")
                    safe_delete_with_retry(path)
        except Exception as e:
            print(f"❌ [Preprocessor] Error: {e}")

    def playback_worker():
        global last_resumed_at, last_resume_requested_at
        audio_playing.set()
        if avatar_gui:
            avatar_gui.set_speaking_state(True)
        last_chunk_end_time = None

        try:
            while not stop_playback.is_set():
                while playback_paused.is_set() and not stop_playback.is_set():
                    time.sleep(0.05)

                # Get the next chunk from the preprocessor
                item = ready_for_playback.get()
                if item is None:
                    break

                path, emotion, txt, chunk_sequence, chunk_result = item
                kind = chunk_result.get("kind", "audio")

                if kind == "musetalk":
                    current_sequence = int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0)
                    previous_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
                    try:
                        chunk_duration_seconds = float(sf.info(path).duration or 0.0)
                    except Exception:
                        chunk_duration_seconds = 0.0
                    frame_dir = chunk_result.get("frame_dir", "")
                    fps = int(chunk_result.get("fps", RUNTIME_CONFIG.get("musetalk_fps", 24)) or 24)
                    ready_event = chunk_result.get("ready_event")
                    result_holder = chunk_result.get("result_holder", {})
                    if result_holder.get("cancelled"):
                        shared_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            status="cancelled",
                            playback_state="cancelled",
                        )
                        safe_delete_with_retry(path)
                        continue
                    if _is_musetalk_avatar_adapter(avatar_gui):
                        chunk_generation = int(result_holder.get("generation", -1))
                        if chunk_generation != int(getattr(avatar_gui, "reply_generation", chunk_generation)):
                            shared_state.update_musetalk_pipeline_chunk(
                                current_sequence,
                                reply_id=pipeline_reply_id,
                                status="cancelled",
                                playback_state="cancelled",
                            )
                            safe_delete_with_retry(path)
                            continue
                    trim_start_frames = int(result_holder.get("trim_start_frames", 0) or 0)
                    is_first_reply_chunk = bool(chunk_result.get("sequence_index") == 0)
                    stream_fast_start = bool(RUNTIME_CONFIG.get("stream_mode", False))
                    if is_first_reply_chunk and stream_fast_start:
                        min_buffer_frames = max(10, min(int(fps * 0.5), 16))
                        shared_state.append_musetalk_preview_log(
                            f"🌊 [Stream] First chunk fast-start gate {chunk_result.get('chunk_id')}: "
                            f"min_buffer_frames={min_buffer_frames}"
                        )
                    elif is_first_reply_chunk:
                        min_buffer_frames = max(24, min(int(fps * 2.5), 72))
                    else:
                        min_buffer_frames = max(24, min(int(fps * 2.5), 72))
                    if is_first_reply_chunk:
                        shared_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            startup_buffer_frames=min_buffer_frames,
                        )
                    wait_start = time.time()
                    if is_first_reply_chunk:
                        shared_state.append_musetalk_preview_log(
                            f"🕒 [MuseTalkStartup] First chunk buffer wait start {chunk_result.get('chunk_id')}: "
                            f"min_buffer_frames={min_buffer_frames}"
                        )
                        log_musetalk_memory_checkpoint(
                            "first_chunk_buffer_wait_start",
                            chunk_result.get("chunk_id"),
                            {"min_buffer_frames": min_buffer_frames},
                        )
                    try:
                        frame_paths = list_png_frames(frame_dir)
                    except FileNotFoundError:
                        frame_paths = []

                    while (
                        len(frame_paths) < min_buffer_frames
                        and ready_event is not None
                        and not ready_event.is_set()
                        and not stop_playback.is_set()
                        and time.time() - wait_start < 60
                    ):
                        time.sleep(0.1)
                        try:
                            frame_paths = list_png_frames(frame_dir)
                        except FileNotFoundError:
                            frame_paths = []
                        if result_holder.get("cancelled"):
                            break

                    if result_holder.get("cancelled"):
                        shared_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            status="cancelled",
                            playback_state="cancelled",
                        )
                        safe_delete_with_retry(path)
                        continue

                    if is_first_reply_chunk:
                        shared_state.append_musetalk_preview_log(
                            f"🕒 [MuseTalkStartup] First chunk buffer wait done {chunk_result.get('chunk_id')}: "
                            f"waited_ms={(time.time() - wait_start) * 1000.0:.1f} "
                            f"buffered={len(frame_paths)} ready_event={bool(ready_event and ready_event.is_set())}"
                        )
                        log_musetalk_memory_checkpoint(
                            "first_chunk_buffer_wait_done",
                            chunk_result.get("chunk_id"),
                            {
                                "buffered": len(frame_paths),
                                "ready_event": bool(ready_event and ready_event.is_set()),
                            },
                        )
                        dry_run.record_reply_metric(
                            dry_run_reply_id,
                            "first_chunk_buffer_wait_ms",
                            round((time.time() - wait_start) * 1000.0, 1),
                        )

                    if not frame_paths and ready_event is not None and ready_event.is_set():
                        try:
                            frame_paths = list_png_frames(frame_dir)
                        except FileNotFoundError:
                            frame_paths = []

                    if trim_start_frames > 0 and frame_paths:
                        trimmed_paths = frame_paths[min(trim_start_frames, len(frame_paths) - 1):]
                        if trimmed_paths:
                            frame_paths = trimmed_paths

                    if not frame_paths and ready_event is not None and not ready_event.is_set() and not stop_playback.is_set():
                        while (
                            not frame_paths
                            and ready_event is not None
                            and not ready_event.is_set()
                            and not stop_playback.is_set()
                        ):
                            time.sleep(0.1)
                            try:
                                frame_paths = list_png_frames(frame_dir)
                            except FileNotFoundError:
                                frame_paths = []
                        if trim_start_frames > 0 and frame_paths:
                            trimmed_paths = frame_paths[min(trim_start_frames, len(frame_paths) - 1):]
                            if trimmed_paths:
                                frame_paths = trimmed_paths

                    if not frame_paths:
                        shared_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            status="failed",
                            playback_state="failed",
                        )
                        print(
                            f"⚠️ [MuseTalk] No buffered frames for chunk {chunk_result.get('chunk_id')} "
                            f"(dir={frame_dir}, result_frames={result_holder.get('frame_count')})"
                        )
                        safe_delete_with_retry(path)
                        continue

                    visible_start_index = int(result_holder.get("start_index", 0) or 0)
                    live_previous_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
                    previous_avatar_id = live_previous_state.get("avatar_id", previous_state.get("avatar_id"))
                    current_avatar_id = chunk_result.get("avatar_id")
                    previous_status = live_previous_state.get("status", previous_state.get("status"))
                    previous_chunk_id = live_previous_state.get("chunk_id", previous_state.get("chunk_id"))
                    previous_start_index = int(live_previous_state.get("start_index", previous_state.get("start_index", 0)) or 0)
                    if (
                        current_avatar_id == previous_avatar_id
                        and previous_status == "ready"
                        and previous_chunk_id
                    ):
                        preview_chunk_id = live_previous_state.get("preview_chunk_id")
                        preview_source_index = live_previous_state.get("preview_source_index")
                        if preview_chunk_id == previous_chunk_id and preview_source_index is not None:
                            visible_start_index = int(preview_source_index) + 1
                        else:
                            previous_displayed_frames = estimate_displayed_musetalk_frames(live_previous_state)
                            visible_start_index = previous_start_index + previous_displayed_frames
                    elif (
                        bool(chunk_result.get("sequence_index") == 0)
                        and previous_status == "idle"
                        and previous_chunk_id
                        and str(previous_chunk_id).startswith("first_chunk_plan:")
                    ):
                        preview_chunk_id = live_previous_state.get("preview_chunk_id")
                        preview_source_index = live_previous_state.get("preview_source_index")
                        if preview_chunk_id == previous_chunk_id and preview_source_index is not None:
                            try:
                                target_entry_index = int(visible_start_index)
                                wait_started_at = time.time()
                                if bool(RUNTIME_CONFIG.get("stream_mode", False)):
                                    max_wait_seconds = STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS
                                else:
                                    max_wait_seconds = max(0.75, min(2.5, MUSE_FIRST_CHUNK_PREDICTED_DELAY_SECONDS))
                                while (
                                    not stop_flag.is_set()
                                    and (time.time() - wait_started_at) < max_wait_seconds
                                ):
                                    live_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
                                    if live_state.get("chunk_id") != previous_chunk_id:
                                        break
                                    live_preview_source = live_state.get("preview_source_index")
                                    if live_preview_source is None:
                                        time.sleep(0.01)
                                        continue
                                    live_preview_source = int(live_preview_source)
                                    if live_preview_source == target_entry_index:
                                        visible_start_index = target_entry_index
                                        break
                                    time.sleep(0.01)
                                shared_state.append_musetalk_preview_log(
                                    f"🕒 [MuseTalkStartup] First chunk plan sync {chunk_result.get('chunk_id')}: "
                                    f"target={target_entry_index} final_preview={getattr(shared_state, 'current_musetalk_frame_data', {}).get('preview_source_index')} "
                                    f"waited_ms={(time.time() - wait_started_at) * 1000.0:.1f}"
                                )
                                log_musetalk_memory_checkpoint(
                                    "first_chunk_plan_sync",
                                    chunk_result.get("chunk_id"),
                                    {
                                        "target": target_entry_index,
                                        "final_preview": getattr(shared_state, "current_musetalk_frame_data", {}).get("preview_source_index"),
                                    },
                                )
                                dry_run.record_reply_metric(
                                    dry_run_reply_id,
                                    "first_chunk_plan_sync_ms",
                                    round((time.time() - wait_started_at) * 1000.0, 1),
                                )
                            except Exception:
                                pass
                    elif (
                        bool(chunk_result.get("sequence_index") == 0)
                        and previous_status == "idle"
                        and previous_chunk_id == "idle"
                    ):
                        preview_source_index = live_previous_state.get("preview_source_index")
                        preview_chunk_id = live_previous_state.get("preview_chunk_id")
                        if preview_chunk_id == "idle" and preview_source_index is not None:
                            try:
                                target_entry_index = int(visible_start_index)
                                wait_started_at = time.time()
                                if bool(RUNTIME_CONFIG.get("stream_mode", False)):
                                    max_wait_seconds = STREAM_FIRST_CHUNK_IDLE_SYNC_MAX_SECONDS
                                else:
                                    max_wait_seconds = max(0.25, min(1.5, abs(target_entry_index - int(preview_source_index)) / max(fps, 1) + 0.25))
                                while (
                                    not stop_flag.is_set()
                                    and (time.time() - wait_started_at) < max_wait_seconds
                                ):
                                    live_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
                                    if live_state.get("chunk_id") != "idle":
                                        break
                                    live_preview_source = live_state.get("preview_source_index")
                                    if live_preview_source is None:
                                        time.sleep(0.01)
                                        continue
                                    live_preview_source = int(live_preview_source)
                                    if live_preview_source == target_entry_index:
                                        visible_start_index = target_entry_index
                                        break
                                    time.sleep(0.01)
                                shared_state.append_musetalk_preview_log(
                                    f"🕒 [MuseTalkStartup] First chunk idle sync {chunk_result.get('chunk_id')}: "
                                    f"target={target_entry_index} final_preview={getattr(shared_state, 'current_musetalk_frame_data', {}).get('preview_source_index')} "
                                    f"waited_ms={(time.time() - wait_started_at) * 1000.0:.1f}"
                                )
                                dry_run.record_reply_metric(
                                    dry_run_reply_id,
                                    "first_chunk_idle_sync_ms",
                                    round((time.time() - wait_started_at) * 1000.0, 1),
                                )
                            except Exception:
                                pass

                    raw_expected_frame_count = max(
                        len(frame_paths),
                        int(round(chunk_duration_seconds * max(fps, 1))),
                        int(result_holder.get("frame_count", 0) or 0),
                    )
                    expected_frame_count = max(
                        len(frame_paths),
                        max(raw_expected_frame_count - trim_start_frames, 0),
                    )
                    duration_seconds = max(
                        chunk_duration_seconds,
                        max(expected_frame_count - 1, 0) / max(fps, 1),
                    )
                    publish_time = time.time()
                    if (
                        dry_run_reply_id
                        and int(chunk_result.get("sequence_index", 0) or 0) > 0
                        and live_previous_state.get("chunk_id")
                    ):
                        previous_audio_started_at = live_previous_state.get("audio_started_at")
                        previous_duration_seconds = float(live_previous_state.get("duration_seconds", 0.0) or 0.0)
                        if previous_audio_started_at and previous_duration_seconds > 0:
                            followup_headroom_ms = (
                                (float(previous_audio_started_at) + previous_duration_seconds) - publish_time
                            ) * 1000.0
                            dry_run.accumulate_reply_metric(
                                dry_run_reply_id,
                                "followup_headroom_sum_ms",
                                round(followup_headroom_ms, 1),
                            )
                            dry_run.accumulate_reply_metric(
                                dry_run_reply_id,
                                "followup_headroom_count",
                                1,
                            )
                            dry_run.update_reply_min_metric(
                                dry_run_reply_id,
                                "min_followup_headroom_ms",
                                round(followup_headroom_ms, 1),
                            )

                    shared_state.set_current_musetalk_frame_data({
                        "frame_paths": frame_paths,
                        "frame_dir": frame_dir,
                        "fps": fps,
                        "sync_time": publish_time,
                        "duration_seconds": duration_seconds,
                        "expected_frame_count": expected_frame_count,
                        "trim_start_frames": trim_start_frames,
                        "chunk_id": chunk_result.get("chunk_id"),
                        "text": txt,
                        "status": "ready",
                        "loop": False,
                        "start_index": visible_start_index,
                        "frame_count": expected_frame_count,
                        "avatar_id": chunk_result.get("avatar_id"),
                        "sequence_index": chunk_result.get("sequence_index"),
                        "is_first_reply_chunk": bool(chunk_result.get("sequence_index") == 0),
                        "published_at": publish_time,
                        "preview_chunk_id": None,
                        "preview_frame_index": -1,
                        "preview_source_index": None,
                    })
                    shared_state.update_musetalk_pipeline_chunk(
                        current_sequence,
                        reply_id=pipeline_reply_id,
                        playback_state="buffered",
                        duration_seconds=duration_seconds,
                        expected_frame_count=expected_frame_count,
                        chunk_id=chunk_result.get("chunk_id"),
                    )
                    dry_run.record_reply_event(dry_run_reply_id, "first_chunk_published_at")
                    dry_run.record_reply_metric(dry_run_reply_id, "first_chunk_start_index", visible_start_index)
                    dry_run.record_reply_metric(dry_run_reply_id, "first_chunk_expected_frames", expected_frame_count)
                    startup_resume_ms = None
                    if last_resumed_at and (time.time() - last_resumed_at) < 30.0:
                        startup_resume_ms = (time.time() - last_resumed_at) * 1000.0
                    prime_musetalk_preview_frame(shared_state.current_musetalk_frame_data)
                    save_musetalk_seam_debug_images(previous_state, shared_state.current_musetalk_frame_data)
                    schedule_musetalk_runtime_cleanup(keep_frame_dirs=[frame_dir])
                    print(
                        f"✅ [MuseTalk] Initial buffer {len(frame_paths)} frame(s): {txt[:20]}... "
                        f"(chunk={chunk_result.get('chunk_id')}, start_index={visible_start_index}, trim={trim_start_frames})"
                    )
                    if startup_resume_ms is not None:
                        message = (
                            f"🕒 [MuseTalkStartup] Resume -> initial buffer {chunk_result.get('chunk_id')}: "
                            f"{startup_resume_ms:.1f} ms"
                        )
                        print(message)
                        shared_state.append_musetalk_preview_log(message)
                    if is_first_reply_chunk:
                        shared_state.append_musetalk_preview_log(
                            f"🕒 [MuseTalkStartup] First chunk published {chunk_result.get('chunk_id')}: "
                            f"buffered={len(frame_paths)} expected={expected_frame_count} "
                            f"start_index={visible_start_index}"
                        )
                        log_musetalk_memory_checkpoint(
                            "first_chunk_published",
                            chunk_result.get("chunk_id"),
                            {
                                "buffered": len(frame_paths),
                                "expected": expected_frame_count,
                                "start_index": visible_start_index,
                            },
                        )
                    print(
                        f"▶️ [MuseTalk] Playing chunk {chunk_result.get('chunk_id')} "
                        f"(initial buffer {len(frame_paths)} frame(s), ~{len(frame_paths) / max(fps, 1):.2f}s ready)"
                    )
                    time.sleep(0.01)
                elif kind in {"vam", "none"}:
                    delegated_label = "VaM" if kind == "vam" else "None"
                    current_sequence = int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0)
                    delegated_duration_seconds = max(
                        0.0,
                        float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                    )
                    expected_frame_count = max(
                        2,
                        int(chunk_result.get("expected_frame_count", 0) or 0),
                        int(round(delegated_duration_seconds * 50.0)) if delegated_duration_seconds > 0 else 2,
                    )
                    shared_state.set_current_musetalk_frame_data({
                        "frame_paths": [],
                        "frame_dir": "",
                        "fps": 50,
                        "sync_time": 0.0,
                        "duration_seconds": delegated_duration_seconds,
                        "expected_frame_count": expected_frame_count,
                        "trim_start_frames": 0,
                        "chunk_id": chunk_result.get("chunk_id"),
                        "text": txt,
                        "status": "ready",
                        "loop": False,
                        "start_index": 0,
                        "frame_count": expected_frame_count,
                        "sequence_index": current_sequence,
                        "preview_chunk_id": chunk_result.get("chunk_id"),
                        "preview_frame_index": 0,
                        "preview_source_index": 0,
                        "avatar_id": kind,
                    })
                    shared_state.update_musetalk_pipeline_chunk(
                        current_sequence,
                        reply_id=pipeline_reply_id,
                        playback_state="buffered",
                        duration_seconds=delegated_duration_seconds,
                        expected_frame_count=expected_frame_count,
                        chunk_id=chunk_result.get("chunk_id"),
                    )
                    print(
                        f"✅ [{delegated_label}] Chunk buffered for delegated playback "
                        f"({delegated_duration_seconds:.2f}s, chunk={chunk_result.get('chunk_id')})"
                    )

                if not stop_playback.is_set():
                    preview_stream_stop = threading.Event()
                    preview_stream_thread = None
                    skip_local_playback = bool(chunk_result.get("skip_local_playback", False))
                    delegated_playback_duration = max(
                        0.0,
                        float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                    )
                    if kind == "musetalk":
                        audio_start_time = time.time()
                        _queue_story_visual_reply(txt, emotion)
                        current_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
                        if current_state.get("chunk_id") == chunk_result.get("chunk_id"):
                            current_state["sync_time"] = audio_start_time
                            current_state["audio_started_at"] = audio_start_time
                            shared_state.write_musetalk_preview_snapshot(current_state)
                            preview_stream_thread = threading.Thread(
                                target=stream_musetalk_preview_frames,
                                args=(current_state, preview_stream_stop),
                                daemon=True,
                            )
                            preview_stream_thread.start()
                        shared_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            playback_state="playing",
                            audio_started_at=audio_start_time,
                        )
                        startup_audio_ms = None
                        if last_resumed_at and (audio_start_time - last_resumed_at) < 30.0:
                            startup_audio_ms = (audio_start_time - last_resumed_at) * 1000.0
                        print(
                            f"⏱️ [MuseTalk] Audio start {chunk_result.get('chunk_id')}: "
                            f"audio={chunk_duration_seconds:.2f}s preview={float(shared_state.current_musetalk_frame_data.get('duration_seconds', 0.0) or 0.0):.2f}s"
                        )
                        if startup_audio_ms is not None:
                            message = (
                                f"🕒 [MuseTalkStartup] Resume -> audio start {chunk_result.get('chunk_id')}: "
                                f"{startup_audio_ms:.1f} ms"
                            )
                            print(message)
                            shared_state.append_musetalk_preview_log(message)
                        if is_first_reply_chunk:
                            shared_state.append_musetalk_preview_log(
                                f"🕒 [MuseTalkStartup] First chunk audio start {chunk_result.get('chunk_id')}: "
                                f"buffered={len(current_state.get('frame_paths', []) or [])} "
                                f"preview_duration={float(current_state.get('duration_seconds', 0.0) or 0.0):.2f}s"
                            )
                            log_musetalk_memory_checkpoint(
                                "first_chunk_audio_start",
                                chunk_result.get("chunk_id"),
                                {
                                    "buffered": len(current_state.get("frame_paths", []) or []),
                                    "preview_duration_s": round(float(current_state.get("duration_seconds", 0.0) or 0.0), 3),
                                },
                            )
                            dry_run.record_reply_event(dry_run_reply_id, "first_chunk_audio_start_at")
                            dry_run.record_reply_metric(
                                dry_run_reply_id,
                                "first_chunk_preview_duration_s",
                                round(float(current_state.get("duration_seconds", 0.0) or 0.0), 3),
                            )
                            dry_run.finalize_reply(dry_run_reply_id)
                    elif kind in {"vam", "none"}:
                        if kind == "vam" and _is_vam_avatar_adapter(avatar_gui):
                            skip_local_playback = bool(avatar_gui.begin_chunk_playback(chunk_result))
                        audio_start_time = time.time()
                        _queue_story_visual_reply(txt, emotion)
                        current_sequence = int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0)
                        current_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
                        if current_state.get("chunk_id") == chunk_result.get("chunk_id"):
                            current_state["sync_time"] = audio_start_time
                            current_state["audio_started_at"] = audio_start_time
                            shared_state.write_musetalk_preview_snapshot(current_state)
                            preview_stream_thread = threading.Thread(
                                target=stream_delegated_audio_progress,
                                args=(current_state, preview_stream_stop),
                                daemon=True,
                            )
                            preview_stream_thread.start()
                        shared_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            playback_state="playing",
                            audio_started_at=audio_start_time,
                        )
                    else:
                        audio_start_time = time.time()
                        _queue_story_visual_reply(txt, emotion)
                    if skip_local_playback:
                        wait_seconds = delegated_playback_duration
                        if wait_seconds <= 0:
                            try:
                                wait_seconds = max(0.0, float(AudioSegment.from_file(path).duration_seconds or 0.0))
                            except Exception:
                                wait_seconds = 0.0
                        if wait_seconds > 0:
                            deadline = time.time() + wait_seconds
                            while time.time() < deadline and not stop_playback.is_set():
                                time.sleep(0.02)
                        else:
                            time.sleep(0.05)
                    else:
                        play_audio_file(path)
                    preview_stream_stop.set()
                    if preview_stream_thread is not None:
                        preview_stream_thread.join(timeout=0.2)
                    audio_elapsed = time.time() - audio_start_time
                    if kind == "musetalk":
                        print(
                            f"⏱️ [MuseTalk] Audio end {chunk_result.get('chunk_id')}: "
                            f"elapsed={audio_elapsed:.2f}s"
                        )
                    ctrl.add_spoken(txt)

                if kind == "musetalk" and not stop_flag.is_set():
                    if stop_playback.is_set():
                        transition_musetalk_to_local_idle(advance_to_next_frame=True)
                    elif ready_for_playback.empty():
                        current_avatar_id = chunk_result.get("avatar_id")
                        if not maybe_transition_musetalk_avatar_back_to_default(current_avatar_id):
                            transition_musetalk_to_local_idle(advance_to_next_frame=True)
                elif kind in {"vam", "none"} and not stop_flag.is_set():
                    pass
                else:
                    clear_avatar_stream_state()
                safe_delete_with_retry(path)
                if kind in {"musetalk", "vam", "none"}:
                    shared_state.update_musetalk_pipeline_chunk(
                        int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
                        reply_id=pipeline_reply_id,
                        playback_state="completed",
                        audio_finished_at=time.time(),
                    )
                    if kind == "musetalk":
                        print(f"⏹️ [MuseTalk] Finished chunk {chunk_result.get('chunk_id')}")
                    else:
                        shared_state.update_current_musetalk_frame_data(
                            preview_frame_index=max(
                                0,
                                int(chunk_result.get("expected_frame_count", 0) or 0) - 1,
                            ),
                            preview_source_index=max(
                                0,
                                int(chunk_result.get("expected_frame_count", 0) or 0) - 1,
                            ),
                        )
                        if kind == "vam":
                            print(f"⏹️ [VaM] Finished delegated chunk {chunk_result.get('chunk_id')}")
                        else:
                            print(f"⏹️ [None] Finished audio-only chunk {chunk_result.get('chunk_id')}")
                    last_chunk_end_time = time.time()

                if pause_after_chunk.is_set() and not stop_playback.is_set():
                    pause_after_chunk.clear()
                    playback_paused.set()
                    if avatar_gui:
                        avatar_gui.set_speaking_state(False)
                    if _is_musetalk_avatar_adapter(avatar_gui):
                        current_avatar_id = chunk_result.get("avatar_id")
                        if not maybe_transition_musetalk_avatar_back_to_default(current_avatar_id):
                            transition_musetalk_to_local_idle(advance_to_next_frame=True)
                    print("- - - PAUSED (after chunk) - - -")
                    while playback_paused.is_set() and not stop_playback.is_set():
                        time.sleep(0.05)
                    if avatar_gui and not stop_playback.is_set():
                        last_resumed_at = time.time()
                        avatar_gui.set_speaking_state(True)
                        if last_resume_requested_at:
                            resume_ms = (last_resumed_at - last_resume_requested_at) * 1000.0
                            message = f"- - - RESUMED - - - ({resume_ms:.1f} ms after request)"
                            print(message)
                            shared_state.append_musetalk_preview_log(message)
                        else:
                            message = "- - - RESUMED - - -"
                            print(message)
                            shared_state.append_musetalk_preview_log(message)

        finally:
            if pipeline_telemetry_enabled:
                shared_state.update_musetalk_pipeline_flags(
                    reply_id=pipeline_reply_id,
                    active=False,
                    stream_open=False,
                )
            for q in [playback_queue, ready_for_playback]:
                while not q.empty():
                    try:
                        val = q.get_nowait()
                        if val:
                            safe_delete_with_retry(val[0])
                    except:
                        break

            if _is_musetalk_avatar_adapter(avatar_gui) and not stop_flag.is_set():
                if stop_playback.is_set():
                    transition_musetalk_to_local_idle(advance_to_next_frame=True)
                else:
                    current_avatar_id = getattr(shared_state, "current_musetalk_frame_data", {}).get("avatar_id")
                    if not maybe_transition_musetalk_avatar_back_to_default(current_avatar_id):
                        transition_musetalk_to_local_idle(advance_to_next_frame=True)
            elif avatar_mode == "vam" and not stop_flag.is_set():
                pass
            else:
                clear_avatar_stream_state()
            audio_playing.clear()
            pause_after_chunk.clear()
            playback_paused.clear()
            schedule_musetalk_runtime_cleanup(max_keep=4)
            if avatar_gui:
                avatar_gui.set_speaking_state(False)
            ctrl.done.set()


    threading.Thread(target=generator_worker, daemon=True, name="nc-tts-generator").start()
    threading.Thread(target=expression_preprocessor, daemon=True, name="nc-tts-preprocessor").start()
    threading.Thread(target=playback_worker, daemon=True, name="nc-tts-playback").start()
    return ctrl


def speak_async_stream(text_queue, dry_run_reply_id=None) -> TTSController:
    return speak_async("", text_iterable=_iter_queue_text_chunks(text_queue, dry_run_reply_id=dry_run_reply_id), dry_run_reply_id=dry_run_reply_id)

def safe_delete(file_path):
    return runtime_files.safe_delete(file_path, logger=print)


def safe_delete_with_retry(file_path, retries=5, delay=0.1):
    return runtime_files.safe_delete_with_retry(file_path, retries=retries, delay=delay, logger=print)
# ============================================================================
# SPEECH RECOGNITION
# ============================================================================

def transcribe_audio_with_main_whisper(audio, language="en"):
    return stt_runtime.transcribe_audio_with_whisper(
        audio,
        model_getter=lambda: whisper_model,
        init_model=init_whisper,
        safe_delete_with_retry=safe_delete_with_retry,
        language=language,
    )

def listen_for_speech(source, timeout=None):
    return stt_runtime.listen_for_speech(
        source,
        recognizer=recognizer,
        microphone_active=microphone_active,
        transcribe_func=transcribe_audio_with_main_whisper,
        sr_module=sr,
        settings={
            "energy_threshold": ENERGY_THRESHOLD,
            "dynamic_energy_threshold": DYNAMIC_ENERGY_THRESHOLD,
            "pause_threshold": PAUSE_THRESHOLD,
            "non_speaking_duration": NON_SPEAKING_DURATION,
            "phrase_threshold": PHRASE_THRESHOLD,
        },
        np_module=np,
        timeout=timeout,
        logger=print,
    )


def listen_for_speech_push_to_talk(source, chunk_size=1024, max_seconds=PUSH_TO_TALK_MAX_SECONDS, trailing_chunks=None):
    return stt_runtime.listen_for_speech_push_to_talk(
        source,
        recognizer=recognizer,
        microphone_active=microphone_active,
        transcribe_func=transcribe_audio_with_main_whisper,
        sr_module=sr,
        is_push_to_talk_held=is_push_to_talk_held,
        audio_data_factory=sr.AudioData,
        chunk_size=chunk_size,
        max_seconds=max_seconds,
        tail_seconds=PUSH_TO_TALK_TAIL_SECONDS,
        min_tail_chunks=PUSH_TO_TALK_MIN_TAIL_CHUNKS,
        trailing_chunks=trailing_chunks,
        logger=print,
    )


# ============================================================================
# LLM INTERACTION
# ============================================================================

def _proactive_placeholder_role():
    return "user"


def _configured_input_message_role():
    role = str(RUNTIME_CONFIG.get("input_message_role", "user") or "user").strip().lower()
    if role not in {"user", "system", "assistant"}:
        role = "user"
    return role


def _input_history_roles():
    return {"user", "system", _configured_input_message_role()}


def _chat_context_window_messages():
    return conversation_history_runtime.chat_context_window_messages(RUNTIME_CONFIG)


def _stored_chat_history_limit():
    return conversation_history_runtime.stored_chat_history_limit(RUNTIME_CONFIG)


def _request_chat_view_rebuild():
    print(CHAT_REBUILD_SENTINEL)


def _apply_stored_chat_history_limit():
    global conversation_history
    limit = _stored_chat_history_limit()
    conversation_history = conversation_history_runtime.apply_stored_chat_history_limit(conversation_history, limit)


def _chat_context_overflow_policy():
    return conversation_history_runtime.chat_context_overflow_policy(RUNTIME_CONFIG)


ChatContextLimitReached = conversation_history_runtime.ChatContextLimitReached


def _apply_overflow_policy_to_history(history, limit, policy):
    return conversation_history_runtime.apply_overflow_policy_to_history(history, limit, policy)


def _blank_user_anchor():
    return conversation_history_runtime.blank_user_anchor()


def _repair_model_history_window(history, policy=None):
    return conversation_history_runtime.repair_model_history_window(
        history,
        policy=policy or _chat_context_overflow_policy(),
        assistant_prefix_anchor_threshold=ASSISTANT_PREFIX_ANCHOR_THRESHOLD,
    )


def _build_model_history_window():
    limit = _chat_context_window_messages()
    policy = _chat_context_overflow_policy()
    return conversation_history_runtime.build_model_history_window(
        conversation_history,
        limit=limit,
        policy=policy,
        assistant_prefix_anchor_threshold=ASSISTANT_PREFIX_ANCHOR_THRESHOLD,
    )


def _build_chat_message_from_turn(turn):
    return conversation_history_runtime.build_chat_message_from_turn(
        turn,
        data_url_for_local_image=_data_url_for_local_image,
    )


def _pop_last_proactive_placeholder(content):
    if conversation_history:
        last = conversation_history[-1]
        if str(last.get("content", "") or "") == str(content or "") and str(last.get("role", "") or "") in {"user", "system"}:
            conversation_history.pop()
            return True
    return False


def build_llm_request():
    full_system_prompt = f"{RUNTIME_CONFIG['emotional_instructions']}\n\n{RUNTIME_CONFIG['system_prompt']}"
    model_history_window = _build_model_history_window()
    messages = [{"role": "system", "content": full_system_prompt}]
    active_preset_name = str(RUNTIME_CONFIG.get("active_preset_name", "") or "").strip().lower()
    help_context = ""
    help_debug = None
    if active_preset_name == "tutorial persona":
        help_debug = app_help.explain_help_lookup(model_history_window)
        help_context = app_help.build_help_context(model_history_window)
    else:
        latest = app_help.explain_help_lookup(model_history_window)
        print(
            "🧭 [AppHelp] Skipped: active_preset_name="
            f"{RUNTIME_CONFIG.get('active_preset_name', '')!r} "
            f"query={latest.get('query', '')[:120]!r}"
        )
    if help_context:
        topic_titles = ", ".join(help_debug.get("topic_titles", [])) if help_debug else ""
        print(
            "🧭 [AppHelp] Injected "
            f"{help_debug.get('topic_count', 0) if help_debug else 0} topic(s): {topic_titles}"
        )
        messages.append({"role": "system", "content": help_context})
    elif help_debug is not None:
        print(
            "🧭 [AppHelp] No context injected "
            f"(looks_like_app_question={help_debug.get('looks_like_app_question')}, "
            f"query={help_debug.get('query', '')[:120]!r})"
        )
    visual_instruction = _visual_reply_generation_instruction()
    if visual_instruction:
        messages.append({"role": "system", "content": visual_instruction})
    sensory_instruction = _sensory_feedback_instruction()
    if sensory_instruction:
        messages.append({"role": "system", "content": sensory_instruction})
    retained_sensory_context = _build_retained_sensory_context_text()
    if retained_sensory_context:
        messages.append({"role": "system", "content": retained_sensory_context})
    active_hidden_proactive_context = _build_active_hidden_proactive_context_text()
    hidden_proactive_active = bool(active_hidden_proactive_context)
    if active_hidden_proactive_context:
        messages.append({"role": "system", "content": active_hidden_proactive_context})
    history_messages = [
        message
        for message in (_build_chat_message_from_turn(item) for item in model_history_window)
        if message is not None
    ]
    hidden_proactive_prompt_message = _build_active_hidden_proactive_prompt_message() if hidden_proactive_active else None
    sensory_messages = [] if hidden_proactive_active else _build_sensory_feedback_messages()
    if hidden_proactive_active:
        print("👁️ [Sensory] Skipping fresh sensory injection for hidden proactive reply; using queued hidden context instead.")
    if sensory_messages and history_messages:
        last_user_index = next(
            (idx for idx in range(len(history_messages) - 1, -1, -1) if str(history_messages[idx].get("role", "") or "").strip().lower() == "user"),
            None,
        )
        if last_user_index is None:
            history_messages.extend(sensory_messages)
        else:
            for offset, message in enumerate(sensory_messages):
                history_messages.insert(last_user_index + offset, message)
    elif sensory_messages:
        history_messages.extend(sensory_messages)
    if hidden_proactive_prompt_message:
        history_messages.append(hidden_proactive_prompt_message)
    messages.extend(history_messages)
    params = {
        "model": RUNTIME_CONFIG["model_name"],
        "messages": messages,
    }
    additional_params = {}
    _apply_chat_provider_generation_fields(params, additional_params)
    return params, additional_params


def chat_with_llm():
    global conversation_history, RUNTIME_CONFIG
    _llm_request_active.set()
    try:
        params, additional_params = build_llm_request()
        response = _chat_completion_create(params, additional_params)
        return str(response or "")
    except ChatContextLimitReached as e:
        print(f"⚠️ Context limit reached: {e}")
        return str(e)
    except Exception as e:
        print(f"✗ LLM Error: {e}")
        return "I'm having trouble thinking right now."
    finally:
        _llm_request_active.clear()


def start_streamed_llm_reply(text_queue, dry_run_reply_id=None):
    state = StreamingReplyState()
    stream_target_chars, stream_max_chars = get_stream_chunk_limits()
    assembler = StreamingChunkAssembler(stream_target_chars, stream_max_chars)

    def worker():
        full_parts = []
        first_token_at = None
        visual_tail_open = False

        def _strip_visual_tail_from_stream_chunk(raw_text: str) -> str:
            nonlocal visual_tail_open
            text = str(raw_text or "")
            if not text:
                return ""
            if visual_tail_open:
                close_index = text.rfind("]")
                if close_index < 0:
                    return ""
                visual_tail_open = False
                return ""
            match = VISUAL_REPLY_TAG_START_RE.search(text)
            if not match:
                return text
            cleaned = text[:match.start()]
            tail = text[match.end():]
            close_index = tail.rfind("]")
            if close_index < 0:
                visual_tail_open = True
            return cleaned

        shared_state.append_musetalk_preview_log(
            f"🌊 [Stream] Reply stream started: target_chars={stream_target_chars} max_chars={stream_max_chars}"
        )
        dry_run.record_reply_event(dry_run_reply_id, "stream_reply_started_at")
        _llm_request_active.set()
        try:
            params, additional_params = build_llm_request()
            stream = _chat_completion_create(params, additional_params, stream=True)
            for content in stream:
                if state.cancel_requested.is_set() or stop_playback.is_set():
                    break
                if not content:
                    continue
                now = time.time()
                if first_token_at is None:
                    first_token_at = now
                    shared_state.append_musetalk_preview_log(
                        f"🌊 [Stream] First token received: len={len(content)}"
                    )
                    dry_run.record_reply_event(dry_run_reply_id, "first_token_at")
                full_parts.append(content)

                for chunk_info in assembler.feed(content):
                    raw_chunk_text = str(chunk_info.get("text", "") or "")
                    speech_source_text = _strip_visual_tail_from_stream_chunk(raw_chunk_text)
                    chunk_text = sanitize_assistant_text_for_speech(speech_source_text, preserve_emotion_tags=True)
                    if not chunk_text:
                        continue
                    text_queue.put(chunk_text)
                    state.first_chunk_emitted.set()
                    dry_run.accumulate_reply_metric(
                        dry_run_reply_id,
                        "chunk_quality_sum",
                        float(chunk_info.get("quality", 0.0) or 0.0),
                    )
                    dry_run.accumulate_reply_metric(dry_run_reply_id, "chunk_quality_count", 1)
                    dry_run.accumulate_reply_metric(
                        dry_run_reply_id,
                        "chunk_chars_sum",
                        int(chunk_info.get("chars", len(raw_chunk_text)) or len(raw_chunk_text)),
                    )
                    dry_run.accumulate_reply_metric(dry_run_reply_id, "chunk_chars_count", 1)
                    shared_state.append_musetalk_preview_log(
                        f"🌊 [Stream] Chunk emitted: chars={len(chunk_text.strip())} "
                        f"quality={float(chunk_info.get('quality', 0.0) or 0.0):.2f} "
                        f"reason={chunk_info.get('reason', 'unknown')} "
                        f"text={raw_chunk_text[:240]!r}"
                    )

            for chunk_info in assembler.feed("", final=True):
                raw_chunk_text = str(chunk_info.get("text", "") or "")
                speech_source_text = _strip_visual_tail_from_stream_chunk(raw_chunk_text)
                chunk_text = sanitize_assistant_text_for_speech(speech_source_text, preserve_emotion_tags=True)
                if not chunk_text:
                    continue
                text_queue.put(chunk_text)
                state.first_chunk_emitted.set()
                dry_run.accumulate_reply_metric(
                    dry_run_reply_id,
                    "chunk_quality_sum",
                    float(chunk_info.get("quality", 0.0) or 0.0),
                )
                dry_run.accumulate_reply_metric(dry_run_reply_id, "chunk_quality_count", 1)
                dry_run.accumulate_reply_metric(
                    dry_run_reply_id,
                    "chunk_chars_sum",
                    int(chunk_info.get("chars", len(raw_chunk_text)) or len(raw_chunk_text)),
                )
                dry_run.accumulate_reply_metric(dry_run_reply_id, "chunk_chars_count", 1)
                shared_state.append_musetalk_preview_log(
                    f"🌊 [Stream] Final chunk emitted: chars={len(chunk_text.strip())} "
                    f"quality={float(chunk_info.get('quality', 0.0) or 0.0):.2f} "
                    f"reason={chunk_info.get('reason', 'unknown')} "
                    f"text={raw_chunk_text[:240]!r}"
                )
        except ChatContextLimitReached as e:
            state.error = str(e)
            text_queue.put(str(e))
            print(f"⚠️ Streamed context limit reached: {e}")
            shared_state.append_musetalk_preview_log(f"🌊 [Stream] Context limit: {e}")
        except Exception as e:
            error_text = str(e) or repr(e)
            shared_state.append_musetalk_preview_log(f"🌊 [Stream] Error: {error_text}")
            if first_token_at is None and not state.cancel_requested.is_set() and not stop_playback.is_set():
                try:
                    print(f"⚠️ LLM Stream startup failed, falling back to non-stream reply: {error_text}")
                    fallback_text = chat_with_llm()
                    if fallback_text:
                        full_parts.append(fallback_text)
                        chunk_text = sanitize_assistant_text_for_speech(fallback_text, preserve_emotion_tags=True)
                        if chunk_text:
                            text_queue.put(chunk_text)
                            state.first_chunk_emitted.set()
                    else:
                        state.error = error_text
                except Exception as fallback_exc:
                    state.error = str(fallback_exc) or repr(fallback_exc)
                    print(f"✗ LLM Stream Error: {error_text}")
                    shared_state.append_musetalk_preview_log(f"🌊 [Stream] Fallback error: {state.error}")
            else:
                state.error = error_text
                print(f"✗ LLM Stream Error: {error_text}")
        finally:
            _llm_request_active.clear()
            state.full_text = "".join(full_parts).strip()
            text_queue.put(None)
            state.done.set()
            shared_state.append_musetalk_preview_log(
                f"🌊 [Stream] Reply stream done: total_chars={len(state.full_text)} emitted_any={state.first_chunk_emitted.is_set()}"
            )

    threading.Thread(target=worker, daemon=True).start()
    return state


def check_for_barge_in(source, energy_threshold=800, chunk_size=1024):
    global _barge_in_streak, _barge_in_last_sample_at
    try:
        if source.stream is None:
            _barge_in_streak = 0
            return False
        data = source.stream.read(chunk_size)
        if not data:
            _barge_in_streak = 0
            return False
        audio_data = np.frombuffer(data, dtype=np.int16)
        energy = np.sqrt(np.mean(audio_data.astype(np.int64) ** 2))
        now = time.time()
        if now - _barge_in_last_sample_at > BARGE_IN_RESET_SECONDS:
            _barge_in_streak = 0
        _barge_in_last_sample_at = now
        calibrated_floor = float(getattr(recognizer, "energy_threshold", 0.0) or 0.0)
        effective_threshold = max(float(energy_threshold), calibrated_floor * 1.6)
        if energy > effective_threshold:
            _barge_in_streak += 1
            if _barge_in_streak >= BARGE_IN_CONSECUTIVE_CHUNKS:
                _barge_in_streak = 0
                return True
        else:
            _barge_in_streak = 0
    except Exception as e:
        pass
    return False


# ============================================================================
# MAIN INTERACTION LOOP
# ============================================================================

def main_loop():
    global stop_flag
    print("\n" + "=" * 60)
    print("🎙️  VOICE ASSISTANT READY")
    print("=" * 60)
    if whisper_model is None:
        init_whisper()
    with _open_configured_microphone(sample_rate=16000) as source:
        try:
            print(f"🎚️ Calibrating microphone noise floor ({AMBIENT_CALIBRATION_SECONDS:.1f}s)...")
            recognizer.dynamic_energy_threshold = DYNAMIC_ENERGY_THRESHOLD
            recognizer.adjust_for_ambient_noise(source, duration=AMBIENT_CALIBRATION_SECONDS)
            print(f"✓ Mic calibrated (energy threshold {recognizer.energy_threshold:.0f})")
        except Exception as e:
            print(f"⚠️ Mic calibration skipped: {e}")
        run_conversation_flow(source)

def run_conversation_flow(source):
    global stop_flag, conversation_history, RUNTIME_CONFIG, last_resume_requested_at, pending_loaded_input_turn

    print(f"🧠 Brain Loaded: {RUNTIME_CONFIG['model_name']}")

    last_assistant_text = "I haven't said anything yet."
    user_text = None
    resumed_loaded_turn = None
    response_text = None
    response_text_is_replay = False
    response_text_replay_kind = ""
    current_replay_position = 0
    current_replay_total = 0
    pending_replay_text = None
    pending_replay_sequence = []
    stream_state = None
    active_ctrl = None
    assistant_history_added = False
    discard_assistant_history = False
    silence_elapsed_seconds = 0.0
    regenerating = False
    conversation_controller = build_experimental_controller(
        RUNTIME_CONFIG,
        runtime=SystemClockRuntime(stop_requested=stop_flag.is_set, logger=print),
    )
    conversation_controller.start()
    conversation_controller.state.has_real_user_turn = any(
        str(item.get("role", "") or "") == "user" for item in list(conversation_history or [])
    )
    known_chat_session_state_generation = int(chat_session_state_generation or 0)

    def _resolve_replay_session_start_index(status):
        if status == "replay_chat_session":
            return 1
        return parse_replay_chat_session_start_index(status)

    def _build_replay_sequence_from(start_index):
        replay_messages = collect_replayable_assistant_messages()
        total = len(replay_messages)
        if total <= 0:
            return [], 0, 0
        try:
            resolved_start = max(1, min(int(start_index or 1), total))
        except Exception:
            resolved_start = 1
        remaining = list(replay_messages[resolved_start - 1:])
        return remaining, resolved_start, total

    def _start_replay_session_from(start_index):
        nonlocal response_text, response_text_is_replay, response_text_replay_kind
        nonlocal current_replay_position, current_replay_total, pending_replay_text, pending_replay_sequence
        nonlocal silence_elapsed_seconds
        remaining, resolved_start, total = _build_replay_sequence_from(start_index)
        if not remaining:
            print("\n⚠️ No assistant replies are available in the current chat context.")
            return False
        if resolved_start <= 1:
            print(f"\n🔁 Replaying chat session ({total} assistant message(s))...")
        else:
            print(f"\n🔁 Replaying chat session from message {resolved_start}/{total} ({len(remaining)} assistant message(s))...")
        response_text = remaining[0]
        response_text_is_replay = True
        response_text_replay_kind = "session"
        current_replay_position = resolved_start
        current_replay_total = total
        pending_replay_text = None
        pending_replay_sequence = [
            {"text": item, "index": resolved_start + offset, "total": total}
            for offset, item in enumerate(remaining[1:], start=1)
        ]
        silence_elapsed_seconds = 0.0
        return True

    def _queue_replay_session_from(start_index):
        nonlocal pending_replay_text, pending_replay_sequence
        remaining, resolved_start, total = _build_replay_sequence_from(start_index)
        if not remaining:
            print("\n⚠️ No assistant replies are available in the current chat context.")
            return False
        if resolved_start <= 1:
            print(f"\n🔁 Replaying chat session ({total} assistant message(s)) after current playback stops...")
        else:
            print(f"\n🔁 Replaying chat session from message {resolved_start}/{total} after current playback stops...")
        pending_replay_text = None
        pending_replay_sequence = [
            {"text": item, "index": resolved_start + offset, "total": total}
            for offset, item in enumerate(remaining, start=0)
        ]
        return True

    def _plan_phase2_actions(current_user_text):
        conversation_controller.policy = conversation_controller.machine.policy = ConversationPolicy.from_runtime_config(RUNTIME_CONFIG)
        if str(current_user_text or "") == CONTINUE_ASSISTANT_SENTINEL:
            actions = conversation_controller.on_interaction_status("skip_user_reply")
        elif str(current_user_text or "") == "You continue speaking.":
            actions = conversation_controller.on_interaction_status("skip_speech")
        else:
            actions = conversation_controller.on_user_text(current_user_text)
        actions.extend(conversation_controller.on_thinking_started())
        return actions

    if isinstance(pending_loaded_input_turn, dict):
        loaded_content = str(pending_loaded_input_turn.get("content", "") or "").strip()
        loaded_role = str(pending_loaded_input_turn.get("role", "") or "").strip().lower()
        if loaded_content and loaded_role == "user":
            user_text = loaded_content
            resumed_loaded_turn = {
                "role": loaded_role,
                "content": loaded_content,
                "origin": str(pending_loaded_input_turn.get("origin", "input") or "input"),
            }
            attachment_image_path = str(pending_loaded_input_turn.get("attachment_image_path", "") or "").strip()
            if attachment_image_path:
                resumed_loaded_turn["attachment_image_path"] = attachment_image_path
                resumed_loaded_turn["attachment_source"] = str(pending_loaded_input_turn.get("attachment_source", "image") or "image")
            print("📚 [Session] Resuming loaded user turn immediately...")
        pending_loaded_input_turn = None

    def _hidden_sensory_loop_worker():
        while not stop_flag.is_set():
            try:
                if not _sensory_pingpong_enabled():
                    time.sleep(0.5)
                    continue
                if bool(RUNTIME_CONFIG.get("offline_replay_only", False)):
                    time.sleep(0.5)
                    continue
                if not listening_active.is_set():
                    time.sleep(0.25)
                    continue
                if microphone_active.is_set() or audio_playing.is_set() or _llm_request_active.is_set():
                    time.sleep(0.25)
                    continue
                interval_seconds = _sensory_feedback_interval_seconds()
                now = time.time()
                with sensory_pingpong_lock:
                    last_cycle_at = float(sensory_pingpong_state.get("last_cycle_at", 0.0) or 0.0)
                if last_cycle_at > 0 and (now - last_cycle_at) < interval_seconds:
                    time.sleep(0.25)
                    continue
                run_hidden_sensory_pingpong_cycle(force=False)
            except Exception as exc:
                print(f"⚠️ [Sensory] Hidden PING/PONG loop error: {exc}")
                time.sleep(1.0)
            else:
                time.sleep(0.25)

    threading.Thread(target=_hidden_sensory_loop_worker, daemon=True, name="nc-sensory-loop").start()

    while not stop_flag.is_set():
        current_chat_session_state_generation = int(chat_session_state_generation or 0)
        if current_chat_session_state_generation != known_chat_session_state_generation:
            conversation_controller = build_experimental_controller(
                RUNTIME_CONFIG,
                runtime=SystemClockRuntime(stop_requested=stop_flag.is_set, logger=print),
            )
            conversation_controller.start()
            conversation_controller.state.has_real_user_turn = any(
                str(item.get("role", "") or "") == "user" for item in list(conversation_history or [])
            )
            known_chat_session_state_generation = current_chat_session_state_generation
            regenerating = False
            user_text = None
            response_text = None
            response_text_is_replay = False
            response_text_replay_kind = ""
            current_replay_position = 0
            current_replay_total = 0
            pending_replay_text = None
            pending_replay_sequence = []
            stream_state = None
            active_ctrl = None
            assistant_history_added = False
            discard_assistant_history = False
            if isinstance(pending_loaded_input_turn, dict):
                loaded_content = str(pending_loaded_input_turn.get("content", "") or "").strip()
                loaded_role = str(pending_loaded_input_turn.get("role", "") or "").strip().lower()
                if loaded_content and loaded_role == "user":
                    user_text = loaded_content
                    resumed_loaded_turn = {
                        "role": loaded_role,
                        "content": loaded_content,
                        "origin": str(pending_loaded_input_turn.get("origin", "input") or "input"),
                    }
                    attachment_image_path = str(pending_loaded_input_turn.get("attachment_image_path", "") or "").strip()
                    if attachment_image_path:
                        resumed_loaded_turn["attachment_image_path"] = attachment_image_path
                        resumed_loaded_turn["attachment_source"] = str(pending_loaded_input_turn.get("attachment_source", "image") or "image")
                    print("📚 [Session] Resuming loaded user turn immediately...")
                pending_loaded_input_turn = None
        dry_run_reply_id = None

        # =================================================================================
        # PHASE 1: LISTENING
        # =================================================================================
        if pending_replay_text and not response_text:
            response_text = pending_replay_text
            response_text_is_replay = True
            response_text_replay_kind = "single"
            current_replay_position = 1
            current_replay_total = 1
            pending_replay_text = None
        elif pending_replay_sequence and not response_text:
            current_entry = dict(pending_replay_sequence.pop(0) or {})
            response_text = str(current_entry.get("text", "") or "").strip()
            response_text_is_replay = True
            response_text_replay_kind = "session"
            current_replay_position = int(current_entry.get("index", 1) or 1)
            current_replay_total = int(current_entry.get("total", current_replay_position) or current_replay_position)

        if not user_text and not regenerating and not response_text:
            allow_proactive_replies = bool(RUNTIME_CONFIG.get("allow_proactive_replies", True))
            require_first_user_before_proactive = bool(RUNTIME_CONFIG.get("require_first_user_before_proactive", False))
            hidden_proactive_request = None
            with sensory_pingpong_lock:
                hidden_proactive_request = _sanitize_hidden_proactive_request(sensory_hidden_action_state.get("pending_proactive"))
            if hidden_proactive_request and _hidden_sensory_proactive_speech_allowed():
                if not require_first_user_before_proactive or any(item.get("role") == "user" for item in conversation_history):
                    hidden_proactive_request = _consume_hidden_proactive_candidate()
                    if hidden_proactive_request:
                        print("\n📡 [Sensory] Hidden PONG requested a proactive reply...")
                        user_text = "You continue speaking."
                        silence_elapsed_seconds = 0.0
                        listening_active.clear()
                        continue
            if dry_run.auto_replies_enabled():
                generated_prompt = dry_run.next_auto_reply()
                if generated_prompt:
                    print(f"🧪 [DryRun] Auto prompt: {generated_prompt}")
                    user_text = generated_prompt
                    listening_active.clear()
                    silence_elapsed_seconds = 0.0
                    continue
            listening_active.set()
            print("👂 Waiting for voice...")
            listen_idle_window_seconds = max(0.5, float(RUNTIME_CONFIG.get("listen_idle_window_seconds", 5.0) or 5.0))
            proactive_delay_seconds = max(0.5, float(RUNTIME_CONFIG.get("proactive_delay_seconds", 10.0) or 10.0))
            start_wait = time.time()
            started_talking = False
            force_proactive_reply = False
            status = None

            while time.time() - start_wait < listen_idle_window_seconds:
                if isinstance(pending_loaded_input_turn, dict):
                    loaded_content = str(pending_loaded_input_turn.get("content", "") or "").strip()
                    loaded_role = str(pending_loaded_input_turn.get("role", "") or "").strip().lower()
                    if loaded_content and loaded_role == "user":
                        print("\n📋 [Session] Immediate queued user turn detected. Processing now...")
                        user_text = loaded_content
                        resumed_loaded_turn = {
                            "role": loaded_role,
                            "content": loaded_content,
                            "origin": str(pending_loaded_input_turn.get("origin", "input") or "input"),
                        }
                        attachment_image_path = str(pending_loaded_input_turn.get("attachment_image_path", "") or "").strip()
                        if attachment_image_path:
                            resumed_loaded_turn["attachment_image_path"] = attachment_image_path
                            resumed_loaded_turn["attachment_source"] = str(pending_loaded_input_turn.get("attachment_source", "image") or "image")
                        pending_loaded_input_turn = None
                        listening_active.clear()
                        break
                status = check_interaction_status(source)

                if status == "regenerate_response":
                    print("\n🎲 Regenerating last response...")
                    regenerating = True
                    break
                elif status == "retry_user_input":
                    print("\n↺ Retrying listening...")
                    start_wait = time.time()
                    continue
                elif status in {"barge_in", "push_to_talk"}:
                    started_talking = True
                    break
                elif status == "skip_speech":
                    print("\n⏭️ Skipping wait (Force Proactive)...")
                    force_proactive_reply = True
                    break
                elif status == "skip_user_reply":
                    print("\n⏭️ Skipping user reply (Assistant continuation)...")
                    user_text = CONTINUE_ASSISTANT_SENTINEL
                    silence_elapsed_seconds = 0.0
                    break
                elif status == "replay_last_assistant":
                    replay_source = str(last_assistant_text or "").strip()
                    if replay_source and replay_source != "I haven't said anything yet.":
                        print("\n🔁 Replaying latest assistant reply...")
                        response_text = replay_source
                        response_text_is_replay = True
                        response_text_replay_kind = "single"
                        current_replay_position = 1
                        current_replay_total = 1
                        pending_replay_sequence = []
                        silence_elapsed_seconds = 0.0
                        break
                    print("\n⚠️ No assistant reply available to replay yet.")
                    start_wait = time.time()
                    continue
                elif _resolve_replay_session_start_index(status) is not None:
                    replay_start_index = _resolve_replay_session_start_index(status)
                    if _start_replay_session_from(replay_start_index):
                        break
                    start_wait = time.time()
                    continue
                elif status == "pause_speech":
                    listening_active.clear()
                    print("- - - PAUSED - - -")
                    while True:
                        time.sleep(1.0)
                        status = check_interaction_status(source)
                        if status == "pause_speech":
                            listening_active.set()
                            start_wait = time.time() + 3
                            print("- - - UNPAUSED - - -")
                            break
                        time.sleep(0.2)

                time.sleep(0.05)

            if regenerating:
                listening_active.clear()
                pass
            elif started_talking:
                listening_active.clear()
                if status == "push_to_talk":
                    print("\n🎙️ Push-to-talk active. Recording...")
                    user_text = listen_for_speech_push_to_talk(source)
                else:
                    print("\n🎤 Voice detected! Recording...")
                    user_text = listen_for_speech(source, timeout=0.6)
                silence_elapsed_seconds = 0.0
                if not user_text or not user_text.strip():
                    print("... False alarm")
                    user_text = None
                    continue
                _clear_pending_hidden_proactive_candidate()
                _clear_active_hidden_proactive_candidate()
            elif user_text == CONTINUE_ASSISTANT_SENTINEL or (response_text_is_replay and response_text):
                listening_active.clear()
            else:
                listening_active.clear()
                if force_proactive_reply:
                    print("\n🤖 Forced proactive reply...")
                    user_text = "You continue speaking."
                    silence_elapsed_seconds = 0.0
                else:
                    silence_elapsed_seconds += listen_idle_window_seconds
                    if not allow_proactive_replies:
                        silence_elapsed_seconds = 0.0
                        continue
                    if require_first_user_before_proactive and not any(item.get("role") == "user" for item in conversation_history):
                        silence_elapsed_seconds = 0.0
                        continue
                    if silence_elapsed_seconds >= proactive_delay_seconds:
                        print("\n🤖 AI Decided to speak first...")
                        user_text = "You continue speaking."
                        silence_elapsed_seconds = 0.0
                    else:
                        continue

        if regenerating:
            print("   [Debug] Logic: Fetching history for regeneration...")
            if conversation_history and conversation_history[-1]["role"] == "assistant":
                conversation_history.pop()
            if conversation_history and conversation_history[-1]["role"] in _input_history_roles():
                existing_turn = dict(conversation_history[-1] or {})
                user_text = str(existing_turn.get("content", "") or "")
                resumed_loaded_turn = {
                    "role": str(existing_turn.get("role", "user") or "user"),
                    "content": user_text,
                    "origin": str(existing_turn.get("origin", "input") or "input"),
                }
                attachment_image_path = str(existing_turn.get("attachment_image_path", "") or "").strip()
                if attachment_image_path:
                    resumed_loaded_turn["attachment_image_path"] = attachment_image_path
                    resumed_loaded_turn["attachment_source"] = str(existing_turn.get("attachment_source", "image") or "image")
            elif conversation_history and conversation_history[-1]["role"] == "assistant":
                user_text = CONTINUE_ASSISTANT_SENTINEL
                resumed_loaded_turn = None
            else:
                user_text = "You continue speaking."
            _request_chat_view_rebuild()
            regenerating = False

        # =================================================================================
        # PHASE 2: THINKING
        # =================================================================================
        if user_text:
            response_text_is_replay = False
            stream_state = None
            active_ctrl = None
            assistant_history_added = False
            discard_assistant_history = False
            thinking_actions = _plan_phase2_actions(user_text)
            is_proactive = bool(conversation_controller.state.is_proactive_turn)
            preserve_proactive_placeholder = bool(conversation_controller.state.preserve_proactive_placeholder)
            dry_run_reply_id = dry_run.begin_reply(
                RUNTIME_CONFIG,
                streamed=bool(RUNTIME_CONFIG.get("stream_mode", False)),
                proactive=is_proactive,
            )

            for action in thinking_actions:
                if action.type == ConversationActionType.APPEND_HISTORY:
                    role = str(action.payload.get("role", "user") or "user")
                    content = str(action.payload.get("content", user_text) or user_text)
                    is_placeholder = bool(action.payload.get("placeholder", False))
                    if resumed_loaded_turn and not is_placeholder:
                        resumed_role = str(resumed_loaded_turn.get("role", "") or "").strip().lower()
                        resumed_content = str(resumed_loaded_turn.get("content", "") or "")
                        if role == resumed_role and content == resumed_content:
                            resumed_loaded_turn = None
                            continue
                    resumed_loaded_turn = None
                    if is_placeholder:
                        print(f"🧠 Regenerating proactive thought... ({role})")
                    elif role == "system":
                        print(f"💬 You (system): {content}")
                    elif role == "assistant":
                        print(f"💬 You (assistant): {content}")
                    else:
                        print(f"💬 You: {content}")
                    input_turn = {"role": role, "content": content, "origin": "input"}
                    if role == "user" and not is_placeholder and pending_next_user_attachment:
                        attachment_image_path = str(pending_next_user_attachment.get("attachment_image_path", "") or "").strip()
                        attachment_source = str(pending_next_user_attachment.get("attachment_source", "image") or "image")
                        clipboard_source_enabled = "clipboard" in _sensory_feedback_sources()
                        if attachment_source == "clipboard" and not clipboard_source_enabled:
                            print("📋 [Clipboard] Skipped pending clipboard image because Clipboard source is disabled.")
                        elif attachment_image_path:
                            input_turn["attachment_image_path"] = attachment_image_path
                            input_turn["attachment_source"] = attachment_source
                            print(f"📋 [Clipboard] Attached pending clipboard image to current user turn: {attachment_image_path}")
                        clear_pending_user_image_attachment()
                    conversation_history.append(input_turn)

                elif action.type == ConversationActionType.START_LLM_STREAM:
                    print("⚡ Stream mode enabled...")
                    stream_text_queue = queue.Queue()
                    stream_state = start_streamed_llm_reply(stream_text_queue, dry_run_reply_id=dry_run_reply_id)
                    active_ctrl = speak_async_stream(stream_text_queue, dry_run_reply_id=dry_run_reply_id)
                    conversation_controller.on_stream_started()
                    response_text = None

                elif action.type == ConversationActionType.START_LLM_REQUEST:
                    response_text = finalize_assistant_reply(chat_with_llm())
                    reply_actions = conversation_controller.on_assistant_reply(response_text)
                    for reply_action in reply_actions:
                        if reply_action.type == ConversationActionType.POP_LAST_HISTORY:
                            _pop_last_proactive_placeholder(user_text)

                    if not response_text:
                        _clear_active_hidden_proactive_candidate()
                        dry_run.finalize_reply(dry_run_reply_id)
                        user_text = None
                        continue

                    last_assistant_text = response_text
                    conversation_history.append({"role": "assistant", "content": response_text, "origin": "assistant_reply"})
                    assistant_history_added = True
                    _apply_stored_chat_history_limit()
                    _clear_active_hidden_proactive_candidate()

                    if is_proactive:
                        user_text = None

        # =================================================================================
        # PHASE 3: SPEAKING (TTS PLAYBACK)
        # =================================================================================
        if response_text or active_ctrl:
            listening_active.set()
            microphone_active.clear()
            ctrl = active_ctrl
            if response_text:
                if response_text_is_replay:
                    if response_text_replay_kind == "session":
                        print(f"🔁 Replaying chat session message {current_replay_position}/{max(current_replay_total, 1)}...")
                    else:
                        print("🔁 Replaying latest assistant reply...")
                else:
                    print(f"🤖 Assistant: {response_text}")
                    print("------------------------------------------------------------------------------------------------------")
                    print("------------------------------------------------------------------------------------------------------")
                stop_playback.clear()
                set_seed(3918375115)
                ctrl = speak_async(sanitize_assistant_text_for_speech(response_text, preserve_emotion_tags=True), dry_run_reply_id=dry_run_reply_id)

            was_barge_in = False

            while (
                (audio_playing.is_set() or not ctrl.done.is_set() or (stream_state is not None and not stream_state.done.is_set()))
                and not stop_flag.is_set()
            ):
                if stream_state is not None and stream_state.done.is_set() and not assistant_history_added:
                    response_text = finalize_assistant_reply((stream_state.full_text or "").strip())
                    if stream_state.error and not response_text:
                        response_text = "I'm having trouble thinking right now."
                    reply_actions = conversation_controller.on_assistant_reply(response_text)
                    for reply_action in reply_actions:
                        if reply_action.type == ConversationActionType.POP_LAST_HISTORY:
                            _pop_last_proactive_placeholder(user_text)
                    if response_text:
                        print(f"🤖 Assistant: {response_text}")
                        print("------------------------------------------------------------------------------------------------------")
                        print("------------------------------------------------------------------------------------------------------")
                        last_assistant_text = response_text
                        conversation_history.append({"role": "assistant", "content": response_text, "origin": "assistant_reply"})
                        _apply_stored_chat_history_limit()
                        assistant_history_added = True
                    _clear_active_hidden_proactive_candidate()
                    if is_proactive:
                        user_text = None
                status = check_interaction_status(source)

                # --- ACTION: SKIP / STOP ---
                if status == "skip_speech":
                    print("\n⏭️ Skipping speech...")
                    stop_playback.set()
                    if stream_state is not None:
                        stream_state.cancel_requested.set()
                    # We don't mark as interrupted for history purposes on skip
                    # (Usually you want the full text in history even if you skipped reading it)
                    pending_replay_text = None
                    pending_replay_sequence = []
                    break

                # --- ACTION: REGENERATE ---
                elif status == "regenerate_response":
                    print("\n🎲 Cutting speech to regenerate...")
                    stop_playback.set()
                    if stream_state is not None:
                        stream_state.cancel_requested.set()
                    discard_assistant_history = True
                    regenerating = True
                    pending_replay_text = None
                    pending_replay_sequence = []
                    break

                    # --- ACTION: RETRY USER ---
                elif status == "retry_user_input":
                    print("\nscrapped last input, listening again...")
                    stop_playback.set()
                    if stream_state is not None:
                        stream_state.cancel_requested.set()
                    discard_assistant_history = True
                    if conversation_history and conversation_history[-1]["role"] == "assistant":
                        conversation_history.pop()
                    if conversation_history and conversation_history[-1]["role"] in _input_history_roles():
                        conversation_history.pop()
                    _request_chat_view_rebuild()
                    pending_replay_text = None
                    pending_replay_sequence = []
                    user_text = None
                    response_text = None
                    break

                elif status == "replay_last_assistant":
                    replay_source = str(last_assistant_text or "").strip()
                    if replay_source and replay_source != "I haven't said anything yet.":
                        print("\n🔁 Replaying latest assistant reply after current playback stops...")
                        stop_playback.set()
                        if stream_state is not None:
                            stream_state.cancel_requested.set()
                        pending_replay_sequence = []
                        pending_replay_text = replay_source
                        break
                    print("\n⚠️ No assistant reply available to replay yet.")

                elif _resolve_replay_session_start_index(status) is not None:
                    replay_start_index = _resolve_replay_session_start_index(status)
                    if _queue_replay_session_from(replay_start_index):
                        stop_playback.set()
                        if stream_state is not None:
                            stream_state.cancel_requested.set()
                        break

                # --- ACTION: BARGE-IN (Voice) ---
                elif status in {"barge_in", "push_to_talk"}:
                    if status == "push_to_talk":
                        print("\n🎙️ Push-to-talk interruption...")
                    else:
                        print(f"\n🛑 Barge-in! Listening...")
                    stop_playback.set()
                    if stream_state is not None:
                        stream_state.cancel_requested.set()

                    # 1. Capture what was spoken BEFORE we process the new input
                    # We grab this immediately so the controller state is fresh
                    spoken_so_far = response_text or ""  # Fallback
                    if hasattr(ctrl, "get_spoken_text"):
                        spoken_so_far = ctrl.get_spoken_text()

                    was_barge_in = True

                    # 2. Listen for the interruption
                    if status == "push_to_talk":
                        potential_text = listen_for_speech_push_to_talk(source)
                    else:
                        potential_text = listen_for_speech(source, timeout=0.6)

                    if potential_text:
                        print(f"⚡ Interrupted with: '{potential_text}'")

                        # 3. Update History using YOUR Logic
                        final_assistant = spoken_so_far.strip() + " ... (user interrupted)"

                        if conversation_history and conversation_history[-1]["role"] == "assistant":
                            conversation_history[-1]["content"] = final_assistant
                            print(f"   [History Update] Truncated to: \"{final_assistant}\"")
                        elif final_assistant.strip():
                            conversation_history.append({"role": "assistant", "content": final_assistant, "origin": "assistant_reply"})
                            assistant_history_added = True

                        discard_assistant_history = True
                        pending_replay_text = None
                        pending_replay_sequence = []
                        conversation_controller.on_barge_in_text(potential_text)
                        user_text = potential_text
                        response_text = None
                        break
                    else:
                        was_barge_in = False
                        listening_active.set()
                        break
                elif status == "pause_speech":
                    conversation_controller.on_pause_toggled()
                    if playback_paused.is_set():
                        playback_paused.clear()
                        last_resume_requested_at = time.time()
                        print("- - - RESUME REQUESTED - - -")
                    elif pause_after_chunk.is_set():
                        pause_after_chunk.clear()
                        print("- - - PAUSE AFTER CHUNK CANCELED - - -")
                    else:
                        pause_after_chunk.set()
                        print("- - - WILL PAUSE AFTER CURRENT CHUNK - - -")

                time.sleep(0.02)

            ctrl.done.wait(timeout=0.5)
            stop_playback.set()
            if stream_state is not None:
                stream_state.cancel_requested.set()
                stream_state.done.wait(timeout=1.0)
                if not assistant_history_added and not discard_assistant_history:
                    response_text = finalize_assistant_reply((stream_state.full_text or "").strip())
                    spoken_text = ctrl.get_spoken_text().strip() if hasattr(ctrl, "get_spoken_text") else ""
                    if not response_text and spoken_text:
                        response_text = spoken_text
                    if stream_state.error and not response_text:
                        response_text = "I'm having trouble thinking right now."
                    reply_actions = conversation_controller.on_assistant_reply(response_text)
                    for reply_action in reply_actions:
                        if reply_action.type == ConversationActionType.POP_LAST_HISTORY:
                            _pop_last_proactive_placeholder(user_text)
                    if response_text:
                        print(f"🤖 Assistant: {response_text}")
                        print("------------------------------------------------------------------------------------------------------")
                        print("------------------------------------------------------------------------------------------------------")
                        last_assistant_text = response_text
                        conversation_history.append({"role": "assistant", "content": response_text, "origin": "assistant_reply"})
                        _apply_stored_chat_history_limit()
                        assistant_history_added = True

            conversation_controller.on_speaking_finished()
            dry_run.finalize_reply(dry_run_reply_id)

            # FINALLY: Clear state
            if pending_replay_text or pending_replay_sequence:
                user_text = None
                response_text = None
                response_text_is_replay = False
                response_text_replay_kind = ""
                listening_active.clear()
                active_ctrl = None
                stream_state = None
                continue
            if regenerating:
                response_text = None
                response_text_is_replay = False
                response_text_replay_kind = ""
            elif was_barge_in and user_text:
                response_text = None
                response_text_is_replay = False
                response_text_replay_kind = ""
            else:
                user_text = None
                response_text = None
                response_text_is_replay = False
                response_text_replay_kind = ""
            listening_active.clear()
            active_ctrl = None
            stream_state = None


# ============================================================================
# AVATAR ADAPTER PATTERN
# ============================================================================
AvatarAdapter = avatar_runtime.AvatarAdapter


def _build_avatar_runtime_context():
    return avatar_runtime.AvatarRuntimeContext(
        runtime_config=RUNTIME_CONFIG,
        dependencies={
            "avatar_profile": AVATAR_PROFILE,
            "current_body_state": CURRENT_BODY_STATE,
            "edit_emotion_getter": lambda: EDIT_EMOTION,
            "force_edit_mode_getter": lambda: FORCE_EDIT_MODE,
            "hand_debug": HAND_DEBUG,
            "hand_calibration": HAND_CALIBRATION,
            "normalize_vam_root": normalize_vam_root,
            "derive_vam_bridge_root": derive_vam_bridge_root,
            "default_vam_root": DEFAULT_VAM_ROOT,
            "default_vam_emotion_preset_map": DEFAULT_VAM_EMOTION_PRESET_MAP,
            "default_vam_timeline_clip_map": DEFAULT_VAM_TIMELINE_CLIP_MAP,
            "audio_segment_cls": AudioSegment,
            "invalidate_available_emotion_names_fn": invalidate_available_emotion_names,
            "shared_state_module": shared_state,
            "log_memory_checkpoint_fn": log_musetalk_memory_checkpoint,
            "stop_flag_event": stop_flag,
            "stop_playback_event": stop_playback,
            "dry_run_module": dry_run,
        },
    )


def _create_fallback_avatar_adapter(mode, runtime_context):
    if mode == "none":
        return None
    if mode == "musetalk":
        from addons.musetalk_avatar.main import Addon as MuseTalkAvatarAddon

        return MuseTalkAvatarAddon()._create_adapter(runtime_context=runtime_context)
    if mode == "vam":
        from addons.vam_avatar.main import Addon as VaMAvatarAddon

        return VaMAvatarAddon()._create_adapter(runtime_context=runtime_context)
    from addons.vseeface_avatar.main import Addon as VSeeFaceAvatarAddon

    return VSeeFaceAvatarAddon()._create_adapter(runtime_context=runtime_context)


def create_avatar_adapter_for_mode(avatar_mode: str):
    """Create the selected avatar adapter from addon registry, then addon fallback."""
    mode = avatar_runtime.normalize_provider_id(avatar_mode, fallback="vseeface")
    runtime_context = _build_avatar_runtime_context()
    registered_adapter = avatar_runtime.create_avatar_adapter(mode, runtime_context=runtime_context)
    if registered_adapter is not None:
        return registered_adapter
    return _create_fallback_avatar_adapter(mode, runtime_context)


# ============================================================================
# ENTRY POINT (Refactored for GUI)
# ============================================================================
def run_companion(config_override=None):
    global avatar_gui, stop_flag, RUNTIME_CONFIG
    if config_override:
        RUNTIME_CONFIG.update(config_override)

    print("🚀 Starting Companion Engine...")
    print(
        "🔊 Audio devices: "
        f"input={RUNTIME_CONFIG.get('audio_input_device', 'Default Input')!r}, "
        f"output={RUNTIME_CONFIG.get('audio_output_device', 'Default Output')!r}"
    )
    stop_flag.clear()
    clear_avatar_stream_state()
    schedule_musetalk_runtime_cleanup(max_keep=0)
    seam_debug_dir = os.path.abspath(os.path.join("MuseTalk", "runtime", "seam_debug"))
    shutil.rmtree(seam_debug_dir, ignore_errors=True)
    os.makedirs(seam_debug_dir, exist_ok=True)

    setup_nltk()
    offline_replay_only = bool(RUNTIME_CONFIG.get("offline_replay_only", False))
    if offline_replay_only:
        print("🔁 Offline replay mode: skipping chat-provider startup check.")
    else:
        if not _chat_provider_connection_check():
            return

    avatar_mode = str(RUNTIME_CONFIG.get("avatar_mode", "vseeface") or "vseeface").strip().lower()
    selected_model_name = str(RUNTIME_CONFIG.get("model_name", "") or "").strip()
    chat_provider = _chat_provider()

    if avatar_mode == "musetalk" and not offline_replay_only and chat_provider == "lmstudio":
        unload_lmstudio_models()

    print(f"🔌 Connecting to Avatar Engine: {avatar_mode.upper()}...")
    try:
        avatar_gui = create_avatar_adapter_for_mode(avatar_mode)

        if avatar_gui is not None:
            avatar_gui.start()
            if stop_flag.is_set():
                shutdown_avatar_engine()
                return
            if avatar_mode == "musetalk":
                try:
                    avatar_gui.warm_up()
                except Exception as e:
                    print(f"⚠️ [MuseTalk] Warmup exception: {e}")
                if stop_flag.is_set():
                    shutdown_avatar_engine()
                    return
                set_musetalk_idle_state()
    except Exception as e:
        print(f"⚠️ Could not connect to Avatar Engine: {e}")
        avatar_gui = None

    if stop_flag.is_set():
        shutdown_avatar_engine()
        return

    if avatar_mode == "musetalk" and selected_model_name and not offline_replay_only and chat_provider == "lmstudio":
        load_lmstudio_model(selected_model_name)

    if not init_tts():
        print("✗ Failed to initialize TTS. Exiting.")
        return

    try:
        if offline_replay_only:
            print("🔁 Replay runtime ready (no microphone or Whisper initialization needed).")
            run_conversation_flow(None)
        else:
            print("Testing microphone...")
            try:
                with _open_configured_microphone() as source:
                    print("✓ Microphone ready")
            except Exception as e:
                print(f"✗ Microphone error: {e}")
                return
            main_loop()
    except Exception as e:
        print(f"CRITICAL ERROR IN LOOP: {e}")
    finally:
        listening_active.clear()
        microphone_active.clear()
        push_to_talk_gui_held.clear()
        print("🛑 Engine stopping...")
        shutdown_avatar_engine()
        print("👋 Engine Shutdown Complete.")


if __name__ == "__main__":
    try:
        run_companion()
    except KeyboardInterrupt:
        stop_flag.set()
