#!/usr/bin/env python3
"""
Voice Assistant: Microphone → LM Studio → ChatterboxTurboTTS
Standalone script for voice interaction with local LLM
"""
import queue
import os
import sys
import time
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
import torch
import sounddevice as sd
import numpy as np

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")
warnings.filterwarnings(
    "ignore",
    message=r".*pkg_resources is deprecated as an API.*",
    category=UserWarning,
)

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
from core import sensory, audio_story_runtime, avatar_hand_state, avatar_runtime, avatar_runtime_context, chat_providers, conversation_history as conversation_history_runtime, lmstudio_runtime, runtime_chat, runtime_files, runtime_hotkeys, runtime_paths, runtime_shutdown, speech_text, streaming_text, stt_runtime, text_chunking, text_tags, tts_runtime, audio_playback, user_image_turns
from core import expression_state
from core.addons import bootstrap_runtime
from core.addons.runtime_defaults import addon_runtime_defaults
from core.conversation_flow_v2 import ConversationActionType, ConversationPolicy, SystemClockRuntime, build_experimental_controller


def _configure_ffmpeg_tools():
    ffmpeg_bin = str(os.environ.get("NC_FFMPEG_BIN", "") or "").strip()
    if not ffmpeg_bin:
        ffmpeg_bin = str(Path(__file__).resolve().parent / "tools" / "ffmpeg" / "bin")
    bin_path = Path(ffmpeg_bin)
    ffmpeg_exe = bin_path / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    ffprobe_exe = bin_path / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not ffmpeg_exe.exists() or not ffprobe_exe.exists():
        return None
    current_path = os.environ.get("PATH", "")
    bin_text = str(bin_path)
    path_parts = [part for part in current_path.split(os.pathsep) if part]
    if bin_text not in path_parts:
        os.environ["PATH"] = bin_text + (os.pathsep + current_path if current_path else "")
    return ffmpeg_exe, ffprobe_exe


_FFMPEG_TOOLS = _configure_ffmpeg_tools()
from pydub import AudioSegment

if _FFMPEG_TOOLS is not None:
    AudioSegment.converter = str(_FFMPEG_TOOLS[0])
    AudioSegment.ffmpeg = str(_FFMPEG_TOOLS[0])
    AudioSegment.ffprobe = str(_FFMPEG_TOOLS[1])

_ORIGINAL_SUBPROCESS_POPEN = subprocess.Popen


class _AddonModuleProxy:
    def __init__(self, module_name):
        self._module_name = str(module_name or "")
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name):
        return getattr(self._load(), name)


musetalk_state = _AddonModuleProxy("addons.musetalk_avatar.state")


def _safe_text_mode_popen(*args, **kwargs):
    text_mode = bool(kwargs.get("text")) or bool(kwargs.get("universal_newlines"))
    if text_mode and kwargs.get("errors") is None:
        kwargs["errors"] = "replace"
    if text_mode and kwargs.get("encoding") is None and os.name == "nt":
        kwargs["encoding"] = locale.getpreferredencoding(False) or "utf-8"
    return _ORIGINAL_SUBPROCESS_POPEN(*args, **kwargs)


if getattr(subprocess.Popen, "__name__", "") != "_safe_text_mode_popen":
    subprocess.Popen = _safe_text_mode_popen


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
stt_model = None
stt_backend_name = None

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


def _normalize_hotkey_settings(raw=None, *, legacy_push_to_talk=None, legacy_manual=None, legacy_ui=None):
    return runtime_hotkeys.normalize_hotkey_settings(
        raw,
        legacy_push_to_talk=legacy_push_to_talk,
        legacy_manual=legacy_manual,
        legacy_ui=legacy_ui,
    )


def _sync_legacy_hotkey_runtime_keys(settings):
    payload = _normalize_hotkey_settings(settings)
    RUNTIME_CONFIG["hotkeys"] = payload
    RUNTIME_CONFIG["push_to_talk_hotkey"] = payload["push_to_talk"]
    RUNTIME_CONFIG["manual_action_hotkeys"] = dict(payload["manual_actions"])
    RUNTIME_CONFIG["ui_action_hotkeys"] = dict(payload["ui_actions"])
    return payload


def register_ui_hotkey_actions(actions=None, labels=None):
    defaults = runtime_hotkeys.register_ui_action_hotkeys(actions, labels)
    current = _normalize_ui_action_hotkeys(get_hotkey_settings().get("ui_actions", defaults))
    update_runtime_config("ui_action_hotkeys", current)
    return defaults


def get_hotkey_settings():
    return _normalize_hotkey_settings(
        RUNTIME_CONFIG.get("hotkeys", {}),
        legacy_push_to_talk=RUNTIME_CONFIG.get("push_to_talk_hotkey", DEFAULT_PUSH_TO_TALK_HOTKEY),
        legacy_manual=RUNTIME_CONFIG.get("manual_action_hotkeys", DEFAULT_MANUAL_ACTION_HOTKEYS),
        legacy_ui=RUNTIME_CONFIG.get("ui_action_hotkeys", DEFAULT_UI_ACTION_HOTKEYS),
    )


def get_push_to_talk_hotkey():
    configured = normalize_hotkey_text(get_hotkey_settings().get("push_to_talk", DEFAULT_PUSH_TO_TALK_HOTKEY))
    return configured or DEFAULT_PUSH_TO_TALK_HOTKEY


def get_manual_action_hotkeys():
    return _normalize_manual_action_hotkeys(get_hotkey_settings().get("manual_actions", DEFAULT_MANUAL_ACTION_HOTKEYS))


def get_ui_action_hotkeys():
    return _normalize_ui_action_hotkeys(get_hotkey_settings().get("ui_actions", DEFAULT_UI_ACTION_HOTKEYS))


def get_hotkey_bindings():
    bindings = {"push_to_talk": get_push_to_talk_hotkey()}
    bindings.update(get_manual_action_hotkeys())
    bindings.update(get_ui_action_hotkeys())
    return bindings


def set_push_to_talk_hotkey(binding):
    update_runtime_config("push_to_talk_hotkey", binding)
    return get_push_to_talk_hotkey()


def set_hotkey_settings(settings):
    update_runtime_config("hotkeys", settings)
    return get_hotkey_settings()


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
Valid Tags: [neutral], [sad], [angry]

VOICE SOUNDS (Action-based):
Insert one of these tags to express a vocal emotion at any given moment.
Valid Tags: [laugh], [chuckle], [sigh], [groan], [gasp], [clear throat], [sniff]

Example of how to use tags in a sentence:
"[angry] You did what? [laugh] [sad] Oh my god, are you okay? [neutral] Or just clumsy?"

Do NOT use emojis when speaking!"""

DEFAULT_SENSORY_PINGPONG_PROMPT = """You are NC's hidden sensory ping/pong layer. The user never sees this exchange.
You receive hidden sensory PINGs and must return JSON only, with no prose or markdown.
Schema: {"keep": boolean, "emotion": string, "attention": string, "summary": string, "proactive_candidate": string, "visual_candidate": string, "should_speak": boolean, "should_generate_image": boolean, "tags": [string]}.

General rules:
- Return exactly one JSON object and nothing else.
- Use the exact schema keys, in double quotes. Do not invent variants such as "visual Candidate", "visualCandidate", or "should generate image".
- Quote all string keys and string values with standard double quotes. Do not use markdown, smart quotes, comments, or bare keys.
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
- Never copy, paraphrase, or continue a prior proactive_candidate or recent Assistant reply. Each proactive_candidate must be newly grounded in the current PING's visible content and current summary.
- If the current screen/content changed but you cannot form a new comment about the new content, set should_speak=false and proactive_candidate="".
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
  {"keep": true, "emotion": "angry", "attention": "unexpected event", "summary": "A sudden change needs NC's attention.", "proactive_candidate": "I noticed something changed and want to react to it.", "visual_candidate": "", "should_speak": true, "should_generate_image": false, "tags": []}
- Image-generation shape example:
  {"keep": true, "emotion": "sad", "attention": "screen", "summary": "A source-specific cue suggests generating an image.", "proactive_candidate": "", "visual_candidate": "concise source-grounded image prompt", "should_speak": false, "should_generate_image": true, "tags": []}
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


def _addon_runtime_defaults():
    return addon_runtime_defaults(Path(__file__).resolve().parent, environ=os.environ)


def _invoke_bootstrap_addon_capability(addon_id, capability, payload=None, default=None):
    return bootstrap_runtime.invoke_addon_capability(
        addon_id,
        capability,
        payload or {},
        app_root=Path(__file__).resolve().parent,
        default=default,
    )


def _create_visual_reply_engine_bridge():
    return _invoke_bootstrap_addon_capability(
        "nc.visual_reply",
        "runtime.engine_bridge",
        {
            "config_getter": lambda: RUNTIME_CONFIG,
            "environ": os.environ,
            "output_dir": Path(__file__).resolve().parent / "runtime" / "visual_replies",
        },
    )


def _invoke_musetalk_pack_capability(capability, payload=None, default=None):
    return _invoke_bootstrap_addon_capability(
        "nc.musetalk_avatar",
        capability,
        payload or {},
        default=default,
    )


def _active_avatar_vram_mode(default="quality"):
    avatar_mode = str(RUNTIME_CONFIG.get("avatar_mode", "") or "").strip().lower()
    if avatar_mode:
        value = _invoke_avatar_addon_capability(
            avatar_mode,
            "runtime.vram_mode",
            {
                "runtime_config": RUNTIME_CONFIG,
                "default": default,
            },
            default="",
        )
        if value:
            return str(value or default).strip().lower()
    return str(RUNTIME_CONFIG.get("avatar_vram_mode", RUNTIME_CONFIG.get("vram_mode", default)) or default).strip().lower()


def _normalized_abs_path(raw_path):
    return runtime_paths.normalized_abs_path(raw_path)


def _path_endswith_parts(path_value, *parts):
    return runtime_paths.path_endswith_parts(path_value, *parts)


_AVATAR_ADDON_MODULE_CACHE = {}
_AVATAR_PROVIDER_FOLDER_CACHE = {}


