"""Constants shared by the runtime-backed main window and bridge shims."""

import ctypes
import os
from collections import OrderedDict
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
APP_TITLE = "Neural Companion"
SESSION_PATH = Path("qt_session.json")
DEFAULT_LOCAL_VAM_ROOT = ""
DEFAULT_LOCAL_VAM_EXECUTABLE = "VaM.exe"
DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER = "VaM (Desktop Mode).bat"
DEFAULT_LOCAL_VAM_VR_LAUNCHER = "VaM (OpenVR).bat"
QT_PREVIEW_CACHE_LIMIT = 384
QT_PREVIEW_INITIAL_PRELOAD = 96
QT_PREVIEW_AHEAD_PRELOAD = 72
QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_MAX_RESPONSE_TOKENS = 600
DRY_RUN_MAX_RESPONSE_TOKENS = 600
MUSE_VRAM_MODE_LABELS = OrderedDict([
    ("quality", "Quality"),
    ("balanced", "Balanced"),
    ("low", "Low VRAM"),
    ("very_low", "Very Low VRAM"),
])
MUSE_AVATAR_RESULTS_DIR = Path("MuseTalk") / "results" / "v15" / "avatars"
MODEL_ADVISOR_BUILTIN_FINGERPRINTS_GIB = {
    "musetalk": {
        "Quality": 5.8,
        "Balanced": 4.0,
        "Low VRAM": 2.3,
        "Very Low VRAM": 1.5,
    },
    "vseeface": 0.8,
    "vam": 1.0,
}
MODEL_ADVISOR_TTS_OVERHEAD_GIB = {
    "pockettts": 2.0,
    "pockettts_multilingual": 2.0,
    "chatterbox": 5.2,
    "chatterbox_multilingual": 5.8,
}
MODEL_ADVISOR_STREAM_OVERHEAD_GIB = 0.5
MODEL_ADVISOR_SAFETY_MARGIN_GIB = 1.5
PERFORMANCE_PROFILE_APPLY_KEYS = {
    "avatar_mode",
    "stream_mode",
    "tts_backend",
    "musetalk_vram_mode",
    "model_name",
    "chunk_target_chars",
    "chunk_max_chars",
    "musetalk_chunk_target_chars",
    "musetalk_chunk_max_chars",
    "musetalk_quickstart_1_target_chars",
    "musetalk_quickstart_1_max_chars",
    "musetalk_quickstart_2_target_chars",
    "musetalk_quickstart_2_max_chars",
    "stream_chunk_target_chars",
    "stream_chunk_max_chars",
    "stream_first_chunk_min_chars",
    "stream_force_flush_seconds",
    "stream_force_flush_later_seconds",
}

_WIN32_DOCK_OWNER_SUPPORTED = False
_WIN32_GWLP_HWNDPARENT = -8
_win32_set_window_owner = None
try:
    if os.name == "nt":
        _win32_user32 = ctypes.windll.user32
        _win32_get_window_owner = getattr(_win32_user32, "GetWindowLongPtrW", None) or getattr(_win32_user32, "GetWindowLongW", None)
        _win32_set_window_owner = getattr(_win32_user32, "SetWindowLongPtrW", None) or getattr(_win32_user32, "SetWindowLongW", None)
        if _win32_get_window_owner is not None and _win32_set_window_owner is not None:
            _win32_get_window_owner.argtypes = [ctypes.c_void_p, ctypes.c_int]
            _win32_get_window_owner.restype = ctypes.c_void_p
            _win32_set_window_owner.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            _win32_set_window_owner.restype = ctypes.c_void_p
            _WIN32_DOCK_OWNER_SUPPORTED = True
except Exception:
    _WIN32_DOCK_OWNER_SUPPORTED = False