def _avatar_addon_folder_for_provider(provider_id):
    provider = avatar_runtime.normalize_provider_id(provider_id, fallback="")
    if not provider:
        return ""
    if provider in _AVATAR_PROVIDER_FOLDER_CACHE:
        return _AVATAR_PROVIDER_FOLDER_CACHE[provider]
    addons_root = Path(__file__).resolve().parent / "addons"
    for manifest_path in sorted(addons_root.glob("*/addon.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for service in list(payload.get("services") or []):
            if not isinstance(service, dict):
                continue
            if str(service.get("id") or "").strip() != "avatar_provider_registry":
                continue
            if str(service.get("provider_id") or "").strip().lower() == provider:
                folder = manifest_path.parent.name
                _AVATAR_PROVIDER_FOLDER_CACHE[provider] = folder
                return folder
    _AVATAR_PROVIDER_FOLDER_CACHE[provider] = ""
    return ""


def _load_avatar_addon_module(provider_id):
    folder = _avatar_addon_folder_for_provider(provider_id)
    if not folder:
        return None
    if folder in _AVATAR_ADDON_MODULE_CACHE:
        return _AVATAR_ADDON_MODULE_CACHE[folder]
    module_path = Path(__file__).resolve().parent / "addons" / folder / "main.py"
    if not module_path.exists():
        return None
    module_name = f"_nc_engine_avatar_bootstrap_{folder}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _AVATAR_ADDON_MODULE_CACHE[folder] = module
    return module


def _invoke_avatar_addon_capability(provider_id, capability, payload=None, default=None):
    module = _load_avatar_addon_module(provider_id)
    addon_cls = getattr(module, "Addon", None) if module is not None else None
    if addon_cls is None:
        return default
    try:
        addon = addon_cls()
        result = addon.invoke_capability(capability, payload or {})
    except Exception:
        logging.getLogger(__name__).exception("Avatar addon capability failed: %s/%s", provider_id, capability)
        return default
    return default if result is None else result


def _vam_config():
    return _invoke_avatar_addon_capability("vam", "runtime.vam_config", default={}) or {}


def _detect_default_vam_root():
    fn = _vam_config().get("detect_default_root")
    if callable(fn):
        return fn()
    return runtime_paths.detect_default_vam_root(app_root=Path(__file__).resolve().parent, environ=os.environ)


def derive_vam_bridge_root(vam_root):
    fn = _vam_config().get("derive_bridge_root")
    if callable(fn):
        return fn(vam_root)
    return runtime_paths.derive_vam_bridge_root(vam_root, app_root=Path(__file__).resolve().parent)


def derive_vam_plugin_dir(vam_root):
    fn = _vam_config().get("derive_plugin_dir")
    if callable(fn):
        return fn(vam_root)
    return runtime_paths.derive_vam_plugin_dir(vam_root)


DEFAULT_VAM_ROOT = _vam_config().get("default_root") or _detect_default_vam_root()
LEGACY_VAM_BRIDGE_ROOTS = tuple(_vam_config().get("legacy_bridge_roots") or runtime_paths.legacy_vam_bridge_roots(app_root=Path(__file__).resolve().parent))


def normalize_vam_root(raw_value=None, migrate_legacy=True):
    fn = _vam_config().get("normalize_root")
    if callable(fn):
        return fn(raw_value, migrate_legacy=migrate_legacy)
    return runtime_paths.normalize_vam_root(
        raw_value,
        default_vam_root=DEFAULT_VAM_ROOT,
        legacy_roots=LEGACY_VAM_BRIDGE_ROOTS,
        migrate_legacy=migrate_legacy,
    )


def normalize_vam_bridge_root(raw_value=None, migrate_legacy=True):
    fn = _vam_config().get("normalize_bridge_root")
    if callable(fn):
        return fn(raw_value, migrate_legacy=migrate_legacy)
    return runtime_paths.normalize_vam_bridge_root(
        raw_value,
        app_root=Path(__file__).resolve().parent,
        default_vam_root=DEFAULT_VAM_ROOT,
        legacy_roots=LEGACY_VAM_BRIDGE_ROOTS,
        migrate_legacy=migrate_legacy,
    )


DEFAULT_VAM_EMOTION_PRESET_MAP = dict(_vam_config().get("default_emotion_preset_map") or {
    "neutral": "nc_neutral",
    "happy": "nc_happy",
    "angry": "nc_angry",
    "sad": "nc_sad",
    "surprised": "nc_surprised",
    "shy": "nc_shy",
    "default": "nc_neutral",
})
DEFAULT_VAM_TIMELINE_CLIP_MAP = dict(_vam_config().get("default_timeline_clip_map") or {
    "happy": "talk_happy",
    "angry": "talk_angry",
    "sad": "talk_sad",
    "surprised": "talk_surprised",
    "shy": "talk_shy",
    "default": "talk_default",
})
DEFAULT_VAM_BRIDGE_ROOT = _vam_config().get("default_bridge_root") or derive_vam_bridge_root(DEFAULT_VAM_ROOT)

_visual_reply_bridge = _create_visual_reply_engine_bridge()
VISUAL_REPLY_STORY_THEME_PRESETS = tuple(getattr(_visual_reply_bridge, "VISUAL_REPLY_STORY_THEME_PRESETS", ()) or ())


def _default_visual_reply_story_theme_prompts():
    if _visual_reply_bridge is not None:
        return _visual_reply_bridge.default_story_theme_prompts()
    return {}

RUNTIME_CONFIG = {
    "active_preset_name": "",
    "model_name": "",
    "model_requires_vision": False,
    "model_supports_images": None,
    "model_supports_reasoning": False,
    "model_supports_reasoning_toggle": False,
    "chat_provider": os.environ.get("NC_CHAT_PROVIDER", chat_providers.DEFAULT_PROVIDER_ID),
    "chat_provider_settings": {},
    "chat_provider_generation_settings": {},
    "emotional_instructions": DEFAULT_EMOTIONAL_INSTRUCTIONS,
    "system_prompt": "You are Echo, a witty and helpful AI companion. Keep answers concise.",
    "voice_path": "",
    "chat_replay_role_voices": {},
    "stt_backend": "whisper_english",
    "stt_model_size": "tiny.en",
    "stt_language": "en",
    "tts_backend": "chatterbox",
    "chatterbox_multilingual_language": "en",
    "chatterbox_multilingual_apply_watermark": True,
    "tts_prewarm_on_start": True,
    "tts_use_cloned_voice": True,
    "tts_apply_watermark": True,
    "pocket_tts_python": DEFAULT_POCKET_TTS_PYTHON if os.path.exists(DEFAULT_POCKET_TTS_PYTHON) else "",
    "pocket_tts_language": "en",
    "pocket_tts_temperature": 0.7,
    "pocket_tts_lsd_decode_steps": 1,
    "pocket_tts_eos_threshold": -4.0,
    "pocket_tts_max_tokens": 50,
    "pocket_tts_frames_after_eos": 0,
    "pocket_tts_builtin_voice": "auto",
    "pocket_tts_use_cloned_voice": True,
    "pocket_tts_prewarm_on_start": True,
    "avatar_mode": "vseeface",
    "vam_root": DEFAULT_VAM_ROOT,
    "vam_bridge_root": DEFAULT_VAM_BRIDGE_ROOT,
    "vam_emotion_preset_map": _env_json_dict("NC_VAM_EMOTION_PRESET_MAP", DEFAULT_VAM_EMOTION_PRESET_MAP),
    "vam_timeline_clip_map": _env_json_dict("NC_VAM_TIMELINE_CLIP_MAP", DEFAULT_VAM_TIMELINE_CLIP_MAP),
    "input_mode": "voice_activation",
    "show_all_audio_input_devices": False,
    "hotkeys": runtime_hotkeys.normalize_hotkey_settings(),
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
    "stream_chunk_target_chars": 80,
    "stream_chunk_max_chars": 185,
    "stream_first_chunk_min_chars": STREAM_FIRST_CHUNK_MIN_CHARS,
    "stream_force_flush_seconds": STREAM_FORCE_FLUSH_SECONDS,
    "stream_force_flush_later_seconds": STREAM_FORCE_FLUSH_LATER_SECONDS,
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "min_p": 0.05,
    "repeat_penalty": 1.15,
    "limit_response_length": False,
    "max_response_tokens": 600,
    "allow_proactive_replies": False,
    "require_first_user_before_proactive": False,
    "listen_idle_window_seconds": 5.0,
    "proactive_delay_seconds": 10.0,
    **_addon_runtime_defaults(),
    "visual_reply_story_theme_prompts": _default_visual_reply_story_theme_prompts(),
    "sensory_feedback_source": os.environ.get("NC_SENSORY_FEEDBACK_SOURCE", "off"),
    "sensory_feedback_interval_seconds": float(os.environ.get("NC_SENSORY_FEEDBACK_INTERVAL_SECONDS", "7.0") or 7.0),
    "sensory_pingpong_enabled": str(os.environ.get("NC_SENSORY_PINGPONG_ENABLED", "0") or "0").strip().lower() in {"1", "true", "yes", "on"},
    "sensory_pingpong_history_depth": int(os.environ.get("NC_SENSORY_PINGPONG_HISTORY_DEPTH", "3") or 3),
    "sensory_pingpong_prompt": os.environ.get("NC_SENSORY_PINGPONG_PROMPT", DEFAULT_SENSORY_PINGPONG_PROMPT),
    "sensory_pingpong_source_prompts": {},
    "sensory_provider_metadata_overrides": {},
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
HAND_DEBUG = avatar_hand_state.HAND_DEBUG
HAND_CALIBRATION = avatar_hand_state.HAND_CALIBRATION

def update_runtime_config(key, value):
    """Called by GUI to update settings in real-time"""
    global RUNTIME_CONFIG
    if key in RUNTIME_CONFIG:
        if key == "hotkeys":
            _sync_legacy_hotkey_runtime_keys(value)
            return
        if key == "push_to_talk_hotkey":
            value = normalize_hotkey_text(value) or DEFAULT_PUSH_TO_TALK_HOTKEY
            settings = get_hotkey_settings()
            settings["push_to_talk"] = value
            _sync_legacy_hotkey_runtime_keys(settings)
            return
        elif key == "manual_action_hotkeys":
            value = _normalize_manual_action_hotkeys(value)
            settings = get_hotkey_settings()
            settings["manual_actions"] = value
            _sync_legacy_hotkey_runtime_keys(settings)
            return
        elif key == "ui_action_hotkeys":
            value = _normalize_ui_action_hotkeys(value)
            settings = get_hotkey_settings()
            settings["ui_actions"] = value
            _sync_legacy_hotkey_runtime_keys(settings)
            return
        elif key == "chat_provider":
            value = chat_providers.normalize_provider_id(value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        elif key == "chat_provider_settings":
            value = dict(value or {})
        elif key == "chat_replay_role_voices":
            value = _normalize_chat_replay_role_voices(value)
        elif key == "musetalk_enabled_pack_emotions":
            value = _normalize_musetalk_enabled_pack_emotions(value)
        RUNTIME_CONFIG[key] = value
        if key == "chat_provider_settings":
            chat_providers.set_provider_settings(value)
        if key in {"musetalk_avatar_pack_id", "musetalk_enabled_pack_emotions"}:
            invalidate_available_emotion_names()


def _normalize_musetalk_enabled_pack_emotions(value):
    return _invoke_musetalk_pack_capability(
        "runtime.normalize_enabled_pack_emotions",
        {"value": value},
        default={},
    )


def get_musetalk_enabled_pack_emotions(pack_id):
    return _invoke_musetalk_pack_capability(
        "runtime.enabled_pack_emotions",
        {
            "runtime_config": RUNTIME_CONFIG,
            "pack_id": pack_id,
        },
        default=None,
    )


# ============================================================================
# GLOBAL STATE
# ============================================================================
LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LMSTUDIO_API_KEY = "lm-studio"
chat_providers.set_provider_settings(RUNTIME_CONFIG.get("chat_provider_settings", {}))
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
manual_pause_active = threading.Event()
last_resume_requested_at = 0.0
last_resumed_at = 0.0
avatar_gui = None
tts_model = None
tts_backend_name = None
_shutdown_avatar_engine_lock = threading.RLock()
recognizer = sr.Recognizer()
conversation_history = []
sent_tokenize = None
PENDING_GUI_ACTION = None
_musetalk_cleanup_lock = threading.Lock()
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
    "last_proactive_candidate_key": "",
    "last_proactive_candidate_at": 0.0,
    "last_visual_key": "",
    "last_visual_at": 0.0,
    "last_screen_subject_comment_key": "",
    "last_screen_supervisor_meaningful_key": "",
    "last_screen_supervisor_meaningful_subject": "",
    "last_screen_supervisor_meaningful_trigger": "",
}
_addon_event_publisher = None
_addon_manager_getter = None
_chat_runtime = runtime_chat.ChatProviderRuntime(lambda: RUNTIME_CONFIG)


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


def _collect_addon_chat_contexts(model_history_window):
    manager = _get_addon_manager()
    if manager is None:
        return []
    invoke_all = getattr(manager, "invoke_all_capabilities", None)
    if not callable(invoke_all):
        return []
    try:
        results = invoke_all(
            "chat_context.collect",
            {
                "messages": list(model_history_window or []),
                "active_preset_name": str(RUNTIME_CONFIG.get("active_preset_name", "") or ""),
            },
        )
    except Exception as exc:
        print(f"⚠️ [Addons] Chat context collection failed: {exc}")
        return []

    contexts = []
    for result in list(results or []):
        if isinstance(result, str):
            text = result.strip()
            debug = {}
        elif isinstance(result, dict):
            text = str(result.get("context") or "").strip()
            debug = dict(result.get("debug") or {})
        else:
            continue
        if not text:
            continue
        contexts.append({"context": text, "debug": debug})
    return contexts


def _invoke_addon_capability(capability, payload=None):
    manager = _get_addon_manager()
    if manager is None:
        return None
    invoker = getattr(manager, "invoke_capability", None)
    if not callable(invoker):
        return None
    try:
        return invoker(str(capability or ""), dict(payload or {}))
    except Exception as exc:
        print(f"⚠️ [Addons] Capability '{capability}' failed: {exc}")
        return None


def _addon_voice_route(payload=None):
    route = _invoke_addon_capability("tts.voice_route", payload or {})
    return dict(route or {}) if isinstance(route, dict) else {}


def _addon_voice_segment_result(payload=None):
    result = _invoke_addon_capability("tts.voice_segments", payload or {})
    if isinstance(result, dict):
        raw_segments = result.get("segments")
        suppress_original = bool(result.get("suppress_original", False))
    elif isinstance(result, list):
        raw_segments = result
        suppress_original = False
    else:
        raw_segments = []
        suppress_original = False
    segments = []
    for raw in list(raw_segments or []):
        if not isinstance(raw, dict):
            continue
        piece_text = str(raw.get("text", "") or "").strip()
        if not piece_text:
            continue
        item = dict(raw)
        item["text"] = piece_text
        if item.get("voice_path"):
            item["voice_path"] = _resolve_voice_reference_path(item.get("voice_path", "")) or ""
        segments.append(item)
    return segments, suppress_original


def _addon_voice_segments(payload=None):
    segments, _suppress_original = _addon_voice_segment_result(payload)
    return segments


def _expand_addon_voice_segments(source_iterable, *, streaming=False, voice_path_override=""):
    last_stream_text = ""
    stream_source_index = 0
    for source_item in source_iterable:
        if voice_path_override or isinstance(source_item, dict):
            if streaming and isinstance(source_item, dict):
                text, deduped = _dedupe_adjacent_tts_stream_text(last_stream_text, source_item.get("text", ""))
                if deduped:
                    source_item = dict(source_item)
                    source_item["text"] = text
                if not str(text or "").strip():
                    continue
                last_stream_text = str(text)
                stream_source_index += 1
            yield source_item
            continue
        piece_text = str(source_item or "")
        route_payload = {
            "text": piece_text,
            "tts_backend": str(RUNTIME_CONFIG.get("tts_backend", "") or ""),
            "streaming": bool(streaming),
        }
        if streaming:
            route_payload["stream_start"] = stream_source_index == 0
            route_payload["stream_source_index"] = stream_source_index
        segments, suppress_original = _addon_voice_segment_result(route_payload)
        if streaming:
            stream_source_index += 1
        if segments:
            for segment in segments:
                if streaming:
                    text, deduped = _dedupe_adjacent_tts_stream_text(last_stream_text, segment.get("text", ""))
                    if deduped:
                        segment = dict(segment)
                        segment["text"] = text
                    if not str(text or "").strip():
                        continue
                    last_stream_text = str(text)
                yield segment
        elif suppress_original:
            continue
        else:
            if streaming:
                text, deduped = _dedupe_adjacent_tts_stream_text(last_stream_text, piece_text)
                if deduped:
                    source_item = text
                if not str(source_item or "").strip():
                    continue
                last_stream_text = str(source_item)
            yield source_item


def _notify_addon_assistant_reply(text):
    content = str(text or "").strip()
    if not content:
        return False
    result = _invoke_addon_capability("roleplay.assistant_reply", {"text": content})
    return result is not None


def _play_addon_story_audio_cues(cue_ids) -> bool:
    cues = [str(cue_id or "").strip() for cue_id in list(cue_ids or []) if str(cue_id or "").strip()]
    if not cues:
        return False
    result = _invoke_addon_capability("roleplay.play_audio_cues", {"cue_ids": cues})
    return result is not None


def _notify_addon_tts_segment_started(payload=None) -> bool:
    result = _invoke_addon_capability("tts.segment_started", payload or {})
    return result is not None


def list_available_tts_backends():
    return tts_runtime.list_available_tts_backends(_get_addon_manager, logger=print)


def list_available_stt_backends():
    return stt_runtime.list_available_stt_backends(_get_addon_manager, logger=print)


def _resolve_addon_tts_backend(backend_id: str):
    return tts_runtime.resolve_addon_tts_backend(backend_id, _get_addon_manager)


def _resolve_addon_stt_backend(backend_id: str):
    return stt_runtime.resolve_addon_stt_backend(backend_id, _get_addon_manager)


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


def _apply_chat_provider_generation_fields(params, additional_params, provider=None):
    _chat_runtime.apply_generation_fields(params, additional_params, provider=provider)


def _ensure_chat_provider_model_ready(provider, model):
    provider_id = chat_providers.normalize_provider_id(provider, fallback=chat_providers.DEFAULT_PROVIDER_ID)
    model_name = str(model or "").strip()
    if provider_id == "lmstudio" and model_name and not _is_model_catalog_placeholder(model_name):
        return load_lmstudio_model(model_name)
    return True


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
        base_url = str(chat_providers.get_provider_setting(provider, "base_url") or LMSTUDIO_BASE_URL)
        print(f"Checking {label} at {base_url}...")
        print("LM Studio note: open Developer -> Local Server and make sure Status is Running.")
    else:
        print(f"Checking {label} connectivity...")
    status = _chat_runtime.check_connection(provider)
    if status.ok:
        print(f"✓ {status.message}")
        return True
    print(f"✗ {status.message}")
    return False


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
    if os.path.isdir(runtime_dir):
        for name in os.listdir(runtime_dir):
            if not name.endswith((".tmp", ".part")):
                continue
            try:
                os.remove(os.path.join(runtime_dir, name))
            except Exception:
                pass
        sensory_dir = os.path.join(runtime_dir, "sensory_feedback")
        if os.path.isdir(sensory_dir):
            for name in os.listdir(sensory_dir):
                target = os.path.join(sensory_dir, name)
                try:
                    if os.path.isdir(target):
                        shutil.rmtree(target)
                    else:
                        os.remove(target)
                except Exception:
                    pass
    runtime_temp_dir = runtime_paths.runtime_temp_dir(create=True)
    for name in os.listdir(runtime_temp_dir):
        target = runtime_temp_dir / name
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
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
        if bool(RUNTIME_CONFIG.get("offline_replay_only", False)) and not _manual_action_allowed_during_replay(action):
            print(f"[Replay] Ignored unavailable replay action: {action}")
            return None
        return action

    # --- KEYBOARD SHORTCUTS ---
    for action, binding in get_manual_action_hotkeys().items():
        if is_hotkey_binding_pressed(binding):
            LAST_INPUT_TIME = now
            if bool(RUNTIME_CONFIG.get("offline_replay_only", False)) and not _manual_action_allowed_during_replay(action):
                print(f"[Replay] Ignored unavailable replay hotkey: {action}")
                return None
            return action

    input_mode = str(RUNTIME_CONFIG.get("input_mode", "voice_activation") or "voice_activation").lower()
    if source is not None and input_mode == "push_to_talk" and is_push_to_talk_held():
        LAST_INPUT_TIME = now
        return "push_to_talk"
    if input_mode == "text_only":
        return None

    # --- VOICE BARGE-IN ---
    if source is not None and input_mode != "push_to_talk" and check_for_barge_in(source, energy_threshold=BARGE_IN_THRESHOLD):
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


def _manual_action_allowed_during_replay(action):
    raw = str(action or "").strip()
    if raw in {"pause_speech", "skip_speech", "replay_last_assistant", "replay_chat_session"}:
        return True
    return parse_replay_chat_session_start_index(raw) is not None

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
AddonSTTBackendAdapter = stt_runtime.AddonSTTBackendAdapter


def init_stt():
    global stt_model, stt_backend_name
    state = stt_runtime.initialize_stt_backend(
        runtime_config=RUNTIME_CONFIG,
        current_model=stt_model,
        current_backend_name=stt_backend_name,
        addon_resolver=_resolve_addon_stt_backend,
        addon_adapter_cls=AddonSTTBackendAdapter,
        logger=print,
    )
    stt_model = state.model
    stt_backend_name = state.backend_name
    return bool(state.ok)


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


def play_audio_file(path: str, stop_event=None):
    class _PlaybackStopEvent:
        def is_set(self):
            try:
                return bool(stop_playback.is_set() or (stop_event is not None and stop_event.is_set()))
            except Exception:
                return bool(stop_playback.is_set())

    return audio_playback.play_audio_file(
        path,
        soundfile_module=sf,
        sounddevice_module=sd,
        stop_event=_PlaybackStopEvent(),
        audio_playing_event=audio_playing,
        output_device=_selected_sounddevice_output_index(),
        logger=print,
    )


def save_audio_file(path, wav, sample_rate):
    tensor = wav.detach().cpu() if hasattr(wav, "detach") else torch.as_tensor(wav).cpu()
    if tensor.ndim == 1:
        audio = tensor.numpy()
    else:
        audio = tensor.transpose(0, 1).contiguous().numpy()
    sf.write(str(path), audio, int(sample_rate))


def stream_musetalk_preview_frames(playback_state, stop_event):
    return _invoke_musetalk_pack_capability(
        "runtime.preview.stream_frames",
        {
            "playback_state": playback_state,
            "stop_event": stop_event,
            "runtime_config": RUNTIME_CONFIG,
        },
    )


def stream_delegated_audio_progress(playback_state, stop_event):
    return _invoke_musetalk_pack_capability(
        "runtime.preview.stream_delegated_audio_progress",
        {
            "playback_state": playback_state,
            "stop_event": stop_event,
        },
    )


def prime_musetalk_preview_frame(playback_state):
    return _invoke_musetalk_pack_capability(
        "runtime.preview.prime_frame",
        {
            "playback_state": playback_state,
            "runtime_config": RUNTIME_CONFIG,
        },
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
        except Exception as find_exc:
            try:
                print(f"Downloading NLTK {resource_name} tokenizer...")
                try:
                    nltk.download(resource_name, quiet=True, force=True)
                except TypeError:
                    nltk.download(resource_name, quiet=True)
                nltk.data.find(resource_path)
                print(f"✓ NLTK {resource_name} tokenizer downloaded")
            except Exception as e:
                print(f"⚠️ Failed to prepare NLTK {resource_name}, using fallback splitter: {find_exc}; {e}")

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


AddonTTSBackendAdapter = tts_runtime.AddonTTSBackendAdapter


def init_tts():
    global tts_model, tts_backend_name
    state = tts_runtime.initialize_tts_backend(
        runtime_config=RUNTIME_CONFIG,
        current_model=tts_model,
        current_backend_name=tts_backend_name,
        addon_resolver=_resolve_addon_tts_backend,
        addon_adapter_cls=AddonTTSBackendAdapter,
        logger=print,
    )
    tts_model = state.model
    tts_backend_name = state.backend_name
    if state.ok and tts_model is not None:
        warmer = getattr(tts_model, "warm_up", None)
        if callable(warmer):
            try:
                warmer()
            except Exception as exc:
                print(f"⚠️ TTS warmup failed: {exc}")
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


def get_avatar_chunk_limits_for_index(chunk_index: int):
    avatar_mode = str(RUNTIME_CONFIG.get("avatar_mode", "") or "").strip().lower()
    if avatar_mode and avatar_mode != "vseeface":
        value = _invoke_avatar_addon_capability(
            avatar_mode,
            "runtime.chunk_limits_for_index",
            {
                "chunk_index": chunk_index,
                "runtime_config": RUNTIME_CONFIG,
                "defaults": {
                    "quickstart": MUSE_QUICKSTART_CHUNK_LIMITS,
                    "target": MUSE_TARGET_CHARS_PER_CHUNK,
                    "max": MUSE_MAX_CHARS_PER_CHUNK,
                },
            },
            default=None,
        )
        if value:
            return value
    return (MUSE_TARGET_CHARS_PER_CHUNK, MUSE_MAX_CHARS_PER_CHUNK)


def intelligent_chunk_text_progressive(long_text: str, start_chunk_index: int = 0) -> list:
    return text_chunking.progressive_chunk_text(
        long_text,
        start_chunk_index=start_chunk_index,
        limit_getter=get_avatar_chunk_limits_for_index,
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

    avatars_root = os.path.abspath(os.path.join("MuseTalk", "results", "v15", "avatars"))
    try:
        names = _invoke_musetalk_pack_capability(
            "runtime.available_pack_emotion_names",
            {
                "runtime_config": RUNTIME_CONFIG,
                "default_names": list(DEFAULT_EMOTION_NAMES),
                "avatar_profile": AVATAR_PROFILE,
                "legacy_map": MUSE_EMOTION_AVATAR_MAP,
                "legacy_transitions": MUSE_AVATAR_TRANSITIONS,
                "avatars_dir": Path(avatars_root),
            },
            default=None,
        )
        if names is None:
            raise RuntimeError("MuseTalk pack runtime unavailable.")
    except Exception:
        names = set(DEFAULT_EMOTION_NAMES)
        try:
            names.update(str(key or "").strip().lower() for key in AVATAR_PROFILE.keys() if str(key or "").strip())
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
    return _visual_reply_bridge.looks_like_visual_reply_tag_prefix(fragment)


VISUAL_REPLY_TAG_RE = _visual_reply_bridge.VISUAL_REPLY_TAG_RE
VISUAL_REPLY_TAG_START_RE = _visual_reply_bridge.VISUAL_REPLY_TAG_START_RE
VISUAL_REPLY_OUTPUT_DIR = Path(__file__).resolve().parent / "runtime" / "visual_replies"
SENSORY_FEEDBACK_OUTPUT_DIR = Path(__file__).resolve().parent / "runtime" / "sensory_feedback"
VISUAL_REPLY_XAI_BASE_URL = _visual_reply_bridge.VISUAL_REPLY_XAI_BASE_URL
_sensory_feedback_lock = threading.Lock()
_sensory_feedback_state = {}


def _visual_reply_mode():
    return _visual_reply_bridge.mode()


def _visual_reply_enabled():
    return _visual_reply_bridge.enabled()


def _visual_reply_generation_available():
    return _visual_reply_bridge.generation_available()


def _visual_reply_story_mode_enabled():
    return _visual_reply_bridge.story_mode_enabled()


def _visual_reply_story_max_images():
    return _visual_reply_bridge.story_max_images()


def _visual_reply_story_continuity_strength():
    return _visual_reply_bridge.story_continuity_strength()


def _visual_reply_story_theme_prompts():
    return _visual_reply_bridge.story_theme_prompts()


def _visual_reply_story_theme_enabled():
    return _visual_reply_bridge.story_theme_enabled()


def _visual_reply_story_theme_suffix():
    return _visual_reply_bridge.story_theme_suffix()


def _visual_reply_master_style_prompt():
    return _visual_reply_bridge.master_style_prompt()


def _visual_reply_master_style_suffix():
    return _visual_reply_bridge.master_style_suffix()


def _visual_reply_master_prompt_safety_suffix():
    return _visual_reply_bridge.master_prompt_safety_suffix()


def _visual_reply_no_speech_bubbles_suffix():
    return _visual_reply_bridge.no_speech_bubbles_suffix()


def _apply_visual_reply_style_anchor(prompt_text: str):
    return _visual_reply_bridge.apply_style_anchor(prompt_text)


def _ensure_visual_reply_story_worker():
    return _visual_reply_bridge.ensure_story_worker()


def begin_visual_reply_story_session():
    return _visual_reply_bridge.begin_story_session()


def clear_visual_reply_story_queue():
    return _visual_reply_bridge.clear_story_queue()


def enqueue_visual_reply_story_generation(prompt: str, *, source_text: str = "", session_id: int | None = None, request_id: str | None = None):
    return _visual_reply_bridge.enqueue_story_generation(
        prompt,
        source_text=source_text,
        session_id=session_id,
        request_id=request_id,
    )


def _perform_visual_reply_generation(
    prompt_text: str,
    *,
    source_text: str = "",
    request_id: str | None = None,
    keep_current_image: bool = False,
):
    return _visual_reply_bridge.perform_generation(
        prompt_text,
        source_text=source_text,
        request_id=request_id,
        keep_current_image=keep_current_image,
    )


def _story_visual_reply_style_guide_from_text(story_text: str, continuity_strength: float = 0.8) -> str:
    return _visual_reply_bridge.story_style_guide_from_text(
        story_text,
        continuity_strength=continuity_strength,
    )


def _story_visual_reply_prompt_from_text(prompt_text: str, emotion: str = "", story_style_guide: str = "") -> str:
    return _visual_reply_bridge.story_prompt_from_text(
        prompt_text,
        emotion=emotion,
        story_style_guide=story_style_guide,
    )


def _next_visual_reply_request_id():
    return _visual_reply_bridge.next_request_id()


def _normalize_visual_reply_prompt_text(prompt_text: str) -> str:
    return _visual_reply_bridge.normalize_prompt_text(prompt_text)


def _strip_visual_reply_tail(text: str):
    return _visual_reply_bridge.strip_visual_reply_tail(text)


def extract_visual_reply_prompt(text: str):
    return _visual_reply_bridge.extract_visual_reply_prompt(text)


def _visual_reply_generation_instruction():
    if not _visual_reply_generation_available():
        return ""
    instruction = (
        "Visual reply capability is available. If the user explicitly asks you to generate, "
        "draw, create, show, or make an image or picture, "
        "append exactly one tag at the end of your reply in this form: "
        "[visualize: concise image prompt]. Keep the prompt concrete and under 180 characters. "
        "For image-only requests, keep the visible text reply to a brief acknowledgement. "
        "If the user also asks for text, answer that text request normally."
    )
    if _automatic_visual_reply_generation_allowed():
        instruction += " You may also use this sparingly when a generated image would meaningfully help."
    return instruction


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
        effective = _sensory_provider_effective_payload(source, provider=provider)
        instruction = str(effective.get("instruction") or "").strip()
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


def _hidden_sensory_pingpong_blocked():
    """Hidden PING/PONG should not run while chat playback is paused mid-reply."""
    return bool(
        microphone_active.is_set()
        or audio_playing.is_set()
        or _llm_request_active.is_set()
        or manual_pause_active.is_set()
        or pause_after_chunk.is_set()
        or playback_paused.is_set()
        or bool(RUNTIME_CONFIG.get("offline_replay_only", False))
    )


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


def _canonical_hidden_action_key(value):
    text = _sanitize_hidden_action_text(value, limit=220, lower=True)
    if not text:
        return ""
    text = re.sub(r"\[(?:neutral|sad|angry|laugh|chuckle|sigh|groan|gasp|clear throat|sniff)\]", " ", text)
    text = re.sub(r"[*_`~\"'“”‘’.,!?;:()\[\]{}<>/\\|-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_HIDDEN_SUBJECT_SIMILARITY_STOPWORDS = {
    "activity",
    "article",
    "browser",
    "browsing",
    "content",
    "current",
    "document",
    "editing",
    "image",
    "item",
    "page",
    "playing",
    "post",
    "screen",
    "scene",
    "show",
    "showing",
    "site",
    "the",
    "thread",
    "user",
    "video",
    "view",
    "visible",
    "watching",
    "webpage",
    "window",
}


def _hidden_subject_similarity_tokens(value):
    key = _canonical_hidden_action_key(value)
    return {
        word
        for word in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", key)
        if word not in _HIDDEN_SUBJECT_SIMILARITY_STOPWORDS
    }


def _hidden_subject_keys_are_similar(left, right):
    left_key = _canonical_hidden_action_key(left)
    right_key = _canonical_hidden_action_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if left_key in right_key or right_key in left_key:
        return True
    left_tokens = _hidden_subject_similarity_tokens(left_key)
    right_tokens = _hidden_subject_similarity_tokens(right_key)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    return overlap >= 2 and (overlap / max(1, smaller)) >= 0.5


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


def _clean_hidden_subject_identity(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^[\"'“”‘’]+|[\"'“”‘’.,;:]+$", "", text).strip()
    text = re.sub(
        r"\s+(?:on\s+[a-z0-9 _-]+|video|shorts item|post|thread|article|page|gameplay video|gameplay|full game walkthrough|early access menu|menu|paused|playing|with .*)$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(r"^(?:a|an|the|different|current)\s+", "", text, flags=re.IGNORECASE).strip()
    return text[:140]


def _extract_hidden_screen_subject_identity(summary="", attention=""):
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    if not text:
        return ""
    patterns = [
        r"\b(?:video|post|thread|article|page|item)\s*:\s*['\"“”‘’](?P<title>.+?)['\"“”‘’]\s+(?:by|from|featuring|showing|with|is|,|[.;]|$)",
        r"\b(?:video|post|thread|article|page|item)\s+(?:changed|switched)?\s*(?:to\s+)?['\"“”‘’](?P<title>.+?)['\"“”‘’]\s+(?:by|from|featuring|showing|with|is|,|[.;]|$)",
        r"\b(?:titled|called|named)\s+['\"“”‘’](?P<title>.+?)['\"“”‘’]\s+(?:by|from|featuring|showing|with|is|,|[.;]|$)",
        r"\b(?:video|post|thread|article|page|item)\s+by\s+.+?\s+(?:titled|called|named|on)\s+['\"“”‘’](?P<title>[^'\"“”‘’]+)['\"“”‘’]",
        r"\b(?:watching|viewing|browsing|reading|playing)\s+.+?\s+(?:video|post|thread|article|page|item)\s+['\"“”‘’](?P<title>[^'\"“”‘’]+)['\"“”‘’]",
        r"\b(?:video|post|thread|article|page|item)\s+['\"“”‘’](?P<title>[^'\"“”‘’]+)['\"“”‘’]",
        r"\b(?:screen\s+(?:now\s+)?shows\s+)?(?:a|an|the)?\s*(?:[a-z0-9_.-]+\s+)?(?:video|post|thread|article|page|item)\s+from\s+(?P<title>.+?)(?:\s+(?:now\s+)?(?:playing|shows|showing|featuring|with)|[.;]|$)",
        r"\bswitched\s+from\b.+?\bto\s+(?:watching|viewing|browsing|reading|playing|opening)?\s*(?:a|an|the)?\s*(?P<title>.+?)(?:\s+on\s+[a-z0-9 _-]+|\s+gameplay\s+video|\s+video|\s+post|\s+thread|\s+article|\s+page|\s+gameplay|\s+menu|[.;]|$)",
        r"\bdifferent\s+(?:video|post|thread|article|page|item|screen|game|app):\s*['\"“”‘’](?P<title>[^'\"“”‘’]+)['\"“”‘’]",
        r"\b(?:watching|viewing|browsing|reading|playing)\s+['\"“”‘’](?P<title>[^'\"“”‘’]+)['\"“”‘’]",
        r"\b(?:post|thread|video|article|page|item)\s+(?:titled|called|named)\s+['\"“”‘’](?P<title>[^'\"“”‘’]+)['\"“”‘’]",
        r"\b(?:watching|viewing|browsing|reading|playing)\s+(?:a|an|the)?\s*(?P<title>.+?)(?:\s+on\s+[a-z0-9 _-]+|\s+with\s+|\s*;|[.]|$)",
        r"\bshows\s+(?:[A-Za-z0-9_ -]+(?:'s|’s)\s+)?(?P<title>.+?)\s+video\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        title = _clean_hidden_subject_identity(match.group("title"))
        key = _canonical_hidden_action_key(title)
        if key:
            return key
    quoted = [
        _clean_hidden_subject_identity(item)
        for item in re.findall(r"['\"“”‘’]([^'\"“”‘’]{4,})['\"“”‘’]", text)
    ]
    quoted = [item for item in quoted if _canonical_hidden_action_key(item)]
    if quoted:
        return _canonical_hidden_action_key(quoted[-1])
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


def _queue_hidden_proactive_candidate(candidate, *, summary="", attention="", source="sensory", allow_repeated_candidate=False):
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
    candidate_key = "|".join(
        [
            request.get("source", "sensory"),
            _canonical_hidden_action_key(request.get("candidate", "")),
        ]
    )
    with sensory_pingpong_lock:
        now = time.time()
        last_key = str(sensory_hidden_action_state.get("last_proactive_key", "") or "")
        last_at = float(sensory_hidden_action_state.get("last_proactive_at", 0.0) or 0.0)
        if (
            not bool(allow_repeated_candidate)
            and request_key
            and request_key == last_key
            and (now - last_at) < 45.0
        ):
            print("🤐 [Sensory] Suppressed duplicate proactive candidate for unchanged hidden PONG.")
            return False
        last_candidate_key = str(sensory_hidden_action_state.get("last_proactive_candidate_key", "") or "")
        last_candidate_at = float(sensory_hidden_action_state.get("last_proactive_candidate_at", 0.0) or 0.0)
        if (
            not bool(allow_repeated_candidate)
            and candidate_key
            and candidate_key == last_candidate_key
            and (now - last_candidate_at) < 300.0
        ):
            print("🤐 [Sensory] Suppressed repeated proactive candidate without a new spoken cue.")
            return False
        sensory_hidden_action_state["pending_proactive"] = request
        sensory_hidden_action_state["last_proactive_key"] = request_key
        sensory_hidden_action_state["last_proactive_at"] = now
        sensory_hidden_action_state["last_proactive_candidate_key"] = candidate_key
        sensory_hidden_action_state["last_proactive_candidate_at"] = now
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
        tags = list(entry.get("tags", []) or [])
        if tags:
            parts.append(f"tags={', '.join([str(tag) for tag in tags[:6]])}")
        lines.append(" | ".join(parts))
    if not lines:
        return ""
    return (
        "Retained hidden sensory events below are ambient internal state, not user messages. "
        "Use them as latent context only when relevant. Do not reuse or continue earlier proactive wording.\n"
        + "\n".join(f"- {line}" for line in lines)
    )


def _hidden_proactive_candidate_reuses_recent_stale_text(candidate, summary):
    candidate_key = _canonical_hidden_action_key(candidate)
    if not candidate_key:
        return False
    summary_key = _canonical_hidden_action_key(summary)
    recent_events = []
    with sensory_pingpong_lock:
        recent_events = list(sensory_hidden_history or [])[-6:]
    for entry in reversed(recent_events):
        if not isinstance(entry, dict):
            continue
        previous_candidate = str(entry.get("proactive_candidate", "") or "").strip()
        if not previous_candidate:
            continue
        if _canonical_hidden_action_key(previous_candidate) != candidate_key:
            continue
        previous_summary_key = _canonical_hidden_action_key(entry.get("summary", ""))
        if summary_key and previous_summary_key and summary_key != previous_summary_key:
            return True
    return False


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
    repaired = repaired.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    repaired = re.sub(r'"visual\s+candidate"', '"visual_candidate"', repaired, flags=re.IGNORECASE)
    repaired = re.sub(r'"visualCandidate"', '"visual_candidate"', repaired, flags=re.IGNORECASE)
    repaired = re.sub(r'(?<!")\b(keep|emotion|attention|summary|proactive_candidate|visual_candidate|should_speak|should_generate_image|tags)\b\s*:', r'"\1":', repaired)
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


def _extract_sensory_string_field(text, *keys):
    raw = str(text or "").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    for key in keys:
        key_pattern = re.escape(str(key or "")).replace(r"\ ", r"\s+")
        match = re.search(
            rf'["\']?{key_pattern}["\']?\s*:?\s*(["\'])(?P<value>(?:\\.|(?!\1).)*?)\1',
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            value = match.group("value")
            if "\\" in value:
                value = value.replace(r"\"", '"').replace(r"\'", "'")
            return re.sub(r"\s+", " ", value).strip()
    return ""


def _extract_sensory_bool_field(text, *keys):
    raw = str(text or "").replace("“", '"').replace("”", '"')
    for key in keys:
        key_pattern = re.escape(str(key or "")).replace(r"\ ", r"\s+")
        match = re.search(
            rf'["\']?{key_pattern}["\']?\s*:?\s*(?P<value>true|false|yes|no|on|off|1|0)\b',
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return _normalize_boolish(match.group("value"))
    return False


def _extract_sensory_tags_field(text):
    raw = str(text or "").replace("“", '"').replace("”", '"')
    match = re.search(r'["\']?tags["\']?\s*:?\s*\[(?P<items>[^\]]*)\]', raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    tags = []
    for item in re.findall(r'(["\'])(?P<value>.*?)(?:\1)', match.group("items")):
        value = _sanitize_hidden_action_text(item[1], limit=80)
        if value and value not in tags:
            tags.append(value)
    return tags


def _coerce_sensory_pong_from_text(text):
    raw = str(text or "").strip()
    if not raw:
        return None
    summary = _extract_sensory_string_field(raw, "summary")
    proactive_candidate = _extract_sensory_string_field(raw, "proactive_candidate", "proactive candidate", "proactive")
    visual_candidate = _extract_sensory_string_field(raw, "visual_candidate", "visual candidate", "visualCandidate")
    emotion = _extract_sensory_string_field(raw, "emotion")
    attention = _extract_sensory_string_field(raw, "attention")
    should_speak = _extract_sensory_bool_field(raw, "should_speak", "should speak")
    should_generate_image = _extract_sensory_bool_field(raw, "should_generate_image", "should generate image", "visual_generate_image")
    keep = _extract_sensory_bool_field(raw, "keep")
    tags = _extract_sensory_tags_field(raw)
    if not any((summary, proactive_candidate, visual_candidate, emotion, attention, should_speak, should_generate_image, keep, tags)):
        return None
    return {
        "keep": keep,
        "emotion": emotion,
        "attention": attention,
        "summary": summary,
        "proactive_candidate": proactive_candidate,
        "visual_candidate": visual_candidate,
        "should_speak": should_speak,
        "should_generate_image": should_generate_image,
        "tags": tags,
    }


def _parse_sensory_pong(payload_text):
    payload = _extract_json_object_from_text(payload_text)
    repaired_payload = None
    if not isinstance(payload, dict):
        repaired_payload = _repair_common_json_mistakes(payload_text)
        if repaired_payload and repaired_payload != str(payload_text or ""):
            payload = _extract_json_object_from_text(repaired_payload)
    if not isinstance(payload, dict):
        payload = _coerce_sensory_pong_from_text(payload_text)
        if not isinstance(payload, dict):
            return None
        repaired_payload = str(payload_text or "")
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


def _sensory_provider_metadata_override_map():
    payload = RUNTIME_CONFIG.get("sensory_provider_metadata_overrides", {})
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _sensory_provider_effective_payload(provider_id, provider=None):
    provider_key = str(provider_id or "").strip().lower()
    provider = provider if provider is not None else sensory.get_provider(provider_key)
    base_metadata = dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}
    payload = {
        "label": str(getattr(provider, "label", provider_key) or provider_key),
        "instruction": str(getattr(provider, "instruction", "") or ""),
        "description": str(getattr(provider, "description", "") or ""),
        "metadata": base_metadata,
    }
    overrides = _sensory_provider_metadata_override_map().get(provider_key, {})
    if isinstance(overrides, dict):
        for key in ("label", "instruction", "description"):
            if key in overrides:
                payload[key] = str(overrides.get(key) or "")
        metadata_override = overrides.get("metadata", {})
        if isinstance(metadata_override, dict):
            merged_metadata = dict(base_metadata)
            merged_metadata.update(dict(metadata_override))
            payload["metadata"] = merged_metadata
    legacy_prompt = _sensory_pingpong_source_prompt_map().get(provider_key)
    if legacy_prompt is not None:
        metadata = dict(payload.get("metadata") or {})
        metadata["pingpong_prompt"] = str(legacy_prompt or "")
        payload["metadata"] = metadata
    return payload


def _sensory_metadata_lines(raw, *, name_key="field", description_key="description"):
    lines = []
    if isinstance(raw, (list, tuple, set)):
        for item in list(raw):
            if isinstance(item, dict):
                name = str(item.get(name_key) or item.get("field") or item.get("tag") or "").strip()
                description = str(item.get(description_key) or item.get("description") or item.get("action") or "").strip()
                text = name
                if name and description:
                    text = f"{name}: {description}"
                elif description:
                    text = description
            else:
                text = str(item or "").strip()
            if text and text not in lines:
                lines.append(text)
    return lines


def _sensory_pingpong_source_prompt_text(source_ids):
    fragments = []
    seen = set()
    normalized_source_ids = [str(item or "").strip().lower() for item in list(source_ids or []) if str(item or "").strip()]
    for source_id in normalized_source_ids:
        provider = sensory.get_provider(source_id)
        effective = _sensory_provider_effective_payload(source_id, provider=provider)
        metadata = dict(effective.get("metadata") or {})
        if metadata.get("prompt_fragment_enabled", True) is not False:
            label = str(effective.get("label") or source_id)
            fragment = str(metadata.get("pingpong_prompt") or "").strip()
            metadata_sections = []
            ping_payload = _sensory_metadata_lines(metadata.get("ping_payload", []))
            pong_influences = _sensory_metadata_lines(metadata.get("pong_influences", metadata.get("pong_outputs", [])))
            tag_subscriptions = _sensory_metadata_lines(metadata.get("tag_subscriptions", []), name_key="tag", description_key="action")
            if ping_payload:
                metadata_sections.append("Declared PING payload:\n" + "\n".join(f"- {line}" for line in ping_payload))
            if pong_influences:
                metadata_sections.append("May influence PONG:\n" + "\n".join(f"- {line}" for line in pong_influences))
            if tag_subscriptions:
                metadata_sections.append("Declared tag subscriptions:\n" + "\n".join(f"- {line}" for line in tag_subscriptions))
            full_fragment = "\n\n".join([item for item in [fragment, *metadata_sections] if item])
            if full_fragment and full_fragment not in seen:
                seen.add(full_fragment)
                fragments.append(f"Source prompt for {label}:\n{full_fragment}")
        for contributor in sensory.list_prompt_contributors(source_id):
            contributor_label = str(getattr(contributor, "label", source_id) or source_id)
            fragment = str(getattr(contributor, "prompt", "") or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            fragments.append(f"Behavior prompt for {contributor_label}:\n{fragment}")
    return "\n\n".join(fragments)


def _screen_supervisor_prompt_contributors(source_ids):
    source_keys = {
        str(source_id or "").strip().lower()
        for source_id in list(source_ids or [])
        if str(source_id or "").strip()
    }
    contributors = []
    for contributor in sensory.list_prompt_contributors("screen"):
        contributor_id = str(getattr(contributor, "id", "") or "").strip()
        if contributor_id != "nc.screen_supervisor.behavior":
            continue
        prompt = str(getattr(contributor, "prompt", "") or "").strip()
        if not prompt:
            continue
        contributor_source = str(getattr(contributor, "source_id", "") or "").strip().lower()
        source_matches = (
            not source_keys
            or contributor_source in source_keys
            or (contributor_source == "screen" and any("screen" in key for key in source_keys))
        )
        if source_matches:
            contributors.append(contributor)
    return contributors


def _screen_supervisor_prompt_active(source_ids):
    return bool(_screen_supervisor_prompt_contributors(source_ids))


_SCREEN_SUPERVISOR_TRIGGER_STOPWORDS = {
    "about",
    "action",
    "app",
    "are",
    "being",
    "browse",
    "browsing",
    "clearly",
    "comment",
    "content",
    "current",
    "doing",
    "feed",
    "image",
    "looking",
    "page",
    "playing",
    "post",
    "screen",
    "seeing",
    "shows",
    "site",
    "something",
    "that",
    "the",
    "this",
    "thread",
    "user",
    "video",
    "view",
    "visible",
    "watch",
    "watching",
    "with",
}


def _screen_supervisor_trigger_tokens(trigger):
    words = re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", str(trigger or "").lower())
    return [
        word
        for word in words
        if word not in _SCREEN_SUPERVISOR_TRIGGER_STOPWORDS
    ]


def _screen_supervisor_configured_triggers(source_ids):
    triggers = []
    for contributor in _screen_supervisor_prompt_contributors(source_ids):
        metadata = dict(getattr(contributor, "metadata", None) or {})
        for behavior in list(metadata.get("active_behaviors") or []):
            if not isinstance(behavior, dict):
                continue
            trigger = str(behavior.get("trigger") or "").strip()
            if trigger and trigger not in triggers:
                triggers.append(trigger)
        if triggers:
            continue
        prompt = str(getattr(contributor, "prompt", "") or "")
        for trigger in re.findall(r"Visual Trigger:\s*(.+)", prompt):
            trigger = str(trigger or "").strip()
            if trigger and trigger not in triggers:
                triggers.append(trigger)
    return triggers


def _screen_supervisor_configured_behaviors(source_ids):
    behaviors = []
    for contributor in _screen_supervisor_prompt_contributors(source_ids):
        metadata = dict(getattr(contributor, "metadata", None) or {})
        for behavior in list(metadata.get("active_behaviors") or []):
            if not isinstance(behavior, dict):
                continue
            trigger = str(behavior.get("trigger") or "").strip()
            if not trigger:
                continue
            behaviors.append(
                {
                    "trigger": trigger,
                    "repeat_mode": str(behavior.get("repeat_mode") or "").strip() or "Meaningful change only",
                    "repeat_interval": behavior.get("repeat_interval"),
                }
            )
    if behaviors:
        return behaviors
    return [{"trigger": trigger, "repeat_mode": "Meaningful change only"} for trigger in _screen_supervisor_configured_triggers(source_ids)]


def _screen_supervisor_current_focus_text(*parts):
    text = " ".join(str(item or "") for item in parts if str(item or "").strip())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    focus_patterns = [
        r"\bswitched\s+from\b.+?\bto\s+(?P<focus>.+)$",
        r"\bchanged\s+from\b.+?\bto\s+(?P<focus>.+)$",
        r"\bwent\s+from\b.+?\bto\s+(?P<focus>.+)$",
        r"\breplaced\b.+?\bwith\s+(?P<focus>.+)$",
    ]
    for pattern in focus_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            focus = re.sub(r"\b(previously|before|earlier)\b.+$", "", match.group("focus"), flags=re.IGNORECASE).strip()
            return focus or text
    return text


def _screen_supervisor_pong_trigger_decision(source_ids, *, summary="", attention="", proactive_candidate=""):
    behaviors = _screen_supervisor_configured_behaviors(source_ids)
    if not behaviors:
        return True, "no configured trigger metadata available", None
    full_haystack = " ".join(
        str(item or "").lower()
        for item in (summary, attention, proactive_candidate)
        if str(item or "").strip()
    )
    current_haystack = _screen_supervisor_current_focus_text(summary, attention, proactive_candidate).lower()
    if not full_haystack:
        return False, "no PONG text available for trigger check", None
    saw_tokenized_trigger = False
    checked = []
    for behavior in behaviors:
        trigger = str(behavior.get("trigger") or "").strip()
        tokens = _screen_supervisor_trigger_tokens(trigger)
        if not tokens:
            checked.append(f"{trigger!r}: no significant tokens")
            continue
        saw_tokenized_trigger = True
        checked.append(f"{trigger!r}: tokens={tokens}")
        for token in tokens:
            token_pattern = rf"(?<![a-z0-9_+-]){re.escape(token)}(?![a-z0-9_+-])"
            if re.search(token_pattern, current_haystack):
                return True, f"trigger {trigger!r} matched token {token!r}", dict(behavior)
            if re.search(token_pattern, full_haystack):
                return (
                    False,
                    f"trigger {trigger!r} matched token {token!r} only in previous/transition context",
                    dict(behavior),
                )
    if not saw_tokenized_trigger:
        fallback_behavior = dict(behaviors[0]) if behaviors else None
        return True, "configured triggers had no significant tokens", fallback_behavior
    fallback_behavior = dict(behaviors[0]) if behaviors else None
    return False, "no configured trigger token matched PONG text; " + "; ".join(checked[:4]), fallback_behavior


def _screen_supervisor_repeat_key(behavior, subject_identity):
    trigger_key = _canonical_hidden_action_key((behavior or {}).get("trigger", "")) or "screen-supervisor"
    subject_key = _canonical_hidden_action_key(subject_identity) or "unknown-subject"
    return f"{trigger_key}::{subject_key}"


def _screen_supervisor_subject_from_tags(tags):
    for tag in list(tags or []):
        tag_text = str(tag or "").strip()
        match = re.match(r"^\[?screen_subject\s*:\s*(?P<subject>.+?)\]?$", tag_text, flags=re.IGNORECASE)
        if not match:
            continue
        subject = _canonical_hidden_action_key(match.group("subject"))
        if subject:
            return subject[:180]
    return ""


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
    snapshot_list = list(snapshots or [])
    snapshot_source_ids = [
        str((item or {}).get("source", "") or "").strip().lower()
        for item in snapshot_list
        if isinstance(item, dict)
    ]
    tags = []
    for item in list(result.get("tags", []) or []):
        tag_text = _sanitize_hidden_action_text(item, limit=80)
        if tag_text and tag_text not in tags:
            tags.append(tag_text)
    should_speak = _normalize_boolish(result.get("should_speak", False))
    if should_speak and not proactive_candidate:
        proactive_candidate = _derive_hidden_proactive_candidate(summary=summary, attention=attention, emotion=emotion)
    screen_subject_identity = ""
    screen_supervisor_repeat_key = ""
    screen_supervisor_new_meaningful_subject = False
    screen_supervisor_allow_same_subject_repeat = False
    screen_supervisor_repeat_mode = ""
    if _screen_supervisor_prompt_active(snapshot_source_ids):
        supervisor_match_tag = "[screen_supervisor_match]"
        has_supervisor_match = any(str(tag or "").strip().lower() == supervisor_match_tag for tag in tags)
        screen_subject_tag_identity = _screen_supervisor_subject_from_tags(tags)
        tags = [
            tag
            for tag in tags
            if str(tag or "").strip().lower() != supervisor_match_tag
            and not re.match(r"^\[?screen_subject\s*:", str(tag or "").strip(), flags=re.IGNORECASE)
        ]
        print(
            "[SupervisorDebug] model_match_tag="
            f"{has_supervisor_match} sources={snapshot_source_ids or ['?']}"
        )
        if (should_speak or proactive_candidate) and not has_supervisor_match:
            print("🤐 [Sensory] Suppressed screen comment without a matching Screen Supervisor behavior.")
            proactive_candidate = ""
            should_speak = False
        if should_speak or proactive_candidate:
            token_trigger_matched, trigger_reason, matched_behavior = _screen_supervisor_pong_trigger_decision(
                snapshot_source_ids,
                summary=summary,
                attention=attention,
                proactive_candidate=proactive_candidate,
            )
            trigger_matched = bool(has_supervisor_match)
            print(
                f"[SupervisorDebug] trigger_match={trigger_matched} "
                f"reason=model affirmed configured behavior; lexical_check={token_trigger_matched} ({trigger_reason})"
            )
            if matched_behavior and not token_trigger_matched:
                print("🤐 [Sensory] Suppressed screen comment without current visible evidence for the configured trigger.")
                proactive_candidate = ""
                should_speak = False
                matched_behavior = None
            if matched_behavior:
                extracted_subject_identity = _extract_hidden_screen_subject_identity(
                    summary=summary,
                    attention=attention,
                )
                screen_subject_identity = extracted_subject_identity or screen_subject_tag_identity
                if not screen_subject_identity:
                    screen_subject_identity = _canonical_hidden_action_key(summary)
                screen_supervisor_repeat_key = _screen_supervisor_repeat_key(matched_behavior, screen_subject_identity)
                repeat_mode = str(matched_behavior.get("repeat_mode") or "").strip()
                screen_supervisor_repeat_mode = repeat_mode
                print(
                    "[SupervisorDebug] repeat_mode="
                    f"{repeat_mode or '?'} subject={screen_subject_identity or '?'}"
                )
                if repeat_mode == "Every Nth match":
                    screen_supervisor_allow_same_subject_repeat = True
                if repeat_mode == "Meaningful change only" and screen_supervisor_repeat_key:
                    with sensory_pingpong_lock:
                        last_repeat_key = str(
                            sensory_hidden_action_state.get("last_screen_supervisor_meaningful_key", "") or ""
                        )
                        last_repeat_subject = str(
                            sensory_hidden_action_state.get("last_screen_supervisor_meaningful_subject", "") or ""
                        )
                        last_repeat_trigger = str(
                            sensory_hidden_action_state.get("last_screen_supervisor_meaningful_trigger", "") or ""
                        )
                    trigger_key = _canonical_hidden_action_key(matched_behavior.get("trigger", ""))
                    same_repeat_key = screen_supervisor_repeat_key == last_repeat_key
                    same_subject = (
                        trigger_key == last_repeat_trigger
                        and _hidden_subject_keys_are_similar(screen_subject_identity, last_repeat_subject)
                    )
                    if same_repeat_key or same_subject:
                        print(
                            "🤐 [Sensory] Suppressed repeated Screen Supervisor comment without meaningful subject change "
                            f"(previous_subject={last_repeat_subject or '?'})"
                        )
                        proactive_candidate = ""
                        should_speak = False
                    else:
                        screen_supervisor_new_meaningful_subject = True
        if not screen_subject_identity:
            screen_subject_identity = _extract_hidden_screen_subject_identity(summary=summary, attention=attention)
        if (
            should_speak
            and proactive_candidate
            and screen_subject_identity
            and not screen_supervisor_allow_same_subject_repeat
        ):
            with sensory_pingpong_lock:
                last_subject_key = str(sensory_hidden_action_state.get("last_screen_subject_comment_key", "") or "")
            if screen_subject_identity == last_subject_key:
                if should_speak or proactive_candidate:
                    print("🤐 [Sensory] Suppressed repeated screen comment for the same visible subject.")
                proactive_candidate = ""
                should_speak = False
    if (
        should_speak
        and proactive_candidate
        and not screen_supervisor_new_meaningful_subject
        and _hidden_proactive_candidate_reuses_recent_stale_text(proactive_candidate, summary)
    ):
        print("🤐 [Sensory] Suppressed stale proactive candidate reused from a different hidden PONG.")
        proactive_candidate = ""
        should_speak = False
    should_generate_image = _normalize_boolish(result.get("should_generate_image", False))
    if should_generate_image and not visual_candidate:
        visual_candidate = _derive_hidden_visual_candidate(summary=summary, attention=attention, emotion=emotion)
    keep_value = bool(result.get("keep", False))
    snapshot_source = ",".join([str((item or {}).get("source", "sensory") or "sensory") for item in snapshot_list if isinstance(item, dict)]) or "sensory"
    if should_generate_image and visual_candidate and _screen_supervisor_prompt_active(
        [str((item or {}).get("source", "") or "").strip().lower() for item in snapshot_list if isinstance(item, dict)]
    ):
        print("🖼️ [Sensory] Suppressed screen-supervisor visual generation request; supervisor behavior is comment-only.")
        visual_candidate = ""
        should_generate_image = False
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
        proactive_queued = _queue_hidden_proactive_candidate(
            proactive_candidate,
            summary=summary,
            attention=attention,
            source=snapshot_source,
            allow_repeated_candidate=screen_supervisor_new_meaningful_subject,
        )
        if proactive_queued:
            if screen_subject_identity:
                with sensory_pingpong_lock:
                    sensory_hidden_action_state["last_screen_subject_comment_key"] = screen_subject_identity
            if screen_supervisor_repeat_key:
                with sensory_pingpong_lock:
                    sensory_hidden_action_state["last_screen_supervisor_meaningful_key"] = screen_supervisor_repeat_key
                    sensory_hidden_action_state["last_screen_supervisor_meaningful_subject"] = screen_subject_identity
                    sensory_hidden_action_state["last_screen_supervisor_meaningful_trigger"] = _canonical_hidden_action_key(
                        screen_supervisor_repeat_key.split("::", 1)[0]
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
    if stop_flag.is_set() or _hidden_sensory_pingpong_blocked():
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
    params = {
        "model": RUNTIME_CONFIG["model_name"],
        "messages": messages,
        "temperature": 0.2,
        "top_p": min(0.8, float(RUNTIME_CONFIG.get("top_p", 0.8) or 0.8)),
        "max_tokens": 220,
        "response_format": {"type": "json_object"},
    }
    additional_params = {
        "top_k": int(RUNTIME_CONFIG.get("top_k", 40) or 40),
        "min_p": float(RUNTIME_CONFIG.get("min_p", 0.05) or 0.05),
        "repeat_penalty": float(RUNTIME_CONFIG.get("repeat_penalty", 1.1) or 1.1),
    }
    try:
        try:
            payload_text = _chat_completion_create(params, additional_params)
        except Exception as exc:
            message = str(exc)
            if "response_format" not in message and "json_object" not in message:
                raise
            params.pop("response_format", None)
            payload_text = _chat_completion_create(params, additional_params)
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
    # A literal [visualize: ...] tag is an explicit assistant request. The
    # hidden sensory "allow visual replies" toggle only controls whether NC asks
    # the model to produce those tags automatically.
    if visual_prompt and _visual_reply_enabled():
        request_visual_reply_generation(visual_prompt, source_text=cleaned_text)
    _notify_addon_assistant_reply(cleaned_text)
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
            int(RUNTIME_CONFIG.get("stream_chunk_target_chars", 80) or 80),
            int(RUNTIME_CONFIG.get("stream_chunk_max_chars", 185) or 185),
        )
    return (
        int(RUNTIME_CONFIG.get("chunk_target_chars", 90) or 90),
        int(RUNTIME_CONFIG.get("chunk_max_chars", 180) or 180),
    )


def get_text_chunk_limits():
    if RUNTIME_CONFIG.get("avatar_mode", "vseeface") == "musetalk":
        return get_avatar_chunk_limits_for_index(2)
    return (
        int(RUNTIME_CONFIG.get("chunk_target_chars", TARGET_CHARS_PER_CHUNK) or TARGET_CHARS_PER_CHUNK),
        int(RUNTIME_CONFIG.get("chunk_max_chars", MAX_CHARS_PER_CHUNK) or MAX_CHARS_PER_CHUNK),
    )


def clear_avatar_stream_state():
    expression_state.reset_current_expression_data()
    musetalk_state.reset_musetalk_pipeline_data()
    musetalk_state.set_current_musetalk_frame_data({
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
    state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
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
    musetalk_state.append_musetalk_preview_log(message)
    print(message)


def set_musetalk_idle_state():
    if not _is_musetalk_avatar_adapter(avatar_gui):
        clear_avatar_stream_state()
        return

    idle_payload = avatar_gui.get_idle_payload()
    if not idle_payload:
        clear_avatar_stream_state()
        return

    expression_state.reset_current_expression_data()
    musetalk_state.set_current_musetalk_frame_data(idle_payload)
    prime_musetalk_preview_frame(idle_payload)
    schedule_musetalk_runtime_cleanup()


def set_musetalk_idle_state_for_avatar(avatar_id):
    if not _is_musetalk_avatar_adapter(avatar_gui):
        clear_avatar_stream_state()
        return

    target_avatar_id = str(avatar_id or "").strip() or str(getattr(avatar_gui, "default_avatar_id", "") or "").strip()
    current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
    current_avatar_id = str(current_state.get("avatar_id", "") or "").strip()
    current_status = str(current_state.get("status", "") or "").strip().lower()
    current_frame_paths = list(current_state.get("frame_paths", []) or [])
    if current_status == "idle" and current_avatar_id == target_avatar_id and current_frame_paths:
        return

    idle_payload = avatar_gui.get_idle_payload(avatar_id=target_avatar_id)
    if not idle_payload:
        clear_avatar_stream_state()
        return

    expression_state.reset_current_expression_data()
    musetalk_state.set_current_musetalk_frame_data(idle_payload)
    prime_musetalk_preview_frame(idle_payload)
    schedule_musetalk_runtime_cleanup()


def build_musetalk_idle_payload_from_state(advance_to_next_frame=True):
    if not _is_musetalk_avatar_adapter(avatar_gui):
        return None

    current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
    builder = getattr(avatar_gui, "build_idle_payload_from_state", None)
    if not callable(builder):
        return None
    return builder(current_state=current_state, advance_to_next_frame=advance_to_next_frame)


def transition_musetalk_to_local_idle(advance_to_next_frame=True):
    idle_payload = build_musetalk_idle_payload_from_state(advance_to_next_frame=advance_to_next_frame)
    if idle_payload:
        expression_state.reset_current_expression_data()
        musetalk_state.set_current_musetalk_frame_data(idle_payload)
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
    expression_state.reset_current_expression_data()
    musetalk_state.set_current_musetalk_frame_data(payload)
    prime_musetalk_preview_frame(musetalk_state.current_musetalk_frame_data)

    def _finish_transition():
        time.sleep(duration_seconds)
        current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
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
    return _invoke_musetalk_pack_capability(
        "runtime.pack_catalog",
        {
            "runtime_config": RUNTIME_CONFIG,
            "legacy_map": MUSE_EMOTION_AVATAR_MAP,
            "legacy_transitions": MUSE_AVATAR_TRANSITIONS,
        },
        default=[],
    )


def apply_musetalk_avatar_pack_selection(pack_id):
    requested_pack_id = str(pack_id or "").strip()
    if not requested_pack_id:
        return str(RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
    try:
        selected_pack_id = _invoke_musetalk_pack_capability(
            "runtime.select_pack",
            {
                "runtime_config": RUNTIME_CONFIG,
                "requested_pack_id": requested_pack_id,
                "legacy_map": MUSE_EMOTION_AVATAR_MAP,
                "legacy_transitions": MUSE_AVATAR_TRANSITIONS,
            },
            default="",
        )
        if not selected_pack_id:
            raise LookupError(requested_pack_id)
    except LookupError:
        return str(RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
    update_runtime_config("musetalk_avatar_pack_id", selected_pack_id)
    invalidate_available_emotion_names()
    if _is_musetalk_avatar_adapter(avatar_gui):
        avatar_gui.select_avatar_pack(selected_pack_id)
        if not audio_playing.is_set() and not stop_flag.is_set():
            try:
                set_musetalk_idle_state_for_avatar(avatar_gui.default_avatar_id)
            except Exception:
                pass
    return selected_pack_id


def loop_current_musetalk_state():
    current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
    frame_paths = current_state.get("frame_paths", [])
    frame_dir = current_state.get("frame_dir", "")
    if not frame_paths and not frame_dir:
        clear_avatar_stream_state()
        return

    expression_state.reset_current_expression_data()
    musetalk_state.set_current_musetalk_frame_data({
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
    prime_musetalk_preview_frame(musetalk_state.current_musetalk_frame_data)
    schedule_musetalk_runtime_cleanup(keep_frame_dirs=[frame_dir] if frame_dir else None)


def freeze_current_musetalk_frame():
    current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
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

    expression_state.reset_current_expression_data()
    musetalk_state.set_current_musetalk_frame_data({
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
    prime_musetalk_preview_frame(musetalk_state.current_musetalk_frame_data)
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
    global avatar_gui, tts_model, tts_backend_name, stt_model, stt_backend_name
    with _shutdown_avatar_engine_lock:
        had_tts_model = tts_model is not None
        has_tts_to_unload = bool(unload_tts and tts_model is not None)
        has_stt_to_unload = bool(unload_stt and stt_model is not None)
        if avatar_gui is None and not has_tts_to_unload and not has_stt_to_unload:
            stop_playback.set()
            manual_pause_active.clear()
            pause_after_chunk.clear()
            playback_paused.clear()
            clear_avatar_stream_state()
            return
        avatar_gui, tts_model, stt_model = runtime_shutdown.shutdown_runtime_components(
            avatar_gui=avatar_gui,
            tts_model=tts_model,
            stt_model=stt_model,
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
        if unload_stt and stt_model is None:
            stt_backend_name = None


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
        "last_proactive_candidate_key": "",
        "last_proactive_candidate_at": 0.0,
        "last_visual_key": "",
        "last_visual_at": 0.0,
        "last_screen_subject_comment_key": "",
        "last_screen_supervisor_meaningful_key": "",
        "last_screen_supervisor_meaningful_subject": "",
        "last_screen_supervisor_meaningful_trigger": "",
    }
    chat_session_state_generation += 1
    print("🧼 [Session] Chat history and memory reset.")


def reset_chat_runtime_state():
    global last_resume_requested_at, pending_loaded_input_turn
    pending_loaded_input_turn = None
    user_image_turns.clear_pending_attachment()
    _clear_pending_hidden_proactive_candidate()
    _clear_active_hidden_proactive_candidate()
    stop_playback.set()
    manual_pause_active.clear()
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
    return user_image_turns.set_pending_attachment(image_path, source=source)


def clear_pending_user_image_attachment():
    user_image_turns.clear_pending_attachment()


def _attach_pending_user_image_to_turn(input_turn, *, is_placeholder: bool = False) -> dict:
    turn = dict(input_turn or {})
    role = str(turn.get("role", "") or "").strip().lower()
    pending_attachment = user_image_turns.consume_pending_attachment()
    if role != "user" or is_placeholder or not pending_attachment:
        return turn
    attachment_image_path = str(pending_attachment.get("attachment_image_path", "") or "").strip()
    attachment_source = str(pending_attachment.get("attachment_source", "image") or "image")
    clipboard_source_enabled = "clipboard" in _sensory_feedback_sources()
    if attachment_source == "clipboard" and not clipboard_source_enabled:
        print("📋 [Clipboard] Skipped pending clipboard image because Clipboard source is disabled.")
    elif attachment_image_path:
        turn["attachment_image_path"] = attachment_image_path
        turn["attachment_source"] = attachment_source
        source_label = "Clipboard" if attachment_source == "clipboard" else attachment_source.title()
        print(f"📎 [{source_label}] Attached pending image to current user turn: {attachment_image_path}")
    return turn


def _maybe_arm_screen_image_for_user_turn(input_turn, *, is_placeholder: bool = False) -> None:
    turn = dict(input_turn or {})
    role = str(turn.get("role", "") or "").strip().lower()
    if role != "user" or is_placeholder:
        return
    if user_image_turns.pending_attachment():
        return
    if not bool(RUNTIME_CONFIG.get("screen_source_auto_attach_next_user_turn", False)):
        return
    if "screen" not in _sensory_feedback_sources():
        return
    try:
        snapshot = _capture_sensory_feedback_snapshot("screen")
    except Exception as exc:
        print(f"⚠️ [ScreenSource] Could not capture screen attachment for user turn: {exc}")
        return
    image_path = str((snapshot or {}).get("image_path", "") or "").strip()
    if not image_path:
        return
    try:
        user_image_turns.set_pending_attachment(image_path, source="screen")
        print(f"🖥️ [ScreenSource] Armed screen capture for current user turn: {image_path}")
    except Exception as exc:
        print(f"⚠️ [ScreenSource] Could not arm screen attachment for user turn: {exc}")


def queue_user_image_turn(image_path, *, content=None, source="clipboard"):
    return user_image_turns.queue_image_turn(
        image_path,
        content=content,
        source=source,
    )


def export_chat_session_state():
    return {
        "version": 1,
        "saved_at": time.time(),
        "conversation_history": [turn for turn in (_sanitize_chat_turn(item) for item in list(conversation_history or [])) if turn],
        "assistant_memory": json.loads(json.dumps(assistant_memory or _default_assistant_memory())),
        "sensory_hidden_history": [item for item in (_sanitize_sensory_hidden_event(entry) for entry in list(sensory_hidden_history or [])) if item],
    }


def _chat_replay_role_label(turn):
    role = str((turn or {}).get("role", "") or "").strip().lower()
    origin = str((turn or {}).get("origin", "") or "").strip().lower()
    if role == "assistant" and origin == "assistant_reply":
        return "Assistant"
    if role == "assistant":
        return "User as assistant"
    if role == "system":
        return "System"
    if role == "tool":
        return "Tool"
    return "User"


def _chat_replay_spoken_text(turn, content):
    label = _chat_replay_role_label(turn)
    text = str(content or "").strip()
    return f"{label}: {text}" if label else text


def _normalize_chat_replay_role_voices(value):
    raw = dict(value or {}) if isinstance(value, dict) else {}
    normalized = {}
    for role in ("assistant", "user", "system"):
        voice_path = str(raw.get(role, "") or "").strip()
        normalized[role] = voice_path
    return normalized


def _resolve_voice_reference_path(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidates = []
    path = Path(raw)
    candidates.append(path)
    if not path.is_absolute():
        candidates.append(Path.cwd() / path)
        candidates.append(Path.cwd() / "voices" / path.name)
    for candidate in candidates:
        try:
            if candidate.exists():
                return str(candidate.resolve())
        except Exception:
            continue
    return ""


def _chat_replay_voice_path_for_turn(turn):
    voices = _normalize_chat_replay_role_voices(RUNTIME_CONFIG.get("chat_replay_role_voices", {}) or {})
    role = str((turn or {}).get("role", "") or "").strip().lower()
    origin = str((turn or {}).get("origin", "") or "").strip().lower()
    if role == "assistant" and origin == "assistant_reply":
        key = "assistant"
    elif role == "system":
        key = "system"
    else:
        key = "user"
    configured = voices.get(key, "") or (voices.get("assistant", "") if key == "system" else "")
    return _resolve_voice_reference_path(configured)


_replay_voice_warmup_cache = set()


def _warm_up_replay_voice_paths(entries):
    if tts_model is None:
        return
    paths = []
    for entry in list(entries or []):
        voice_path = str((entry or {}).get("voice_path", "") or "").strip()
        if voice_path and voice_path not in paths:
            paths.append(voice_path)
    if not paths:
        return
    generator = getattr(tts_model, "generate", None)
    if not callable(generator):
        return
    backend_key = str(RUNTIME_CONFIG.get("tts_backend", "") or "").strip().lower()
    for voice_path in paths:
        cache_key = (backend_key, voice_path)
        if cache_key in _replay_voice_warmup_cache:
            continue
        try:
            kwargs = tts_runtime.build_generation_kwargs(
                RUNTIME_CONFIG,
                set_seed=set_seed,
                path_exists=os.path.exists,
                logger=print,
            )
            kwargs["audio_prompt_path"] = voice_path
            generator("Ready.", **kwargs)
            _replay_voice_warmup_cache.add(cache_key)
            print(f"✓ Replay voice warmup complete: {os.path.basename(voice_path)}")
        except Exception as exc:
            print(f"⚠️ Replay voice warmup failed for {os.path.basename(voice_path)}: {exc}")


def collect_replayable_chat_entries(history=None):
    replayable = []
    replay_index = 0
    for history_index, item in enumerate(list(history if history is not None else (conversation_history or []))):
        turn = _sanitize_chat_turn(item)
        if not turn:
            continue
        content = str(turn.get("content", "") or "").strip()
        if not content:
            continue
        replay_index += 1
        label = _chat_replay_role_label(turn)
        preview_source = f"{label}: {content}" if label else content
        preview = re.sub(r"\s+", " ", preview_source).strip()
        replayable.append({
            "replay_index": replay_index,
            "history_index": history_index,
            "role": str(turn.get("role", "") or ""),
            "origin": str(turn.get("origin", "") or ""),
            "label": label,
            "content": content,
            "spoken_text": _chat_replay_spoken_text(turn, content),
            "voice_path": _chat_replay_voice_path_for_turn(turn),
            "preview": preview[:140] + ("..." if len(preview) > 140 else ""),
        })
    return replayable


def collect_replayable_chat_messages(history=None):
    return [str(item.get("spoken_text", "") or "") for item in collect_replayable_chat_entries(history)]


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
    return _invoke_musetalk_pack_capability(
        "runtime.preview.estimate_displayed_frames",
        {
            "state": state,
            "now": now,
            "runtime_config": RUNTIME_CONFIG,
        },
        default=0,
    )


def get_current_musetalk_source_index(state=None, advance_to_next_frame=False):
    return _invoke_musetalk_pack_capability(
        "runtime.preview.current_source_index",
        {
            "state": state,
            "runtime_config": RUNTIME_CONFIG,
            "advance_to_next_frame": advance_to_next_frame,
        },
        default=int((state or {}).get("start_index", 0) or 0),
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


def _dedupe_adjacent_tts_stream_text(previous: str, current: str) -> tuple[str, bool]:
    prev = str(previous or "").strip()
    cur = str(current or "").strip()
    if not prev or not cur:
        return cur, False
    prev_norm = re.sub(r"\s+", " ", prev).strip().lower()
    cur_norm = re.sub(r"\s+", " ", cur).strip().lower()
    if len(prev_norm) >= 16 and prev_norm == cur_norm:
        return "", True
    if len(prev_norm) >= 24 and cur_norm.startswith(prev_norm):
        return cur[len(prev):].lstrip(" \t\r\n,.;:-"), True

    max_overlap = min(len(prev), len(cur), 160)
    for size in range(max_overlap, 23, -1):
        left = re.sub(r"\s+", " ", prev[-size:]).strip().lower()
        right = re.sub(r"\s+", " ", cur[:size]).strip().lower()
        if left and left == right:
            return cur[size:].lstrip(" \t\r\n,.;:-"), True
    return cur, False


def _iter_queue_text_chunks(text_queue, dry_run_reply_id=None):
    first_yield_logged = False
    while True:
        while True:
            if stop_playback.is_set() or stop_flag.is_set():
                musetalk_state.append_musetalk_preview_log("🌊 [Stream] Text queue stopped before sentinel")
                return
            try:
                item = text_queue.get(timeout=0.1)
                break
            except queue.Empty:
                continue
        if item is None:
            musetalk_state.append_musetalk_preview_log("🌊 [Stream] Text queue received sentinel")
            break
        if item and str(item).strip():
            if not first_yield_logged:
                musetalk_state.append_musetalk_preview_log(
                    f"🌊 [Stream] First chunk dequeued for TTS: chars={len(str(item).strip())}"
                )
                dry_run.record_reply_event(dry_run_reply_id, "first_chunk_dequeued_at")
                first_yield_logged = True
            yield str(item)


def speak_async(text: str, text_iterable=None, dry_run_reply_id=None, voice_path_override=None, replay_items=None) -> TTSController:
    global tts_model, stop_playback, audio_playing, avatar_gui, last_resumed_at, last_resume_requested_at
    ctrl = TTSController()
    stop_playback.clear()
    manual_pause_active.clear()
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

    resolved_voice_path_override = ""
    if voice_path_override:
        resolved_voice_path_override = _resolve_voice_reference_path(voice_path_override)
        if not resolved_voice_path_override:
            print(f"⚠️ Replay voice file not found: {voice_path_override}. Continuing with the current TTS voice.")

    replay_mode = bool(replay_items)
    playback_queue = queue.Queue(maxsize=6 if replay_mode else 0)
    ready_for_playback = queue.Queue(maxsize=6 if replay_mode else 0)
    output_dir = runtime_paths.runtime_temp_dir("tts")
    sample_rate = getattr(tts_model, "sr", 24000)
    chunk_target_chars, chunk_max_chars = get_text_chunk_limits()
    avatar_mode = RUNTIME_CONFIG.get("avatar_mode", "vseeface").lower()
    pipeline_telemetry_enabled = avatar_mode in {"musetalk", "vam", "none"}
    pipeline_reply_id = None
    if pipeline_telemetry_enabled:
        pipeline_reply_id = musetalk_state.begin_musetalk_pipeline_reply(
            stream_mode=bool(text_iterable is not None or RUNTIME_CONFIG.get("stream_mode", False))
        )
        musetalk_state.update_musetalk_pipeline_flags(
            reply_id=pipeline_reply_id,
            engine_mode=avatar_mode,
        )
    else:
        musetalk_state.reset_musetalk_pipeline_data()

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

    def _pipeline_stopping() -> bool:
        return bool(stop_playback.is_set() or stop_flag.is_set() or ctrl.cancel_requested.is_set())

    def _put_unless_stopping(target_queue, item) -> bool:
        while not _pipeline_stopping():
            try:
                target_queue.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def generator_worker():
        cnt = 0
        muse_chunk_index = 0
        if replay_mode:
            source_iterable = list(replay_items or [])
        elif text_iterable is None and not resolved_voice_path_override:
            source_iterable = _addon_voice_segments(
                {
                    "text": str(text or ""),
                    "tts_backend": str(RUNTIME_CONFIG.get("tts_backend", "") or ""),
                    "streaming": False,
                }
            ) or [text]
        else:
            source_iterable = text_iterable if text_iterable is not None else [text]
        source_iterable = _expand_addon_voice_segments(
            source_iterable,
            streaming=bool(text_iterable is not None or RUNTIME_CONFIG.get("stream_mode", False)),
            voice_path_override=resolved_voice_path_override,
        )
        first_piece_logged = False
        first_subchunk_logged = False
        first_wav_logged = False
        for source_offset, source_item in enumerate(source_iterable):
            if stop_playback.is_set() or ctrl.cancel_requested.is_set(): break
            source_meta = {}
            piece_voice_route = {}
            piece_voice_path = resolved_voice_path_override
            if isinstance(source_item, dict):
                piece_text = str(source_item.get("text", "") or "")
                raw_voice_route = source_item.get("voice_route")
                if isinstance(raw_voice_route, dict):
                    piece_voice_route = dict(raw_voice_route)
                source_meta = {
                    "replay_message_id": str(source_item.get("message_id", "") or ""),
                    "replay_index": int(source_item.get("index", 0) or 0),
                    "replay_total": int(source_item.get("total", 0) or 0),
                    "replay_label": str(source_item.get("label", "") or ""),
                    "persona_id": str(source_item.get("persona_id", "") or ""),
                    "display_name": str(source_item.get("display_name", "") or ""),
                    "voice_route": dict(piece_voice_route),
                    "story_audio_cues": list(source_item.get("story_audio_cues") or []),
                }
                piece_voice_path = _resolve_voice_reference_path(source_item.get("voice_path", "")) or resolved_voice_path_override
            else:
                piece_text = source_item
            if not piece_voice_path:
                if not piece_voice_route:
                    piece_voice_route = _addon_voice_route(
                        {
                            "text": str(piece_text or ""),
                            "tts_backend": str(RUNTIME_CONFIG.get("tts_backend", "") or ""),
                            "streaming": bool(text_iterable is not None or RUNTIME_CONFIG.get("stream_mode", False)),
                        }
                    )
                if bool(piece_voice_route.get("supported")):
                    piece_voice_path = _resolve_voice_reference_path(piece_voice_route.get("sample_path", ""))
                elif piece_voice_route.get("warning"):
                    print(f"⚠️ [TTS] {piece_voice_route.get('warning')}")
            if not piece_text or not str(piece_text).strip():
                continue
            replay_message_id = str(source_meta.get("replay_message_id", "") or "")
            replay_index = int(source_meta.get("replay_index", 0) or 0)
            while (
                replay_mode
                and source_offset > 0
                and replay_index > 0
                and hasattr(ctrl, "can_prepare_replay_index")
                and not ctrl.can_prepare_replay_index(replay_index, lookahead=1)
                and not stop_playback.is_set()
                and not ctrl.cancel_requested.is_set()
                and not stop_flag.is_set()
            ):
                time.sleep(0.05)
            if stop_playback.is_set() or ctrl.cancel_requested.is_set() or stop_flag.is_set():
                break
            message_chunk_index = 0
            if text_iterable is not None and not first_piece_logged:
                musetalk_state.append_musetalk_preview_log(
                    f"🌊 [Stream] Generator received first text piece: chars={len(str(piece_text).strip())}"
                )
                first_piece_logged = True
            segments = parse_text_segments(str(piece_text))
            if avatar_mode == "musetalk":
                segments = coalesce_musetalk_leading_segments(segments)
            for emotion, seg_text in segments:
                if stop_playback.is_set() or ctrl.cancel_requested.is_set():
                    break
                if ctrl.should_skip_message(replay_message_id):
                    break
                if avatar_mode == "musetalk":
                    sub_chunks = intelligent_chunk_text_progressive(seg_text, start_chunk_index=muse_chunk_index)
                else:
                    sub_chunks = intelligent_chunk_text(seg_text, chunk_target_chars, chunk_max_chars)
                print(f"🧩 [{RUNTIME_CONFIG.get('avatar_mode', 'vseeface').upper()}] {len(sub_chunks)} chunk(s) for emotion '{emotion}'")
                for sub in sub_chunks:
                    if stop_playback.is_set() or ctrl.cancel_requested.is_set(): break
                    if ctrl.should_skip_message(replay_message_id):
                        break
                    chunk_sequence = muse_chunk_index if avatar_mode == "musetalk" else cnt
                    if pipeline_telemetry_enabled:
                        musetalk_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="generating_audio",
                            playback_state="pending",
                            text=str(sub or ""),
                            emotion=str(emotion or ""),
                        )
                    if text_iterable is not None and not first_subchunk_logged:
                        musetalk_state.append_musetalk_preview_log(
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
                    if piece_voice_path:
                        kwargs["audio_prompt_path"] = piece_voice_path
                    route_language = str((piece_voice_route or {}).get("language") or "").strip().lower()
                    route_backend = str(RUNTIME_CONFIG.get("tts_backend", "") or "").strip().lower().replace("-", "_")
                    if route_backend == "pocket_tts":
                        route_backend = "pockettts"
                    if route_language and route_backend in {"pockettts", "pockettts_multilingual"}:
                        kwargs["pocket_tts_language"] = route_language
                    try:
                        ctrl.set_generating_message_id(replay_message_id)
                        wav = tts_model.generate(sub, **kwargs)
                    except Exception as e:
                        if _pipeline_stopping():
                            print(f"⏹️ [TTS] Generation cancelled during shutdown: {e}")
                            return
                        if ctrl.should_skip_message(replay_message_id):
                            print("⏭️ [Replay] TTS generation cancelled for skipped message.")
                            break
                        raise
                    finally:
                        ctrl.clear_generating_message_id(replay_message_id)
                    if ctrl.cancel_requested.is_set() or stop_playback.is_set():
                        try:
                            del wav
                        except Exception:
                            pass
                        break
                    if ctrl.should_skip_message(replay_message_id):
                        try:
                            del wav
                        except Exception:
                            pass
                        break
                    path = str(output_dir / f"speech_{cnt}_{int(time.time())}.wav")
                    save_audio_file(path, wav, sample_rate)
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
                        musetalk_state.append_musetalk_preview_log(
                            f"🌊 [Stream] First audio chunk generated: file={os.path.basename(path)} chars={len(sub.strip())}"
                        )
                        dry_run.record_reply_event(dry_run_reply_id, "first_audio_chunk_at")
                        first_wav_logged = True
                    if pipeline_telemetry_enabled:
                        musetalk_state.update_musetalk_pipeline_chunk(
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
                    chunk_meta = dict(source_meta)
                    chunk_meta["replay_message_first_chunk"] = bool(replay_mode and message_chunk_index == 0)
                    chunk_meta["tts_source_first_chunk"] = bool(message_chunk_index == 0)
                    if message_chunk_index > 0:
                        chunk_meta["story_audio_cues"] = []
                    if ctrl.cancel_requested.is_set() or stop_playback.is_set():
                        safe_delete_with_retry(path)
                        break
                    if not _put_unless_stopping(playback_queue, (path, emotion, sub, chunk_sequence, chunk_meta)):
                        safe_delete_with_retry(path)
                        break
                    cnt += 1
                    message_chunk_index += 1
                    if avatar_mode == "musetalk":
                        muse_chunk_index += 1
        if not _pipeline_stopping():
            _put_unless_stopping(playback_queue, None)
        if pipeline_telemetry_enabled:
            musetalk_state.update_musetalk_pipeline_flags(
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
            while not stop_playback.is_set() and not ctrl.cancel_requested.is_set():
                try:
                    item = playback_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    if not _pipeline_stopping():
                        _put_unless_stopping(ready_for_playback, None)
                    break

                if len(item) >= 5:
                    path, emotion, txt, chunk_sequence, source_meta = item
                else:
                    path, emotion, txt, chunk_sequence = item
                    source_meta = {}
                replay_message_id = str((source_meta or {}).get("replay_message_id", "") or "")
                if ctrl.cancel_requested.is_set() or stop_playback.is_set():
                    safe_delete_with_retry(path)
                    continue
                if ctrl.should_skip_message(replay_message_id):
                    safe_delete_with_retry(path)
                    continue
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
                        musetalk_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendering",
                            playback_state="pending",
                            chunk_id=predicted_chunk_id,
                            frame_dir=predicted_frame_dir,
                        )
                    if ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        continue
                    result = avatar_gui.process_audio_chunk(
                        vocal_only_path,
                        txt,
                        output_filename=temp_json_name,
                        dry_run_reply_id=dry_run_reply_id,
                        cancel_check=(lambda message_id=replay_message_id: ctrl.cancel_requested.is_set() or ctrl.should_skip_message(message_id)) if replay_message_id else (lambda: ctrl.cancel_requested.is_set()),
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
                    musetalk_state.set_current_musetalk_frame_data({
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
                    if ctrl.cancel_requested.is_set() or stop_playback.is_set() or ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        if vocal_only_path != path:
                            safe_delete_with_retry(vocal_only_path)
                        continue
                    if avatar_mode == "musetalk":
                        musetalk_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendering",
                            playback_state="pending",
                            frame_dir=str(chunk_result.get("frame_dir", "") or ""),
                            chunk_id=str(chunk_result.get("chunk_id", "") or ""),
                            fps=int(chunk_result.get("fps", RUNTIME_CONFIG.get("musetalk_fps", 24)) or RUNTIME_CONFIG.get("musetalk_fps", 24) or 24),
                        )
                    elif avatar_mode == "vam":
                        musetalk_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendered",
                            playback_state="pending",
                            duration_seconds=float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                            expected_frame_count=int(chunk_result.get("expected_frame_count", 0) or 0),
                            chunk_id=str(chunk_result.get("chunk_id", "") or ""),
                        )
                    elif avatar_mode == "none":
                        musetalk_state.update_musetalk_pipeline_chunk(
                            chunk_sequence,
                            reply_id=pipeline_reply_id,
                            status="rendered",
                            playback_state="pending",
                            duration_seconds=float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                            expected_frame_count=int(chunk_result.get("expected_frame_count", 0) or 0),
                            chunk_id=str(chunk_result.get("chunk_id", "") or ""),
                        )
                    if replay_message_id:
                        ctrl.mark_message_ready(replay_message_id)
                    if not _put_unless_stopping(ready_for_playback, (path, emotion, txt, chunk_sequence, chunk_result, source_meta)):
                        safe_delete_with_retry(path)
                        if vocal_only_path != path:
                            safe_delete_with_retry(vocal_only_path)
                        break
                    if vocal_only_path != path:
                        safe_delete_with_retry(vocal_only_path)
                else:
                    if pipeline_telemetry_enabled:
                        musetalk_state.update_musetalk_pipeline_chunk(
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
            while not stop_playback.is_set() and not ctrl.cancel_requested.is_set():
                while playback_paused.is_set() and not stop_playback.is_set() and not ctrl.cancel_requested.is_set():
                    time.sleep(0.05)

                # Get the next chunk from the preprocessor
                try:
                    item = ready_for_playback.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break

                if len(item) >= 6:
                    path, emotion, txt, chunk_sequence, chunk_result, source_meta = item
                else:
                    path, emotion, txt, chunk_sequence, chunk_result = item
                    source_meta = {}
                replay_message_id = str((source_meta or {}).get("replay_message_id", "") or "")
                if ctrl.cancel_requested.is_set() or stop_playback.is_set():
                    safe_delete_with_retry(path)
                    continue
                if replay_message_id:
                    ctrl.clear_skip_current_message_if_new(replay_message_id)
                    if ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        continue
                    ctrl.set_current_message_id(replay_message_id)
                    if bool((source_meta or {}).get("replay_message_first_chunk", False)):
                        replay_index = int((source_meta or {}).get("replay_index", 0) or 0)
                        replay_total = int((source_meta or {}).get("replay_total", 0) or 0)
                        if replay_index and replay_total:
                            print(f"🔁 Replaying chat session message {replay_index}/{max(replay_total, 1)}...")
                kind = chunk_result.get("kind", "audio")

                if kind == "musetalk":
                    current_sequence = int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0)
                    previous_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                    try:
                        chunk_duration_seconds = float(sf.info(path).duration or 0.0)
                    except Exception:
                        chunk_duration_seconds = 0.0
                    frame_dir = chunk_result.get("frame_dir", "")
                    fps = int(chunk_result.get("fps", RUNTIME_CONFIG.get("musetalk_fps", 24)) or 24)
                    ready_event = chunk_result.get("ready_event")
                    result_holder = chunk_result.get("result_holder", {})
                    if result_holder.get("cancelled"):
                        musetalk_state.update_musetalk_pipeline_chunk(
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
                            musetalk_state.update_musetalk_pipeline_chunk(
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
                        musetalk_state.append_musetalk_preview_log(
                            f"🌊 [Stream] First chunk fast-start gate {chunk_result.get('chunk_id')}: "
                            f"min_buffer_frames={min_buffer_frames}"
                        )
                    elif is_first_reply_chunk:
                        min_buffer_frames = max(24, min(int(fps * 2.5), 72))
                    else:
                        min_buffer_frames = max(24, min(int(fps * 2.5), 72))
                    if is_first_reply_chunk:
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            startup_buffer_frames=min_buffer_frames,
                        )
                    wait_start = time.time()
                    if is_first_reply_chunk:
                        musetalk_state.append_musetalk_preview_log(
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
                        and not ctrl.cancel_requested.is_set()
                        and not ctrl.should_skip_message(replay_message_id)
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
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            status="cancelled",
                            playback_state="cancelled",
                        )
                        safe_delete_with_retry(path)
                        continue

                    if ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        continue

                    if is_first_reply_chunk:
                        musetalk_state.append_musetalk_preview_log(
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

                    if (
                        not frame_paths
                        and ready_event is not None
                        and not ready_event.is_set()
                        and not stop_playback.is_set()
                        and not ctrl.cancel_requested.is_set()
                        and not ctrl.should_skip_message(replay_message_id)
                    ):
                        while (
                            not frame_paths
                            and ready_event is not None
                            and not ready_event.is_set()
                            and not stop_playback.is_set()
                            and not ctrl.cancel_requested.is_set()
                            and not ctrl.should_skip_message(replay_message_id)
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

                    if ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        continue

                    if not frame_paths:
                        musetalk_state.update_musetalk_pipeline_chunk(
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
                    live_previous_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
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
                                    live_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
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
                                musetalk_state.append_musetalk_preview_log(
                                    f"🕒 [MuseTalkStartup] First chunk plan sync {chunk_result.get('chunk_id')}: "
                                    f"target={target_entry_index} final_preview={getattr(musetalk_state, 'current_musetalk_frame_data', {}).get('preview_source_index')} "
                                    f"waited_ms={(time.time() - wait_started_at) * 1000.0:.1f}"
                                )
                                log_musetalk_memory_checkpoint(
                                    "first_chunk_plan_sync",
                                    chunk_result.get("chunk_id"),
                                    {
                                        "target": target_entry_index,
                                        "final_preview": getattr(musetalk_state, "current_musetalk_frame_data", {}).get("preview_source_index"),
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
                                    live_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
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
                                musetalk_state.append_musetalk_preview_log(
                                    f"🕒 [MuseTalkStartup] First chunk idle sync {chunk_result.get('chunk_id')}: "
                                    f"target={target_entry_index} final_preview={getattr(musetalk_state, 'current_musetalk_frame_data', {}).get('preview_source_index')} "
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

                    musetalk_state.set_current_musetalk_frame_data({
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
                    musetalk_state.update_musetalk_pipeline_chunk(
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
                    prime_musetalk_preview_frame(musetalk_state.current_musetalk_frame_data)
                    save_musetalk_seam_debug_images(previous_state, musetalk_state.current_musetalk_frame_data)
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
                        musetalk_state.append_musetalk_preview_log(message)
                    if is_first_reply_chunk:
                        musetalk_state.append_musetalk_preview_log(
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
                    musetalk_state.set_current_musetalk_frame_data({
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
                    musetalk_state.update_musetalk_pipeline_chunk(
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

                if not stop_playback.is_set() and not ctrl.cancel_requested.is_set():
                    preview_stream_stop = threading.Event()
                    preview_stream_thread = None
                    skip_local_playback = bool(chunk_result.get("skip_local_playback", False))
                    delegated_playback_duration = max(
                        0.0,
                        float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                    )
                    story_audio_cues = list((source_meta or {}).get("story_audio_cues") or [])
                    if story_audio_cues:
                        _play_addon_story_audio_cues(story_audio_cues)
                    if bool((source_meta or {}).get("tts_source_first_chunk", False)):
                        persona_id = str((source_meta or {}).get("persona_id", "") or "").strip()
                        if persona_id:
                            _notify_addon_tts_segment_started(
                                {
                                    "persona_id": persona_id,
                                    "display_name": str((source_meta or {}).get("display_name", "") or ""),
                                    "text": str(txt or ""),
                                    "emotion": str(emotion or ""),
                                    "voice_route": dict((source_meta or {}).get("voice_route") or {}),
                                    "chunk_id": chunk_result.get("chunk_id"),
                                    "sequence_index": int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
                                }
                            )
                    if kind == "musetalk":
                        audio_start_time = time.time()
                        _queue_story_visual_reply(txt, emotion)
                        current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                        if current_state.get("chunk_id") == chunk_result.get("chunk_id"):
                            current_state["sync_time"] = audio_start_time
                            current_state["audio_started_at"] = audio_start_time
                            musetalk_state.write_musetalk_preview_snapshot(current_state)
                            if not _env_flag("NC_MUSETALK_DISABLE_PREVIEW_STREAM_THREAD"):
                                preview_stream_thread = threading.Thread(
                                    target=stream_musetalk_preview_frames,
                                    args=(current_state, preview_stream_stop),
                                    daemon=True,
                                )
                                preview_stream_thread.start()
                        musetalk_state.update_musetalk_pipeline_chunk(
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
                            f"audio={chunk_duration_seconds:.2f}s preview={float(musetalk_state.current_musetalk_frame_data.get('duration_seconds', 0.0) or 0.0):.2f}s"
                        )
                        if startup_audio_ms is not None:
                            message = (
                                f"🕒 [MuseTalkStartup] Resume -> audio start {chunk_result.get('chunk_id')}: "
                                f"{startup_audio_ms:.1f} ms"
                            )
                            print(message)
                            musetalk_state.append_musetalk_preview_log(message)
                        if is_first_reply_chunk:
                            musetalk_state.append_musetalk_preview_log(
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
                        current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                        if current_state.get("chunk_id") == chunk_result.get("chunk_id"):
                            current_state["sync_time"] = audio_start_time
                            current_state["audio_started_at"] = audio_start_time
                            musetalk_state.write_musetalk_preview_snapshot(current_state)
                            preview_stream_thread = threading.Thread(
                                target=stream_delegated_audio_progress,
                                args=(current_state, preview_stream_stop),
                                daemon=True,
                            )
                            preview_stream_thread.start()
                        musetalk_state.update_musetalk_pipeline_chunk(
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
                            while (
                                time.time() < deadline
                                and not stop_playback.is_set()
                                and not ctrl.cancel_requested.is_set()
                                and not ctrl.should_skip_message(replay_message_id)
                            ):
                                time.sleep(0.02)
                        else:
                            time.sleep(0.05)
                    else:
                        play_audio_file(path, stop_event=ctrl.skip_current_message if replay_message_id else None)
                    if ctrl.should_skip_message(replay_message_id):
                        print("⏭️ [Replay] Skipped current replay message.")
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
                    musetalk_state.update_musetalk_pipeline_chunk(
                        int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
                        reply_id=pipeline_reply_id,
                        playback_state="completed",
                        audio_finished_at=time.time(),
                    )
                    if kind == "musetalk":
                        print(f"⏹️ [MuseTalk] Finished chunk {chunk_result.get('chunk_id')}")
                    else:
                        musetalk_state.update_current_musetalk_frame_data(
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
                    manual_pause_active.set()
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
                    manual_pause_active.clear()
                    if avatar_gui and not stop_playback.is_set():
                        last_resumed_at = time.time()
                        avatar_gui.set_speaking_state(True)
                        if last_resume_requested_at:
                            resume_ms = (last_resumed_at - last_resume_requested_at) * 1000.0
                            message = f"- - - RESUMED - - - ({resume_ms:.1f} ms after request)"
                            print(message)
                            musetalk_state.append_musetalk_preview_log(message)
                        else:
                            message = "- - - RESUMED - - -"
                            print(message)
                            musetalk_state.append_musetalk_preview_log(message)

        finally:
            if pipeline_telemetry_enabled:
                musetalk_state.update_musetalk_pipeline_flags(
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
                    current_avatar_id = getattr(musetalk_state, "current_musetalk_frame_data", {}).get("avatar_id")
                    if not maybe_transition_musetalk_avatar_back_to_default(current_avatar_id):
                        transition_musetalk_to_local_idle(advance_to_next_frame=True)
            elif avatar_mode == "vam" and not stop_flag.is_set():
                pass
            else:
                clear_avatar_stream_state()
            audio_playing.clear()
            manual_pause_active.clear()
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

def _ensure_selected_stt_backend():
    desired_backend = str(RUNTIME_CONFIG.get("stt_backend", "none") or "none").strip().lower()
    if stt_model is None or stt_backend_name != desired_backend:
        init_stt()
    return stt_model


def transcribe_audio_with_stt(audio, language=None):
    model = _ensure_selected_stt_backend()
    if model is None:
        return None
    return model.transcribe(
        audio,
        language=language if language is not None else RUNTIME_CONFIG.get("stt_language", None),
    )


def transcribe_file_with_stt(path, language=None):
    model = _ensure_selected_stt_backend()
    if model is None:
        return (), None
    raw_transcriber = getattr(model, "transcribe_file_raw", None)
    if callable(raw_transcriber):
        return raw_transcriber(
            str(path),
            language=language if language is not None else RUNTIME_CONFIG.get("stt_language", None),
        )
    text = model.transcribe_file(
        str(path),
        language=language if language is not None else RUNTIME_CONFIG.get("stt_language", None),
    )
    return (), {"text": text or ""}


audio_story_runtime.configure_runtime(
    runtime_config=RUNTIME_CONFIG,
    update_runtime_config=update_runtime_config,
    audio_segment_cls=AudioSegment,
    transcribe_file=transcribe_file_with_stt,
    init_tts=init_tts,
    get_text_chunk_limits=get_text_chunk_limits,
    intelligent_chunk_text=intelligent_chunk_text,
    tts_model_getter=lambda: tts_model,
    set_seed=set_seed,
    save_wav=save_audio_file,
    safe_delete=safe_delete_with_retry,
    apply_chat_provider_generation_fields=_apply_chat_provider_generation_fields,
    ensure_chat_provider_model_ready=_ensure_chat_provider_model_ready,
)


def listen_for_speech(source, timeout=None):
    return stt_runtime.listen_for_speech(
        source,
        recognizer=recognizer,
        microphone_active=microphone_active,
        transcribe_func=transcribe_audio_with_stt,
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
        transcribe_func=transcribe_audio_with_stt,
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


def _display_input_turn_content(turn):
    content = str((turn or {}).get("content", "") or "").strip()
    attachment_image_path = str((turn or {}).get("attachment_image_path", "") or "").strip()
    if attachment_image_path:
        content = (content or "Please respond to the image I just sent you.") + " [Image attached]"
    return content


def _append_chat_turn(turn):
    conversation_history.append(dict(turn))


def _set_pending_loaded_input_turn(turn):
    global pending_loaded_input_turn
    pending_loaded_input_turn = dict(turn)


def _consume_pending_loaded_input_turn():
    global pending_loaded_input_turn
    if not isinstance(pending_loaded_input_turn, dict):
        return None
    loaded_content = str(pending_loaded_input_turn.get("content", "") or "").strip()
    loaded_role = str(pending_loaded_input_turn.get("role", "") or "").strip().lower()
    if not loaded_content or loaded_role not in {"user", "system", "assistant"}:
        pending_loaded_input_turn = None
        return None
    resumed_turn = {
        "role": loaded_role,
        "content": loaded_content,
        "origin": str(pending_loaded_input_turn.get("origin", "input") or "input"),
    }
    attachment_image_path = str(pending_loaded_input_turn.get("attachment_image_path", "") or "").strip()
    if attachment_image_path:
        resumed_turn["attachment_image_path"] = attachment_image_path
        resumed_turn["attachment_source"] = str(pending_loaded_input_turn.get("attachment_source", "image") or "image")
    pending_loaded_input_turn = None
    return resumed_turn


def queue_typed_chat_message(text, role=None):
    content = str(text or "").strip()
    if not content:
        return {"queued": False, "reason": "empty"}
    input_role = str(role or _configured_input_message_role() or "user").strip().lower()
    if input_role not in {"user", "system", "assistant"}:
        input_role = "user"
    turn = {
        "role": input_role,
        "content": content,
        "origin": "input",
    }
    if input_role != "user" and user_image_turns.pending_attachment():
        clear_pending_user_image_attachment()
    _maybe_arm_screen_image_for_user_turn(turn)
    turn = _attach_pending_user_image_to_turn(turn)
    _append_chat_turn(turn)
    _set_pending_loaded_input_turn(turn)
    _request_chat_view_rebuild()
    return {"queued": True, "role": input_role, "content": content}


def _apply_stored_chat_history_limit():
    global conversation_history
    limit = _stored_chat_history_limit()
    conversation_history = conversation_history_runtime.apply_stored_chat_history_limit(conversation_history, limit)


user_image_turns.configure_queue_runtime(
    sanitize_chat_turn=_sanitize_chat_turn,
    append_chat_turn=_append_chat_turn,
    apply_stored_chat_history_limit=_apply_stored_chat_history_limit,
    set_pending_loaded_input_turn=_set_pending_loaded_input_turn,
    request_chat_view_rebuild=_request_chat_view_rebuild,
)


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
    normalized_active_preset_name = active_preset_name.replace("_", " ").replace("-", " ")
    help_context = ""
    help_debug = None
    if normalized_active_preset_name == "tutorial persona":
        help_debug = app_help.explain_help_lookup(model_history_window, force_app_question=True)
        help_context = app_help.build_help_context(model_history_window, force_app_question=True)
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
    for addon_context in _collect_addon_chat_contexts(model_history_window):
        debug = dict(addon_context.get("debug") or {})
        sources = ", ".join(str(item) for item in debug.get("sources", [])[:4])
        print(
            "[RAG] Injected "
            f"{debug.get('matches', '?')} matching chunk(s)"
            f"{f' from {sources}' if sources else ''}."
        )
        messages.append({"role": "system", "content": addon_context.get("context", "")})
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


def refine_system_prompt_text(system_prompt):
    """Refine a system prompt through the currently selected chat provider."""
    original = str(system_prompt or "").strip()
    if not original:
        raise ValueError("System prompt is empty.")
    provider = _chat_provider()
    provider_label = _chat_provider_label(provider)
    provider_metadata = chat_providers.provider_metadata(provider)
    if bool(provider_metadata.get("supports_hosted_runtime")) and not _chat_provider_api_key(provider):
        env_names = []
        for field in list(provider_metadata.get("config_fields") or []):
            if not isinstance(field, dict) or str(field.get("id") or "").strip() != "api_key":
                continue
            env_names = [
                str(name or "").strip()
                for name in list(field.get("env") or [])
                if str(name or "").strip()
            ]
            break
        env_hint = f" or set {' / '.join(env_names)}" if env_names else ""
        raise RuntimeError(f"{provider_label} API key is required. Add it in Chat Provider settings{env_hint}.")
    model_name = str(RUNTIME_CONFIG.get("model_name", "") or "").strip()
    if _is_model_catalog_placeholder(model_name):
        raise RuntimeError("Choose a chat model before refining the system prompt.")
    messages = [
        {
            "role": "system",
            "content": (
                "You refine system prompts for a local desktop AI companion. "
                "Preserve the user's intended persona, behavioral constraints, and safety boundaries. "
                "Improve clarity, structure, instruction hierarchy, and wording. "
                "Return only the refined system prompt text. Do not include commentary, titles, "
                "markdown fences, before/after notes, or explanations."
            ),
        },
        {
            "role": "user",
            "content": "Refine this system prompt:\n\n" + original,
        },
    ]
    params = {"model": model_name, "messages": messages}
    additional_params = {}
    _apply_chat_provider_generation_fields(params, additional_params)
    response = str(_chat_completion_create(params, additional_params) or "").strip()
    if not response:
        raise RuntimeError("The provider returned an empty refined prompt.")
    return response


def refine_instruction_text(text, *, label="Instruction", guidance=""):
    """Refine a short user-authored instruction through the current chat provider."""
    original = str(text or "").strip()
    field_label = str(label or "Instruction").strip() or "Instruction"
    extra_guidance = str(guidance or "").strip()
    if not original:
        raise ValueError(f"{field_label} is empty.")
    provider = _chat_provider()
    provider_label = _chat_provider_label(provider)
    provider_metadata = chat_providers.provider_metadata(provider)
    if bool(provider_metadata.get("supports_hosted_runtime")) and not _chat_provider_api_key(provider):
        env_names = []
        for field in list(provider_metadata.get("config_fields") or []):
            if not isinstance(field, dict) or str(field.get("id") or "").strip() != "api_key":
                continue
            env_names = [
                str(name or "").strip()
                for name in list(field.get("env") or [])
                if str(name or "").strip()
            ]
            break
        env_hint = f" or set {' / '.join(env_names)}" if env_names else ""
        raise RuntimeError(f"{provider_label} API key is required. Add it in Chat Provider settings{env_hint}.")
    model_name = str(RUNTIME_CONFIG.get("model_name", "") or "").strip()
    if _is_model_catalog_placeholder(model_name):
        raise RuntimeError(f"Choose a chat model before refining {field_label}.")
    guidance_text = extra_guidance or "No additional guidance."
    messages = [
        {
            "role": "system",
            "content": (
                "You refine short configuration instructions for a local desktop AI companion. "
                "Preserve the user's intent, constraints, tone, and operational meaning. "
                "Improve clarity, specificity, and wording without adding new requirements. "
                f"Field label: {field_label}. "
                f"Refinement guidance: {guidance_text} "
                "Use the field label and guidance only as instructions; do not rewrite, quote, "
                "summarize, or include them in the answer. The user message contains only the "
                "original text to refine. Return only the refined version of that original text. "
                "Do not include commentary, titles, markdown fences, before/after notes, "
                "explanations, or prompt-wrapper labels."
            ),
        },
        {
            "role": "user",
            "content": original,
        },
    ]
    params = {"model": model_name, "messages": messages}
    additional_params = {}
    _apply_chat_provider_generation_fields(params, additional_params)
    response = str(_chat_completion_create(params, additional_params) or "").strip()
    if not response:
        raise RuntimeError("The provider returned empty refined text.")
    return response


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
            cleaned_parts = []
            if visual_tail_open:
                close_index = text.find("]")
                if close_index < 0:
                    return ""
                visual_tail_open = False
                text = text[close_index + 1:]
            while text:
                match = VISUAL_REPLY_TAG_START_RE.search(text)
                if not match:
                    cleaned_parts.append(text)
                    break
                cleaned_parts.append(text[:match.start()])
                tail = text[match.end():]
                close_index = tail.find("]")
                if close_index < 0:
                    visual_tail_open = True
                    break
                text = tail[close_index + 1:]
            return "".join(cleaned_parts)

        musetalk_state.append_musetalk_preview_log(
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
                    musetalk_state.append_musetalk_preview_log(
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
                    musetalk_state.append_musetalk_preview_log(
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
                musetalk_state.append_musetalk_preview_log(
                    f"🌊 [Stream] Final chunk emitted: chars={len(chunk_text.strip())} "
                    f"quality={float(chunk_info.get('quality', 0.0) or 0.0):.2f} "
                    f"reason={chunk_info.get('reason', 'unknown')} "
                    f"text={raw_chunk_text[:240]!r}"
                )
        except ChatContextLimitReached as e:
            state.error = str(e)
            text_queue.put(str(e))
            print(f"⚠️ Streamed context limit reached: {e}")
            musetalk_state.append_musetalk_preview_log(f"🌊 [Stream] Context limit: {e}")
        except Exception as e:
            error_text = str(e) or repr(e)
            musetalk_state.append_musetalk_preview_log(f"🌊 [Stream] Error: {error_text}")
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
                    musetalk_state.append_musetalk_preview_log(f"🌊 [Stream] Fallback error: {state.error}")
            else:
                state.error = error_text
                print(f"✗ LLM Stream Error: {error_text}")
        finally:
            _llm_request_active.clear()
            state.full_text = "".join(full_parts).strip()
            text_queue.put(None)
            state.done.set()
            musetalk_state.append_musetalk_preview_log(
                f"🌊 [Stream] Reply stream done: total_chars={len(state.full_text)} emitted_any={state.first_chunk_emitted.is_set()}"
            )

    threading.Thread(target=worker, daemon=True, name="nc-llm-stream").start()
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
    if stt_model is None:
        init_stt()
    if str(RUNTIME_CONFIG.get("stt_backend", "none") or "none").strip().lower() == "none":
        print("🔇 STT disabled; microphone input is off. Typed chat and GUI actions remain available.")
        run_conversation_flow(None)
        return
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
    current_replay_voice_path = ""
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
        replay_entries = collect_replayable_chat_entries()
        total = len(replay_entries)
        if total <= 0:
            return [], 0, 0
        try:
            resolved_start = max(1, min(int(start_index or 1), total))
        except Exception:
            resolved_start = 1
        remaining = list(replay_entries[resolved_start - 1:])
        return remaining, resolved_start, total

    def _start_replay_session_from(start_index):
        nonlocal response_text, response_text_is_replay, response_text_replay_kind
        nonlocal current_replay_position, current_replay_total, current_replay_voice_path, pending_replay_text, pending_replay_sequence
        nonlocal silence_elapsed_seconds
        remaining, resolved_start, total = _build_replay_sequence_from(start_index)
        if not remaining:
            print("\n⚠️ No replayable chat messages are available in the current chat context.")
            return False
        if resolved_start <= 1:
            print(f"\n🔁 Replaying chat session ({total} message(s))...")
        else:
            print(f"\n🔁 Replaying chat session from message {resolved_start}/{total} ({len(remaining)} message(s))...")
        _warm_up_replay_voice_paths(remaining)
        response_text = str(remaining[0].get("spoken_text", "") or "").strip()
        current_replay_voice_path = str(remaining[0].get("voice_path", "") or "").strip()
        response_text_is_replay = True
        response_text_replay_kind = "session"
        current_replay_position = resolved_start
        current_replay_total = total
        pending_replay_text = None
        pending_replay_sequence = [
            {
                "text": str(item.get("spoken_text", "") or "").strip(),
                "voice_path": str(item.get("voice_path", "") or "").strip(),
                "index": resolved_start + offset,
                "total": total,
            }
            for offset, item in enumerate(remaining[1:], start=1)
        ]
        silence_elapsed_seconds = 0.0
        return True

    def _queue_replay_session_from(start_index):
        nonlocal pending_replay_text, pending_replay_sequence
        remaining, resolved_start, total = _build_replay_sequence_from(start_index)
        if not remaining:
            print("\n⚠️ No replayable chat messages are available in the current chat context.")
            return False
        if resolved_start <= 1:
            print(f"\n🔁 Replaying chat session ({total} message(s)) after current playback stops...")
        else:
            print(f"\n🔁 Replaying chat session from message {resolved_start}/{total} after current playback stops...")
        pending_replay_text = None
        pending_replay_sequence = [
            {
                "text": str(item.get("spoken_text", "") or "").strip(),
                "voice_path": str(item.get("voice_path", "") or "").strip(),
                "index": resolved_start + offset,
                "total": total,
            }
            for offset, item in enumerate(remaining, start=0)
        ]
        return True

    def _plan_phase2_actions(current_user_text, input_role_override=None):
        conversation_controller.policy = conversation_controller.machine.policy = ConversationPolicy.from_runtime_config(RUNTIME_CONFIG)
        override_role = str(input_role_override or "").strip().lower()
        if override_role in {"user", "system", "assistant"}:
            conversation_controller.policy.input_message_role = override_role
            conversation_controller.machine.policy.input_message_role = override_role
        if str(current_user_text or "") == CONTINUE_ASSISTANT_SENTINEL:
            actions = conversation_controller.on_interaction_status("skip_user_reply")
        elif str(current_user_text or "") == "You continue speaking.":
            actions = conversation_controller.on_interaction_status("skip_speech")
        else:
            actions = conversation_controller.on_user_text(current_user_text)
        actions.extend(conversation_controller.on_thinking_started())
        return actions

    resumed_loaded_turn = _consume_pending_loaded_input_turn()
    if resumed_loaded_turn:
        user_text = str(resumed_loaded_turn.get("content", "") or "")
        print("📚 [Session] Resuming loaded input turn immediately...")

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
                if _hidden_sensory_pingpong_blocked():
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
            current_replay_voice_path = ""
            pending_replay_text = None
            pending_replay_sequence = []
            stream_state = None
            active_ctrl = None
            assistant_history_added = False
            discard_assistant_history = False
            resumed_loaded_turn = _consume_pending_loaded_input_turn()
            if resumed_loaded_turn:
                user_text = str(resumed_loaded_turn.get("content", "") or "")
                print("📚 [Session] Resuming loaded input turn immediately...")
        dry_run_reply_id = None

        # =================================================================================
        # PHASE 1: LISTENING
        # =================================================================================
        if pending_replay_text and not response_text:
            response_text = pending_replay_text
            response_text_is_replay = True
            response_text_replay_kind = "single"
            current_replay_voice_path = ""
            current_replay_position = 1
            current_replay_total = 1
            pending_replay_text = None
        elif pending_replay_sequence and not response_text:
            _warm_up_replay_voice_paths(pending_replay_sequence)
            current_entry = dict(pending_replay_sequence.pop(0) or {})
            response_text = str(current_entry.get("text", "") or "").strip()
            current_replay_voice_path = str(current_entry.get("voice_path", "") or "").strip()
            response_text_is_replay = True
            response_text_replay_kind = "session"
            current_replay_position = int(current_entry.get("index", 1) or 1)
            current_replay_total = int(current_entry.get("total", current_replay_position) or current_replay_position)

        if not user_text and not regenerating and not response_text:
            if bool(RUNTIME_CONFIG.get("offline_replay_only", False)) and not PENDING_GUI_ACTION:
                print("🔁 Offline replay complete.")
                stop_flag.set()
                break
            allow_proactive_replies = bool(RUNTIME_CONFIG.get("allow_proactive_replies", False))
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
                queued_loaded_turn = _consume_pending_loaded_input_turn()
                if queued_loaded_turn:
                    print("\n📋 [Session] Immediate queued input turn detected. Processing now...")
                    user_text = str(queued_loaded_turn.get("content", "") or "")
                    resumed_loaded_turn = queued_loaded_turn
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
                        current_replay_voice_path = ""
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
                    manual_pause_active.set()
                    print("- - - PAUSED - - -")
                    while True:
                        time.sleep(1.0)
                        status = check_interaction_status(source)
                        if status == "pause_speech":
                            manual_pause_active.clear()
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
            input_role_override = None
            if isinstance(resumed_loaded_turn, dict):
                input_role_override = str(resumed_loaded_turn.get("role", "") or "").strip().lower()
            thinking_actions = _plan_phase2_actions(user_text, input_role_override=input_role_override)
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
                    if role != "user" and not is_placeholder and user_image_turns.pending_attachment():
                        clear_pending_user_image_attachment()
                    if resumed_loaded_turn and not is_placeholder:
                        resumed_role = str(resumed_loaded_turn.get("role", "") or "").strip().lower()
                        resumed_content = str(resumed_loaded_turn.get("content", "") or "")
                        if role == resumed_role and content == resumed_content:
                            resumed_loaded_turn = None
                            continue
                    resumed_loaded_turn = None
                    input_turn = {"role": role, "content": content, "origin": "input"}
                    _maybe_arm_screen_image_for_user_turn(input_turn, is_placeholder=is_placeholder)
                    input_turn = _attach_pending_user_image_to_turn(input_turn, is_placeholder=is_placeholder)
                    display_content = _display_input_turn_content(input_turn)
                    if is_placeholder:
                        print(f"🧠 Regenerating proactive thought... ({role})")
                    elif role == "system":
                        print(f"💬 You (system): {display_content}")
                    elif role == "assistant":
                        print(f"💬 You (assistant): {display_content}")
                    else:
                        print(f"💬 You: {display_content}")
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
                        print(
                            f"🔁 Replaying chat session from message "
                            f"{current_replay_position}/{max(current_replay_total, 1)}..."
                        )
                    else:
                        print("🔁 Replaying latest assistant reply...")
                else:
                    print(f"🤖 Assistant: {response_text}")
                    print("------------------------------------------------------------------------------------------------------")
                    print("------------------------------------------------------------------------------------------------------")
                stop_playback.clear()
                set_seed(3918375115)
                if response_text_is_replay and response_text_replay_kind == "session":
                    replay_items = [
                        {
                            "text": sanitize_assistant_text_for_speech(response_text, preserve_emotion_tags=True),
                            "voice_path": current_replay_voice_path,
                            "index": current_replay_position,
                            "total": current_replay_total,
                            "message_id": f"replay:{current_replay_position}",
                        }
                    ]
                    for item in list(pending_replay_sequence or []):
                        replay_index = int((item or {}).get("index", 0) or 0)
                        replay_items.append(
                            {
                                "text": sanitize_assistant_text_for_speech(str((item or {}).get("text", "") or ""), preserve_emotion_tags=True),
                                "voice_path": str((item or {}).get("voice_path", "") or "").strip(),
                                "index": replay_index,
                                "total": int((item or {}).get("total", current_replay_total) or current_replay_total),
                                "message_id": f"replay:{replay_index}",
                            }
                        )
                    pending_replay_sequence = []
                    ctrl = speak_async("", dry_run_reply_id=dry_run_reply_id, replay_items=replay_items)
                else:
                    ctrl = speak_async(
                        sanitize_assistant_text_for_speech(response_text, preserve_emotion_tags=True),
                        dry_run_reply_id=dry_run_reply_id,
                        voice_path_override=current_replay_voice_path if response_text_is_replay else None,
                    )

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
                if response_text_is_replay and status in {
                    "regenerate_response",
                    "retry_user_input",
                    "skip_user_reply",
                    "barge_in",
                    "push_to_talk",
                }:
                    print(f"\n[Replay] Ignored unavailable replay action: {status}")
                    status = None

                # --- ACTION: SKIP / STOP ---
                if status == "skip_speech":
                    if response_text_is_replay and response_text_replay_kind == "session" and hasattr(ctrl, "request_skip_current_message"):
                        print("\n⏭️ Skipping replay message...")
                        active_replay_position = int(current_replay_position or 0)
                        if hasattr(ctrl, "current_replay_index"):
                            try:
                                active_replay_position = int(ctrl.current_replay_index() or active_replay_position)
                            except Exception:
                                active_replay_position = int(current_replay_position or 0)
                        has_ready_next = bool(
                            hasattr(ctrl, "has_ready_replay_message_after")
                            and ctrl.has_ready_replay_message_after(active_replay_position)
                        )
                        if has_ready_next:
                            ctrl.request_skip_current_message()
                        else:
                            next_replay_position = active_replay_position + 1
                            if next_replay_position <= int(current_replay_total or 0) and _queue_replay_session_from(next_replay_position):
                                if hasattr(ctrl, "cancel"):
                                    ctrl.cancel()
                                else:
                                    ctrl.request_skip_current_message()
                                if stream_state is not None:
                                    stream_state.cancel_requested.set()
                                break
                            ctrl.request_skip_current_message()
                    else:
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
                        manual_pause_active.clear()
                        playback_paused.clear()
                        last_resume_requested_at = time.time()
                        print("- - - RESUME REQUESTED - - -")
                    elif pause_after_chunk.is_set():
                        manual_pause_active.clear()
                        pause_after_chunk.clear()
                        print("- - - PAUSE AFTER CHUNK CANCELED - - -")
                    else:
                        manual_pause_active.set()
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
                current_replay_voice_path = ""
                listening_active.clear()
                active_ctrl = None
                stream_state = None
                continue
            if regenerating:
                response_text = None
                response_text_is_replay = False
                response_text_replay_kind = ""
                current_replay_voice_path = ""
            elif was_barge_in and user_text:
                response_text = None
                response_text_is_replay = False
                response_text_replay_kind = ""
                current_replay_voice_path = ""
            else:
                user_text = None
                response_text = None
                response_text_is_replay = False
                response_text_replay_kind = ""
                current_replay_voice_path = ""
            listening_active.clear()
            active_ctrl = None
            stream_state = None


# ============================================================================
# AVATAR ADAPTER PATTERN
# ============================================================================
AvatarAdapter = avatar_runtime.AvatarAdapter


def create_avatar_adapter_for_mode(avatar_mode: str):
    """Create the selected avatar adapter through the core avatar host context."""
    runtime_context = avatar_runtime_context.build_avatar_runtime_context(
        runtime_config=RUNTIME_CONFIG,
        avatar_profile=AVATAR_PROFILE,
        current_body_state=CURRENT_BODY_STATE,
        edit_emotion_getter=lambda: EDIT_EMOTION,
        force_edit_mode_getter=lambda: FORCE_EDIT_MODE,
        hand_debug=avatar_hand_state.HAND_DEBUG,
        hand_calibration=avatar_hand_state.HAND_CALIBRATION,
        normalize_vam_root=normalize_vam_root,
        derive_vam_bridge_root=derive_vam_bridge_root,
        default_vam_root=DEFAULT_VAM_ROOT,
        default_vam_emotion_preset_map=DEFAULT_VAM_EMOTION_PRESET_MAP,
        default_vam_timeline_clip_map=DEFAULT_VAM_TIMELINE_CLIP_MAP,
        audio_segment_cls=AudioSegment,
        invalidate_available_emotion_names_fn=invalidate_available_emotion_names,
        avatar_preview_state_module=musetalk_state,
        log_memory_checkpoint_fn=log_musetalk_memory_checkpoint,
        stop_flag_event=stop_flag,
        stop_playback_event=stop_playback,
        dry_run_module=dry_run,
    )
    return avatar_runtime_context.create_avatar_adapter_for_mode(
        avatar_mode,
        runtime_context=runtime_context,
        addon_capability_invoker=lambda addon_id, capability, payload: _invoke_avatar_addon_capability(
            addon_id,
            capability,
            payload=payload,
            default=None,
        ),
        addon_manager_available=_get_addon_manager() is not None,
    )


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
        try:
            print("🔁 Offline replay mode: unloading active LM Studio models to free resources.")
            unload_lmstudio_models()
        except Exception as exc:
            print(f"⚠️ Offline replay could not unload active LM Studio models: {exc}")
    else:
        if not _chat_provider_connection_check():
            return

    avatar_mode = str(RUNTIME_CONFIG.get("avatar_mode", "vseeface") or "vseeface").strip().lower()
    selected_model_name = str(RUNTIME_CONFIG.get("model_name", "") or "").strip()
    chat_provider = _chat_provider()

    if avatar_mode == "musetalk" and not offline_replay_only:
        try:
            unload_lmstudio_models()
        except Exception as exc:
            print(f"⚠️ [LM Studio] Could not unload active models before MuseTalk warmup: {exc}")

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
        elif str(RUNTIME_CONFIG.get("stt_backend", "none") or "none").strip().lower() == "none":
            main_loop()
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
        stop_flag.set()
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
