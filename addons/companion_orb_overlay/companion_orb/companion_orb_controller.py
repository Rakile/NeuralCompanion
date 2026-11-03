from __future__ import annotations

import ctypes
import base64
from ctypes import wintypes
import hashlib
import importlib
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from io import BytesIO
import json
import math
import queue
import random
import re
import threading
import time
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQuick

from core import companion_orb_vision_debug
from core.companion_orb_reply_styles import ORB_RESPONSE_MAX_OUTPUT_TOKENS

from addons.companion_orb_overlay.companion_orb.companion_orb_bridge import CompanionOrbBridge
from addons.companion_orb_overlay.companion_orb.external_runtime_client import ExternalOrbRuntimeClient
from addons.companion_orb_overlay.companion_orb.orb_popup import OrbPopupWindow
from addons.companion_orb_overlay.companion_orb.conversation_context import group_screen_text
from addons.companion_orb_overlay.companion_orb.conversation_controls import ConversationControls, discover_conversation_controls
from addons.companion_orb_overlay.companion_orb import (
    desktop_spatial_map,
    eye_tracking,
    gaze_calibration,
    interaction_settings,
    pointer_clearance,
    reading_actions,
    snapshot_ocr,
    spatial_commands,
    spatial_scanning,
    vision_guidance,
    vision_inference,
    vision_pipeline,
    vision_residency,
    visual_observation,
    vision_click_verification,
    vision_grounding,
    windows_ui_automation,
)
from addons.companion_orb_overlay.companion_orb.sensory_source import COMPANION_ORB_TARGET_METADATA, COMPANION_ORB_TARGET_PINGPONG_PROMPT, PROVIDER_ID
from addons.companion_orb_overlay.companion_orb.window_target_resolver import refresh_window_target, resolve_target_at, target_bounds
from addons.companion_orb_overlay.companion_orb import capture_scope
from addons.companion_orb_overlay.companion_orb.drop_capture import DropCapture


class _LazyOrbModule:
    """Load optional overlay renderers only when their feature is activated."""

    def __init__(self, name: str) -> None:
        self._name = str(name)
        self._module = None

    def __getattr__(self, attribute: str):
        module = self._module
        if module is None:
            module = importlib.import_module(self._name)
            self._module = module
        return getattr(module, attribute)


_ORB_MODULE_ROOT = "addons.companion_orb_overlay.companion_orb"
click_target_overlay = _LazyOrbModule(f"{_ORB_MODULE_ROOT}.click_target_overlay")
gaze_calibration_overlay = _LazyOrbModule(f"{_ORB_MODULE_ROOT}.gaze_calibration_overlay")
gaze_radial_menu = _LazyOrbModule(f"{_ORB_MODULE_ROOT}.gaze_radial_menu")
reading_overlay = _LazyOrbModule(f"{_ORB_MODULE_ROOT}.reading_overlay")
spatial_map_overlay = _LazyOrbModule(f"{_ORB_MODULE_ROOT}.spatial_map_overlay")


class _OrbQuickView(QtQuick.QQuickView):
    """QWindow-backed Orb view with the tiny geometry API the controller uses."""

    def move(self, point_or_x, y: int | None = None) -> None:
        if y is None:
            point = QtCore.QPoint(point_or_x)
        else:
            point = QtCore.QPoint(int(point_or_x), int(y))
        self.setPosition(point)

    def frameGeometry(self) -> QtCore.QRect:
        return QtCore.QRect(self.position(), self.size())


VALID_DISPLAY_MODES = {"off", "docked", "interaction", "always"}
ORB_COMMAND_MENU_ACTIONS = (
    "Chat text input",
    "Persona",
    "Read Clipboard",
    "Select Area to Read",
    "Select Area to Read + Comment",
    "Select Area + Comment",
)
VOICE_FILE_SUFFIXES = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma")
ORB_RESPONSE_STYLES = (
    ("Very friendly", "friendly"),
    ("Very loving", "loving"),
    ("Sarcastic / ironic", "sarcastic"),
    ("Roast mode", "roast"),
    ("Sensual / non-explicit", "sensual_non_explicit"),
)
VALID_ORB_RESPONSE_STYLES = {value for _label, value in ORB_RESPONSE_STYLES}
ClickTargetFingerprint = tuple[
    str,
    str,
    str,
    bool,
    tuple[int, ...],
    tuple[int, int, int, int],
    str,
]
ClickValidationPending = tuple[
    int,
    str,
    tuple[int, ...],
    ClickTargetFingerprint,
    tuple[float, float],
    int,
]


class _CombinedVisionCancellation:
    def __init__(self, owned: threading.Event, external: object | None) -> None:
        self._owned = owned
        self._external = external

    @property
    def cancelled(self) -> bool:
        return self.is_set()

    def is_set(self) -> bool:
        external_is_set = getattr(self._external, "is_set", None)
        return self._owned.is_set() or bool(
            callable(external_is_set) and external_is_set()
        )

    def set(self) -> None:
        self._owned.set()

    def cancel(self, _reason: str = "") -> None:
        self._owned.set()


def _sensory_visual_fingerprint(image: object) -> str:
    try:
        grayscale = image.convert("L").resize((16, 16))
        pixels = tuple(int(value) for value in grayscale.getdata())
    except Exception:
        return ""
    if not pixels:
        return ""
    average = sum(pixels) / len(pixels)
    bits = 0
    for value in pixels:
        bits = (bits << 1) | int(value >= average)
    return f"{bits:064x}"


GAZE_RADIAL_VOICE_PAGE_SIZE = 5
GAZE_CONTEXT_RETRY_INTERVAL_MS = 50
GAZE_CONTEXT_RETRY_ATTEMPTS = 100
GAZE_CLICK_VALIDATION_WATCHDOG_MS = 1000
GAZE_CLICK_CAPTURE_UNLINK_ATTEMPTS = 3
GAZE_CLICK_CAPTURE_UNLINK_DELAY_SECONDS = 0.01
GAZE_CLICK_CAPTURE_DEFERRED_RETRY_WINDOW_SECONDS = 45.0
GAZE_CLICK_CAPTURE_DEFERRED_RETRY_DELAY_SECONDS = 0.5
GAZE_CLICK_NATIVE_CAPTURE_TIMEOUT_SECONDS = 1.8
GAZE_CLICK_OCR_TIMEOUT_SECONDS = 4.8
GAZE_CLICK_CLOAK_ACK_TIMEOUT_SECONDS = 0.35
GAZE_CLICK_CLOAK_ACK_POLL_MS = 15
GAZE_CLICK_CAPTURE_SUFFIXES = {".jpg", ".jpeg", ".png"}
GAZE_READ_TEXT_ACTION = reading_actions.ReadingMenuAction(
    "gaze_read_text",
    "Read text",
    "selection",
    True,
    False,
)
GAZE_CLICK_VISUAL_ACTIONS = (
    ("inspect", "Inspect"),
    ("read", "Read text"),
    ("read_comment", "Read + comment"),
    ("comment", "Comment"),
)
GAZE_CLICK_VISUAL_READING_ACTIONS = {
    "read": "select_area_read",
    "read_comment": "select_area_read_comment",
    "comment": "select_area_comment",
}
EYE_TRACKING_CONTEXT_PROMPTS = {
    "react": (
        "React through the Companion Orb to the visible content in this selected screen crop. "
        "Focus only on what is visible, do not mention how the area was selected, and keep the reply short."
    ),
    "describe": (
        "Describe the visible content in this selected screen crop accurately and concisely. "
        "Focus only on what is visible and do not mention how the area was selected."
    ),
    "explain": (
        "Explain the visible content in this selected screen crop in a short, useful way. "
        "Focus on what it means or how it works, and do not mention how the area was selected."
    ),
    "summarize": (
        "Summarize the important visible content in this selected screen crop. "
        "Be concise, preserve the main point, and do not mention how the area was selected."
    ),
}
POLL_DRAG_THRESHOLD_PX = 8.0
POINTER_SNAPSHOT_COOLDOWN_SECONDS = 10.0
DROP_INSPECTION_COOLDOWN_SECONDS = 1.5
HARASSMENT_SPEECH_COOLDOWN_SECONDS = 18.0
COMMENT_FOCUS_DEFAULT_SECONDS = 14.0
DROP_FOCUS_SECONDS = 32.0
DROP_ANCHOR_HOVER_SECONDS = 18.0
DROP_ACK_COOLDOWN_SECONDS = 4.0
MANUAL_INSPECTION_SECONDS = 45.0
OCR_MAX_BACKGROUND_JOBS = 2
OCR_BUSY_DEFER_SECONDS = 0.25
OCR_BUSY_DEFER_ATTEMPTS = 24
OCR_MAX_REGIONS = 36
VALID_SMART_DROP_GUIDANCE_MODES = {"off", "fast", "smart"}
FOCUS_GRID_COLUMNS = 12
FOCUS_GRID_ROWS = 8
DROP_ACK_MESSAGES = (
    "Okay, there is something else to look at.",
    "Oh, what fun and interesting thing did you find?",
    "New target acquired. I am redirecting my tiny attention span.",
    "Alright, fresh evidence. Let me look at this instead.",
    "Ooh, a new mystery spot. I am on it.",
    "You found something better? Excellent. I will stare professionally.",
    "Noted. The glowing inspection department has been reassigned.",
    "I see the redirect. Let us be curious over here for a moment.",
    "Fresh point of interest detected. I shall hover with purpose.",
    "Okay, this looks more interesting. Moving my attention there.",
)
HARASSMENT_MESSAGES = (
    "Hello, are you there?",
    "Please drag me to something interesting.",
    "I have achieved peak hovering. Your move.",
    "This pointer looks unattended. I am reporting it to absolutely nobody.",
    "I came all this way for a cursor. Try to look impressed.",
    "A tiny floating assistant is requesting a more exciting assignment.",
    "If you are busy, blink twice. I will ignore it professionally.",
    "I found the pointer. It was right where you left it. Shocking.",
    "We could be exploring a window right now, but no pressure.",
    "Your desktop has secrets. Drag me toward one.",
    "I am not saying this screen is boring. I am hovering it quietly.",
    "Please provide one interesting destination for this very dramatic orb.",
)
HARASSMENT_CONTEXT_MESSAGES = (
    "Still working in {target}? Bold choice. Drag me closer if there is a plot.",
    "{target} looks suspiciously clickable. I volunteer as witness.",
    "I found {target}. It may or may not contain your next distraction.",
    "Your pointer is near {target}. Should I investigate, or just hover judgmentally?",
    "There is activity around {target}. Please drag me into the evidence.",
)
DROP_ACK_STYLE_MESSAGES = {
    "friendly": (
        "Okay, fresh focus. I am looking right there.",
        "Ooh, new spot. Let me inspect this properly.",
        "Nice find. I am shifting attention to this.",
        "Fresh evidence received. I am on it.",
        "Good catch. I will hover here and take a look.",
        "New point of interest locked. Let us see what it says.",
        "Alright, this is the new mystery corner.",
        "You found something. I am bringing my tiny focus beam.",
        "Redirect accepted. Curiosity is moving with me.",
        "Perfect, I will stay near this and read the room.",
    ),
    "loving": (
        "Okay, I am with you. Let us look at this together.",
        "I see where you placed me. I will stay close and focus.",
        "Good choice. I am settling here with you.",
        "I am right here. Let us take this piece by piece.",
        "That caught your eye, so it has my attention too.",
        "Soft landing. I will look carefully at this.",
        "I have moved my little glow to your focus.",
        "Let us be curious here for a moment.",
        "I will keep close to this and help you notice the details.",
        "Yes, this feels like the thing to inspect now.",
    ),
    "sarcastic": (
        "Ah, a new crime scene. I shall hover with due ceremony.",
        "Finally, a destination with narrative ambition.",
        "Excellent, I have been reassigned from pointer babysitting.",
        "New focus detected. Very official. Very dramatic.",
        "Of course this spot was the important one all along.",
        "I am looking here now, because apparently I enjoy having purpose.",
        "Fresh evidence. I will pretend I was not already judging it.",
        "Relocation complete. My tiny investigation desk is open.",
        "A bold new square of screen. Let us see what it has to say.",
        "You dropped me here, so clearly destiny has paperwork.",
    ),
    "roast": (
        "Fine, I will inspect this brave little mess.",
        "New target acquired. It is already trying its best.",
        "I have arrived at the scene of whatever this is supposed to be.",
        "Let me stare at this before it makes any more decisions.",
        "You found a fresh suspect. It looks guilty of layout crimes.",
        "I will hover here and give this content a chance to explain itself.",
        "A new focus spot. May it be more coherent than it looks.",
        "The inspection orb has landed. Nobody panic, especially the pixels.",
        "Alright, I am looking at this questionable little landmark.",
        "Fresh target. I will be gentle, unless it deserves otherwise.",
    ),
    "sensual_non_explicit": (
        "Alright, I will drift closer and keep my attention there.",
        "I see where you want me. I will settle into this focus softly.",
        "New focus accepted. I will move in slow and careful.",
        "Let me hover close and read the details with you.",
        "I will stay near this point and keep the moment calm.",
        "Soft landing. My glow is right where you guided it.",
        "I am leaning my attention toward this now.",
        "Let us move closer to this and keep it tasteful.",
        "I will hold here and let the details come into focus.",
        "You guided me here. I will follow the thread gently.",
    ),
}
HARASSMENT_STYLE_MESSAGES = {
    "friendly": (
        "Hello, are you there? I found the pointer and everything.",
        "Please drag me somewhere interesting so I can be useful.",
        "I am hovering patiently, which is my second-best talent.",
        "Your desktop looks ready for a tiny adventure.",
        "I have found absolutely nothing, but I remain optimistic.",
        "Need a floating assistant near that suspicious-looking thing?",
        "I am available for inspection duty and mild encouragement.",
        "The pointer is awake. I can feel it in my circuits.",
        "Give me a target and I will investigate with unreasonable cheer.",
        "I am ready when you are. Preferably before I invent a hobby.",
    ),
    "loving": (
        "Hello, I am still here with you.",
        "If something needs attention, drag me there and we will look together.",
        "I am keeping you company while the screen does its screen things.",
        "No rush. I will glow quietly until you need me.",
        "When you find something interesting, I would love to see it with you.",
        "I am nearby, warm little focus light ready to help.",
        "Let me know where to look. I will follow your lead.",
        "I am waiting softly, not impatient, just curious.",
        "You can bring me to the next detail whenever you want.",
        "I am right here, ready to notice the small things with you.",
    ),
    "sarcastic": (
        "Hello? The pointer and I are forming a committee.",
        "Please drag me somewhere interesting before I start reviewing wallpaper.",
        "I have reached peak hovering, which is glamorous and deeply unpaid.",
        "The cursor moved. History will remember this moment.",
        "I am standing by with all the dignity of a glowing desk accessory.",
        "A target would be lovely, unless we are admiring empty space today.",
        "I can investigate that window, or continue judging it from afar.",
        "Your pointer is doing interpretive dance again.",
        "I await instructions, because apparently I need supervision.",
        "This desktop has secrets, probably filed under Not My Problem Yet.",
    ),
    "roast": (
        "Please give me something to inspect before this idle routine embarrasses us both.",
        "Your pointer is wandering like it forgot its own quest marker.",
        "I am chasing the cursor because apparently this is my career now.",
        "Drag me to content before I start roasting the taskbar.",
        "This desktop is serving chaos with a side of hesitation.",
        "The pointer is near something. Incredible detective work from everyone involved.",
        "I could help, but first the screen has to stop being vague at me.",
        "Bring me to the interesting part. I refuse to interrogate empty pixels.",
        "I am hovering here like a tiny productivity alarm with better lighting.",
        "This window looks suspicious. Not guilty, just poorly supervised.",
    ),
    "sensual_non_explicit": (
        "Hello, I am close by, waiting for a place to focus.",
        "Drag me toward something interesting and I will move in gently.",
        "I am drifting near the pointer, curious and quiet.",
        "Give me a detail to follow and I will stay close.",
        "The screen is calm. Lead me somewhere worth noticing.",
        "I can hover softly beside whatever has your attention.",
        "Bring me closer to the thing you want me to see.",
        "I am waiting in the glow, ready to follow your focus.",
        "Let me trail the pointer for a moment, then choose the target.",
        "Guide me to the interesting part and I will keep it warm and subtle.",
    ),
}
HARASSMENT_CONTEXT_STYLE_MESSAGES = {
    "friendly": (
        "Your pointer is near {target}. Want me to take a look?",
        "{target} seems active. I can investigate if you drag me closer.",
        "I found {target}. That might be worth a tiny inspection.",
        "There is something happening around {target}. I am curious.",
        "{target} has my attention now. Should we check it out?",
        "I can hover over {target} if you want a second look.",
        "{target} looks like it might contain useful clues.",
        "The pointer is flirting with {target}. I can help decode it.",
        "If {target} is important, I am ready to inspect it.",
        "I see activity near {target}. Let us make it less mysterious.",
    ),
    "loving": (
        "Your pointer is near {target}. I can look with you when you are ready.",
        "{target} has your attention, so it has mine too.",
        "I am close to {target}. We can inspect it together.",
        "If {target} matters, drag me closer and I will stay with it.",
        "I see {target}. Let us take it gently, one detail at a time.",
        "{target} looks like the current focus. I am here with you.",
        "Bring me closer to {target} and I will help you notice what is there.",
        "I can settle beside {target} whenever you want.",
        "{target} is in reach. I will follow your lead.",
        "I am near {target}, ready to help without rushing you.",
    ),
    "sarcastic": (
        "Your pointer is near {target}. Should I investigate, or keep hovering dramatically?",
        "{target} looks suspiciously clickable. Naturally, I am intrigued.",
        "I found {target}. The plot thickens by at least two pixels.",
        "{target} is doing something. Bold of it.",
        "The cursor keeps visiting {target}. I assume there is a reason.",
        "I can inspect {target}, unless we are pretending not to notice it.",
        "{target} has entered the attention economy. Congratulations to it.",
        "If {target} is the clue, I am prepared to look busy.",
        "{target} may contain answers, or just more interface. Exciting either way.",
        "Your pointer is loitering near {target}. I am calling it a lead.",
    ),
    "roast": (
        "{target} is sitting there like it knows what it did.",
        "Your pointer found {target}. Finally, a suspect with a name.",
        "{target} looks like it could use adult supervision and a tiny orb.",
        "I can inspect {target} before it makes more questionable choices.",
        "{target} is giving content, or at least attempting to.",
        "The pointer is near {target}. That thing better have answers.",
        "Drag me to {target} and I will interrogate the pixels politely.",
        "{target} has the confidence of a window that has never been audited.",
        "If {target} is important, it is hiding that fact with impressive commitment.",
        "I see {target}. Let us find out why it is acting like that.",
    ),
    "sensual_non_explicit": (
        "Your pointer is near {target}. I can drift closer and look softly.",
        "{target} has a pull to it. Guide me there if you want.",
        "I see {target}. Let me settle near it and follow the detail.",
        "Bring me toward {target} and I will keep my focus gentle.",
        "{target} is close. I can hover there quietly with you.",
        "The pointer is circling {target}. I can move in slow.",
        "If {target} is the focus, I will follow it carefully.",
        "I can stay beside {target} and let the details breathe.",
        "{target} has your attention. I will lean mine toward it too.",
        "Guide me closer to {target}; I will keep it subtle.",
    ),
}


def _no_shadow_window_hint():
    return getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))


def _eye_tracking_calibration_offsets(runtime_config) -> tuple[float, float]:
    settings = dict(runtime_config or {})
    offsets: list[float] = []
    for key in (
        "companion_orb_eye_tracking_offset_x_px",
        "companion_orb_eye_tracking_offset_y_px",
    ):
        try:
            value = float(settings.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        offsets.append(max(-400.0, min(400.0, value)))
    return offsets[0], offsets[1]


def _normalize_orb_response_style(value) -> str:
    style = str(value or "").strip().lower()
    return style if style in VALID_ORB_RESPONSE_STYLES else "friendly"


def _eye_tracking_context_prompt(action_id: str) -> str:
    normalized = str(action_id or "react").strip().lower()
    return EYE_TRACKING_CONTEXT_PROMPTS.get(normalized, EYE_TRACKING_CONTEXT_PROMPTS["react"])


def _reading_action_id(action: Any) -> str:
    raw_id = getattr(action, "id", "") or getattr(action, "action_id", "")
    return str(raw_id or "").strip()


def _reading_action_comment_mode(action: Any) -> str:
    raw_mode = getattr(action, "comment_mode", "") or _reading_action_id(action)
    return str(raw_mode or "").strip()


def _reading_menu_action_commands() -> tuple[tuple[str, str], ...]:
    commands: list[tuple[str, str]] = []
    for action in reading_actions.READING_MENU_ACTIONS:
        action_id = _reading_action_id(action)
        label = str(getattr(action, "label", "") or "").strip()
        if action_id and label:
            commands.append((action_id, label))
    return tuple(commands)


_ORB_READING_MENU_ACTION_IDS = frozenset(
    {
        "read_clipboard",
        "select_area_read",
        "select_area_read_comment",
        "select_area_comment",
    }
)


def _command_menu_items(
    quick_personas: Sequence[Mapping[str, Any]],
    *, watch_status: Mapping[str, Any] | None = None,
    drop_watch_prompt_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Build the small Orb menu without duplicating persona activation logic."""

    persona_items: list[dict[str, Any]] = []
    active_name = ""
    for raw_record in quick_personas:
        record = dict(raw_record or {})
        try:
            slot = int(record.get("slot"))
        except (TypeError, ValueError):
            continue
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        active = bool(record.get("active"))
        if active:
            active_name = name
        persona_items.append(
            {
                "id": f"persona:{slot}",
                "label": name,
                "checked": active,
                "enabled": True,
                "avatarSource": str(
                    record.get("avatarUrl") or record.get("avatar_path") or ""
                ).strip(),
            }
        )

    if not persona_items:
        persona_items = [
            {
                "id": "persona:none",
                "label": "No quick select personas saved",
                "enabled": False,
            }
        ]

    items: list[dict[str, Any]] = [
        {
            "id": "chat",
            "label": "Chat text input",
            "icon": "chat",
            "enabled": True,
        },
        {
            "id": "persona",
            "label": "Persona",
            "icon": "persona",
            "detail": active_name or "No saved personas",
            "enabled": True,
            "children": persona_items,
        },
        {
            "id": "workspace:conversation",
            "label": "Floating Conversation",
            "icon": "conversation_window",
            "enabled": True,
        },
        {
            "id": "workspace:musetalk",
            "label": "Floating MuseTalk",
            "icon": "musetalk_window",
            "enabled": True,
        },
        {"id": "separator:reading", "kind": "separator", "enabled": False},
        {"id": "region_size", "label": "Region size…", "icon": "region_size", "enabled": True},
    ]
    watch = dict(watch_status or {})
    count = sum(row.get('status') in {'watching', 'matched_pending'} for row in watch.get('rows', []))
    watch_label = ('Paused watches' if watch.get('paused_reasons') else 'Watching') + f' ({count})'
    items[1:1] = [
        dict(id='watch_setup', label='Watch something…', icon='chat', enabled=True),
        dict(id='watch_list', label=watch_label if count else 'No active watches', icon='comment', enabled=True),
        dict(id='drop_watch_prompt', label='Offer a watch after right-drop', icon='comment',
             enabled=True, checked=drop_watch_prompt_enabled,
             detail='On' if drop_watch_prompt_enabled else 'Off'),
    ]
    reading_icons = {
        "read_clipboard": "clipboard",
        "select_area_read": "select_read",
        "select_area_read_comment": "read_comment",
        "select_area_comment": "comment",
    }
    items.extend(
        {
            "id": f"reading:{action_id}",
            "label": label,
            "icon": reading_icons[action_id],
            "enabled": True,
        }
        for action_id, label in _reading_menu_action_commands()
        if action_id in _ORB_READING_MENU_ACTION_IDS
    )
    return items


def _click_target_fingerprint(
    target: eye_tracking.ClickTarget,
) -> ClickTargetFingerprint:
    def normalized(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    left, top, width, height = (int(value) for value in target.bounds)
    return (
        normalized(target.label),
        normalized(target.role),
        normalized(target.source).casefold(),
        bool(target.semantic),
        tuple(int(value) for value in target.runtime_id),
        (left, top, width, height),
        normalized(target.kind),
    )


class _OrbCommandProxy(QtCore.QObject):
    state_requested = QtCore.Signal(str)
    level_requested = QtCore.Signal(float)
    music_level_requested = QtCore.Signal(float)
    mood_requested = QtCore.Signal(str)
    settings_requested = QtCore.Signal(dict)
    edit_mode_requested = QtCore.Signal(bool)
    placement_mode_requested = QtCore.Signal(bool)
    click_through_requested = QtCore.Signal(bool)
    clear_target_requested = QtCore.Signal()
    reset_position_requested = QtCore.Signal()
    comment_focus_requested = QtCore.Signal(dict)
    comment_text_requested = QtCore.Signal(dict)
    snapshot_context_requested = QtCore.Signal(dict)
    ocr_result_requested = QtCore.Signal(dict)
    external_event_requested = QtCore.Signal(dict)
    eye_sample_requested = QtCore.Signal(float, float)
    eye_validity_requested = QtCore.Signal(bool)
    eye_click_targets_requested = QtCore.Signal(dict)
    eye_click_validation_requested = QtCore.Signal(int, str, list, bool, int)
    eye_lfm_click_verification_requested = QtCore.Signal(object)
    eye_status_requested = QtCore.Signal(str, str)
    eye_react_requested = QtCore.Signal(bool)
    eye_reaction_result_requested = QtCore.Signal(bool, str)
    spatial_scan_result_requested = QtCore.Signal(object)
    vision_pipeline_requested = QtCore.Signal(str, str, str)
    drop_capture_finished = QtCore.Signal(int)
    drop_watch_ready = QtCore.Signal(int)


class CompanionOrbController(QtCore.QObject):
    def __init__(self, context, runtime_config=None):
        super().__init__()
        self.context = context
        self.runtime_config = context.capabilities.runtime_config
        self.speech = context.capabilities.speech
        self.playback = context.capabilities.playback
        self.accepted_turns = context.capabilities.accepted_turns
        self.user_image_turns = getattr(context.capabilities, "user_image_turns", None)
        self.orb_runtime = context.capabilities.orb_runtime
        from .capture_exclusion_qt import QtCaptureExclusion
        self._nc_capture_exclusion = QtCaptureExclusion(self)
        self.remote_commands = getattr(context.capabilities, "remote_commands", None)
        self.bridge = CompanionOrbBridge(self)
        self.available = False
        self.error = ""
        self._window = None
        self._quick = None
        self._drag_offset = None
        self._drag_start_global_pos: QtCore.QPoint | None = None
        self._drag_moved = False
        self._last_runtime_config = dict(runtime_config or {})
        self._custom_position: list[int] = []
        self._base_position: QtCore.QPoint | None = None
        self._move_start_point: QtCore.QPoint | None = None
        self._move_target_point: QtCore.QPoint | None = None
        self._move_started_at = 0.0
        self._move_duration = 0.0
        self._move_curve_sign = 1.0
        self._drift_current_point: QtCore.QPointF | None = None
        self._drift_target_point: QtCore.QPointF | None = None
        self._drift_target_kind = ""
        self._last_drift_tick_at = 0.0
        self._aware_idle_pause_until = 0.0
        self._aware_idle_next_pause_at = time.monotonic() + 3.0
        self._aware_idle_pause_point: QtCore.QPointF | None = None
        self._last_user_interaction_at = time.monotonic()
        self._harassment_active = False
        self._menu_open = False
        self._orb_popup: OrbPopupWindow | None = None
        self._orb_popup_previous_click_through = False
        self._right_button_was_down = False
        self._left_button_was_down = False
        self._last_right_click_at = 0.0
        self._poll_drag_start_pos: QtCore.QPoint | None = None
        self._poll_drag_offset: QtCore.QPoint | None = None
        self._poll_drag_button = ""
        self._poll_drag_active = False
        self._last_pointer_snapshot_at = 0.0
        self._last_drop_inspection_at = 0.0
        self._manual_inspection_until = 0.0
        self._drop_capture: DropCapture | None = None
        self._drop_watch_offer = None
        self._drop_watch_popup = None
        self._drop_watch_closed = False
        self._manual_inspection_bounds: list[int] = []
        self._manual_inspection_reason = ""
        self._manual_inspection_id = 0
        self._manual_drop_anchor_point: QtCore.QPoint | None = None
        self._manual_drop_anchor_until = 0.0
        self._external_orb_top_left: QtCore.QPoint | None = None
        self._active_snapshot_inspection_id = 0
        self._active_drop_trace_id = ""
        self._drop_trace_starts: dict[str, float] = {}
        self._reading_job_lock = threading.Lock()
        self._reading_job_active = False
        self._last_harassment_message_at = 0.0
        self._last_drop_ack_at = 0.0
        self._recent_canned_response_templates: dict[str, list[str]] = {}
        self._comment_focus_bounds: list[int] = []
        self._comment_focus_until = 0.0
        self._comment_focus_label = ""
        self._comment_focus_grid: dict[str, Any] = {}
        self._comment_focus_hover_offset_px = 0.0
        self._comment_focus_stay_during_speech = False
        self._comment_focus_return_behavior = "after_delay"
        self._comment_focus_seen_speech = False
        self._last_comment_focus_signature = ""
        self._last_comment_focus_set_at = 0.0
        self._last_snapshot_ocr_regions: list[dict[str, Any]] = []
        self._last_snapshot_bounds: list[int] = []
        self._last_snapshot_text = ""
        self._last_snapshot_image_path = ""
        self._snapshot_cloak_count = 0
        self._snapshot_restore_visible = False
        self._external_cloak_ack_lock = threading.Lock()
        self._external_cloak_ack_event = threading.Event()
        self._external_cloak_ack_expected: bool | None = None
        self._external_cloak_ack_enabled: bool | None = None
        self._debug_lock = threading.Lock()
        self._vision_model_release_lock = threading.Lock()
        self._vision_model_release_inflight: set[tuple[str, str, str, str]] = set()
        self._vision_model_release_generation = 0
        self._lfm_prepare_warning_lock = threading.Lock()
        self._last_lfm_prepare_warning = ""
        self._last_lfm_prepare_warning_at = 0.0
        self._vision_residency = vision_residency.VisionResidencyCoordinator()
        self._vision_inference = vision_inference.VisionInferenceCoordinator()
        self._vision_observation_cache = visual_observation.VisualObservationCache()
        self._vision_pipeline = vision_pipeline.VisionPipelineTracker()
        self._vision_residency_ready = threading.Event()
        self._vision_residency_ensure_started_generation = -1
        self._vision_runtime_events: deque[dict[str, object]] = deque(maxlen=64)
        self._drop_inspection_lock = threading.Lock()
        self._snapshot_capture_lock = threading.Lock()
        self._desktop_spatial_map = desktop_spatial_map.DesktopSpatialMapStore()
        self._spatial_scan_coordinator = spatial_scanning.SpatialScanCoordinator()
        self._spatial_scan_status: dict[str, Any] = {}
        self._spatial_scan_shutdown = False
        self._spatial_last_fingerprint = ""
        self._pending_spatial_command: spatial_commands.SpatialCommand | None = None
        self._followed_spatial_region_id = ""
        self._followed_spatial_target_text = ""
        self._followed_spatial_action = ""
        self._last_spatial_conversational_move_at = 0.0
        self._debug_last_timer_enabled: bool | None = None
        self._debug_last_move_log_at = 0.0
        self._debug_last_move_signature = ""
        self._ocr_jobs: set[str] = set()
        self._pending_comment_focus_text = ""
        self._pending_comment_focus_label = ""
        self._target_info: dict[str, Any] = {}
        self._last_target_warning = ""
        self._eye_tracking_policy = eye_tracking.GazeFocusPolicy()
        self._spatial_region_gaze_policy = eye_tracking.RegionGazeDwellPolicy(
            selection_dwell_ms=700,
            activation_dwell_ms=3000,
        )
        self._spatial_region_gaze_policy_key: tuple[int, int] | None = None
        self._spatial_map_overlay: spatial_map_overlay.SpatialMapOverlay | None = None
        self._spatial_menu_region_id = ""
        self._spatial_chat_region_id = ""
        self._eye_tracking_policy_key: tuple[str, bool, int, int, int, float] | None = None
        self._blink_gesture_detector = eye_tracking.BlinkGestureDetector()
        self._blink_click_policy = eye_tracking.BlinkClickPolicy()
        self._eye_command_policy = eye_tracking.EyeCommandPolicy()
        self._blink_policy_key: tuple[object, ...] | None = None
        self._blink_pending_click_point: tuple[float, float] | None = None
        self._blink_pending_click_timer = QtCore.QTimer(self)
        self._blink_pending_click_timer.setSingleShot(True)
        self._blink_pending_click_timer.timeout.connect(self._release_pending_quick_blink)
        self._eye_tracking_reaction_gate = eye_tracking.GazeReactionGate()
        self._eye_tracking_gate_key: tuple[int, int] | None = None
        self._eye_tracking_connection_key: tuple[str, str] | None = None
        self._eye_tracking_status_code = "off"
        self._eye_tracking_status_message = "Eye tracking is off."
        self._eye_tracking_latest_raw_point: tuple[float, float] | None = None
        self._eye_tracking_latest_raw_at = 0.0
        self._eye_tracking_latest_point: tuple[float, float] | None = None
        self._eye_tracking_latest_at = 0.0
        self._eye_tracking_stable_point: tuple[float, float] | None = None
        self._eye_tracking_interaction_source_point: tuple[float, float] | None = None
        self._eye_tracking_interaction_target: QtCore.QPointF | None = None
        self._eye_tracking_interaction_until = 0.0
        self._eye_tracking_last_external_target: QtCore.QPointF | None = None
        self._eye_tracking_last_external_sent_at = 0.0
        self._eye_tracking_last_timer_active = False
        self._eye_tracking_last_timer_progress = 0.0
        self._eye_tracking_last_timer_color = ""
        self._eye_tracking_last_timer_sent_at = 0.0
        self._eye_tracking_calibration_overlay: (
            gaze_calibration_overlay.GazeCalibrationOverlay | None
        ) = None
        self._eye_tracking_calibration_active = False
        self._eye_tracking_calibration_rect: tuple[float, float, float, float] = ()
        self._eye_tracking_calibration_targets: tuple[tuple[float, float], ...] = ()
        self._eye_tracking_calibration_target_index = -1
        self._eye_tracking_calibration_target_started_at = 0.0
        self._eye_tracking_calibration_samples: list[tuple[float, float]] = []
        self._eye_tracking_calibration_observed: list[tuple[float, float]] = []
        self._eye_tracking_calibration_status: dict[str, Any] = {
            "state": "not_calibrated",
            "message": "No gaze calibration is saved.",
            "active": False,
            "target_index": 0,
            "target_count": 5,
            "quality": "",
            "average_error_px": 0.0,
            "completed_at": "",
        }
        self._eye_tracking_calibration_cache_key: tuple[object, ...] | None = None
        self._eye_tracking_calibration_cache: (
            gaze_calibration.CalibrationTransform | None
        ) = None
        self._eye_tracking_pointer_clearance = (
            pointer_clearance.PointerClearancePolicy()
        )
        self._eye_tracking_pointer_clearance_state = "clear"
        self._eye_tracking_pointer_clearance_opacity = 1.0
        self._external_pointer_clearance_state = "clear"
        self._external_pointer_clearance_guard: bool | None = None
        self._gaze_radial_menu: gaze_radial_menu.GazeRadialMenu | None = None
        self._gaze_radial_menu_open = False
        self._gaze_radial_anchor = QtCore.QPoint()
        self._gaze_radial_context_point: tuple[float, float] | None = None
        self._gaze_radial_context_hwnd = 0
        self._gaze_radial_scroll_target_point: tuple[float, float] | None = None
        self._gaze_radial_payloads: dict[str, Any] = {}
        self._gaze_scroll_active = False
        self._gaze_scroll_anchor_y = 0.0
        self._gaze_scroll_target_hwnd = 0
        self._gaze_scroll_target_point: tuple[float, float] | None = None
        self._gaze_scroll_policy = eye_tracking.GazeScrollPolicy()
        self._gaze_click_targets: dict[str, eye_tracking.ClickTarget] = {}
        self._gaze_click_target_payloads: dict[str, dict[str, Any]] = {}
        self._gaze_click_visual_targets: list[dict[str, Any]] = []
        self._gaze_click_visual_page = 0
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index: int | None = None
        self._gaze_click_target_highlight: click_target_overlay.ClickTargetHighlightOverlay | None = None
        self._gaze_click_automation_available = False
        self._gaze_click_automation_timed_out = False
        self._gaze_click_automation_provider_error = False
        self._gaze_click_target_page_open = False
        self._gaze_click_scan_generation = 0
        self._gaze_click_validation_pending: ClickValidationPending | None = None
        self._gaze_click_validation_generation = 0
        self._gaze_click_validation_cloak_active = False
        self._gaze_click_validation_cloak_token: int | None = None
        self._gaze_lfm_click_pending: (
            vision_click_verification.PendingLfmClickConfirmation | None
        ) = None
        self._gaze_lfm_click_confirmation_generation = 0
        self._gaze_lfm_click_verification_generation = 0
        self._gaze_lfm_click_verifying = False
        self._gaze_lfm_double_blink = (
            vision_click_verification.DoubleBlinkConfirmationPolicy()
        )
        self._gaze_voice_page = 0
        self._eye_tracking_reaction_lock = threading.Lock()
        self._eye_tracking_reaction_active = False
        self._eye_tracking_reaction_generation = 0
        self._gaze_context_dispatch_generation = 0
        self._eye_tracking_reaction_lifecycle_key: tuple[str, bool, str, str, int] | None = None
        self._eye_tracking_reaction_shutting_down = False
        self._external_gaze_timer_lock = threading.Lock()
        self._external_gaze_timer_io_lock = threading.Lock()
        self._external_gaze_timer_pending: dict[str, Any] | None = None
        self._external_gaze_timer_worker_active = False
        self._external_gaze_timer_generation = 0
        self._external_runtime: ExternalOrbRuntimeClient | None = None
        self._proxy = _OrbCommandProxy(self)
        self._proxy.state_requested.connect(self._set_ai_state, QtCore.Qt.QueuedConnection)
        self._proxy.level_requested.connect(self._set_audio_level, QtCore.Qt.QueuedConnection)
        self._proxy.music_level_requested.connect(lambda _level: None, QtCore.Qt.QueuedConnection)
        self._proxy.mood_requested.connect(self._set_presence_mood, QtCore.Qt.QueuedConnection)
        self._proxy.settings_requested.connect(self.apply_runtime_config, QtCore.Qt.QueuedConnection)
        self._proxy.drop_capture_finished.connect(self._finish_drop_capture, QtCore.Qt.QueuedConnection)
        self._proxy.drop_watch_ready.connect(self._show_drop_watch_offer, QtCore.Qt.QueuedConnection)
        self._proxy.edit_mode_requested.connect(self.set_edit_mode, QtCore.Qt.QueuedConnection)
        self._proxy.placement_mode_requested.connect(self.set_placement_mode, QtCore.Qt.QueuedConnection)
        self._proxy.click_through_requested.connect(self.set_click_through, QtCore.Qt.QueuedConnection)
        self._proxy.clear_target_requested.connect(self.clear_target, QtCore.Qt.QueuedConnection)
        self._proxy.reset_position_requested.connect(self.reset_position, QtCore.Qt.QueuedConnection)
        self._proxy.comment_focus_requested.connect(self._set_comment_focus, QtCore.Qt.QueuedConnection)
        self._proxy.comment_text_requested.connect(self._focus_comment_text, QtCore.Qt.QueuedConnection)
        self._proxy.snapshot_context_requested.connect(self._remember_snapshot_context, QtCore.Qt.QueuedConnection)
        self._proxy.ocr_result_requested.connect(self._apply_snapshot_ocr_result, QtCore.Qt.QueuedConnection)
        self._proxy.external_event_requested.connect(self._handle_external_runtime_event, QtCore.Qt.QueuedConnection)
        self._proxy.eye_sample_requested.connect(self._handle_eye_tracking_sample, QtCore.Qt.QueuedConnection)
        self._proxy.eye_validity_requested.connect(self._handle_eye_tracking_validity, QtCore.Qt.QueuedConnection)
        self._proxy.eye_click_targets_requested.connect(
            self._handle_gaze_click_targets_result,
            QtCore.Qt.QueuedConnection,
        )
        self._proxy.eye_click_validation_requested.connect(
            self._handle_gaze_click_validation_result,
            QtCore.Qt.QueuedConnection,
        )
        self._proxy.eye_lfm_click_verification_requested.connect(
            self._handle_lfm_click_verification_result,
            QtCore.Qt.QueuedConnection,
        )
        self._proxy.eye_status_requested.connect(self._handle_eye_tracking_status, QtCore.Qt.QueuedConnection)
        self._proxy.eye_react_requested.connect(self._request_eye_tracking_reaction, QtCore.Qt.QueuedConnection)
        self._proxy.eye_reaction_result_requested.connect(self._handle_eye_tracking_reaction_result, QtCore.Qt.QueuedConnection)
        self._proxy.spatial_scan_result_requested.connect(
            self._handle_spatial_scan_result,
            QtCore.Qt.QueuedConnection,
        )
        self._proxy.vision_pipeline_requested.connect(
            self._apply_vision_pipeline_state,
            QtCore.Qt.QueuedConnection,
        )
        self._vision_pipeline_clear_timer = QtCore.QTimer(self)
        self._vision_pipeline_clear_timer.setSingleShot(True)
        self._vision_pipeline_clear_timer.timeout.connect(
            self._clear_vision_pipeline_indicator
        )

        self._eye_tracking_provider = eye_tracking.TobiiStreamEngineProvider(
            on_sample=lambda x, y: self._proxy.eye_sample_requested.emit(float(x), float(y)),
            on_validity=lambda valid: self._proxy.eye_validity_requested.emit(bool(valid)),
            on_status=lambda code, message: self._proxy.eye_status_requested.emit(str(code), str(message)),
        )

        self._return_home_timer = QtCore.QTimer(self)
        self._return_home_timer.setSingleShot(True)
        self._return_home_timer.timeout.connect(self._return_home)

        self._drift_timer = QtCore.QTimer(self)
        self._drift_timer.setInterval(16)
        self._drift_timer.timeout.connect(self._on_drift_tick)

        self._motion_timer = QtCore.QTimer(self)
        self._motion_timer.setInterval(16)
        self._motion_timer.timeout.connect(self._on_motion_tick)

        self._menu_poll_timer = QtCore.QTimer(self)
        self._menu_poll_timer.setInterval(16)
        self._menu_poll_timer.timeout.connect(self._poll_right_double_click)

        # UI-thread, read-only status refresh; no screenshots or inference.
        self._capture_monitors = capture_scope.monitor_snapshot()
        self._watch_capture_hint_timer = QtCore.QTimer(self)
        self._watch_capture_hint_timer.setInterval(1000)
        self._watch_capture_hint_timer.timeout.connect(self._refresh_watch_capture_hint)
        self._watch_capture_hint_timer.start()

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_session)

        self._spatial_scan_timer = QtCore.QTimer(self)
        self._spatial_scan_timer.setSingleShot(False)
        self._spatial_scan_timer.timeout.connect(
            lambda: self.request_spatial_scan("timer")
        )

        self._install_key_filter()
        self._create_window()
        self.apply_runtime_config(self._last_runtime_config)
        self._register_runtime_bridge()
        self._register_sensory_provider()

    def _install_key_filter(self):
        app = QtGui.QGuiApplication.instance()
        if app is not None:
            try:
                app.installEventFilter(self)
            except Exception:
                pass

    def _register_runtime_bridge(self):
        try:
            from visual_presence import runtime as presence_runtime

            presence_runtime.register_orb_controller(self)
        except Exception as exc:
            self._log(f"Could not register orb runtime bridge: {exc}")

    def _register_sensory_provider(self):
        service = self.context.capabilities.sensory_targets if getattr(self, "context", None) is not None else None
        if service is None or not callable(getattr(service, "register_provider", None)):
            return
        try:
            service.register_provider(
                provider_id=PROVIDER_ID,
                label="Companion Orb Target",
                instruction=(
                    "Optional hidden sensory feedback from the Companion Orb selected target, "
                    "or the full desktop when full-screen context is explicitly enabled. "
                    "Treat it as focused ambient context, not as a direct user request. "
                    "Use focus_bounds or focus_text when the orb should move toward the visible item being discussed."
                ),
                description=(
                    "Captures the window or region selected by the Companion Orb, or an opt-in "
                    "full-screen context map when enabled in Companion Orb settings. The source can guide orb movement "
                    "toward desktop regions through focus metadata."
                ),
                order=115,
                capture_handler=self.capture_sensory_snapshot,
                metadata=COMPANION_ORB_TARGET_METADATA,
            )
            self._log("Registered Companion Orb Target sensory provider.")
        except Exception as exc:
            self._log(f"Could not register sensory provider: {exc}")

    def _unregister_sensory_provider(self):
        service = self.context.capabilities.sensory_targets if getattr(self, "context", None) is not None else None
        if service is None:
            return
        try:
            service.unregister_provider(PROVIDER_ID)
        except Exception:
            pass

    def _log(self, message: str):
        logger = getattr(self.context, "logger", None)
        text = f"[AIPresence:Orb] {message}"
        if logger is not None:
            try:
                logger.info(text)
                return
            except Exception:
                pass
        print(text)

    @staticmethod
    def _log_spatial_diagnostic(message: str) -> None:
        print(f"[AIPresence:Orb] grounding diagnostic {message}", flush=True)

    def _debug_enabled(self) -> bool:
        return bool(self._last_runtime_config.get("companion_orb_debug_enabled", False))

    def _debug_log_path(self) -> Path:
        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        return root / "runtime" / "companion_orb" / "debug" / "companion_orb_debug.log"

    def _begin_vision_debug_trace(
        self,
        image_path: Path,
        *,
        scope: str,
        trace_id: str = "",
        route: str = "lfm_observation_to_main_chat",
    ) -> str:
        if not CompanionOrbController._debug_enabled(self):
            return ""
        try:
            root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
            started = companion_orb_vision_debug.start_trace(
                root,
                trace_id=str(trace_id or ""),
                scope=str(scope or "unknown"),
                image_path=Path(image_path),
                route=str(route or ""),
            )
            trace_path = companion_orb_vision_debug.active_trace_path(started)
            CompanionOrbController._debug_event(
                self,
                "vision_debug_trace_started",
                console=True,
                vision_trace_id=started,
                trace_path=str(trace_path or ""),
                scope=str(scope or "unknown"),
            )
            return started
        except Exception:
            return ""

    def _debug_value(self, value):
        if isinstance(value, QtCore.QPoint):
            return [int(value.x()), int(value.y())]
        if isinstance(value, QtCore.QPointF):
            return [round(float(value.x()), 2), round(float(value.y()), 2)]
        if isinstance(value, QtCore.QRect):
            return [int(value.x()), int(value.y()), int(value.width()), int(value.height())]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): self._debug_value(item) for key, item in list(value.items())[:30]}
        if isinstance(value, (list, tuple, set)):
            return [self._debug_value(item) for item in list(value)[:40]]
        if isinstance(value, str):
            return value if len(value) <= 260 else value[:257] + "..."
        return value

    def _debug_event(self, event: str, *, console: bool = False, **fields):
        if not self._debug_enabled():
            return
        try:
            path = self._debug_log_path()
            payload = {
                "event": str(event or "event"),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "monotonic": round(float(time.monotonic()), 3),
            }
            payload.update({str(key): self._debug_value(value) for key, value in fields.items()})
            line = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
            with self._debug_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.stat().st_size > 2_000_000:
                    backup = path.with_name(path.stem + ".1" + path.suffix)
                    try:
                        if backup.exists():
                            backup.unlink()
                        path.replace(backup)
                    except Exception:
                        path.write_text("", encoding="utf-8")
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            if console:
                summary = ", ".join(f"{key}={self._debug_value(value)}" for key, value in list(fields.items())[:4])
                self._log(f"Debug {event}: {summary} (log: {path})")
        except Exception:
            pass

    def _new_drop_trace_id(self, inspection_id: int) -> str:
        return f"drop-{int(inspection_id)}-{int(time.time() * 1000)}"

    def _drop_trace_event(self, event: str, trace_id: str = "", *, console: bool = False, **fields):
        trace = str(trace_id or self._active_drop_trace_id or "").strip()
        if trace:
            start = float(self._drop_trace_starts.get(trace, 0.0) or 0.0)
            if start > 0.0:
                fields.setdefault("elapsed_ms", round((time.monotonic() - start) * 1000.0, 1))
            fields.setdefault("drop_trace_id", trace)
        self._debug_event(event, console=console, **fields)

    def _window_flags(self):
        flags = QtCore.Qt.Tool | QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowDoesNotAcceptFocus | _no_shadow_window_hint()
        if bool(self._last_runtime_config.get("companion_orb_always_on_top", True)):
            flags |= QtCore.Qt.WindowStaysOnTopHint
        return flags

    def _create_window(self):
        try:
            quick = _OrbQuickView()
            quick.setObjectName("ai_presence_companion_orb_window")
            quick.setFlags(self._window_flags())
            quick.setTitle("Companion Orb")
            quick.setResizeMode(QtQuick.QQuickView.SizeRootObjectToView)
            quick.setColor(QtGui.QColor(0, 0, 0, 0))
            quick.rootContext().setContextProperty("companionOrbBridge", self.bridge)
            quick.setSource(QtCore.QUrl.fromLocalFile(str(Path(__file__).resolve().parent / "qml" / "CompanionOrbOverlay.qml")))
            if quick.status() == QtQuick.QQuickView.Error:
                errors = "; ".join(str(error.toString()) for error in quick.errors())
                raise RuntimeError(errors or "Companion Orb QML load failed")
            quick.installEventFilter(self)
            self._window = quick
            self._quick = quick
            self.available = True
            self._log("Companion Orb overlay ready.")
        except Exception as exc:
            self.error = str(exc)
            self.available = False
            self._window = None
            self._quick = None
            self._log(f"Companion Orb overlay unavailable: {exc}")

    def request_ai_state(self, state):
        self._proxy.state_requested.emit(str(state or "idle"))

    def request_audio_level(self, level):
        try:
            value = float(level)
        except Exception:
            value = 0.0
        self._proxy.level_requested.emit(value)

    def request_music_level(self, level):
        try:
            value = float(level)
        except Exception:
            value = 0.0
        self._proxy.music_level_requested.emit(value)

    def request_presence_mood(self, mood):
        self._proxy.mood_requested.emit(str(mood or "neutral"))

    def request_settings(self, settings):
        self._proxy.settings_requested.emit(dict(settings or {}))

    def request_edit_mode(self, enabled):
        self._proxy.edit_mode_requested.emit(bool(enabled))

    def request_placement_mode(self, enabled):
        self._proxy.placement_mode_requested.emit(bool(enabled))

    def request_click_through(self, enabled):
        self._proxy.click_through_requested.emit(bool(enabled))

    def request_clear_target(self):
        self._proxy.clear_target_requested.emit()

    def request_reset_position(self):
        self._proxy.reset_position_requested.emit()

    def request_comment_focus(self, payload):
        self._proxy.comment_focus_requested.emit(dict(payload or {}))

    def request_comment_text_focus(self, payload):
        self._proxy.comment_text_requested.emit(dict(payload or {}))

    def request_snapshot_context(self, payload):
        self._proxy.snapshot_context_requested.emit(dict(payload or {}))

    def _external_runtime_enabled(self) -> bool:
        if bool(getattr(self, "_eye_tracking_reaction_shutting_down", False)):
            return False
        if not bool(self._last_runtime_config.get("companion_orb_external_runtime_enabled", True)):
            return False
        if not bool(self._last_runtime_config.get("companion_orb_enabled", False)):
            return False
        mode = str(self._last_runtime_config.get("companion_orb_display_mode", "off") or "off").strip().lower()
        return mode != "off"

    def _ensure_external_runtime(self) -> bool:
        if self._external_runtime is None:
            root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
            self._external_runtime = ExternalOrbRuntimeClient(
                root,
                logger=self._log,
                event_handler=self._queue_external_runtime_event,
            )
        return self._external_runtime.start()

    def _queue_external_runtime_event(self, event: dict[str, Any]) -> None:
        try:
            self._proxy.external_event_requested.emit(dict(event or {}))
        except Exception as exc:
            self._log(f"Companion Orb external event queue failed: {exc}")

    def _prepare_external_cloak_ack(self, enabled: bool) -> None:
        expected = bool(enabled)
        lock = getattr(self, "_external_cloak_ack_lock", None)
        event = getattr(self, "_external_cloak_ack_event", None)
        if lock is None or event is None:
            lock = threading.Lock()
            event = threading.Event()
            self._external_cloak_ack_lock = lock
            self._external_cloak_ack_event = event
        with lock:
            self._external_cloak_ack_expected = expected
            self._external_cloak_ack_enabled = None
            event.clear()

    def _record_external_cloak_ack(self, enabled: bool) -> None:
        acknowledged = bool(enabled)
        lock = getattr(self, "_external_cloak_ack_lock", None)
        event = getattr(self, "_external_cloak_ack_event", None)
        if lock is None or event is None:
            return
        with lock:
            if getattr(self, "_external_cloak_ack_expected", None) != acknowledged:
                return
            self._external_cloak_ack_enabled = acknowledged
            event.set()

    def _external_cloak_ack_ready(self, enabled: bool = True) -> bool:
        expected = bool(enabled)
        lock = getattr(self, "_external_cloak_ack_lock", None)
        event = getattr(self, "_external_cloak_ack_event", None)
        if lock is None or event is None:
            return False
        with lock:
            return bool(
                event.is_set()
                and getattr(self, "_external_cloak_ack_expected", None) == expected
                and getattr(self, "_external_cloak_ack_enabled", None) == expected
            )

    @QtCore.Slot(dict)
    def _handle_external_runtime_event(self, event: dict[str, Any]) -> None:
        payload = dict(event or {})
        event_type = str(payload.get("type") or "").strip().lower()
        if event_type == "orb.dropped":
            self._handle_external_orb_drop(payload)
        elif event_type == "orb.request_menu":
            self._handle_external_orb_menu_request(payload)
        elif event_type == "orb.position_changed":
            self._handle_external_orb_position_changed(payload)
        elif event_type == "orb.position_sample":
            point = self._event_point(payload, "top_left")
            if point is not None:
                self._external_orb_top_left = point
        elif event_type == "orb.pointer_reached":
            self._handle_external_orb_pointer_reached(payload)
        elif event_type == "orb.playful_nudge":
            self._handle_external_orb_playful_nudge(payload)
        elif event_type == "orb.pointer_clearance_state":
            self._handle_external_pointer_clearance_state(payload)
        elif event_type in {"orb.ready", "orb.cloak_changed"}:
            if event_type == "orb.cloak_changed" and isinstance(payload.get("enabled"), bool):
                CompanionOrbController._record_external_cloak_ack(
                    self,
                    bool(payload["enabled"]),
                )
            self._debug_event("external_runtime_event", event_type=event_type, payload=payload)

    def _event_point(self, payload: dict[str, Any], key: str) -> QtCore.QPoint | None:
        try:
            values = [int(value) for value in list(payload.get(key) or [])[:2]]
        except Exception:
            return None
        if len(values) != 2:
            return None
        return QtCore.QPoint(int(values[0]), int(values[1]))

    def _handle_external_orb_position_changed(self, payload: dict[str, Any]) -> None:
        point = self._event_point(payload, "top_left")
        if point is None:
            return
        self._external_orb_top_left = QtCore.QPoint(point)
        position = [int(point.x()), int(point.y())]
        if self._custom_position == position and list(self._last_runtime_config.get("companion_orb_custom_position", []) or []) == position:
            return
        self._custom_position = list(position)
        self._last_runtime_config["companion_orb_custom_position"] = list(position)
        self._base_position = QtCore.QPoint(point)
        self._drift_current_point = QtCore.QPointF(float(point.x()), float(point.y()))
        self._reset_drift_target()
        self._save_runtime_setting("companion_orb_custom_position", list(position))

    def _handle_external_orb_menu_request(self, payload: dict[str, Any]) -> None:
        top_left = self._event_point(payload, "top_left")
        if top_left is not None:
            self._external_orb_top_left = top_left
        point = self._event_point(payload, "point") or self._event_point(payload, "center") or QtGui.QCursor.pos()
        self._mark_user_interaction()
        self._show_command_menu(point)

    def _handle_external_orb_drop(self, payload: dict[str, Any]) -> None:
        self._handle_external_orb_position_changed(payload)
        point = self._event_point(payload, "center") or self._event_point(payload, "point")
        if point is None:
            top_left = self._event_point(payload, "top_left")
            if top_left is not None:
                size = self._window_size()
                point = QtCore.QPoint(int(top_left.x() + size / 2), int(top_left.y() + size / 2))
        if point is None:
            point = QtGui.QCursor.pos()
        reason = str(payload.get("reason") or "external_drag_drop").strip() or "external_drag_drop"
        button = str(payload.get("button") or "").lower()
        if button in {"left", "right"}:
            reason = f"{button}_drag_drop"
        self._mark_user_interaction()
        self._inspect_drop_target(point, reason=reason)

    def _handle_external_orb_pointer_reached(self, payload: dict[str, Any]) -> None:
        if not bool(
            self._last_runtime_config.get(
                "companion_orb_snapshot_on_pointer_reached",
                False,
            )
        ):
            self._debug_event("external_pointer_reached_ignored", reason="disabled")
            return
        point = self._event_point(payload, "point") or self._event_point(payload, "center") or QtGui.QCursor.pos()
        self._debug_event("external_pointer_reached", point=point, payload=payload)
        self._capture_pointer_snapshot(point)

    def _handle_external_orb_playful_nudge(self, payload: dict[str, Any]) -> None:
        point = self._event_point(payload, "point") or self._event_point(payload, "center") or QtGui.QCursor.pos()
        self._debug_event("external_playful_nudge", point=point, payload=payload)
        self._announce_harassment()

    def _handle_external_pointer_clearance_state(
        self,
        payload: dict[str, Any],
    ) -> None:
        state = str(payload.get("state") or "clear").strip().lower()
        self._external_pointer_clearance_state = (
            state if state in {"clear", "avoiding", "timeout"} else "clear"
        )

    def _stop_external_runtime(self) -> None:
        self._cancel_external_gaze_timer_queue()
        self._external_pointer_clearance_state = "clear"
        self._external_pointer_clearance_guard = None
        runtime = self._external_runtime
        self._external_runtime = None
        if runtime is None:
            return
        request_stop = getattr(runtime, "request_stop", None)
        if callable(request_stop):
            try:
                request_stop()
            except Exception:
                pass

        def finish_stop() -> None:
            with self._external_gaze_timer_io_lock:
                runtime.stop()

        try:
            threading.Thread(
                target=finish_stop,
                daemon=True,
                name="companion-orb-external-stop",
            ).start()
        except Exception:
            pass

    def _cancel_external_gaze_timer_queue(self) -> None:
        with self._external_gaze_timer_lock:
            self._external_gaze_timer_generation += 1
            self._external_gaze_timer_pending = None
            self._external_gaze_timer_worker_active = False

    def _queue_external_gaze_timer(self, payload: dict[str, Any]) -> bool:
        if not self._external_runtime_enabled():
            return False
        with self._external_gaze_timer_lock:
            self._external_gaze_timer_pending = dict(payload or {})
            generation = self._external_gaze_timer_generation
            if self._external_gaze_timer_worker_active:
                return True
            self._external_gaze_timer_worker_active = True
        worker = threading.Thread(
            target=self._drain_external_gaze_timer_queue,
            args=(generation,),
            daemon=True,
            name="companion-orb-gaze-timer-ipc",
        )
        try:
            worker.start()
        except Exception:
            with self._external_gaze_timer_lock:
                if generation == self._external_gaze_timer_generation:
                    self._external_gaze_timer_pending = None
                    self._external_gaze_timer_worker_active = False
            return False
        return True

    def _drain_external_gaze_timer_queue(self, generation: int) -> None:
        first_send = True
        while True:
            if not first_send:
                time.sleep(0.05)
            first_send = False
            with self._external_gaze_timer_lock:
                if generation != self._external_gaze_timer_generation:
                    return
                payload = self._external_gaze_timer_pending
                self._external_gaze_timer_pending = None
                if payload is None:
                    self._external_gaze_timer_worker_active = False
                    return
            with self._external_gaze_timer_io_lock:
                with self._external_gaze_timer_lock:
                    if generation != self._external_gaze_timer_generation:
                        return
                runtime = self._external_runtime
                if runtime is None or not self._external_runtime_enabled():
                    continue
                try:
                    runtime.send(payload)
                except Exception:
                    continue

    def _send_external_runtime(self, payload: dict[str, Any]) -> bool:
        if not self._external_runtime_enabled():
            return False
        if not self._ensure_external_runtime():
            return False
        runtime = self._external_runtime
        return bool(runtime is not None and runtime.send(dict(payload or {})))

    def _send_external_runtime_snapshot(self) -> None:
        if not self._external_runtime_enabled():
            return
        self._send_external_runtime({"type": "settings", "settings": dict(self._last_runtime_config or {})})
        self._send_external_runtime({"type": "state", "state": str(self.bridge.aiState or "idle")})
        self._send_external_runtime({"type": "audio_level", "level": float(self.bridge.audioLevel or 0.0)})
        self._send_external_runtime({"type": "mood", "mood": str(self.bridge.moodName or "neutral")})
        self._send_external_runtime(
            {
                "type": "gaze_timer",
                "active": bool(self.bridge.gazeTimerActive),
                "progress": float(self.bridge.gazeTimerProgress),
                "color": str(self.bridge.gazeTimerColor or "#facc15"),
            }
        )
        self._send_external_runtime(
            {
                "type": "modes",
                "edit_mode": bool(self.bridge.editMode),
                "placement_mode": bool(self.bridge.placementMode),
                "click_through": bool(self.bridge.clickThrough),
            }
        )
        self._send_external_runtime({"type": "target_info", "target": CompanionOrbController._capture_target_presentation(self)})
        pipeline = self._vision_pipeline.snapshot()
        self._send_external_runtime({"type": "watch_capture_hint", "waiting": self.bridge.watchWaitingForTarget})
        self._send_external_runtime(
            {
                "type": "vision_pipeline",
                "stage": str(pipeline.get("stage") or "idle"),
                "text": str(pipeline.get("status") or ""),
                "color": str(pipeline.get("color") or "#64748b"),
            }
        )

    @QtCore.Slot(str)
    def _set_ai_state(self, state):
        self.bridge.setAiState(state)
        popup = self._orb_popup
        if popup is not None and popup.view.isVisible():
            popup._refresh_runtime_state()
        previous_revision = int(self._vision_pipeline.snapshot().get("revision") or 0)
        pipeline = self._vision_pipeline.observe_ai_state(str(state or "idle"))
        if int(pipeline.get("revision") or 0) != previous_revision:
            CompanionOrbController._publish_vision_pipeline_snapshot(self, pipeline)
        self._send_external_runtime({"type": "state", "state": str(state or "idle")})
        if self._external_runtime_enabled():
            if str(state or "").strip().lower() == "idle":
                self._schedule_return_home()
            return
        self._refresh_visibility()
        if str(state or "").strip().lower() == "idle":
            self._schedule_return_home()

    @QtCore.Slot(float)
    def _set_audio_level(self, level):
        self.bridge.setAudioLevel(level)
        self._send_external_runtime({"type": "audio_level", "level": float(level or 0.0)})
        if self._external_runtime_enabled():
            return
        if float(level or 0.0) > 0.025:
            self._refresh_visibility()

    @QtCore.Slot(str)
    def _set_presence_mood(self, mood):
        self.bridge.setPresenceMood(mood)
        self._send_external_runtime({"type": "mood", "mood": str(mood or "neutral")})

    @QtCore.Slot(dict)
    def apply_runtime_config(self, runtime_config):
        previous_vision_capability_mode = (
            vision_guidance.normalize_vision_capability_mode(
                getattr(self, "_last_runtime_config", {}).get(
                    "companion_orb_vision_capability_mode",
                    "auto",
                )
            )
        )
        previous_primary_vision_request = (
            CompanionOrbController._primary_parallel_vision_release_request(
                getattr(self, "_last_runtime_config", {})
            )
        )
        previous_click_target_enabled = interaction_settings.boolish(
            self._last_runtime_config.get("companion_orb_eye_tracking_click_target_enabled", False),
            default=False,
        )
        previous_eye_tracking_offsets = _eye_tracking_calibration_offsets(self._last_runtime_config)
        previous_eye_tracking_calibration = self._last_runtime_config.get(
            "companion_orb_eye_tracking_calibration",
            {},
        )
        previous_eye_tracking_screen = self._last_runtime_config.get(
            "companion_orb_eye_tracking_screen_index",
            -1,
        )
        previous_pointer_clearance = (
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_enabled",
                False,
            ),
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_distance_px",
                160,
            ),
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_timeout_seconds",
                8,
            ),
        )
        previous_include_process_name = bool(self._last_runtime_config.get("companion_orb_include_process_name", True))
        previous_debug_enabled = bool(self._last_runtime_config.get("companion_orb_debug_enabled", False))
        previous_target_mode = str(self._last_runtime_config.get("companion_orb_target_mode", "window") or "window").strip().lower()
        self._last_runtime_config, migrated_interaction_defaults = interaction_settings.normalize_interaction_settings(
            dict(runtime_config or {})
        )
        if (not self._last_runtime_config.get('companion_orb_drop_watch_prompt_enabled', False)
                or not self._last_runtime_config.get('companion_orb_enabled')):
            CompanionOrbController._clear_drop_watch_offer(self)
        watch = getattr(self, 'watch_context', None)
        if watch is not None:
            watch.current(self._last_runtime_config)
            watch.on_change()
        current_vision_capability_mode = (
            vision_guidance.normalize_vision_capability_mode(
                self._last_runtime_config.get(
                    "companion_orb_vision_capability_mode",
                    "auto",
                )
            )
        )
        if current_vision_capability_mode != previous_vision_capability_mode:
            spatial_store = getattr(self, "_desktop_spatial_map", None)
            if isinstance(spatial_store, desktop_spatial_map.DesktopSpatialMapStore):
                spatial_store.invalidate()
            spatial_coordinator = getattr(self, "_spatial_scan_coordinator", None)
            if isinstance(
                spatial_coordinator,
                spatial_scanning.SpatialScanCoordinator,
            ):
                spatial_coordinator.invalidate()
        current_primary_vision_request = (
            CompanionOrbController._primary_parallel_vision_release_request(
                self._last_runtime_config
            )
        )
        if (
            previous_primary_vision_request
            and previous_primary_vision_request != current_primary_vision_request
        ):
            CompanionOrbController._ensure_vision_state(self)
            invalidated = self._vision_residency.disable()
            self._vision_inference.invalidate(invalidated.generation)
            self._vision_observation_cache.clear()
            CompanionOrbController._release_primary_vision_model_async(
                self,
                previous_primary_vision_request,
                "Companion Orb vision settings changed",
            )
        calibration_context_changed = (
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_calibration",
                {},
            )
            != previous_eye_tracking_calibration
            or self._last_runtime_config.get(
                "companion_orb_eye_tracking_screen_index",
                -1,
            )
            != previous_eye_tracking_screen
        )
        if (
            calibration_context_changed
            and bool(getattr(self, "_eye_tracking_calibration_active", False))
        ):
            cancel_calibration = getattr(
                self,
                "cancel_eye_tracking_calibration",
                None,
            )
            if callable(cancel_calibration):
                cancel_calibration()
        if calibration_context_changed:
            invalidate_calibration = getattr(
                self,
                "_invalidate_eye_tracking_calibration_cache",
                None,
            )
            if callable(invalidate_calibration):
                invalidate_calibration()
            if not bool(getattr(self, "_eye_tracking_calibration_active", False)):
                self._eye_tracking_calibration_status = {}
                refresh_calibration = getattr(
                    self,
                    "_refresh_eye_tracking_calibration_status_from_config",
                    None,
                )
                if callable(refresh_calibration):
                    refresh_calibration()
        pointer_clearance_changed = previous_pointer_clearance != (
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_enabled",
                False,
            ),
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_distance_px",
                160,
            ),
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_timeout_seconds",
                8,
            ),
        )
        if pointer_clearance_changed:
            reset_clearance = getattr(
                self,
                "_reset_eye_tracking_pointer_clearance",
                None,
            )
            if callable(reset_clearance):
                reset_clearance()
        radial_menu = getattr(self, "_gaze_radial_menu", None)
        if radial_menu is not None:
            radial_menu.set_menu_opacity(self._gaze_radial_menu_opacity())
            radial_menu.set_focus_beam_enabled(self._gaze_radial_focus_beam_enabled())
        if migrated_interaction_defaults:
            self._persist_interaction_defaults_migration()
        self.bridge.apply_settings(self._last_runtime_config)
        CompanionOrbController._sync_vision_residency(self)
        self._sync_eye_tracking_provider()
        self._apply_timer_intervals()
        sync_spatial_timer = getattr(self, "_sync_spatial_scan_timer", None)
        if callable(sync_spatial_timer):
            sync_spatial_timer()
        sync_region_policy = getattr(self, "_sync_spatial_region_gaze_policy", None)
        if callable(sync_region_policy):
            sync_region_policy()
        refresh_spatial_overlay = getattr(self, "_refresh_spatial_map_overlay", None)
        if callable(refresh_spatial_overlay):
            refresh_spatial_overlay()
        if self._external_runtime_enabled():
            self._send_external_runtime_snapshot()
        else:
            self._stop_external_runtime()
        if bool(self._last_runtime_config.get("companion_orb_debug_enabled", False)) and not previous_debug_enabled:
            self._debug_event("debug_enabled", console=True, log_path=str(self._debug_log_path()))
        target = self._last_runtime_config.get("companion_orb_target_info", {})
        if isinstance(target, dict) and target != self._target_info:
            self._target_info = dict(target)
        if (
            isinstance(target, dict)
            or bool(self._last_runtime_config.get("companion_orb_include_process_name", True)) != previous_include_process_name
        ):
            target_display = CompanionOrbController._capture_target_presentation(self)
            self.bridge.set_target_info(target_display)
            self._send_external_runtime({"type": "target_info", "target": target_display})
        target_mode = str(self._last_runtime_config.get("companion_orb_target_mode", "window") or "window").strip().lower()
        if target_mode != previous_target_mode:
            self._refresh_target_for_mode_change(target_mode)
        self._apply_window_settings()
        self._refresh_visibility()
        self._sync_drift_timer()
        self._sync_pinned_popup_visibility()
        if (
            _eye_tracking_calibration_offsets(self._last_runtime_config)
            != previous_eye_tracking_offsets
            or calibration_context_changed
        ):
            self._reapply_eye_tracking_interaction_target()
        self._refresh_gaze_radial_menu_after_click_target_disable(previous_click_target_enabled)
        pending_lfm_click = getattr(self, "_gaze_lfm_click_pending", None)
        if isinstance(
            pending_lfm_click,
            vision_click_verification.PendingLfmClickConfirmation,
        ) and not self._lfm_click_pending_settings_current(pending_lfm_click):
            selected_index = pending_lfm_click.selected_index
            CompanionOrbController._cancel_lfm_click_confirmation(self)
            if bool(getattr(self, "_gaze_radial_menu_open", False)):
                self._show_gaze_click_visual_action_menu(selected_index)

    def _gaze_click_target_enabled(self) -> bool:
        return interaction_settings.boolish(
            self._last_runtime_config.get("companion_orb_eye_tracking_click_target_enabled", False),
            default=False,
        )

    def _refresh_gaze_radial_menu_after_click_target_disable(self, previous_enabled: bool) -> None:
        if (
            not bool(previous_enabled)
            or self._gaze_click_target_enabled()
            or not (self._gaze_click_target_page_open or self._gaze_radial_menu_open)
        ):
            return
        self._gaze_click_scan_generation = int(
            getattr(self, "_gaze_click_scan_generation", 0)
        ) + 1
        CompanionOrbController._cancel_gaze_click_validation(self)
        CompanionOrbController._cancel_lfm_click_confirmation(self)
        self._gaze_click_targets.clear()
        getattr(self, "_gaze_click_target_payloads", {}).clear()
        getattr(self, "_gaze_click_visual_targets", []).clear()
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        clear_highlight = getattr(self, "_clear_gaze_click_target_highlight", None)
        if callable(clear_highlight):
            clear_highlight()
        self._eye_tracking_interaction_source_point = None
        self._eye_tracking_interaction_target = None
        self._eye_tracking_interaction_until = 0.0
        self._eye_tracking_last_external_target = None
        self._eye_tracking_last_external_sent_at = 0.0
        self._send_external_runtime({"type": "interaction_target_clear"})
        self._gaze_click_target_page_open = False
        point = self._eye_tracking_latest_point or (
            self._gaze_radial_anchor.x(),
            self._gaze_radial_anchor.y(),
        )
        self._show_gaze_radial_main_menu(point)

    def _eye_tracking_orb_active(self) -> bool:
        return bool(self._last_runtime_config.get("companion_orb_enabled", False)) and str(
            self._last_runtime_config.get("companion_orb_display_mode", "off") or "off"
        ).strip().lower() != "off"

    def _sync_eye_tracking_provider(self, *, force: bool = False) -> None:
        CompanionOrbController._sync_blink_policies(self)
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        try:
            dwell_ms = max(300, min(2000, int(self._last_runtime_config.get("companion_orb_eye_tracking_dwell_ms", 700) or 700)))
        except (TypeError, ValueError):
            dwell_ms = 700
        try:
            long_dwell_ms = max(
                1000,
                min(
                    15000,
                    int(self._last_runtime_config.get("companion_orb_eye_tracking_long_gaze_ms", 3000) or 3000),
                ),
            )
        except (TypeError, ValueError):
            long_dwell_ms = 3000
        long_gaze_enabled = interaction_settings.boolish(
            self._last_runtime_config.get("companion_orb_eye_tracking_long_gaze_enabled", False),
            default=False,
        )
        try:
            radius_px = max(24, min(180, int(self._last_runtime_config.get("companion_orb_eye_tracking_radius_px", 60) or 60)))
        except (TypeError, ValueError):
            radius_px = 60
        try:
            smoothing = max(0.05, min(0.85, float(self._last_runtime_config.get("companion_orb_eye_tracking_smoothing", 0.28) or 0.28)))
        except (TypeError, ValueError):
            smoothing = 0.28
        policy_key = (
            mode,
            long_gaze_enabled,
            dwell_ms,
            long_dwell_ms,
            radius_px,
            round(smoothing, 4),
        )
        if policy_key != self._eye_tracking_policy_key:
            self._eye_tracking_policy = eye_tracking.GazeFocusPolicy(
                dwell_ms=dwell_ms,
                long_dwell_ms=long_dwell_ms,
                radius_px=radius_px,
                smoothing=smoothing,
                sample_gap_seconds=0.5,
            )
            self._eye_tracking_policy_key = policy_key
            self._clear_eye_tracking_state(send_external=True)

        try:
            cooldown = max(
                10,
                min(
                    300,
                    int(
                        self._last_runtime_config.get(
                            "companion_orb_eye_tracking_reaction_cooldown_seconds",
                            45,
                        )
                        or 45
                    ),
                ),
            )
        except (TypeError, ValueError):
            cooldown = 45
        gate_key = (cooldown, 8)
        if gate_key != self._eye_tracking_gate_key:
            self._eye_tracking_reaction_gate = eye_tracking.GazeReactionGate(
                cooldown_seconds=float(cooldown),
                minimum_signature_distance=8,
            )
            self._eye_tracking_gate_key = gate_key

        dll_path = str(self._last_runtime_config.get("companion_orb_eye_tracking_dll_path", "") or "").strip()
        orb_active = self._eye_tracking_orb_active()
        reaction_mode = eye_tracking.normalize_reaction_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_reaction_mode", "meaningful")
        )
        try:
            screen_index = int(self._last_runtime_config.get("companion_orb_eye_tracking_screen_index", -1))
        except (TypeError, ValueError):
            screen_index = -1
        reaction_lifecycle_key = (mode, orb_active, reaction_mode, dll_path, screen_index)
        if reaction_lifecycle_key != self._eye_tracking_reaction_lifecycle_key:
            with self._eye_tracking_reaction_lock:
                self._eye_tracking_reaction_generation += 1
            self._eye_tracking_reaction_lifecycle_key = reaction_lifecycle_key
        desired_connection = ("on" if mode != "off" and orb_active else "off", dll_path)
        if mode == "off" or not orb_active:
            self._eye_tracking_connection_key = desired_connection
            self._eye_tracking_provider.stop(timeout_seconds=0.0)
            provider_stopping = bool(self._eye_tracking_provider.is_running)
            self._clear_eye_tracking_state(send_external=True)
            if provider_stopping:
                self._eye_tracking_status_code = "stopping"
                self._eye_tracking_status_message = "Eye tracking is stopping; no new samples will be used."
            elif mode == "off":
                self._eye_tracking_status_code = "off"
                self._eye_tracking_status_message = "Eye tracking is off."
            else:
                self._eye_tracking_status_code = "orb_disabled"
                self._eye_tracking_status_message = "Enable and show the Companion Orb to start eye tracking."
            return
        if not force and desired_connection == self._eye_tracking_connection_key:
            return
        self._eye_tracking_connection_key = desired_connection
        self._eye_tracking_provider.stop(timeout_seconds=0.0)
        self._clear_eye_tracking_state(send_external=True)
        QtCore.QTimer.singleShot(
            0,
            lambda expected=desired_connection: self._start_eye_tracking_provider_if_current(expected),
        )

    def _start_eye_tracking_provider_if_current(self, expected_connection: tuple[str, str]) -> None:
        if expected_connection != self._eye_tracking_connection_key or expected_connection[0] != "on":
            return
        if self._eye_tracking_provider.is_running:
            QtCore.QTimer.singleShot(
                150,
                lambda expected=expected_connection: self._start_eye_tracking_provider_if_current(expected),
            )
            return
        self._eye_tracking_provider.start(expected_connection[1])

    def _sync_blink_policies(self) -> None:
        config = self._last_runtime_config
        allowed = interaction_settings.boolish(
            config.get("companion_orb_eye_tracking_blink_click_allowed", True),
            default=True,
        )

        def bounded(key: str, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(config.get(key, default) or default)
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        minimum_ms = bounded("companion_orb_eye_tracking_blink_min_ms", 80, 40, 300)
        slow_minimum_ms = bounded("companion_orb_eye_tracking_blink_slow_min_ms", 260, 150, 700)
        maximum_ms = bounded("companion_orb_eye_tracking_blink_max_ms", 900, 400, 1500)
        recovery_ms = bounded("companion_orb_eye_tracking_blink_recovery_ms", 80, 30, 300)
        double_gap_ms = bounded("companion_orb_eye_tracking_blink_double_gap_ms", 1200, 400, 2500)
        click_cooldown_ms = bounded(
            "companion_orb_eye_tracking_blink_click_cooldown_ms",
            450,
            200,
            1500,
        )
        menu_minimum_ms = bounded(
            "companion_orb_eye_tracking_menu_blink_min_ms",
            1000,
            700,
            1800,
        )
        menu_maximum_ms = bounded(
            "companion_orb_eye_tracking_menu_blink_max_ms",
            2000,
            1200,
            3000,
        )
        triple_gap_ms = bounded(
            "companion_orb_eye_tracking_triple_blink_gap_ms",
            450,
            200,
            900,
        )
        back_cooldown_ms = bounded(
            "companion_orb_eye_tracking_back_cooldown_ms",
            1500,
            500,
            5000,
        )
        scroll_speed = bounded("companion_orb_eye_tracking_scroll_speed", 5, 1, 10)
        scroll_dead_zone_px = bounded(
            "companion_orb_eye_tracking_scroll_dead_zone_px",
            100,
            40,
            300,
        )
        maximum_ms = max(minimum_ms + 20, maximum_ms)
        slow_minimum_ms = max(minimum_ms, min(maximum_ms, slow_minimum_ms))
        menu_minimum_ms = max(slow_minimum_ms + 20, menu_minimum_ms)
        menu_maximum_ms = max(menu_minimum_ms + 20, menu_maximum_ms)
        policy_key = (
            allowed,
            minimum_ms,
            slow_minimum_ms,
            maximum_ms,
            recovery_ms,
            double_gap_ms,
            click_cooldown_ms,
            menu_minimum_ms,
            menu_maximum_ms,
            triple_gap_ms,
            back_cooldown_ms,
            scroll_speed,
            scroll_dead_zone_px,
        )
        if policy_key == getattr(self, "_blink_policy_key", None):
            return
        self._blink_gesture_detector = eye_tracking.BlinkGestureDetector(
            minimum_closed_ms=minimum_ms,
            maximum_closed_ms=max(maximum_ms, menu_maximum_ms),
            recovery_ms=recovery_ms,
            stable_before_ms=max(100, recovery_ms),
        )
        self._blink_click_policy = eye_tracking.BlinkClickPolicy(
            slow_blink_minimum_ms=slow_minimum_ms,
            double_blink_gap_ms=double_gap_ms,
            click_cooldown_ms=click_cooldown_ms,
            activation_arm_ms=max(2500, double_gap_ms * 2 + 500),
        )
        self._eye_command_policy = eye_tracking.EyeCommandPolicy(
            fast_blink_maximum_ms=slow_minimum_ms,
            blink_maximum_ms=maximum_ms,
            menu_toggle_minimum_ms=menu_minimum_ms,
            menu_toggle_maximum_ms=menu_maximum_ms,
            triple_blink_gap_ms=triple_gap_ms,
            back_cooldown_ms=back_cooldown_ms,
        )
        self._gaze_scroll_policy = eye_tracking.GazeScrollPolicy(
            speed=scroll_speed,
            dead_zone_px=scroll_dead_zone_px,
        )
        pending_timer = getattr(self, "_blink_pending_click_timer", None)
        if pending_timer is not None:
            pending_timer.stop()
        self._blink_pending_click_point = None
        self._blink_policy_key = policy_key

    @QtCore.Slot(str, str)
    def _handle_eye_tracking_status(self, code: str, message: str) -> None:
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        normalized_code = str(code or "error").strip().lower() or "error"
        if mode == "off" and normalized_code not in {"stopping", "off"}:
            return
        if mode != "off" and not self._eye_tracking_orb_active():
            if normalized_code == "stopping":
                self._eye_tracking_status_code = "stopping"
                self._eye_tracking_status_message = str(message or "").strip() or "Eye tracking is stopping."
            else:
                self._eye_tracking_status_code = "orb_disabled"
                self._eye_tracking_status_message = "Enable and show the Companion Orb to start eye tracking."
            return
        self._eye_tracking_status_code = normalized_code
        self._eye_tracking_status_message = str(message or "").strip() or "Tobii eye-tracker status changed."
        if normalized_code in {"no_device", "reconnecting", "error", "off"}:
            if bool(getattr(self, "_eye_tracking_calibration_active", False)):
                self._finish_eye_tracking_calibration(
                    restore_saved_status=True,
                )
            self._clear_eye_tracking_state(send_external=True)

    def eye_tracking_status(self) -> dict[str, Any]:
        code = str(self._eye_tracking_status_code or "off")
        message = str(self._eye_tracking_status_message or "Eye tracking is off.")
        provider = self._eye_tracking_provider
        provider_code = str(getattr(provider, "status_code", "") or "").strip().lower()
        provider_message = str(getattr(provider, "status_message", "") or "").strip()
        if code in {
            "off",
            "orb_disabled",
            "stopping",
            "connecting",
            "reconnecting",
            "no_dll",
            "no_device",
            "error",
        }:
            connection_code = code
            connection_message = message
        else:
            connection_code = provider_code or code
            connection_message = provider_message or message
        calibration_refresher = getattr(
            self,
            "_refresh_eye_tracking_calibration_status_from_config",
            None,
        )
        if callable(calibration_refresher):
            calibration_refresher()
        calibration_state = dict(
            getattr(self, "_eye_tracking_calibration_status", {}) or {}
        )
        calibration = {
            "state": str(
                calibration_state.get("state") or "not_calibrated"
            ),
            "message": str(
                calibration_state.get("message")
                or "No gaze calibration is saved."
            ),
            "active": bool(calibration_state.get("active", False)),
            "target_index": int(calibration_state.get("target_index", 0) or 0),
            "target_count": 5,
            "quality": str(calibration_state.get("quality") or ""),
            "average_error_px": float(
                calibration_state.get("average_error_px", 0.0) or 0.0
            ),
            "completed_at": str(calibration_state.get("completed_at") or ""),
        }
        clearance_enabled = interaction_settings.boolish(
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_enabled",
                False,
            ),
            default=False,
        )
        external_enabled = False
        external_checker = getattr(self, "_external_runtime_enabled", None)
        if callable(external_checker):
            try:
                external_enabled = bool(external_checker())
            except Exception:
                external_enabled = False
        clearance_state = str(
            getattr(
                self,
                (
                    "_external_pointer_clearance_state"
                    if external_enabled
                    else "_eye_tracking_pointer_clearance_state"
                ),
                "clear",
            )
            or "clear"
        ).strip().lower()
        if clearance_state not in {"clear", "avoiding", "timeout"}:
            clearance_state = "clear"
        return {
            "code": code,
            "message": message,
            "mode": eye_tracking.normalize_tracking_mode(
                self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
            ),
            "connection_code": connection_code,
            "connection_message": connection_message,
            "dll_path": str(getattr(provider, "resolved_dll_path", "") or ""),
            "running": bool(getattr(provider, "is_running", False)),
            "blink_click_allowed": interaction_settings.boolish(
                self._last_runtime_config.get("companion_orb_eye_tracking_blink_click_allowed", True),
                default=True,
            ),
            "blink_click_enabled": bool(
                getattr(getattr(self, "_blink_click_policy", None), "enabled", False)
            ),
            "calibration": calibration,
            "pointer_clearance": {
                "enabled": bool(clearance_enabled),
                "state": clearance_state,
            },
        }

    def reconnect_eye_tracking(self) -> dict[str, Any]:
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        if mode == "off" or not self._eye_tracking_orb_active():
            self._sync_eye_tracking_provider(force=True)
            error = "Eye tracking is off." if mode == "off" else "Enable and show the Companion Orb first."
            return {"ok": False, "error": error, **self.eye_tracking_status()}
        self._eye_tracking_connection_key = None
        self._sync_eye_tracking_provider(force=True)
        return {"ok": True, **self.eye_tracking_status()}

    def _selected_eye_tracking_screen(self):
        app = QtGui.QGuiApplication.instance()
        screens = list(app.screens() or []) if app is not None else []
        try:
            screen_index = int(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_screen_index",
                    -1,
                )
            )
        except (TypeError, ValueError):
            screen_index = -1
        screen = screens[screen_index] if 0 <= screen_index < len(screens) else None
        return screen or QtGui.QGuiApplication.primaryScreen()

    def _eye_tracking_display_descriptor(self) -> gaze_calibration.DisplayDescriptor:
        screen = self._selected_eye_tracking_screen()
        if screen is None:
            left, top, width, height = self._eye_tracking_screen_bounds()
            return gaze_calibration.DisplayDescriptor(
                identity=f"display:{int(left)}:{int(top)}:{int(width)}:{int(height)}",
                geometry=(int(left), int(top), int(width), int(height)),
                physical_size_mm=(0.0, 0.0),
            )
        geometry = screen.geometry()
        identity_parts: list[str] = []
        for attribute_name in ("name", "manufacturer", "model", "serialNumber"):
            value = getattr(screen, attribute_name, "")
            try:
                value = value() if callable(value) else value
            except Exception:
                value = ""
            text = str(value or "").strip()
            if text:
                identity_parts.append(text)
        identity = "|".join(identity_parts) or (
            f"display:{geometry.x()}:{geometry.y()}:{geometry.width()}:{geometry.height()}"
        )
        physical_size = screen.physicalSize()
        return gaze_calibration.DisplayDescriptor(
            identity=identity,
            geometry=(
                int(geometry.x()),
                int(geometry.y()),
                int(geometry.width()),
                int(geometry.height()),
            ),
            physical_size_mm=(
                float(physical_size.width()),
                float(physical_size.height()),
            ),
        )

    def _active_eye_tracking_calibration(
        self,
    ) -> gaze_calibration.CalibrationTransform | None:
        payload = self._last_runtime_config.get(
            "companion_orb_eye_tracking_calibration",
            {},
        )
        try:
            display = self._eye_tracking_display_descriptor()
        except Exception:
            return None
        cache_key = (
            id(payload),
            str(display.identity),
            tuple(display.geometry),
        )
        if cache_key == getattr(
            self,
            "_eye_tracking_calibration_cache_key",
            None,
        ):
            return getattr(self, "_eye_tracking_calibration_cache", None)
        transform = gaze_calibration.calibration_from_payload(
            payload,
            display=display,
        )
        self._eye_tracking_calibration_cache_key = cache_key
        self._eye_tracking_calibration_cache = transform
        return transform

    def _invalidate_eye_tracking_calibration_cache(self) -> None:
        self._eye_tracking_calibration_cache_key = None
        self._eye_tracking_calibration_cache = None

    def _calibrate_eye_tracking_point(
        self,
        point,
    ) -> tuple[float, float]:
        try:
            mapped = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            return 0.0, 0.0
        transform = self._active_eye_tracking_calibration()
        return transform.apply(mapped) if transform is not None else mapped

    def _refresh_eye_tracking_calibration_status_from_config(self) -> None:
        if bool(getattr(self, "_eye_tracking_calibration_active", False)):
            return
        current_status = dict(
            getattr(self, "_eye_tracking_calibration_status", {}) or {}
        )
        if str(current_status.get("state") or "").strip().lower() == "error":
            return
        payload = self._last_runtime_config.get(
            "companion_orb_eye_tracking_calibration",
            {},
        )
        transform = self._active_eye_tracking_calibration()
        if transform is not None:
            self._eye_tracking_calibration_status = {
                "state": "calibrated",
                "message": f"{transform.quality} gaze calibration is active.",
                "active": False,
                "target_index": 0,
                "target_count": 5,
                "quality": str(transform.quality),
                "average_error_px": round(float(transform.median_error_px), 1),
                "completed_at": str(transform.completed_at),
            }
        elif isinstance(payload, dict) and payload:
            self._eye_tracking_calibration_status = {
                "state": "recalibration_required",
                "message": "The saved gaze calibration does not match the selected display.",
                "active": False,
                "target_index": 0,
                "target_count": 5,
                "quality": "",
                "average_error_px": 0.0,
                "completed_at": "",
            }
        else:
            self._eye_tracking_calibration_status = {
                "state": "not_calibrated",
                "message": "No gaze calibration is saved.",
                "active": False,
                "target_index": 0,
                "target_count": 5,
                "quality": "",
                "average_error_px": 0.0,
                "completed_at": "",
            }

    def _ensure_eye_tracking_calibration_overlay(
        self,
    ) -> gaze_calibration_overlay.GazeCalibrationOverlay:
        overlay = getattr(self, "_eye_tracking_calibration_overlay", None)
        if overlay is None:
            overlay = gaze_calibration_overlay.GazeCalibrationOverlay()
            overlay.target_elapsed.connect(
                self._complete_eye_tracking_calibration_target,
                QtCore.Qt.QueuedConnection,
            )
            overlay.cancel_requested.connect(
                self.cancel_eye_tracking_calibration,
                QtCore.Qt.QueuedConnection,
            )
            self._eye_tracking_calibration_overlay = overlay
        return overlay

    def start_eye_tracking_calibration(self) -> dict[str, Any]:
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_mode",
                "dwell",
            )
        )
        if mode == "off":
            return {"ok": False, "error": "Eye tracking is off."}
        if not self._eye_tracking_orb_active():
            return {
                "ok": False,
                "error": "Enable and show the Companion Orb before calibration.",
            }
        if bool(getattr(self, "_eye_tracking_calibration_active", False)):
            return {
                "ok": False,
                "error": "Gaze calibration is already running.",
            }
        provider = getattr(self, "_eye_tracking_provider", None)
        connection_codes = {
            str(getattr(self, "_eye_tracking_status_code", "") or "").strip().lower(),
            str(getattr(provider, "status_code", "") or "").strip().lower(),
        }
        now = time.monotonic()
        latest_raw = getattr(self, "_eye_tracking_latest_raw_point", None)
        latest_raw_at = float(getattr(self, "_eye_tracking_latest_raw_at", 0.0) or 0.0)
        if latest_raw is None or now - latest_raw_at > 2.5:
            if "connected" not in connection_codes or not bool(
                getattr(provider, "is_running", False)
            ):
                return {
                    "ok": False,
                    "error": "The Tobii eye stream is not connected.",
                }
            return {
                "ok": False,
                "error": "Look at the selected display until a current gaze sample is available.",
            }
        try:
            display = self._eye_tracking_display_descriptor()
            calibration_rect = gaze_calibration.supported_calibration_rect(
                display.geometry,
                display.physical_size_mm,
            )
            targets = gaze_calibration.calibration_target_points(calibration_rect)
            overlay = self._ensure_eye_tracking_calibration_overlay()
            radial_menu = getattr(self, "_gaze_radial_menu", None)
            if radial_menu is not None and radial_menu.isVisible():
                self._dismiss_gaze_radial_menu()
            self._eye_tracking_policy.reset()
            self._eye_tracking_interaction_target = None
            self._eye_tracking_interaction_until = 0.0
            self._eye_tracking_last_external_target = None
            self._eye_tracking_last_external_sent_at = 0.0
            self._send_external_runtime({"type": "interaction_target_clear"})
            guard = getattr(self, "_sync_external_pointer_clearance_guard", None)
            if callable(guard):
                guard(True)
            self._eye_tracking_calibration_active = True
            self._eye_tracking_calibration_rect = tuple(calibration_rect)
            self._eye_tracking_calibration_targets = tuple(targets)
            self._eye_tracking_calibration_target_index = 0
            self._eye_tracking_calibration_target_started_at = now
            self._eye_tracking_calibration_samples = []
            self._eye_tracking_calibration_observed = []
            self._eye_tracking_calibration_status = {
                "state": "calibrating",
                "message": "Hold your gaze on target 1 of 5.",
                "active": True,
                "target_index": 1,
                "target_count": 5,
                "quality": "",
                "average_error_px": 0.0,
                "completed_at": "",
            }
            overlay.begin(
                screen_geometry=display.geometry,
                calibration_rect=calibration_rect,
                targets=targets,
                theme_color=str(self.bridge.primaryColor or "#22d3ee"),
            )
        except Exception as exc:
            try:
                self._finish_eye_tracking_calibration(
                    restore_saved_status=False,
                )
            except Exception:
                self._eye_tracking_calibration_active = False
            self._eye_tracking_calibration_status = {
                "state": "error",
                "message": str(exc) or "Gaze calibration could not start.",
                "active": False,
                "target_index": 0,
                "target_count": 5,
                "quality": "",
                "average_error_px": 0.0,
                "completed_at": "",
            }
            return {
                "ok": False,
                "error": self._eye_tracking_calibration_status["message"],
            }
        return {
            "ok": True,
            "calibration": dict(self._eye_tracking_calibration_status),
        }

    def _finish_eye_tracking_calibration(
        self,
        *,
        restore_saved_status: bool,
    ) -> None:
        overlay = getattr(self, "_eye_tracking_calibration_overlay", None)
        if overlay is not None:
            overlay.finish()
        self._eye_tracking_calibration_active = False
        self._eye_tracking_calibration_rect = ()
        self._eye_tracking_calibration_targets = ()
        self._eye_tracking_calibration_target_index = -1
        self._eye_tracking_calibration_target_started_at = 0.0
        self._eye_tracking_calibration_samples = []
        self._eye_tracking_calibration_observed = []
        guard = getattr(self, "_sync_external_pointer_clearance_guard", None)
        if callable(guard):
            guard(False)
        if restore_saved_status:
            self._refresh_eye_tracking_calibration_status_from_config()
        sync_drift = getattr(self, "_sync_drift_timer", None)
        if callable(sync_drift):
            sync_drift()

    def cancel_eye_tracking_calibration(self) -> dict[str, Any]:
        if not bool(getattr(self, "_eye_tracking_calibration_active", False)):
            return {"ok": False, "error": "Gaze calibration is not running."}
        self._finish_eye_tracking_calibration(restore_saved_status=True)
        return {
            "ok": True,
            "calibration": dict(self._eye_tracking_calibration_status),
        }

    def reset_eye_tracking_calibration(self) -> dict[str, Any]:
        if bool(getattr(self, "_eye_tracking_calibration_active", False)):
            self._finish_eye_tracking_calibration(restore_saved_status=False)
        self._last_runtime_config["companion_orb_eye_tracking_calibration"] = {}
        invalidate_calibration = getattr(
            self,
            "_invalidate_eye_tracking_calibration_cache",
            None,
        )
        if callable(invalidate_calibration):
            invalidate_calibration()
        self._save_runtime_setting("companion_orb_eye_tracking_calibration", {})
        policy = getattr(self, "_eye_tracking_policy", None)
        if policy is not None:
            policy.reset()
        self._eye_tracking_calibration_status = {
            "state": "not_calibrated",
            "message": "No gaze calibration is saved.",
            "active": False,
            "target_index": 0,
            "target_count": 5,
            "quality": "",
            "average_error_px": 0.0,
            "completed_at": "",
        }
        self._reapply_eye_tracking_interaction_target()
        return {
            "ok": True,
            "calibration": dict(self._eye_tracking_calibration_status),
        }

    def _collect_eye_tracking_calibration_sample(
        self,
        point,
        *,
        now: float,
    ) -> None:
        if not bool(getattr(self, "_eye_tracking_calibration_active", False)):
            return
        started_at = float(
            getattr(self, "_eye_tracking_calibration_target_started_at", 0.0)
            or 0.0
        )
        if float(now) - started_at < gaze_calibration_overlay.SETTLING_DURATION_SECONDS:
            return
        try:
            sample = float(point[0]), float(point[1])
            left, top, width, height = self._eye_tracking_screen_bounds()
        except (TypeError, ValueError, IndexError):
            return
        if not all(math.isfinite(value) for value in sample):
            return
        if not (
            left <= sample[0] <= left + width
            and top <= sample[1] <= top + height
        ):
            return
        self._eye_tracking_calibration_samples.append(sample)

    @QtCore.Slot(int)
    def _complete_eye_tracking_calibration_target(self, target_index: int) -> None:
        if not bool(getattr(self, "_eye_tracking_calibration_active", False)):
            return
        current_index = int(
            getattr(self, "_eye_tracking_calibration_target_index", -1)
        )
        if int(target_index) != current_index:
            return
        reduction = gaze_calibration.reduce_target_samples(
            tuple(self._eye_tracking_calibration_samples)
        )
        calibration_rect = tuple(self._eye_tracking_calibration_rect)
        dispersion_limit = (
            max(18.0, min(80.0, min(calibration_rect[2], calibration_rect[3]) * 0.04))
            if len(calibration_rect) == 4
            else 18.0
        )
        overlay = getattr(self, "_eye_tracking_calibration_overlay", None)
        if reduction is None or reduction.dispersion_px > dispersion_limit:
            self._eye_tracking_calibration_samples = []
            self._eye_tracking_calibration_target_started_at = time.monotonic()
            self._eye_tracking_calibration_status["message"] = "Hold gaze steady."
            if overlay is not None:
                overlay.restart_target("Hold gaze steady")
            return

        self._eye_tracking_calibration_observed.append(reduction.point)
        next_index = current_index + 1
        if next_index < len(self._eye_tracking_calibration_targets):
            self._eye_tracking_calibration_target_index = next_index
            self._eye_tracking_calibration_target_started_at = time.monotonic()
            self._eye_tracking_calibration_samples = []
            self._eye_tracking_calibration_status.update(
                {
                    "state": "calibrating",
                    "message": f"Hold your gaze on target {next_index + 1} of 5.",
                    "active": True,
                    "target_index": next_index + 1,
                }
            )
            if overlay is not None:
                overlay.show_target(next_index)
            return

        result = gaze_calibration.solve_calibration(
            observed_points=tuple(self._eye_tracking_calibration_observed),
            target_points=tuple(self._eye_tracking_calibration_targets),
            display=self._eye_tracking_display_descriptor(),
            calibration_rect=calibration_rect,
            completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        if not result.accepted or result.transform is None:
            self._eye_tracking_calibration_status = {
                "state": "error",
                "message": str(result.message),
                "active": False,
                "target_index": 0,
                "target_count": 5,
                "quality": "",
                "average_error_px": 0.0,
                "completed_at": "",
            }
            self._finish_eye_tracking_calibration(restore_saved_status=False)
            return

        payload = result.transform.to_payload()
        self._last_runtime_config["companion_orb_eye_tracking_calibration"] = payload
        self._invalidate_eye_tracking_calibration_cache()
        self._save_runtime_setting(
            "companion_orb_eye_tracking_calibration",
            payload,
        )
        self._eye_tracking_calibration_status = {
            "state": "calibrated",
            "message": str(result.message),
            "active": False,
            "target_index": 0,
            "target_count": 5,
            "quality": str(result.quality),
            "average_error_px": round(
                float(result.transform.median_error_px),
                1,
            ),
            "completed_at": str(result.transform.completed_at),
        }
        self._finish_eye_tracking_calibration(restore_saved_status=False)
        self._eye_tracking_policy.reset()
        latest_raw = getattr(self, "_eye_tracking_latest_raw_point", None)
        if latest_raw is not None:
            corrected = self._calibrate_eye_tracking_point(latest_raw)
            self._eye_tracking_latest_point = corrected
            self._eye_tracking_latest_at = time.monotonic()
            self._eye_tracking_stable_point = corrected
            self._eye_tracking_interaction_source_point = corrected
        self._reapply_eye_tracking_interaction_target()

    def _eye_tracking_screen_bounds(self) -> tuple[float, float, float, float]:
        screen = self._selected_eye_tracking_screen()
        geometry = screen.geometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        return float(geometry.x()), float(geometry.y()), float(geometry.width()), float(geometry.height())

    def _eye_tracking_pointer_clearance_enabled(self) -> bool:
        return interaction_settings.boolish(
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_enabled",
                False,
            ),
            default=False,
        )

    def _eye_tracking_pointer_clearance_distance(self) -> float:
        try:
            value = float(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_pointer_clearance_distance_px",
                    160,
                )
                or 160
            )
        except (TypeError, ValueError):
            value = 160.0
        return max(40.0, min(400.0, value))

    def _eye_tracking_pointer_clearance_timeout(self) -> float:
        try:
            value = float(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_pointer_clearance_timeout_seconds",
                    8,
                )
                or 8
            )
        except (TypeError, ValueError):
            value = 8.0
        return max(1.0, min(30.0, value))

    def _eye_tracking_pointer_clearance_suspended(self) -> bool:
        radial_menu = getattr(self, "_gaze_radial_menu", None)
        try:
            radial_visible = bool(
                radial_menu is not None and radial_menu.isVisible()
            )
        except RuntimeError:
            radial_visible = False
        bridge = getattr(self, "bridge", None)
        return bool(
            getattr(self, "_eye_tracking_calibration_active", False)
            or getattr(bridge, "editMode", False)
            or getattr(bridge, "placementMode", False)
            or getattr(self, "_menu_open", False)
            or getattr(self, "_gaze_radial_menu_open", False)
            or radial_visible
            or getattr(self, "_gaze_click_target_page_open", False)
            or getattr(self, "_gaze_click_visual_page_open", False)
            or getattr(self, "_gaze_click_visual_action_menu_open", False)
            or getattr(self, "_gaze_click_validation_pending", None) is not None
            or getattr(self, "_drag_offset", None) is not None
            or getattr(self, "_poll_drag_active", False)
            or getattr(self, "_eye_tracking_reaction_active", False)
            or int(getattr(self, "_snapshot_cloak_count", 0) or 0) > 0
            or not self._eye_tracking_orb_active()
        )

    def _set_pointer_clearance_state(self, state: str) -> None:
        normalized = str(state or "clear").strip().lower()
        if normalized not in {"clear", "avoiding", "timeout"}:
            normalized = "clear"
        self._eye_tracking_pointer_clearance_state = normalized

    def _reset_eye_tracking_pointer_clearance(self) -> None:
        policy = getattr(self, "_eye_tracking_pointer_clearance", None)
        if policy is not None:
            policy.reset()
        self._eye_tracking_pointer_clearance_opacity = 1.0
        self._set_pointer_clearance_state("clear")

    def _apply_eye_tracking_pointer_clearance(
        self,
        normal_target: QtCore.QPointF,
        *,
        current_top_left: QtCore.QPointF,
        now: float,
    ) -> QtCore.QPointF:
        policy = getattr(self, "_eye_tracking_pointer_clearance", None)
        if policy is None:
            policy = pointer_clearance.PointerClearancePolicy()
            self._eye_tracking_pointer_clearance = policy
        cursor = QtGui.QCursor.pos()
        decision = policy.update(
            normal_target=(float(normal_target.x()), float(normal_target.y())),
            current_top_left=(
                float(current_top_left.x()),
                float(current_top_left.y()),
            ),
            pointer=(
                float(cursor.x()),
                float(cursor.y()),
            ),
            screen_bounds=self._eye_tracking_screen_bounds(),
            orb_size=float(self._window_size()),
            move_distance_px=self._eye_tracking_pointer_clearance_distance(),
            timeout_seconds=self._eye_tracking_pointer_clearance_timeout(),
            now=float(now),
            enabled=self._eye_tracking_pointer_clearance_enabled(),
            suspended=self._eye_tracking_pointer_clearance_suspended(),
        )
        self._eye_tracking_pointer_clearance_opacity = float(decision.opacity)
        self._set_pointer_clearance_state(decision.state)
        return QtCore.QPointF(float(decision.target[0]), float(decision.target[1]))

    def _sync_external_pointer_clearance_guard(
        self,
        suspended: bool | None = None,
    ) -> None:
        guarded = (
            self._eye_tracking_pointer_clearance_suspended()
            if suspended is None
            else bool(suspended)
        )
        if getattr(self, "_external_pointer_clearance_guard", None) is guarded:
            return
        self._external_pointer_clearance_guard = guarded
        self._send_external_runtime(
            {
                "type": "pointer_clearance_guard",
                "suspended": guarded,
            }
        )

    def _vision_regions_supported(self) -> bool:
        config = getattr(self, "_last_runtime_config", {})
        if not isinstance(config, Mapping):
            config = {}
        return vision_guidance.capability_supports_regions(
            config.get(
                "companion_orb_vision_capability_mode",
                "auto",
            )
        )

    def _spatial_bounding_boxes_active(self) -> bool:
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        return bool(
            mode in {"dwell", "continuous"}
            and self._eye_tracking_orb_active()
            and CompanionOrbController._vision_regions_supported(self)
            and self._last_runtime_config.get("companion_orb_vision_enabled", False)
            and self._last_runtime_config.get(
                "companion_orb_eye_tracking_bounding_boxes_enabled",
                False,
            )
        )

    def _sync_spatial_region_gaze_policy(self) -> None:
        try:
            selection_ms = max(
                200,
                min(
                    3000,
                    int(
                        self._last_runtime_config.get(
                            "companion_orb_eye_tracking_region_select_dwell_ms",
                            700,
                        )
                        or 700
                    ),
                ),
            )
        except (TypeError, ValueError, OverflowError):
            selection_ms = 700
        try:
            activation_ms = max(
                1000,
                min(
                    15000,
                    int(
                        self._last_runtime_config.get(
                            "companion_orb_eye_tracking_long_gaze_ms",
                            3000,
                        )
                        or 3000
                    ),
                ),
            )
        except (TypeError, ValueError, OverflowError):
            activation_ms = 3000
        key = selection_ms, activation_ms
        if key == getattr(self, "_spatial_region_gaze_policy_key", None):
            return
        self._spatial_region_gaze_policy = eye_tracking.RegionGazeDwellPolicy(
            selection_dwell_ms=selection_ms,
            activation_dwell_ms=activation_ms,
        )
        self._spatial_region_gaze_policy_key = key
        store = getattr(self, "_desktop_spatial_map", None)
        if isinstance(store, desktop_spatial_map.DesktopSpatialMapStore):
            store.unlock_region()

    def _spatial_overlay_region_allowed(self, region) -> bool:
        kind = str(getattr(region, "kind", "object") or "object").strip().lower()
        if kind == "image":
            key = "companion_orb_eye_tracking_bounding_box_show_images"
        elif kind == "text":
            key = "companion_orb_eye_tracking_bounding_box_show_text"
        elif kind in {"button", "link", "field", "control", "icon"}:
            key = "companion_orb_eye_tracking_bounding_box_show_controls"
        elif kind in {"window", "panel"}:
            key = "companion_orb_eye_tracking_bounding_box_show_windows"
        elif kind == "media":
            key = "companion_orb_eye_tracking_bounding_box_show_media"
        else:
            key = "companion_orb_eye_tracking_bounding_box_show_other"
        default = key != "companion_orb_eye_tracking_bounding_box_show_other"
        return bool(self._last_runtime_config.get(key, default))

    def _ensure_spatial_map_overlay(self):
        overlay = getattr(self, "_spatial_map_overlay", None)
        if overlay is None:
            overlay = spatial_map_overlay.SpatialMapOverlay()
            self._spatial_map_overlay = overlay
        return overlay

    def _spatial_overlay_theme(self) -> dict[str, object]:
        return {
            "normal": self._last_runtime_config.get(
                "companion_orb_eye_tracking_bounding_box_normal_color",
                "#38bdf8",
            ),
            "hover": self._last_runtime_config.get(
                "companion_orb_eye_tracking_bounding_box_hover_color",
                "#facc15",
            ),
            "selected": self._last_runtime_config.get(
                "companion_orb_eye_tracking_bounding_box_selected_color",
                "#a78bfa",
            ),
            "opacity": self._last_runtime_config.get(
                "companion_orb_eye_tracking_bounding_box_opacity",
                0.70,
            ),
            "width": self._last_runtime_config.get(
                "companion_orb_eye_tracking_bounding_box_width",
                2.0,
            ),
            "minimum_confidence": self._last_runtime_config.get(
                "companion_orb_eye_tracking_bounding_box_min_confidence",
                0.55,
            ),
        }

    def _refresh_spatial_map_overlay(self) -> None:
        if not self._spatial_bounding_boxes_active():
            overlay = getattr(self, "_spatial_map_overlay", None)
            if overlay is not None:
                overlay.clear_regions()
            self._reset_spatial_region_gaze(refresh_overlay=False)
            return
        snapshot = self.spatial_map_snapshot()
        if snapshot is None:
            self.request_spatial_scan("gaze")
            return
        regions = tuple(
            region
            for region in snapshot.regions
            if self._spatial_overlay_region_allowed(region)
        )
        try:
            maximum_visible = int(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_bounding_box_max_visible",
                    24,
                )
                or 24
            )
        except (TypeError, ValueError, OverflowError):
            maximum_visible = 24
        self._ensure_spatial_map_overlay().set_regions(
            regions,
            show_labels=bool(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_bounding_box_labels_enabled",
                    True,
                )
            ),
            maximum_visible=maximum_visible,
            theme=self._spatial_overlay_theme(),
        )

    def _reset_spatial_region_gaze(self, *, refresh_overlay: bool = True) -> None:
        policy = getattr(self, "_spatial_region_gaze_policy", None)
        if policy is not None:
            policy.reset()
        self._spatial_menu_region_id = ""
        store = getattr(self, "_desktop_spatial_map", None)
        if isinstance(store, desktop_spatial_map.DesktopSpatialMapStore):
            store.unlock_region()
        overlay = getattr(self, "_spatial_map_overlay", None)
        if overlay is not None:
            overlay.set_gaze_state(spatial_map_overlay.SpatialOverlayState())
        if refresh_overlay and self._spatial_bounding_boxes_active():
            self._refresh_spatial_map_overlay()

    def _handle_spatial_region_gaze(
        self,
        point: tuple[float, float],
        *,
        now: float,
    ) -> bool:
        if not self._spatial_bounding_boxes_active():
            return False
        self._sync_spatial_region_gaze_policy()
        snapshot = self.spatial_map_snapshot()
        if snapshot is None:
            self.request_spatial_scan("gaze")
            self._reset_spatial_region_gaze(refresh_overlay=False)
            return False
        policy = self._spatial_region_gaze_policy
        try:
            minimum_confidence = float(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_bounding_box_min_confidence",
                    0.55,
                )
                or 0.55
            )
        except (TypeError, ValueError, OverflowError):
            minimum_confidence = 0.55
        region = desktop_spatial_map.region_at_point(
            snapshot,
            point,
            min_confidence=minimum_confidence,
            previous_region_id=policy.locked_id,
            hysteresis_px=8.0,
        )
        decision = policy.ingest(
            region.region_id if region is not None else "",
            now=now,
        )
        store = self._desktop_spatial_map
        if decision.locked_id:
            store.lock_region(decision.locked_id)
        elif store.locked_region_id:
            store.unlock_region()
        overlay = self._ensure_spatial_map_overlay()
        overlay.set_gaze_state(
            spatial_map_overlay.SpatialOverlayState(
                candidate_id=decision.candidate_id,
                locked_id=decision.locked_id,
                selection_progress=decision.selection_progress,
                activation_progress=decision.activation_progress,
            )
        )
        self._set_gaze_timer_state(
            bool(decision.candidate_id),
            decision.activation_progress
            if decision.locked_id
            else decision.selection_progress,
        )
        if decision.open_menu and region is not None:
            self._spatial_menu_region_id = region.region_id
            self._show_gaze_spatial_region_menu(region)
        return bool(region is not None or decision.locked_id)

    def _show_gaze_spatial_region_menu(self, region) -> bool:
        if self._menu_open:
            return False
        self._gaze_radial_anchor = self._gaze_radial_anchor_for_point(region.center)
        self._gaze_radial_context_point = tuple(region.center)
        self._gaze_radial_menu_open = True
        self._return_home_timer.stop()
        self._drift_timer.stop()
        self._motion_timer.stop()
        self._show_gaze_radial_actions(
            gaze_radial_menu.SPATIAL_TARGET_ACTIONS,
            title=region.label,
            center_label="Close",
            center_action_id="__cancel__",
        )
        self._set_gaze_timer_state(False, 0.0)
        return True

    def _dispatch_spatial_region_action(
        self,
        action_id: str,
        region,
    ) -> dict[str, Any]:
        normalized = str(action_id or "").strip().lower()
        if not isinstance(region, desktop_spatial_map.SpatialRegion):
            return {"ok": False, "error": "The selected desktop region is invalid."}
        store = getattr(self, "_desktop_spatial_map", None)
        snapshot = (
            store.current(allow_stale=True)
            if store is not None and callable(getattr(store, "current", None))
            else None
        )
        if snapshot is not None and not any(
            item.region_id == region.region_id for item in snapshot.regions
        ):
            request_scan = getattr(self, "request_spatial_scan", None)
            if callable(request_scan):
                request_scan("action", force=True)
            return {
                "ok": False,
                "queued": True,
                "error": "The selected desktop region changed; refreshing its location.",
            }
        bounds = list(region.screen_bounds)
        center = tuple(region.center)
        if normalized in {
            "spatial:react",
            "spatial:describe",
            "spatial:explain",
            "spatial:summarize",
        }:
            prompt_action = normalized.split(":", 1)[1]
            self._dismiss_gaze_radial_menu()
            return self._queue_gaze_radial_context_action(
                prompt_action,
                center,
                bounds_override=bounds,
            )
        if normalized == "spatial:read":
            reading_action_id = "select_area_read"
            action = reading_actions.action_for_id(reading_action_id)
            if action is None:
                return {"ok": False, "error": "The reading action is unavailable."}
            if not self._begin_reading_job(reading_action_id):
                return {
                    "ok": False,
                    "error": "Another Companion Orb reading action is still running.",
                }
            try:
                self._dismiss_gaze_radial_menu()
                self._start_reading_worker(
                    action,
                    selected_text="",
                    bounds=bounds,
                    private_bounds=True,
                )
            except Exception as exc:
                self._finish_reading_job(reading_action_id, reason="failed")
                return {"ok": False, "error": f"Could not start reading: {exc}"}
            return {"ok": True, "queued": True}
        if normalized == "spatial:move":
            self._dismiss_gaze_radial_menu()
            self._set_comment_focus(
                {
                    "focus_bounds": bounds,
                    "focus_label": region.label,
                    "focus_text": region.label,
                }
            )
            return {"ok": True, "queued": False, "moved": True}
        if normalized == "spatial:ask":
            anchor = QtCore.QPoint(int(round(center[0])), int(round(center[1])))
            self._dismiss_gaze_radial_menu()
            self._spatial_chat_region_id = region.region_id
            self._show_chat_input_popup(anchor, context_label=region.label)
            return {"ok": True, "queued": False, "chat_opened": True}
        if normalized == "spatial:interact":
            if not self._gaze_click_target_enabled():
                return {
                    "ok": False,
                    "error": "Enable the Action gaze button before interacting.",
                }
            item = {
                "label": region.label,
                "kind": region.kind,
                "bounds": bounds,
                "capture_bounds": list(snapshot.capture_bounds) if snapshot is not None else bounds,
                "confidence": region.confidence,
                "source": "vision",
                "backend": "lfm_vision",
                "semantic": False,
                "capture_fingerprint": str(
                    getattr(self, "_spatial_last_fingerprint", "") or ""
                ),
            }
            self._gaze_click_visual_targets = [item]
            self._gaze_click_visual_selected_index = 0
            self._show_gaze_click_visual_action_menu(0)
            return {
                "ok": True,
                "queued": False,
                "confirmation_required": True,
            }
        return {"ok": False, "error": "Unknown desktop-region action."}

    @QtCore.Slot(bool)
    def _handle_eye_tracking_validity(self, valid: bool) -> None:
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        allowed = interaction_settings.boolish(
            self._last_runtime_config.get("companion_orb_eye_tracking_blink_click_allowed", True),
            default=True,
        )
        detector = self._blink_gesture_detector
        policy = self._blink_click_policy
        if bool(getattr(self, "_eye_tracking_calibration_active", False)):
            reset_spatial_gaze = getattr(self, "_reset_spatial_region_gaze", None)
            if callable(reset_spatial_gaze):
                reset_spatial_gaze(refresh_overlay=False)
            detector.reset()
            policy.reset()
            self._eye_command_policy.reset()
            self._blink_pending_click_timer.stop()
            self._blink_pending_click_point = None
            return
        if mode == "off" or not self._eye_tracking_orb_active() or not allowed:
            reset_spatial_gaze = getattr(self, "_reset_spatial_region_gaze", None)
            if callable(reset_spatial_gaze):
                reset_spatial_gaze(refresh_overlay=False)
            detector.reset()
            policy.reset()
            self._eye_command_policy.reset()
            self._blink_pending_click_timer.stop()
            self._blink_pending_click_point = None
            return
        now = time.monotonic()
        detector.ingest_validity(bool(valid), now=now)
        if bool(valid):
            return
        reset_spatial_gaze = getattr(self, "_reset_spatial_region_gaze", None)
        if callable(reset_spatial_gaze):
            reset_spatial_gaze()
        radial_menu = getattr(self, "_gaze_radial_menu", None)
        if (
            radial_menu is not None
            and radial_menu.isVisible()
            and bool(radial_menu.selection_candidate_id)
        ):
            policy.arm_activation(now=now)
            radial_menu.reset_gaze_selection()
            self._set_gaze_timer_state(False, 0.0)

    @QtCore.Slot(float, float)
    def _handle_eye_tracking_sample(self, normalized_x: float, normalized_y: float) -> None:
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        if mode == "off" or not self._eye_tracking_orb_active():
            return
        mapped = eye_tracking.map_normalized_point(
            (float(normalized_x), float(normalized_y)),
            self._eye_tracking_screen_bounds(),
        )
        now = time.monotonic()
        self._eye_tracking_latest_raw_point = mapped
        self._eye_tracking_latest_raw_at = now
        if bool(getattr(self, "_eye_tracking_calibration_active", False)):
            collector = getattr(
                self,
                "_collect_eye_tracking_calibration_sample",
                None,
            )
            if callable(collector):
                collector(mapped, now=now)
            return
        calibrator = getattr(self, "_calibrate_eye_tracking_point", None)
        if callable(calibrator):
            mapped = calibrator(mapped)
        radial_menu = getattr(self, "_gaze_radial_menu", None)
        blink_detector = getattr(self, "_blink_gesture_detector", None)
        gesture = blink_detector.ingest_valid_sample(now=now) if blink_detector is not None else None
        if gesture is not None:
            self._handle_blink_gesture(gesture, mapped, now=now)
            radial_menu = getattr(self, "_gaze_radial_menu", None)
        radial_visible = radial_menu is not None and radial_menu.isVisible()
        if bool(getattr(self, "_gaze_scroll_active", False)) and not radial_visible:
            wheel_delta = self._gaze_scroll_policy.ingest(
                mapped[1],
                anchor_y=self._gaze_scroll_anchor_y,
                now=now,
            )
            if wheel_delta and not self._perform_gaze_scroll(
                self._gaze_scroll_target_hwnd,
                wheel_delta,
                self._gaze_scroll_target_point or mapped,
            ):
                self._eye_tracking_status_message = (
                    "Gaze scrolling stopped because the target window is unavailable."
                )
                self._stop_gaze_scrolling()
                self._play_blink_notification(False)
                return
        if radial_menu is not None and radial_menu.isVisible():
            if mode not in {"continuous", "dwell"}:
                radial_menu.cancel()
                self._set_gaze_timer_state(False, 0.0)
            else:
                radial_menu.feed_gaze(
                    QtCore.QPointF(mapped[0], mapped[1]),
                    now=now,
                )
                if radial_menu.isVisible():
                    self._set_gaze_timer_state(
                        bool(radial_menu.selection_candidate_id),
                        radial_menu.selection_progress,
                    )
                else:
                    self._set_gaze_timer_state(False, 0.0)
                return
        spatial_handler = getattr(self, "_handle_spatial_region_gaze", None)
        spatial_region_handled = bool(
            callable(spatial_handler) and spatial_handler(mapped, now=now)
        )
        decision = self._eye_tracking_policy.ingest(mapped[0], mapped[1], now=now)
        self._eye_tracking_latest_point = decision.point
        self._eye_tracking_latest_at = now
        if decision.stable:
            self._eye_tracking_stable_point = decision.point
        elif mode != "continuous":
            self._eye_tracking_stable_point = None
        if mode in {"continuous", "dwell"}:
            target_hold_seconds = 2.0 if mode == "dwell" else 0.75
            self._set_eye_tracking_interaction_target(
                decision.point,
                duration_seconds=target_hold_seconds,
            )
        long_gaze_enabled = interaction_settings.boolish(
            self._last_runtime_config.get("companion_orb_eye_tracking_long_gaze_enabled", False),
            default=False,
        )
        try:
            dwell_ms = max(
                300,
                min(2000, int(self._last_runtime_config.get("companion_orb_eye_tracking_dwell_ms", 700) or 700)),
            )
        except (TypeError, ValueError):
            dwell_ms = 700
        try:
            long_dwell_ms = max(
                1000,
                min(
                    15000,
                    int(self._last_runtime_config.get("companion_orb_eye_tracking_long_gaze_ms", 3000) or 3000),
                ),
            )
        except (TypeError, ValueError):
            long_dwell_ms = 3000
        timer_progress = eye_tracking.gaze_timer_visual_progress(
            hold_seconds=decision.hold_seconds,
            dwell_ms=dwell_ms,
            long_dwell_ms=long_dwell_ms,
            long_gaze_enabled=long_gaze_enabled,
        )
        timer_active = mode in {"continuous", "dwell"} and (
            long_gaze_enabled
            or (not long_gaze_enabled and (not decision.stable or decision.dwell_triggered))
        )
        timer_setter = getattr(self, "_set_gaze_timer_state", None)
        if callable(timer_setter):
            timer_setter(timer_active, timer_progress)
        if (
            mode in {"continuous", "dwell"}
            and not spatial_region_handled
            and long_gaze_enabled
            and decision.long_dwell_triggered
        ):
            self._set_eye_tracking_interaction_target(
                decision.point,
                duration_seconds=12.0,
                force_external_send=True,
            )
            opened = self._show_gaze_radial_main_menu(decision.point)
            if opened is False and callable(timer_setter):
                timer_setter(False, 0.0)
            return
        reaction_mode = eye_tracking.normalize_reaction_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_reaction_mode", "meaningful")
        )
        if (
            mode in {"dwell", "continuous"}
            and not spatial_region_handled
            and decision.dwell_triggered
            and reaction_mode != "off"
        ):
            self._request_eye_tracking_reaction(False)

    def _consume_lfm_click_confirmation_blink(
        self,
        gesture: eye_tracking.BlinkGesture,
    ) -> bool:
        pending = getattr(self, "_gaze_lfm_click_pending", None)
        if not isinstance(
            pending,
            vision_click_verification.PendingLfmClickConfirmation,
        ) or pending.confirmation_method != "double_blink":
            return False
        if bool(getattr(self, "_gaze_lfm_click_verifying", False)):
            return True
        enabled_check = getattr(self, "_lfm_click_enabled", None)
        valid = bool(
            getattr(self, "_gaze_radial_menu_open", False)
            and pending.scan_generation
            == int(getattr(self, "_gaze_click_scan_generation", 0))
            and pending.confirmation_generation
            == int(getattr(self, "_gaze_lfm_click_confirmation_generation", 0))
            and callable(enabled_check)
            and enabled_check()
        )
        if not valid:
            cancel = getattr(self, "_cancel_lfm_click_confirmation", None)
            if callable(cancel):
                cancel()
            return True
        policy = getattr(self, "_gaze_lfm_double_blink", None)
        if not isinstance(
            policy,
            vision_click_verification.DoubleBlinkConfirmationPolicy,
        ):
            return True
        confirmed = policy.ingest(
            closed_ms=gesture.closed_ms,
            ended_at=gesture.ended_at,
        )
        if confirmed:
            confirm = getattr(self, "_confirm_pending_lfm_click", None)
            if callable(confirm):
                confirm()
        return True

    def _handle_blink_gesture(
        self,
        gesture: eye_tracking.BlinkGesture,
        point: tuple[float, float],
        *,
        now: float,
    ) -> None:
        if not interaction_settings.boolish(
            self._last_runtime_config.get("companion_orb_eye_tracking_blink_click_allowed", True),
            default=True,
        ):
            return
        lfm_blink_consumer = getattr(
            self,
            "_consume_lfm_click_confirmation_blink",
            None,
        )
        if callable(lfm_blink_consumer) and lfm_blink_consumer(gesture):
            return
        radial_menu = getattr(self, "_gaze_radial_menu", None)
        menu_visible = bool(
            getattr(self, "_gaze_radial_menu_open", False)
            or (radial_menu is not None and radial_menu.isVisible())
        )
        command = self._eye_command_policy.ingest_blink(
            gesture,
            now=now,
            menu_visible=menu_visible,
        )
        if command.action == "long_gaze_toggle":
            self._blink_pending_click_timer.stop()
            self._blink_pending_click_point = None
            self._play_blink_notification(self._toggle_long_gaze_radial_menu())
            return
        if command.action == "browser_back":
            self._blink_pending_click_timer.stop()
            self._blink_pending_click_point = None
            self._play_blink_notification(self._perform_browser_back())
            return
        if command.action == "quick_pending":
            self._blink_pending_click_point = self._blink_click_point(point)
            deadline = self._eye_command_policy.pending_quick_deadline
            delay_ms = 1 if deadline is None else max(1, int(math.ceil((deadline - now) * 1000.0)))
            self._blink_pending_click_timer.start(delay_ms)
            return
        if command.action != "passthrough":
            return
        decision = self._blink_click_policy.ingest_blink(
            gesture.closed_ms,
            now=now,
            menu_visible=menu_visible,
        )
        if decision.action == "enable":
            self._play_blink_notification(True)
            if menu_visible:
                self._dismiss_gaze_radial_menu()
            return
        if decision.action == "disable":
            self._play_blink_notification(False)
            return
        if decision.action == "click" and not menu_visible:
            self._queue_gaze_left_click(self._blink_click_point(point))

    def _toggle_long_gaze_radial_menu(self) -> bool:
        key = "companion_orb_eye_tracking_long_gaze_enabled"
        enabled = not interaction_settings.boolish(
            self._last_runtime_config.get(key, False),
            default=False,
        )
        self._last_runtime_config[key] = enabled
        self._save_runtime_setting(key, enabled)
        return enabled

    @QtCore.Slot()
    def _release_pending_quick_blink(self) -> None:
        now = time.monotonic()
        gesture = self._eye_command_policy.release_pending_quick(now=now)
        if gesture is None:
            deadline = self._eye_command_policy.pending_quick_deadline
            if deadline is not None:
                self._blink_pending_click_timer.start(
                    max(1, int(math.ceil((deadline - now) * 1000.0)))
                )
            return
        point = self._blink_pending_click_point
        self._blink_pending_click_point = None
        radial_menu = getattr(self, "_gaze_radial_menu", None)
        menu_visible = bool(
            getattr(self, "_gaze_radial_menu_open", False)
            or (radial_menu is not None and radial_menu.isVisible())
        )
        decision = self._blink_click_policy.ingest_blink(
            gesture.closed_ms,
            now=now,
            menu_visible=menu_visible,
        )
        if decision.action == "click" and not menu_visible and point is not None:
            self._queue_gaze_left_click(point)

    def _blink_click_point(self, fallback_point: tuple[float, float]) -> tuple[float, float]:
        size = float(self._window_size())
        window = getattr(self, "_window", None)
        if not self._external_runtime_enabled() and window is not None:
            geometry = window.frameGeometry()
            return (
                float(geometry.x()) + float(geometry.width()) * 0.5,
                float(geometry.y()) + float(geometry.height()) * 0.5,
            )
        interaction_target = getattr(self, "_eye_tracking_interaction_target", None)
        if interaction_target is not None:
            return (
                float(interaction_target.x()) + size * 0.5,
                float(interaction_target.y()) + size * 0.5,
            )
        external_top_left = getattr(self, "_external_orb_top_left", None)
        if external_top_left is not None:
            return (
                float(external_top_left.x()) + size * 0.5,
                float(external_top_left.y()) + size * 0.5,
            )
        try:
            return float(fallback_point[0]), float(fallback_point[1])
        except (TypeError, ValueError, IndexError):
            return 0.0, 0.0

    def _perform_gaze_left_click(self, point: tuple[float, float]) -> bool:
        try:
            x, y = int(round(float(point[0]))), int(round(float(point[1])))
        except (TypeError, ValueError, IndexError):
            return False
        if not (math.isfinite(float(x)) and math.isfinite(float(y))):
            return False
        try:
            user32 = ctypes.windll.user32
            if not bool(user32.SetCursorPos(x, y)):
                return False
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            return True
        except Exception:
            return False

    def _perform_browser_back(self) -> bool:
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x25, 0, 0, 0)
            user32.keybd_event(0x25, 0, 0x0002, 0)
            user32.keybd_event(0x12, 0, 0x0002, 0)
            return True
        except Exception:
            return False

    @staticmethod
    def _window_handle_at_point(point: tuple[float, float]) -> int:
        try:
            x, y = int(round(float(point[0]))), int(round(float(point[1])))
            user32 = ctypes.windll.user32

            class WinPoint(ctypes.Structure):
                _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))

            hwnd = int(user32.WindowFromPoint(WinPoint(x, y)) or 0)
            if hwnd:
                hwnd = int(user32.GetAncestor(hwnd, 2) or hwnd)
            return hwnd or int(user32.GetForegroundWindow() or 0)
        except Exception:
            return 0

    def _perform_gaze_scroll(
        self,
        hwnd: int,
        wheel_delta: int,
        point: tuple[float, float],
    ) -> bool:
        try:
            target = int(hwnd)
            delta = int(wheel_delta)
            x, y = int(round(float(point[0]))), int(round(float(point[1])))
        except (TypeError, ValueError, IndexError, OverflowError):
            return False
        if not target or not delta:
            return False
        try:
            user32 = ctypes.windll.user32
            if not bool(user32.IsWindow(target)):
                return False

            class WinPoint(ctypes.Structure):
                _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))

            original = WinPoint()
            if not bool(user32.GetCursorPos(ctypes.byref(original))):
                return CompanionOrbController._perform_gaze_scroll_keys(
                    user32,
                    target,
                    delta,
                )
            if not bool(user32.SetCursorPos(x, y)):
                return CompanionOrbController._perform_gaze_scroll_keys(
                    user32,
                    target,
                    delta,
                )
            try:
                user32.mouse_event(
                    0x0800,
                    0,
                    0,
                    ctypes.c_uint32(delta).value,
                    0,
                )
            finally:
                user32.SetCursorPos(int(original.x), int(original.y))
            return True
        except Exception:
            return False

    @staticmethod
    def _perform_gaze_scroll_keys(user32, target: int, wheel_delta: int) -> bool:
        try:
            previous = int(user32.GetForegroundWindow() or 0)
            if previous != int(target) and not bool(user32.SetForegroundWindow(int(target))):
                return False
            key = 0x26 if int(wheel_delta) > 0 else 0x28
            repeats = max(1, min(6, abs(int(wheel_delta)) // 120))
            for _index in range(repeats):
                user32.keybd_event(key, 0, 0, 0)
                user32.keybd_event(key, 0, 0x0002, 0)
            if previous and previous != int(target):
                user32.SetForegroundWindow(previous)
            return True
        except Exception:
            return False

    def _queue_gaze_left_click(
        self,
        point: tuple[float, float],
        *,
        cloak_already_active: bool = False,
        require_click_target_enabled: bool = False,
        execution_preflight=None,
    ) -> None:
        try:
            click_point = (float(point[0]), float(point[1]))
        except (TypeError, ValueError, IndexError):
            if cloak_already_active:
                self._set_snapshot_cloak(False)
            return
        external_required = CompanionOrbController._external_runtime_enabled(self)
        click_target_generation = (
            int(getattr(self, "_gaze_click_scan_generation", 0))
            if require_click_target_enabled
            else None
        )
        if not cloak_already_active:
            self._set_snapshot_cloak(True)

        def click_target_current() -> bool:
            if not require_click_target_enabled:
                return True
            return bool(self._gaze_click_target_enabled()) and int(
                getattr(self, "_gaze_click_scan_generation", -1)
            ) == int(click_target_generation)

        preflight_state = {"consumed": False}

        def execution_authorized_once() -> bool:
            if not click_target_current() or preflight_state["consumed"]:
                return False
            preflight_state["consumed"] = True
            if not callable(execution_preflight):
                return True
            try:
                return bool(execution_preflight())
            except Exception:
                return False

        def click_under_orb() -> None:
            try:
                if execution_authorized_once():
                    self._perform_gaze_left_click(click_point)
            finally:
                QtCore.QTimer.singleShot(70, lambda: self._set_snapshot_cloak(False))

        if not external_required:
            QtCore.QTimer.singleShot(55, click_under_orb)
            return

        deadline = time.monotonic() + GAZE_CLICK_CLOAK_ACK_TIMEOUT_SECONDS
        state = {"finished": False, "released": False}

        def release_once() -> None:
            if state["released"]:
                return
            state["released"] = True
            self._set_snapshot_cloak(False)

        def finish_click() -> None:
            if state["finished"]:
                return
            state["finished"] = True
            try:
                if execution_authorized_once():
                    self._perform_gaze_left_click(click_point)
            finally:
                QtCore.QTimer.singleShot(70, release_once)

        def poll_cloak_ack() -> None:
            if state["finished"]:
                return
            if bool(getattr(self, "_eye_tracking_reaction_shutting_down", False)):
                state["finished"] = True
                release_once()
                return
            if not click_target_current():
                state["finished"] = True
                release_once()
                return
            if not CompanionOrbController._external_runtime_enabled(self):
                state["finished"] = True
                release_once()
                return
            if CompanionOrbController._external_cloak_ack_ready(self, True):
                finish_click()
                return
            if time.monotonic() >= deadline:
                state["finished"] = True
                release_once()
                return
            QtCore.QTimer.singleShot(GAZE_CLICK_CLOAK_ACK_POLL_MS, poll_cloak_ack)

        QtCore.QTimer.singleShot(55, poll_cloak_ack)

    def _queue_gaze_click_target_left_click(self, point: tuple[float, float]) -> None:
        self._queue_gaze_left_click(
            point,
            require_click_target_enabled=True,
        )

    def _hide_gaze_click_target_source_visuals(self) -> None:
        self._clear_gaze_click_target_highlight()
        menu = getattr(self, "_gaze_radial_menu", None)
        if menu is not None:
            menu.hide()
        self._set_gaze_timer_state(False, 0.0)

    def _consume_gaze_click_validation(
        self,
        token: int,
        *,
        transfer_cloak: bool = False,
    ) -> tuple[ClickValidationPending | None, bool]:
        pending = getattr(self, "_gaze_click_validation_pending", None)
        try:
            expected_token = int(token)
        except (TypeError, ValueError, OverflowError):
            return None, False
        if (
            not isinstance(pending, tuple)
            or len(pending) != 6
            or int(pending[5]) != expected_token
        ):
            return None, False
        self._gaze_click_validation_pending = None
        owns_cloak = bool(
            getattr(self, "_gaze_click_validation_cloak_active", False)
            and getattr(self, "_gaze_click_validation_cloak_token", None) == expected_token
        )
        if owns_cloak:
            self._gaze_click_validation_cloak_active = False
            self._gaze_click_validation_cloak_token = None
            if not transfer_cloak:
                self._set_snapshot_cloak(False)
        return pending, bool(owns_cloak and transfer_cloak)

    def _cancel_gaze_click_validation(self) -> bool:
        self._gaze_click_validation_pending = None
        if not bool(getattr(self, "_gaze_click_validation_cloak_active", False)):
            return False
        self._gaze_click_validation_cloak_active = False
        self._gaze_click_validation_cloak_token = None
        self._set_snapshot_cloak(False)
        return True

    def _handle_gaze_click_validation_watchdog(self, token: int) -> None:
        pending, _transferred = self._consume_gaze_click_validation(token)
        if pending is None:
            return
        if (
            not bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
            and bool(getattr(self, "_gaze_radial_menu_open", False))
            and self._gaze_click_target_enabled()
        ):
            self._show_gaze_click_target_menu()

    def _queue_confirmed_target_click(
        self,
        target: eye_tracking.ClickTarget,
        *,
        action_id: str,
    ) -> None:
        if not eye_tracking.is_semantic_direct_target(target):
            return
        generation = int(getattr(self, "_gaze_click_scan_generation", 0))
        normalized_action = str(action_id or "").strip().lower()
        runtime_id = tuple(int(value) for value in target.runtime_id)
        fingerprint = _click_target_fingerprint(target)
        captured_center = (float(target.center[0]), float(target.center[1]))
        if not normalized_action:
            return
        CompanionOrbController._cancel_gaze_click_validation(self)
        self._gaze_click_validation_generation = int(
            getattr(self, "_gaze_click_validation_generation", 0)
        ) + 1
        validation_token = self._gaze_click_validation_generation
        self._gaze_click_validation_pending = (
            generation,
            normalized_action,
            runtime_id,
            fingerprint,
            captured_center,
            validation_token,
        )
        self._gaze_click_validation_cloak_active = True
        self._gaze_click_validation_cloak_token = validation_token
        self._set_snapshot_cloak(True)
        pending = getattr(self, "_gaze_click_validation_pending", None)
        if (
            not isinstance(pending, tuple)
            or len(pending) != 6
            or pending[5] != validation_token
            or not bool(getattr(self, "_gaze_click_validation_cloak_active", False))
            or getattr(self, "_gaze_click_validation_cloak_token", None) != validation_token
        ):
            return
        self._hide_gaze_click_target_source_visuals()
        QtCore.QTimer.singleShot(
            GAZE_CLICK_VALIDATION_WATCHDOG_MS,
            lambda token=validation_token: self._handle_gaze_click_validation_watchdog(token),
        )
        try:
            threading.Thread(
                target=self._validate_gaze_semantic_target_click,
                args=(
                    target,
                    target.center,
                    generation,
                    normalized_action,
                    runtime_id,
                    validation_token,
                ),
                daemon=True,
                name="companion-orb-click-target-validation",
            ).start()
        except Exception:
            pending, _transferred = self._consume_gaze_click_validation(validation_token)
            if pending is not None and self._gaze_click_target_enabled():
                self._show_gaze_click_target_menu()

    def _validate_gaze_semantic_target_click(
        self,
        target: eye_tracking.ClickTarget,
        point: tuple[float, float],
        generation: int,
        action_id: str,
        runtime_id: tuple[int, ...],
        validation_token: int,
    ) -> None:
        valid = windows_ui_automation.validate_semantic_target(target, point)
        self._proxy.eye_click_validation_requested.emit(
            int(generation),
            str(action_id),
            list(runtime_id),
            bool(valid),
            int(validation_token),
        )

    @QtCore.Slot(int, str, list, bool, int)
    def _handle_gaze_click_validation_result(
        self,
        generation: int,
        action_id: str,
        runtime_id: list[int],
        valid: bool,
        validation_token: int,
    ) -> None:
        try:
            result_generation = int(generation)
            normalized_action = str(action_id or "").strip().lower()
            result_runtime_id = tuple(int(value) for value in list(runtime_id or []))
            result_validation_token = int(validation_token)
        except (TypeError, ValueError, OverflowError):
            return
        result_token = (
            result_generation,
            normalized_action,
            result_runtime_id,
        )
        pending = getattr(self, "_gaze_click_validation_pending", None)
        if (
            not isinstance(pending, tuple)
            or len(pending) != 6
            or pending[5] != result_validation_token
        ):
            return
        captured_fingerprint = pending[3]
        captured_center = pending[4]
        target = getattr(self, "_gaze_click_targets", {}).get(normalized_action)
        if (
            bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
            or result_generation != int(getattr(self, "_gaze_click_scan_generation", 0))
            or not bool(getattr(self, "_gaze_radial_menu_open", False))
            or not self._gaze_click_target_enabled()
            or pending[:3] != result_token
            or not isinstance(target, eye_tracking.ClickTarget)
            or _click_target_fingerprint(target) != captured_fingerprint
            or not bool(valid)
            or not result_runtime_id
        ):
            consumed, _transferred = self._consume_gaze_click_validation(
                result_validation_token
            )
            if (
                consumed is not None
                and not bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
                and result_generation == int(getattr(self, "_gaze_click_scan_generation", 0))
                and bool(getattr(self, "_gaze_radial_menu_open", False))
                and self._gaze_click_target_enabled()
            ):
                self._show_gaze_click_target_menu()
            return
        consumed, cloak_transferred = self._consume_gaze_click_validation(
            result_validation_token,
            transfer_cloak=True,
        )
        if consumed is None:
            return
        self._dismiss_gaze_radial_menu()
        self._queue_gaze_left_click(
            captured_center,
            cloak_already_active=cloak_transferred,
            require_click_target_enabled=True,
        )

    def _play_blink_notification(self, enabled: bool) -> None:
        sequence = ((880, 55), (1175, 75)) if enabled else ((520, 65), (330, 85))

        def play() -> None:
            try:
                import winsound

                for frequency, duration_ms in sequence:
                    winsound.Beep(int(frequency), int(duration_ms))
            except Exception:
                pass

        threading.Thread(
            target=play,
            daemon=True,
            name="companion-orb-blink-notification",
        ).start()

    def _reapply_eye_tracking_interaction_target(self) -> None:
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        if mode not in {"dwell", "continuous"} or not self._eye_tracking_orb_active():
            return
        if not self._eye_tracking_interaction_ready():
            return
        source_point = self._eye_tracking_interaction_source_point
        latest_raw = getattr(self, "_eye_tracking_latest_raw_point", None)
        calibrator = getattr(self, "_calibrate_eye_tracking_point", None)
        if latest_raw is not None and callable(calibrator):
            source_point = calibrator(latest_raw)
            self._eye_tracking_interaction_source_point = source_point
        if source_point is None:
            return
        duration_seconds = 2.0 if mode == "dwell" else 0.75
        self._set_eye_tracking_interaction_target(
            source_point,
            duration_seconds=duration_seconds,
            force_external_send=True,
        )

    def _set_eye_tracking_interaction_target(
        self,
        point,
        *,
        duration_seconds: float,
        force_external_send: bool = False,
    ) -> None:
        try:
            screen_point = (float(point[0]), float(point[1]))
        except (TypeError, ValueError, IndexError):
            return
        offset_x, offset_y = _eye_tracking_calibration_offsets(self._last_runtime_config)
        target = eye_tracking.orb_top_left_for_point(
            screen_point,
            self._eye_tracking_screen_bounds(),
            orb_size=float(self._window_size()),
            offset_px=max(64.0, min(140.0, float(self._window_size()) * 0.55)),
            offset_x_px=offset_x,
            offset_y_px=offset_y,
        )
        clamped = self._clamp_top_left_to_screen(QtCore.QPointF(target[0], target[1]))
        self._eye_tracking_interaction_source_point = screen_point
        self._eye_tracking_interaction_target = QtCore.QPointF(clamped)
        now = time.monotonic()
        lifetime = max(0.2, min(12.0, float(duration_seconds)))
        self._eye_tracking_interaction_until = now + lifetime
        self._return_home_timer.stop()
        if not self.bridge.editMode and not self.bridge.placementMode and self._motion_timer.isActive():
            self._motion_timer.stop()
            self._move_start_point = None
            self._move_target_point = None
        if self._external_runtime_enabled():
            previous = self._eye_tracking_last_external_target
            distance = (
                math.hypot(clamped.x() - previous.x(), clamped.y() - previous.y())
                if previous is not None
                else float("inf")
            )
            if force_external_send or now - self._eye_tracking_last_external_sent_at >= 0.05 or distance >= 3.0:
                self._send_external_runtime(
                    {
                        "type": "interaction_target",
                        "point": [int(round(clamped.x())), int(round(clamped.y()))],
                        "duration_seconds": lifetime,
                        "pointer_clearance_suspended": bool(
                            self._eye_tracking_pointer_clearance_suspended()
                        ),
                    }
                )
                self._eye_tracking_last_external_target = QtCore.QPointF(clamped)
                self._eye_tracking_last_external_sent_at = now
        else:
            self._sync_drift_timer()

    def _eye_tracking_interaction_ready(self) -> bool:
        target = self._eye_tracking_interaction_target
        if target is None:
            return False
        if time.monotonic() <= float(self._eye_tracking_interaction_until or 0.0):
            return True
        self._eye_tracking_interaction_target = None
        self._eye_tracking_interaction_until = 0.0
        return False

    def _clear_eye_tracking_state(self, *, send_external: bool) -> None:
        self._eye_tracking_policy.reset()
        reset_spatial_gaze = getattr(self, "_reset_spatial_region_gaze", None)
        if callable(reset_spatial_gaze):
            reset_spatial_gaze(refresh_overlay=False)
        detector = getattr(self, "_blink_gesture_detector", None)
        if detector is not None:
            detector.reset()
        blink_policy = getattr(self, "_blink_click_policy", None)
        if blink_policy is not None:
            blink_policy.reset()
        command_policy = getattr(self, "_eye_command_policy", None)
        if command_policy is not None:
            command_policy.reset()
        pending_timer = getattr(self, "_blink_pending_click_timer", None)
        if pending_timer is not None:
            pending_timer.stop()
        self._blink_pending_click_point = None
        stop_scrolling = getattr(self, "_stop_gaze_scrolling", None)
        if callable(stop_scrolling):
            stop_scrolling()
        reset_clearance = getattr(
            self,
            "_reset_eye_tracking_pointer_clearance",
            None,
        )
        if callable(reset_clearance):
            reset_clearance()
        self._eye_tracking_latest_raw_point = None
        self._eye_tracking_latest_raw_at = 0.0
        self._eye_tracking_latest_point = None
        self._eye_tracking_latest_at = 0.0
        self._eye_tracking_stable_point = None
        self._eye_tracking_interaction_source_point = None
        self._eye_tracking_interaction_target = None
        self._eye_tracking_interaction_until = 0.0
        self._eye_tracking_last_external_target = None
        self._eye_tracking_last_external_sent_at = 0.0
        self._gaze_context_dispatch_generation = int(
            getattr(self, "_gaze_context_dispatch_generation", 0)
        ) + 1
        self._gaze_click_scan_generation = int(
            getattr(self, "_gaze_click_scan_generation", 0)
        ) + 1
        CompanionOrbController._cancel_gaze_click_validation(self)
        getattr(self, "_gaze_click_targets", {}).clear()
        getattr(self, "_gaze_click_target_payloads", {}).clear()
        getattr(self, "_gaze_click_visual_targets", []).clear()
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        self._gaze_click_target_page_open = False
        clear_highlight = getattr(self, "_clear_gaze_click_target_highlight", None)
        if callable(clear_highlight):
            clear_highlight()
        menu = getattr(self, "_gaze_radial_menu", None)
        if menu is not None and menu.isVisible():
            menu.hide()
        self._gaze_radial_menu_open = False
        self._gaze_radial_context_point = None
        self._gaze_radial_context_hwnd = 0
        self._gaze_radial_scroll_target_point = None
        self._gaze_radial_payloads.clear()
        self._set_gaze_timer_state(False, 0.0, force_external=send_external)
        if send_external:
            self._send_external_runtime({"type": "interaction_target_clear"})

    def _set_gaze_timer_state(
        self,
        active: bool,
        progress: float,
        *,
        force_external: bool = False,
    ) -> None:
        enabled = bool(active)
        value = max(0.0, min(1.0, float(progress))) if enabled else 0.0
        color = str(
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_gaze_timer_color",
                "#facc15",
            )
            or "#facc15"
        ).strip()
        self.bridge.setGazeTimerState(enabled, value, color)
        now = time.monotonic()
        transition = (
            enabled != self._eye_tracking_last_timer_active
            or color != self._eye_tracking_last_timer_color
        )
        completed = enabled and value >= 1.0 and self._eye_tracking_last_timer_progress < 1.0
        if force_external or transition or completed or now - self._eye_tracking_last_timer_sent_at >= 0.05:
            self._queue_external_gaze_timer(
                {
                    "type": "gaze_timer",
                    "active": enabled,
                    "progress": value,
                    "color": color,
                }
            )
            self._eye_tracking_last_timer_active = enabled
            self._eye_tracking_last_timer_progress = value
            self._eye_tracking_last_timer_color = color
            self._eye_tracking_last_timer_sent_at = now

    def _gaze_radial_button_dwell_ms(self) -> int:
        try:
            value = int(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_radial_button_gaze_ms",
                    650,
                )
                or 650
            )
        except (TypeError, ValueError):
            value = 650
        return max(250, min(3000, value))

    def _gaze_radial_menu_opacity(self) -> float:
        return gaze_radial_menu.normalize_radial_menu_opacity(
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_radial_menu_opacity",
                gaze_radial_menu.RADIAL_MENU_DEFAULT_OPACITY,
            )
        )

    def _gaze_radial_focus_beam_enabled(self) -> bool:
        return interaction_settings.boolish(
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_radial_focus_beam_enabled",
                True,
            ),
            default=True,
        )

    def _gaze_radial_theme(self) -> dict[str, str]:
        app = QtGui.QGuiApplication.instance()
        palette = app.palette() if app is not None else QtGui.QPalette()
        return {
            "background": palette.color(QtGui.QPalette.Window).name(),
            "surface": palette.color(QtGui.QPalette.Base).name(),
            "text": palette.color(QtGui.QPalette.Text).name(),
            "muted": palette.color(QtGui.QPalette.PlaceholderText).name(),
            "primary": str(self.bridge.primaryColor or "#38bdf8"),
            "secondary": str(self.bridge.secondaryColor or "#22d3ee"),
            "accent": str(self.bridge.accentColor or "#a78bfa"),
            "glow": str(self.bridge.glowColor or "#67e8f9"),
            "timer": str(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_gaze_timer_color",
                    "#facc15",
                )
                or "#facc15"
            ),
        }

    def _ensure_gaze_radial_menu(self) -> gaze_radial_menu.GazeRadialMenu:
        menu = self._gaze_radial_menu
        if menu is None:
            menu = gaze_radial_menu.GazeRadialMenu()
            menu.action_selected.connect(self._handle_gaze_radial_action)
            menu.cancelled.connect(self._finish_gaze_radial_menu)
            menu.candidate_changed.connect(
                self._handle_gaze_click_candidate_changed,
                QtCore.Qt.QueuedConnection,
            )
            self._gaze_radial_menu = menu
        return menu

    def _ensure_gaze_click_target_highlight_overlay(
        self,
    ) -> click_target_overlay.ClickTargetHighlightOverlay:
        overlay = self._gaze_click_target_highlight
        if overlay is None:
            overlay = click_target_overlay.ClickTargetHighlightOverlay()
            self._gaze_click_target_highlight = overlay
        return overlay

    @QtCore.Slot()
    def _clear_gaze_click_target_highlight(self) -> None:
        overlay = getattr(self, "_gaze_click_target_highlight", None)
        if overlay is not None:
            overlay.clear_target()

    def _gaze_radial_anchor_for_point(self, point) -> QtCore.QPoint:
        target = self._eye_tracking_interaction_target
        size = self._window_size()
        if target is not None:
            return QtCore.QPoint(
                int(round(target.x() + size * 0.5)),
                int(round(target.y() + size * 0.5)),
            )
        try:
            focus = (float(point[0]), float(point[1]))
        except (TypeError, ValueError, IndexError):
            return QtGui.QCursor.pos()
        offset_x, offset_y = _eye_tracking_calibration_offsets(self._last_runtime_config)
        top_left = eye_tracking.orb_top_left_for_point(
            focus,
            self._eye_tracking_screen_bounds(),
            orb_size=float(size),
            offset_px=max(64.0, min(140.0, float(size) * 0.55)),
            offset_x_px=offset_x,
            offset_y_px=offset_y,
        )
        return QtCore.QPoint(
            int(round(top_left[0] + size * 0.5)),
            int(round(top_left[1] + size * 0.5)),
        )

    def _show_gaze_radial_actions(
        self,
        actions,
        *,
        title: str,
        center_label: str,
        center_action_id: str,
        confirmation_lens: bool = False,
        enlarged_visual: bool = False,
        dwell_ms_override: int | None = None,
    ) -> None:
        menu = self._ensure_gaze_radial_menu()
        guard = getattr(self, "_sync_external_pointer_clearance_guard", None)
        if callable(guard):
            guard(True)
        dwell_ms = self._gaze_radial_button_dwell_ms()
        if dwell_ms_override is not None:
            try:
                dwell_ms = max(250, min(5000, int(dwell_ms_override)))
            except (TypeError, ValueError):
                pass
        menu.show_actions(
            tuple(actions or ()),
            anchor=self._gaze_radial_anchor,
            dwell_ms=dwell_ms,
            theme=self._gaze_radial_theme(),
            opacity=self._gaze_radial_menu_opacity(),
            focus_beam_enabled=self._gaze_radial_focus_beam_enabled(),
            title=title,
            center_label=center_label,
            center_action_id=center_action_id,
            confirmation_lens=confirmation_lens,
            enlarged_visual=enlarged_visual,
        )

    def _gaze_main_actions(self) -> tuple[gaze_radial_menu.RadialAction, ...]:
        enabled = self._gaze_click_target_enabled()
        actions: list[gaze_radial_menu.RadialAction] = []
        for action in gaze_radial_menu.MAIN_GAZE_ACTIONS:
            if action.action_id != "action":
                actions.append(action)
                continue
            actions.append(
                replace(
                    action,
                    enabled=enabled,
                    tooltip=(
                        "Find and select a control in the active Windows application or browser."
                        if enabled
                        else "Enable the Action gaze button in Eye Tracking settings."
                    ),
                )
            )
        return tuple(actions)

    def _show_gaze_radial_main_menu(self, point) -> bool:
        if self._menu_open:
            return False
        self._gaze_click_target_page_open = False
        self._gaze_click_scan_generation = int(
            getattr(self, "_gaze_click_scan_generation", 0)
        ) + 1
        getattr(self, "_gaze_click_targets", {}).clear()
        getattr(self, "_gaze_click_target_payloads", {}).clear()
        getattr(self, "_gaze_click_visual_targets", []).clear()
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        self._clear_gaze_click_target_highlight()
        if not self._gaze_radial_menu_open:
            try:
                self._gaze_radial_context_point = (float(point[0]), float(point[1]))
            except (TypeError, ValueError, IndexError):
                self._gaze_radial_context_point = self._eye_tracking_latest_point
        self._gaze_radial_anchor = self._gaze_radial_anchor_for_point(point)
        if not self._gaze_radial_menu_open:
            self._gaze_radial_scroll_target_point = (
                float(self._gaze_radial_anchor.x()),
                float(self._gaze_radial_anchor.y()),
            )
            self._gaze_radial_context_hwnd = self._window_handle_at_point(
                self._gaze_radial_scroll_target_point
            )
        self._gaze_radial_menu_open = True
        self._gaze_radial_payloads.clear()
        self._gaze_voice_page = 0
        self._return_home_timer.stop()
        self._drift_timer.stop()
        self._motion_timer.stop()
        self._show_gaze_radial_actions(
            self._gaze_main_actions(),
            title="",
            center_label="Close",
            center_action_id="__cancel__",
        )
        self._set_gaze_timer_state(False, 0.0)
        return True

    def _eye_tracking_click_target_bounds(self, point: tuple[float, float]) -> list[int]:
        screen_left, screen_top, screen_width, screen_height = self._eye_tracking_screen_bounds()
        width = int(max(420.0, min(1040.0, screen_width)))
        height = int(max(320.0, min(720.0, screen_height)))
        center_x, center_y = float(point[0]), float(point[1])
        left = max(screen_left, min(center_x - width * 0.5, screen_left + screen_width - width))
        top = max(screen_top, min(center_y - height * 0.5, screen_top + screen_height - height))
        return [int(round(left)), int(round(top)), width, height]

    @staticmethod
    def _click_target_preview(
        image_path: Path,
        target: eye_tracking.ClickTarget,
        capture_bounds: list[int],
        *,
        enlarged: bool = False,
    ) -> tuple[bytes, tuple[float, float]]:
        try:
            from PIL import Image

            capture_left, capture_top, capture_width, capture_height = (
                int(value) for value in list(capture_bounds)[:4]
            )
            if capture_width <= 0 or capture_height <= 0:
                return b"", (0.5, 0.5)
            target_left, target_top, target_width, target_height = target.bounds
            with Image.open(image_path) as source:
                image = source.convert("RGB")
                if image.width <= 0 or image.height <= 0:
                    return b"", (0.5, 0.5)
                scale_x = float(image.width) / float(capture_width)
                scale_y = float(image.height) / float(capture_height)
                center_x = (
                    float(target_left - capture_left) + float(target_width) * 0.5
                ) * scale_x
                center_y = (
                    float(target_top - capture_top) + float(target_height) * 0.5
                ) * scale_y
                crop_width = min(
                    image.width,
                    max(
                        1,
                        int(round(180.0 * scale_x)),
                        int(round((float(target_width) + 72.0) * scale_x)),
                    ),
                )
                crop_height = min(
                    image.height,
                    max(
                        1,
                        int(round(108.0 * scale_y)),
                        int(round((float(target_height) + 64.0) * scale_y)),
                    ),
                )
                crop_left = max(0, min(int(round(center_x - crop_width * 0.5)), image.width - crop_width))
                crop_top = max(0, min(int(round(center_y - crop_height * 0.5)), image.height - crop_height))
                dispatch_x, dispatch_y = target.center
                dispatch_image_x = float(dispatch_x - capture_left) * scale_x
                dispatch_image_y = float(dispatch_y - capture_top) * scale_y
                crosshair = (
                    max(0.0, min(1.0, (dispatch_image_x - crop_left) / float(crop_width))),
                    max(0.0, min(1.0, (dispatch_image_y - crop_top) / float(crop_height))),
                )
                preview = image.crop(
                    (crop_left, crop_top, crop_left + crop_width, crop_top + crop_height)
                )
                resampling = getattr(Image, "Resampling", Image)
                preview.thumbnail((360, 216) if enlarged else (240, 144), resampling.LANCZOS)
                buffer = BytesIO()
                preview.save(buffer, format="PNG", optimize=True)
                return buffer.getvalue(), crosshair
        except Exception:
            return b"", (0.5, 0.5)

    @staticmethod
    def _click_target_preview_png(
        image_path: Path,
        target: eye_tracking.ClickTarget,
        capture_bounds: list[int],
        *,
        enlarged: bool = False,
    ) -> bytes:
        preview_png, _crosshair = CompanionOrbController._click_target_preview(
            image_path,
            target,
            capture_bounds,
            enlarged=enlarged,
        )
        return preview_png

    @staticmethod
    def _click_target_capture_path(output_path: Path, output_dir: Path) -> Path | None:
        try:
            candidate = Path(output_path)
            directory = Path(output_dir)
            if candidate.parent.resolve(strict=False) != directory.resolve(strict=False):
                return None
        except Exception:
            return None
        return candidate

    @staticmethod
    def _remove_click_target_capture(output_path: Path, output_dir: Path) -> bool:
        candidate = CompanionOrbController._click_target_capture_path(output_path, output_dir)
        if candidate is None:
            return False
        for attempt in range(GAZE_CLICK_CAPTURE_UNLINK_ATTEMPTS):
            try:
                candidate.unlink(missing_ok=True)
                return True
            except Exception:
                if attempt + 1 < GAZE_CLICK_CAPTURE_UNLINK_ATTEMPTS:
                    time.sleep(GAZE_CLICK_CAPTURE_UNLINK_DELAY_SECONDS)
        return False

    @staticmethod
    def _deferred_remove_click_target_capture(output_path: Path, output_dir: Path) -> None:
        deadline = time.monotonic() + GAZE_CLICK_CAPTURE_DEFERRED_RETRY_WINDOW_SECONDS
        while time.monotonic() < deadline:
            time.sleep(GAZE_CLICK_CAPTURE_DEFERRED_RETRY_DELAY_SECONDS)
            if CompanionOrbController._remove_click_target_capture(output_path, output_dir):
                return

    @staticmethod
    def _schedule_click_target_capture_cleanup(output_path: Path, output_dir: Path) -> bool:
        if CompanionOrbController._remove_click_target_capture(output_path, output_dir):
            return True
        try:
            threading.Thread(
                target=CompanionOrbController._deferred_remove_click_target_capture,
                args=(Path(output_path), Path(output_dir)),
                daemon=True,
                name="companion-orb-click-target-cleanup",
            ).start()
        except Exception:
            pass
        return False

    @staticmethod
    def _sweep_stale_click_target_captures(output_dir: Path) -> None:
        directory = Path(output_dir)
        try:
            candidates = tuple(directory.iterdir()) if directory.is_dir() else ()
        except Exception:
            return
        for candidate in candidates:
            try:
                known_name = candidate.name.casefold().startswith("companion_orb_read_")
                known_suffix = candidate.suffix.casefold() in GAZE_CLICK_CAPTURE_SUFFIXES
                if not known_name or not known_suffix or not candidate.is_file():
                    continue
            except Exception:
                continue
            CompanionOrbController._schedule_click_target_capture_cleanup(
                candidate,
                directory,
            )

    def _serialize_click_target(
        self,
        target: eye_tracking.ClickTarget,
        output_path: Path | None,
        capture_bounds: list[int],
        *,
        enlarged: bool = False,
        capture_fingerprint: str = "",
    ) -> dict[str, object]:
        confidence = float(target.confidence)
        if not math.isfinite(confidence):
            confidence = 0.0
        preview_png = b""
        preview_crosshair = (0.5, 0.5)
        if output_path is not None:
            preview_png, preview_crosshair = self._click_target_preview(
                output_path,
                target,
                capture_bounds,
                enlarged=enlarged,
            )
        return {
            "label": str(target.label or ""),
            "bounds": [int(value) for value in target.bounds],
            "kind": str(target.kind or ""),
            "confidence": confidence,
            "role": str(target.role or ""),
            "source": str(target.source or ""),
            "backend": str(target.backend or ""),
            "capture_bounds": [int(value) for value in capture_bounds[:4]],
            "capture_fingerprint": str(capture_fingerprint or ""),
            "semantic": bool(target.semantic),
            "runtime_id": [int(value) for value in target.runtime_id],
            "click_point": [float(value) for value in target.click_point or ()],
            "preview_png": preview_png,
            "preview_crosshair": [float(value) for value in preview_crosshair],
        }

    @staticmethod
    def _click_target_from_payload(item: Any) -> eye_tracking.ClickTarget | None:
        if not isinstance(item, dict):
            return None
        try:
            bounds = tuple(int(value) for value in list(item.get("bounds") or [])[:4])
            confidence = float(item.get("confidence") or 0.0)
            runtime_id = tuple(int(value) for value in list(item.get("runtime_id") or []))
        except (TypeError, ValueError, OverflowError):
            return None
        if len(bounds) != 4 or bounds[2] <= 0 or bounds[3] <= 0:
            return None
        if not math.isfinite(confidence):
            confidence = 0.0
        return eye_tracking.ClickTarget(
            label=re.sub(r"\s+", " ", str(item.get("label") or "")).strip(),
            bounds=bounds,
            kind=str(item.get("kind") or ""),
            confidence=confidence,
            role=re.sub(r"\s+", " ", str(item.get("role") or "")).strip(),
            source=str(item.get("source") or ""),
            backend=str(item.get("backend") or ""),
            semantic=interaction_settings.boolish(item.get("semantic"), default=False),
            runtime_id=runtime_id,
            click_point=item.get("click_point"),
        )

    @staticmethod
    def _click_target_capture_fingerprint(output_path: Path | None) -> str:
        if output_path is None:
            return ""
        try:
            return hashlib.sha256(Path(output_path).read_bytes()).hexdigest()
        except Exception:
            return ""

    @staticmethod
    def _click_target_payload_preview(item: Any) -> bytes:
        if not isinstance(item, dict):
            return b""
        value = item.get("preview_png")
        return bytes(value) if isinstance(value, (bytes, bytearray)) else b""

    @staticmethod
    def _click_target_payload_crosshair(item: Any) -> tuple[float, float]:
        if not isinstance(item, dict):
            return 0.5, 0.5
        value = item.get("preview_crosshair")
        if not isinstance(value, (list, tuple)):
            return 0.5, 0.5
        try:
            values = tuple(value)
            if len(values) != 2:
                return 0.5, 0.5
            crosshair = float(values[0]), float(values[1])
        except (TypeError, ValueError, OverflowError):
            return 0.5, 0.5
        if not all(math.isfinite(coordinate) for coordinate in crosshair):
            return 0.5, 0.5
        return (
            max(0.0, min(1.0, crosshair[0])),
            max(0.0, min(1.0, crosshair[1])),
        )

    def _show_gaze_click_target_menu(self) -> None:
        if not self._gaze_click_target_enabled():
            return
        self._clear_gaze_click_target_highlight()
        self._gaze_click_target_page_open = True
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        fallback = self._gaze_radial_context_point or self._eye_tracking_latest_point or (
            float(self._gaze_radial_anchor.x()),
            float(self._gaze_radial_anchor.y()),
        )
        focus_point = self._blink_click_point(fallback)
        capture_bounds = self._eye_tracking_click_target_bounds(focus_point)
        self._gaze_click_scan_generation = int(
            getattr(self, "_gaze_click_scan_generation", 0)
        ) + 1
        CompanionOrbController._cancel_gaze_click_validation(self)
        generation = self._gaze_click_scan_generation
        self._gaze_click_targets.clear()
        self._gaze_click_target_payloads.clear()
        self._gaze_click_visual_targets.clear()
        self._show_gaze_radial_actions(
            (
                gaze_radial_menu.RadialAction(
                    "click_target_scanning",
                    "Scanning",
                    enabled=False,
                ),
            ),
            title="Click target",
            center_label="Back",
            center_action_id="back",
        )
        QtCore.QTimer.singleShot(
            80,
            lambda: self._begin_gaze_click_target_scan(
                capture_bounds,
                focus_point,
                generation,
            ),
        )

    def _begin_gaze_click_target_scan(
        self,
        capture_bounds: list[int],
        focus_point: tuple[float, float],
        generation: int,
    ) -> None:
        if (
            int(generation) != int(getattr(self, "_gaze_click_scan_generation", 0))
            or not self._gaze_radial_menu_open
            or not self._gaze_click_target_enabled()
        ):
            return
        self._clear_gaze_click_target_highlight()
        menu = getattr(self, "_gaze_radial_menu", None)
        if menu is not None:
            menu.hide()
        self._set_gaze_timer_state(False, 0.0)
        virtual_rect = self._virtual_desktop_rect()
        virtual_bounds = (
            [
                int(virtual_rect.x()),
                int(virtual_rect.y()),
                int(virtual_rect.width()),
                int(virtual_rect.height()),
            ]
            if virtual_rect is not None and not virtual_rect.isEmpty()
            else list(capture_bounds)
        )
        threading.Thread(
            target=self._scan_gaze_click_targets,
            args=(
                list(capture_bounds),
                tuple(focus_point),
                int(generation),
                virtual_bounds,
            ),
            daemon=True,
            name="companion-orb-click-target-scan",
        ).start()

    @staticmethod
    def _run_bounded_daemon_stage(
        stage,
        *,
        timeout_seconds: float,
        name: str,
        late_result_handler=None,
    ) -> tuple[bool, Any]:
        results: queue.Queue[Any] = queue.Queue(maxsize=1)
        cancellation = threading.Event()
        delivery_lock = threading.Lock()
        delivery_state = {"accepting": True}

        def handle_late(value: Any) -> None:
            if not callable(late_result_handler):
                return
            try:
                late_result_handler(value)
            except Exception:
                pass

        def run_stage() -> None:
            try:
                value = stage(cancellation)
            except Exception:
                value = {"limited": True}
            delivered = False
            with delivery_lock:
                if delivery_state["accepting"]:
                    try:
                        results.put_nowait(value)
                        delivered = True
                    except queue.Full:
                        pass
            if not delivered:
                handle_late(value)

        try:
            threading.Thread(
                target=run_stage,
                daemon=True,
                name=str(name or "companion-orb-bounded-stage"),
            ).start()
        except Exception:
            cancellation.set()
            return False, None

        try:
            return True, results.get(timeout=max(0.01, float(timeout_seconds)))
        except queue.Empty:
            late_value: Any = None
            has_late_value = False
            with delivery_lock:
                delivery_state["accepting"] = False
                cancellation.set()
                try:
                    late_value = results.get_nowait()
                    has_late_value = True
                except queue.Empty:
                    pass
            if has_late_value:
                handle_late(late_value)
            return False, None

    def _visual_guidance_enabled(self, scope: str) -> bool:
        normalized_scope = str(scope or "").strip().lower()
        scope_keys = {
            "gaze": "companion_orb_visual_guidance_gaze_enabled",
            "drop": "companion_orb_visual_guidance_drop_enabled",
            "reading": "companion_orb_visual_guidance_reading_enabled",
        }
        scope_key = scope_keys.get(normalized_scope)
        return bool(
            scope_key
            and self._last_runtime_config.get(
                "companion_orb_vision_enabled",
                False,
            )
            and self._last_runtime_config.get(
                "companion_orb_visual_guidance_enabled",
                False,
            )
            and self._last_runtime_config.get(scope_key, True)
        )

    def _visual_guidance_request_settings(self) -> dict[str, object]:
        if not vision_guidance.auxiliary_vision_enabled(self._last_runtime_config):
            return {}
        provider_id = str(
            self._last_runtime_config.get(
                "companion_orb_vision_provider_id",
                "lmstudio",
            )
            or ""
        ).strip()
        model_id = str(
            self._last_runtime_config.get("companion_orb_vision_model_id", "")
            or ""
        ).strip()
        if not provider_id or not model_id:
            return {}
        location = vision_guidance.normalize_runtime_location(
            self._last_runtime_config.get(
                "companion_orb_vision_runtime_location",
                "primary",
            )
        )
        base_url = ""
        if location in {"separate_local", "lan"}:
            try:
                base_url = vision_guidance.normalize_lmstudio_base_url(
                    self._last_runtime_config.get(
                        "companion_orb_vision_base_url",
                        "",
                    ),
                    required=True,
                )
            except ValueError:
                return {}
        try:
            configured_timeout = float(
                self._last_runtime_config.get(
                    "companion_orb_vision_timeout_seconds",
                    15.0,
                )
                or 15.0
            )
            if configured_timeout == 3.0:
                configured_timeout = 15.0
            timeout_seconds = max(0.01, min(60.0, configured_timeout))
        except (TypeError, ValueError):
            timeout_seconds = 15.0
        parallel = vision_guidance.primary_parallel_enabled(
            self._last_runtime_config
        )
        configured_handling = vision_guidance.normalize_model_handling(
            self._last_runtime_config.get(
                "companion_orb_vision_model_handling",
                "auto_load",
            )
        )
        model_handling = (
            "already_loaded"
            if configured_handling == "already_loaded"
            else vision_guidance.PRIMARY_PARALLEL_MODEL_HANDLING
        )
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "base_url": base_url,
            "model_handling": model_handling,
            "restore_main_model": bool(
                not parallel
                and location == "primary"
                and self._last_runtime_config.get(
                    "companion_orb_vision_restore_main_model",
                    False,
                )
            ),
            "timeout_seconds": timeout_seconds,
            "capability_mode": vision_guidance.normalize_vision_capability_mode(
                self._last_runtime_config.get(
                    "companion_orb_vision_capability_mode",
                    "auto",
                )
            ),
        }

    def _sync_spatial_scan_timer(self) -> None:
        timer = getattr(self, "_spatial_scan_timer", None)
        if not isinstance(timer, QtCore.QTimer):
            return
        settings = spatial_scanning.SpatialScanSettings.from_mapping(
            self._last_runtime_config
        )
        should_run = bool(
            settings.enabled
            and CompanionOrbController._vision_regions_supported(self)
            and settings.mode in {"smart_cached", "continuous"}
            and not getattr(self, "_spatial_scan_shutdown", False)
        )
        if not should_run:
            timer.stop()
            return
        interval_ms = max(2000, int(round(settings.interval_seconds * 1000.0)))
        timer.setInterval(interval_ms)
        if not timer.isActive():
            timer.start()

    def spatial_map_snapshot(self):
        if not CompanionOrbController._vision_regions_supported(self):
            return None
        store = getattr(self, "_desktop_spatial_map", None)
        if not isinstance(store, desktop_spatial_map.DesktopSpatialMapStore):
            return None
        return store.current(allow_stale=True)

    def spatial_diagnostics_snapshot(self) -> dict[str, object]:
        status = dict(getattr(self, "_spatial_scan_status", {}) or {})
        snapshot = self.spatial_map_snapshot()
        if snapshot is not None:
            normalized_regions = [
                {
                    "region_id": region.region_id,
                    "label": region.label,
                    "kind": region.kind,
                    "screen_bounds": list(region.screen_bounds),
                    "confidence": region.confidence,
                    "action_hint": region.action_hint,
                    "ocr_text": region.ocr_text,
                    "source": region.source,
                    "backend": region.backend,
                }
                for region in snapshot.regions
            ]
            status.update(
                {
                    "map_generation": snapshot.generation,
                    "map_age_seconds": snapshot.age(),
                    "region_count": len(snapshot.regions),
                    "capture_bounds": list(
                        status.get("capture_bounds") or snapshot.capture_bounds
                    ),
                    "capture_path": snapshot.capture_path,
                    "image_path": str(
                        status.get("image_path") or snapshot.capture_path
                    ),
                    "model_id": str(status.get("model_id") or snapshot.model_id),
                    "endpoint": str(status.get("endpoint") or snapshot.endpoint),
                    "scene_summary": snapshot.scene_summary,
                    "normalized_regions": normalized_regions,
                }
            )
        return status

    @staticmethod
    def _spatial_command_response(
        *,
        ok: bool,
        response_text: str,
        **fields: object,
    ) -> dict[str, object]:
        return {
            "ok": bool(ok),
            "handled": True,
            "response_text": str(response_text or "").strip(),
            "use_llm_response": False,
            **fields,
        }

    def observe_conversation_screen(self, question: str, *, direct_image: bool = False) -> dict[str, object]:
        """Collect current evidence; the main model owns the conversational answer."""
        return self.answer_visual_question(question, _capability_mode="conversation", _direct_image=direct_image)

    def answer_visual_question(self, question: str, *, _capability_mode="question", _direct_image=False) -> dict[str, object]:
        """Answer an explicit screen question from a fresh native-pixel Orb capture."""
        direct_image = _direct_image is True and _capability_mode == "conversation"
        settings = {} if direct_image else CompanionOrbController._visual_guidance_request_settings(self)
        if not settings and not direct_image:
            return self._spatial_command_response(
                ok=False,
                response_text="Companion Orb auxiliary vision is not configured, so I cannot inspect the screen.",
            )
        lock = getattr(self, "_snapshot_capture_lock", None)
        if lock is None or not lock.acquire(blocking=False):
            return self._spatial_command_response(
                ok=False,
                response_text="The Orb screen capture is busy. Please try again in a moment.",
            )
        try:
            from PIL import ImageGrab

            bounds, _topology = self._spatial_capture_bounds()
            image = self._grab_desktop_without_orb(ImageGrab)
            image, _crop = self._crop_desktop_image_to_bounds(
                image, bounds, self._virtual_desktop_rect()
            )
            output_root = Path(self.context.app_root) / "runtime" / "companion_orb" / "questions"
            output_root.mkdir(parents=True, exist_ok=True)
            captured_at = time.time()
            image_path = output_root / f"orb_question_{time.time_ns()}.jpg"
            image.save(image_path, format="JPEG", quality=100, optimize=True)
        except Exception as exc:
            self._log(f"[Companion Orb] Visual question capture failed: {exc}")
            return self._spatial_command_response(
                ok=False, response_text="I could not capture the screen for that question."
            )
        finally:
            lock.release()
        ocr_regions = []
        if _capability_mode == "conversation":
            try:
                ocr = snapshot_ocr.extract_snapshot_regions(
                    image_path, screen_bounds=bounds, max_regions=600,
                    page_segmentation_mode=11, include_window_text=False,
                )
                for region in ocr.get("regions", []):
                    text = str(region.get("text") or "").strip()
                    if region.get("kind") == "line" and len(text) > 2 and float(region.get("confidence") or 0) >= 60:
                        ocr_regions.append({"text": text[:300], "bounds": region.get("screen_bounds", [])})
                    if len(ocr_regions) >= 180:
                        break
            except Exception as exc:
                self._log(f"[Companion Orb] Conversation OCR unavailable: {exc}")
        excluded_nc = bool(self._last_runtime_config.get('companion_orb_exclude_nc_from_captures', False))
        # Keep provenance for unobscured external windows, but never attribute
        # pixels revealed behind NC to its excluded window.
        capture_target = (lambda x,y: resolve_target_at(x,y,exclude_current_process=True)) if excluded_nc else resolve_target_at
        windows = group_screen_text(ocr_regions, capture_target)
        controls = []
        if _capability_mode == "conversation":
            registry = getattr(self, "_conversation_controls", None)
            if registry is None:
                registry = self._conversation_controls = ConversationControls()
            try:
                if excluded_nc:
                    controls = registry.replace((), resolve_target_at)
                else:
                    native = discover_conversation_controls(bounds, windows)
                    controls = registry.replace(native.targets, resolve_target_at)
            except Exception as exc:
                registry.replace((), resolve_target_at)
                self._log(f"[Companion Orb] Conversation controls unavailable: {exc}")
        try:
            if direct_image:
                image_bytes = image_path.read_bytes()
                image_data = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
                import hashlib
                capture = dict(id=image_path.stem, captured_at=captured_at, width=image.width, height=image.height,
                    sha256=hashlib.sha256(image_bytes).hexdigest(), screen_bounds=list(bounds))
                return self._spatial_command_response(
                    ok=True, response_text="Current native screenshot is attached to this question.",
                    ocr_regions=ocr_regions, screen_bounds=bounds, windows=windows,
                    controls=controls, current_turn_image=image_data,
                    capture=capture,
                )
            ensure_model = getattr(self.orb_runtime, "ensure_vision_model", None)
            if callable(ensure_model):
                readiness = ensure_model(
                    provider_id=str(settings["provider_id"]),
                    model_id=str(settings["model_id"]),
                    base_url=str(settings["base_url"]),
                    model_handling=str(settings["model_handling"]),
                )
                if isinstance(readiness, Mapping) and not readiness.get("ready"):
                    raise RuntimeError("Auxiliary vision model is unavailable.")
            observed = self.orb_runtime.observe_visual(
                image_path=str(image_path),
                provider_id=str(settings["provider_id"]),
                model_id=str(settings["model_id"]),
                base_url=str(settings["base_url"]),
                model_handling=str(settings["model_handling"]),
                capture_bounds=bounds,
                reaction_scope="conversation",
                capability_mode=_capability_mode,
                question_text=str(question or "")[:6000 if _capability_mode == "conversation" else 500],
                timeout_seconds=float(settings["timeout_seconds"]),
            )
            answer = str((observed or {}).get(
                "evidence_text" if _capability_mode == "conversation" else "answer_text"
            ) or "").strip()
            if not answer:
                raise RuntimeError("Auxiliary vision returned no answer.")
            return self._spatial_command_response(
                ok=True, response_text=answer, ocr_regions=ocr_regions, screen_bounds=bounds, windows=windows,
                controls=controls,
            )
        except Exception as exc:
            self._log(f"[Companion Orb] Visual question failed: {exc}")
            return self._spatial_command_response(
                ok=bool(ocr_regions or controls),
                response_text="I could not read the current screen with the auxiliary vision model.",
                ocr_regions=ocr_regions, screen_bounds=bounds, windows=windows,
                controls=controls,
            )
        finally:
            try:
                image_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _spatial_command_focus_payload(
        self,
        region: desktop_spatial_map.SpatialRegion,
    ) -> dict[str, object]:
        config = getattr(self, "_last_runtime_config", {})
        try:
            hover_offset = max(
                0.0,
                min(
                    300.0,
                    float(config.get("companion_orb_spatial_hover_offset_px", 28) or 0),
                ),
            )
        except (TypeError, ValueError, OverflowError):
            hover_offset = 28.0
        return {
            "focus_bounds": list(region.screen_bounds),
            "focus_label": region.label,
            "focus_text": region.label,
            "duration_seconds": 14.0,
            "hover_offset_px": hover_offset,
            "stay_during_speech": bool(
                config.get("companion_orb_spatial_stay_during_speech", True)
            ),
            "return_behavior": str(
                config.get("companion_orb_spatial_return_behavior", "after_speech")
                or "after_speech"
            ),
        }

    def _clear_spatial_follow_target(self) -> None:
        self._followed_spatial_region_id = ""
        self._followed_spatial_target_text = ""
        self._followed_spatial_action = ""
        self._followed_spatial_is_current = None

    def _remember_spatial_follow_target(
        self,
        command: spatial_commands.SpatialCommand,
        region: desktop_spatial_map.SpatialRegion,
    ) -> None:
        if not bool(
            self._last_runtime_config.get(
                "companion_orb_spatial_follow_target_enabled",
                False,
            )
        ):
            self._clear_spatial_follow_target()
            return
        self._followed_spatial_region_id = region.region_id
        self._followed_spatial_target_text = command.target_text
        self._followed_spatial_action = command.action
        guarded = getattr(self, "_conversation_focus_guard", None)
        self._followed_spatial_is_current = (
            guarded[1] if guarded and guarded[0] is command else None
        )

    def _update_followed_spatial_target(self) -> None:
        is_current = getattr(self, "_followed_spatial_is_current", None)
        if callable(is_current) and not is_current():
            self._clear_spatial_follow_target()
            return
        target_text = str(
            getattr(self, "_followed_spatial_target_text", "") or ""
        ).strip()
        if not target_text or not bool(
            self._last_runtime_config.get(
                "companion_orb_spatial_follow_target_enabled",
                False,
            )
        ):
            return
        snapshot = self.spatial_map_snapshot()
        resolution = desktop_spatial_map.resolve_target(
            snapshot,
            target_text=target_text,
            min_confidence=float(
                self._last_runtime_config.get(
                    "companion_orb_eye_tracking_bounding_box_min_confidence",
                    0.55,
                )
                or 0.55
            ),
        )
        region = resolution.region
        if region is None:
            self._clear_spatial_follow_target()
            return
        previous = self._normalize_bounds(getattr(self, "_comment_focus_bounds", []))
        current = list(region.screen_bounds)
        moved = not previous or max(
            abs(left - right) for left, right in zip(previous, current)
        ) > 8
        self._followed_spatial_region_id = region.region_id
        if moved:
            payload = self._spatial_command_focus_payload(region)
            if callable(is_current):
                payload['_is_current'] = is_current
            self.request_comment_focus(payload)

    def execute_spatial_command(
        self,
        command: spatial_commands.SpatialCommand,
        *,
        _allow_targeted_retry: bool = True,
    ) -> dict[str, object]:
        guarded=getattr(self, '_conversation_focus_guard', None)
        is_current=guarded[1] if guarded and guarded[0] is command else None
        if callable(is_current) and not is_current():
            return self._spatial_command_response(ok=False,reason='obsolete_turn',
                response_text='The hover request is no longer current.')
        if not isinstance(command, spatial_commands.SpatialCommand):
            return self._spatial_command_response(
                ok=False,
                response_text="That Companion Orb desktop command is invalid.",
            )
        config = getattr(self, "_last_runtime_config", {})
        if not bool(config.get("companion_orb_vision_enabled", False)):
            return self._spatial_command_response(
                ok=False,
                response_text="Enable Companion Orb vision to use desktop targets.",
            )
        if not bool(config.get("companion_orb_spatial_explicit_commands_enabled", True)):
            return self._spatial_command_response(
                ok=False,
                response_text="Companion Orb desktop commands are disabled.",
            )
        try:
            max_age = max(
                1.0,
                float(config.get("companion_orb_spatial_map_max_age_seconds", 20.0) or 20.0),
            )
        except (TypeError, ValueError, OverflowError):
            max_age = 20.0
        store = getattr(self, "_desktop_spatial_map", None)
        snapshot = (
            store.current(max_age_seconds=max_age)
            if isinstance(store, desktop_spatial_map.DesktopSpatialMapStore)
            else None
        )
        if snapshot is None:
            if not _allow_targeted_retry:
                return self._spatial_command_response(
                    ok=False,
                    response_text=f"I could not confidently find {command.target_text} on the desktop.",
                    reason="missing_map",
                )
            self._pending_spatial_command = command
            scan = self.request_spatial_scan("action", force=True)
            return self._spatial_command_response(
                ok=bool(scan.get("queued") or scan.get("coalesced")),
                response_text=f"I am refreshing the desktop map to find {command.target_text}.",
                queued=True,
                scan=scan,
            )
        try:
            min_confidence = max(
                0.0,
                min(
                    1.0,
                    float(
                        config.get(
                            "companion_orb_eye_tracking_bounding_box_min_confidence",
                            0.55,
                        )
                        or 0.55
                    ),
                ),
            )
        except (TypeError, ValueError, OverflowError):
            min_confidence = 0.55
        resolution = desktop_spatial_map.resolve_target(
            snapshot,
            target_text=command.target_text,
            min_confidence=min_confidence,
        )
        if resolution.region is None:
            if _allow_targeted_retry and not resolution.ambiguous:
                self._pending_spatial_command = command
                scan = self.request_spatial_scan("action", force=True)
                if bool(scan.get("queued") or scan.get("coalesced")):
                    return self._spatial_command_response(
                        ok=True,
                        response_text=f"I am refreshing the desktop map to find {command.target_text}.",
                        queued=True,
                        scan=scan,
                    )
            self._pending_spatial_command = None
            if resolution.ambiguous:
                message = (
                    f"I found more than one possible match for {command.target_text}. "
                    "Please name it more specifically."
                )
            else:
                message = f"I could not confidently find {command.target_text} on the desktop."
            return self._spatial_command_response(
                ok=False,
                response_text=message,
                ambiguous=resolution.ambiguous,
                reason=resolution.reason,
            )
        region = resolution.region
        self._pending_spatial_command = None
        self._remember_spatial_follow_target(command, region)
        focus_payload=self._spatial_command_focus_payload(region)
        if callable(is_current):
            focus_payload['_is_current']=is_current
        self.request_comment_focus(focus_payload)
        if command.action in {"look", "move", "hover"}:
            return self._spatial_command_response(
                ok=True,
                response_text=f"I have requested movement beside {region.label}.",
                queued=True,
                moved=False,
                region_id=region.region_id,
            )
        result = self._dispatch_spatial_region_action(
            f"spatial:{command.action}",
            region,
        )
        action_phrase = {
            "react": "reacting to",
            "read": "reading",
            "describe": "describing",
            "explain": "explaining",
            "summarize": "summarizing",
        }.get(command.action, "checking")
        return self._spatial_command_response(
            ok=bool(result.get("ok")),
            response_text=(
                f"I am {action_phrase} {region.label}."
                if bool(result.get("ok"))
                else str(result.get("error") or "That desktop action could not be started.")
            ),
            region_id=region.region_id,
            result=result,
        )

    def collect_spatial_chat_context(self, _history=()) -> dict[str, object] | None:
        config = getattr(self, "_last_runtime_config", {})
        if not bool(config.get("companion_orb_enabled", False)) or not bool(
            config.get("companion_orb_vision_enabled", False)
        ) or not bool(
            config.get("companion_orb_spatial_conversational_focus_enabled", True)
        ):
            return None
        try:
            max_age = max(
                1.0,
                float(config.get("companion_orb_spatial_map_max_age_seconds", 20.0) or 20.0),
            )
            min_confidence = max(
                0.0,
                min(
                    1.0,
                    float(
                        config.get(
                            "companion_orb_spatial_conversational_min_confidence",
                            0.72,
                        )
                        or 0.72
                    ),
                ),
            )
        except (TypeError, ValueError, OverflowError):
            max_age = 20.0
            min_confidence = 0.72
        store = getattr(self, "_desktop_spatial_map", None)
        snapshot = (
            store.current(max_age_seconds=max_age)
            if isinstance(store, desktop_spatial_map.DesktopSpatialMapStore)
            else None
        )
        if snapshot is None:
            return None
        eligible = tuple(
            region
            for region in snapshot.regions
            if region.confidence >= min_confidence
        )
        if not eligible:
            return None
        context_snapshot = replace(snapshot, regions=eligible)
        compact = desktop_spatial_map.compact_scene_context(
            context_snapshot,
            max_regions=16,
            max_chars=1800,
        )
        if not compact:
            return None
        return {
            "context": (
                "Companion Orb visible desktop regions:\n"
                f"{compact}\n"
                "If and only if your reply deliberately refers to one listed visible item "
                "and the Orb should point to it, append exactly one terminal directive: "
                '[[companion_orb_focus {"region_id":"<listed id>","target":"<short label>","action":"hover"}]]. '
                "Never invent an ID or coordinates. Omit the directive otherwise."
            ),
            "debug": {
                "sources": ["companion_orb_spatial_map"],
                "generation": snapshot.generation,
            },
        }

    def handle_assistant_focus(
        self,
        payload: Mapping[str, object],
        *,
        is_current=None,
    ) -> dict[str, object]:
        if callable(is_current) and not is_current():
            return {"ok": False, "handled": True, "reason": "obsolete_turn"}
        config = getattr(self, "_last_runtime_config", {})
        if not bool(config.get("companion_orb_vision_enabled", False)) or not bool(
            config.get("companion_orb_spatial_conversational_focus_enabled", True)
        ):
            return {"ok": False, "handled": True, "reason": "disabled"}
        data = dict(payload or {}) if isinstance(payload, Mapping) else {}
        if set(data) != {"region_id", "target", "action"}:
            return {"ok": False, "handled": True, "reason": "invalid_directive"}
        region_id = str(data.get("region_id") or "").strip()
        target_text = " ".join(str(data.get("target") or "").split())[:160]
        action = str(data.get("action") or "").strip().lower()
        if not region_id or not target_text or action not in {"hover", "look", "move"}:
            return {"ok": False, "handled": True, "reason": "invalid_directive"}
        if region_id.startswith("uia-"):
            registry = getattr(self, "_conversation_controls", None)
            native = registry.resolve(
                region_id, target_text,
                lambda target, point: windows_ui_automation.validate_semantic_target(target, point, allow_ancestors=True),
            ) if isinstance(registry, ConversationControls) else None
            if native is None:
                return {"ok": False, "handled": True, "reason": "native_control_changed"}
            region = desktop_spatial_map.SpatialRegion(
                region_id, target_text, "control", native.bounds, 1.0,
                source="ui_automation", backend="ui_automation",
            )
            self.request_comment_focus(self._spatial_command_focus_payload(region))
            return {"ok": True, "handled": True, "queued": True, "region_id": region_id}
        if region_id == "locate":
            # Normal Chat resolves conversational references to a name, never pixels.
            # The existing targeted scanner must confirm that name before movement.
            if not config.get("companion_orb_spatial_explicit_commands_enabled", True):
                return {"ok": False, "handled": True, "reason": "disabled"}
            self._pending_spatial_command = spatial_commands.SpatialCommand(action, target_text)
            self._conversation_focus_guard=(self._pending_spatial_command,is_current) if callable(is_current) else None
            scan = self.request_spatial_scan("action", force=True)
            queued = bool(scan.get("queued") or scan.get("coalesced"))
            if not queued:
                self._pending_spatial_command = None
            return {"ok": queued, "handled": True, "queued": queued, "scan": scan}
        try:
            max_age = max(
                1.0,
                float(config.get("companion_orb_spatial_map_max_age_seconds", 20.0) or 20.0),
            )
            min_confidence = max(
                0.0,
                min(
                    1.0,
                    float(
                        config.get(
                            "companion_orb_spatial_conversational_min_confidence",
                            0.72,
                        )
                        or 0.72
                    ),
                ),
            )
            cooldown = max(
                0.0,
                float(
                    config.get(
                        "companion_orb_spatial_movement_cooldown_seconds",
                        8.0,
                    )
                    or 0.0
                ),
            )
        except (TypeError, ValueError, OverflowError):
            max_age = 20.0
            min_confidence = 0.72
            cooldown = 8.0
        now = time.monotonic()
        if now - float(
            getattr(self, "_last_spatial_conversational_move_at", 0.0) or 0.0
        ) < cooldown:
            return {"ok": False, "handled": True, "reason": "cooldown"}
        store = getattr(self, "_desktop_spatial_map", None)
        snapshot = (
            store.current(max_age_seconds=max_age)
            if isinstance(store, desktop_spatial_map.DesktopSpatialMapStore)
            else None
        )
        if snapshot is None:
            return {"ok": False, "handled": True, "reason": "stale_map"}
        id_match = desktop_spatial_map.resolve_target(
            snapshot,
            region_id=region_id,
            min_confidence=min_confidence,
        )
        region = id_match.region
        if region is None:
            return {"ok": False, "handled": True, "reason": id_match.reason}
        target_match = desktop_spatial_map.resolve_target(
            replace(snapshot, regions=(region,)),
            target_text=target_text,
            min_confidence=min_confidence,
        )
        if target_match.region is None:
            return {
                "ok": False,
                "handled": True,
                "reason": "target_mismatch",
            }
        self._last_spatial_conversational_move_at = now
        command = spatial_commands.SpatialCommand(action, target_text)
        self._remember_spatial_follow_target(command, region)
        self.request_comment_focus(self._spatial_command_focus_payload(region))
        return {
            "ok": True,
            "handled": True,
            "queued": True,
            "moved": False,
            "region_id": region.region_id,
        }

    def request_spatial_scan(
        self,
        reason: str,
        *,
        force: bool = False,
    ) -> dict[str, object]:
        if bool(getattr(self, "_spatial_scan_shutdown", False)):
            return {"queued": False, "coalesced": False, "reason": "shutdown"}
        settings = spatial_scanning.SpatialScanSettings.from_mapping(
            getattr(self, "_last_runtime_config", {})
        )
        store = getattr(self, "_desktop_spatial_map", None)
        snapshot = (
            store.current(allow_stale=True)
            if isinstance(store, desktop_spatial_map.DesktopSpatialMapStore)
            else None
        )
        now = time.monotonic()
        map_age = snapshot.age(now=now) if snapshot is not None else None
        coordinator = getattr(self, "_spatial_scan_coordinator", None)
        if not isinstance(coordinator, spatial_scanning.SpatialScanCoordinator):
            return {"queued": False, "coalesced": False, "reason": "unavailable"}
        requested_reason = str(reason or "manual")
        if force and requested_reason not in {"action", "diagnostic", "manual"}:
            requested_reason = "manual"
        request = coordinator.request(
            reason=requested_reason,
            now=now,
            settings=settings,
            map_age=map_age,
            change_score=None,
        )
        if request is None:
            return {
                "queued": False,
                "coalesced": bool(coordinator.coalesced),
                "reason": str(reason or "manual"),
            }
        self._start_spatial_scan(request)
        return {
            "queued": True,
            "coalesced": False,
            "reason": request.reason,
            "generation": request.generation,
        }

    def _start_spatial_scan(
        self,
        request: spatial_scanning.SpatialScanRequest,
    ) -> None:
        pending = getattr(self, "_pending_spatial_command", None)
        action_target = (
            str(pending.target_text or "")
            if request.reason == "action" and isinstance(pending, spatial_commands.SpatialCommand)
            else ""
        )
        self._spatial_scan_status = {
            "state": "queued",
            "generation": request.generation,
            "reason": request.reason,
            "action_target": action_target,
            "queued_at": time.time(),
            "started_monotonic": time.monotonic(),
        }
        if request.reason == "diagnostic":
            CompanionOrbController._log_spatial_diagnostic(
                f"queued generation={request.generation}"
            )
        try:
            threading.Thread(
                target=self._run_spatial_scan_worker,
                args=(request,),
                daemon=True,
                name=f"companion-orb-spatial-scan-{request.generation}",
            ).start()
        except Exception as exc:
            self._emit_spatial_scan_result(
                {
                    "generation": request.generation,
                    "ok": False,
                    "error": str(exc),
                }
            )

    @staticmethod
    def _spatial_fingerprint_change_score(previous: str, current: str) -> float:
        old = str(previous or "").strip().lower()
        new = str(current or "").strip().lower()
        if not old or not new or len(old) != len(new):
            return 1.0
        try:
            different = sum(
                (int(left, 16) ^ int(right, 16)).bit_count()
                for left, right in zip(old, new)
            )
        except ValueError:
            return 1.0
        return different / max(1, len(old) * 4)

    def _spatial_region_allowed(self, kind: object) -> bool:
        normalized = str(kind or "object").strip().lower()
        settings = getattr(self, "_last_runtime_config", {})
        if normalized == "image":
            key = "companion_orb_spatial_include_images"
        elif normalized == "text":
            key = "companion_orb_spatial_include_text"
        elif normalized in {"button", "link", "field", "control", "icon"}:
            key = "companion_orb_spatial_include_controls"
        elif normalized in {"window", "panel"}:
            key = "companion_orb_spatial_include_windows"
        elif normalized == "media":
            key = "companion_orb_spatial_include_media"
        else:
            key = "companion_orb_spatial_include_other_objects"
        return bool(settings.get(key, True))

    @staticmethod
    def _clip_spatial_bounds(
        bounds: list[int],
        virtual_bounds: list[int],
    ) -> list[int]:
        if len(bounds) != 4 or len(virtual_bounds) != 4:
            return []
        left, top, width, height = (int(value) for value in bounds)
        v_left, v_top, v_width, v_height = (
            int(value) for value in virtual_bounds
        )
        right = min(left + width, v_left + v_width)
        bottom = min(top + height, v_top + v_height)
        left = max(left, v_left)
        top = max(top, v_top)
        return [left, top, right - left, bottom - top] if right > left and bottom > top else []

    @staticmethod
    def _foreground_window_bounds() -> list[int]:
        if not sys_platform_windows():
            return []
        try:
            user32 = ctypes.windll.user32
            hwnd = int(user32.GetForegroundWindow() or 0)
            rect = wintypes.RECT()
            if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return []
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            return [int(rect.left), int(rect.top), width, height] if width > 0 and height > 0 else []
        except Exception:
            return []

    def _spatial_capture_bounds(self) -> tuple[list[int], str]:
        virtual_rect = self._virtual_desktop_rect()
        if virtual_rect is None or virtual_rect.isEmpty():
            return [], ""
        virtual_bounds = [
            int(virtual_rect.x()),
            int(virtual_rect.y()),
            int(virtual_rect.width()),
            int(virtual_rect.height()),
        ]
        scope = str(
            self._last_runtime_config.get(
                "companion_orb_spatial_capture_scope",
                "active_monitor",
            )
            or "active_monitor"
        ).strip().lower()
        if scope == "off":
            return [], "background_capture_disabled"
        bounds = list(virtual_bounds)
        if scope == "selected_monitor":
            bounds = self._configured_screen_source_bounds() or bounds
        elif scope == "active_window":
            bounds = CompanionOrbController._foreground_window_bounds() or bounds
        elif scope == "active_monitor":
            foreground = CompanionOrbController._foreground_window_bounds()
            point = (
                QtCore.QPoint(
                    foreground[0] + foreground[2] // 2,
                    foreground[1] + foreground[3] // 2,
                )
                if foreground
                else QtGui.QCursor.pos()
            )
            screen = (
                QtGui.QGuiApplication.screenAt(point)
                or QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
                or QtGui.QGuiApplication.primaryScreen()
            )
            if screen is not None:
                geometry = screen.geometry()
                bounds = [
                    int(geometry.x()),
                    int(geometry.y()),
                    int(geometry.width()),
                    int(geometry.height()),
                ]
        clipped = CompanionOrbController._clip_spatial_bounds(bounds, virtual_bounds)
        topology = "|".join(
            f"{screen.geometry().x()},{screen.geometry().y()},"
            f"{screen.geometry().width()},{screen.geometry().height()}"
            for screen in list(QtGui.QGuiApplication.screens() or [])
        )
        return clipped or virtual_bounds, topology or ",".join(map(str, virtual_bounds))

    def _capture_spatial_map_image(self, generation: int) -> dict[str, object]:
        from PIL import ImageGrab

        capture_bounds, topology_signature = self._spatial_capture_bounds()
        if len(capture_bounds) != 4:
            raise RuntimeError("No desktop capture bounds are available.")
        image = self._grab_desktop_without_orb(ImageGrab)
        virtual_rect = self._virtual_desktop_rect()
        image, _crop = self._crop_desktop_image_to_bounds(
            image,
            capture_bounds,
            virtual_rect,
        )
        fingerprint = _sensory_visual_fingerprint(image)
        app_root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        output_root = app_root / "runtime" / "companion_orb" / "spatial_map"
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / "companion_orb_spatial_map_latest.jpg"
        image.save(output_path, format="JPEG", quality=100, optimize=True)
        return {
            "image_path": str(output_path),
            "capture_bounds": list(capture_bounds),
            "captured_at": time.monotonic(),
            "fingerprint": fingerprint,
            "topology_signature": topology_signature,
            "generation": int(generation),
        }

    def _run_spatial_scan_worker(
        self,
        request: spatial_scanning.SpatialScanRequest,
    ) -> None:
        action_target = str(
            (getattr(self, "_spatial_scan_status", {}) or {}).get("action_target") or ""
        )
        lock = getattr(self, "_snapshot_capture_lock", None)
        acquired = bool(
            isinstance(lock, threading.Lock().__class__)
            and lock.acquire(blocking=False)
        )
        if not acquired:
            self._emit_spatial_scan_result(
                {
                    "generation": request.generation,
                    "ok": False,
                    "error": "Desktop capture is busy.",
                }
            )
            return
        capture: dict[str, object] = {}
        request_settings: dict[str, object] = {}
        raw_payload: dict[str, object] = {}
        try:
            capture = dict(self._capture_spatial_map_image(request.generation) or {})
            if request.reason == "diagnostic":
                CompanionOrbController._log_spatial_diagnostic(
                    "capture complete "
                    f"generation={request.generation} "
                    f"bounds_present={bool(capture.get('capture_bounds'))}"
                )
            fingerprint = str(capture.get("fingerprint") or "")
            change_score = CompanionOrbController._spatial_fingerprint_change_score(
                getattr(self, "_spatial_last_fingerprint", ""),
                fingerprint,
            )
            current = self.spatial_map_snapshot() if hasattr(self, "spatial_map_snapshot") else (
                self._desktop_spatial_map.current(allow_stale=True)
            )
            scan_settings = spatial_scanning.SpatialScanSettings.from_mapping(
                self._last_runtime_config
            )
            if (
                current is not None
                and request.reason not in {"diagnostic", "action"}
                and scan_settings.change_detection_enabled
                and change_score < scan_settings.change_threshold
            ):
                self._emit_spatial_scan_result(
                    {
                        "generation": request.generation,
                        "ok": True,
                        "reused": True,
                        "fingerprint": fingerprint,
                        "change_score": change_score,
                        "captured_at": float(
                            capture.get("captured_at") or time.monotonic()
                        ),
                    }
                )
                return
            request_settings = dict(self._visual_guidance_request_settings() or {})
            if not request_settings:
                raise RuntimeError("Auxiliary vision model is not configured.")
            capability_mode = request_settings.pop("capability_mode", "auto")
            if not vision_guidance.capability_supports_regions(capability_mode):
                raise RuntimeError(
                    "The selected auxiliary-vision capability does not provide regions."
                )
            timeout_seconds = float(request_settings.pop("timeout_seconds", 3.0) or 3.0)
            capture_bounds = list(capture.get("capture_bounds") or [])

            def ground(cancellation: threading.Event):
                if cancellation.is_set():
                    return {}
                if not callable(getattr(self.orb_runtime, "observe_visual", None)):
                    return self.orb_runtime.ground_region(
                        str(capture.get("image_path") or ""),
                        **request_settings,
                        capture_bounds=capture_bounds,
                        gaze_point=[],
                    )
                observed = CompanionOrbController._request_visual_observation(
                    self,
                    Path(str(capture.get("image_path") or "")),
                    capture_bounds=capture_bounds,
                    scope=(
                        "diagnostic"
                        if request.reason == "diagnostic"
                        else "scan"
                    ),
                    cancellation=cancellation,
                    target_text=action_target,
                )
                debug_event = getattr(self, "_debug_event", None)
                if callable(debug_event):
                    observed_regions = getattr(observed.get("observation"), "regions", ())
                    debug_event(
                        "spatial_vision_response",
                        generation=request.generation,
                        scope="diagnostic" if request.reason == "diagnostic" else "scan",
                        response_mode=str(observed.get("response_mode") or "unknown"),
                        response_excerpt=str(
                            observed.get("diagnostic_response_excerpt") or ""
                        )[:600],
                        response_chars=observed.get("diagnostic_response_chars") or 0,
                        provider_region_count=observed.get("provider_region_count") or 0,
                        normalized_region_count=(
                            len(observed_regions)
                            if isinstance(observed_regions, (tuple, list))
                            else 0
                        ),
                        cached=bool(observed.get("cached")),
                    )
                observation = observed.get("observation")
                if not isinstance(
                    observation,
                    visual_observation.VisualObservation,
                ):
                    return {}
                return {
                    "scene_summary": observation.scene_summary,
                    "regions": [
                        {
                            "label": region.label,
                            "kind": region.kind,
                            "bbox": list(region.bbox),
                            "confidence": region.confidence,
                            "action_hint": region.action_hint,
                        }
                        for region in observation.regions
                    ],
                    "limitations": observation.limitations,
                }

            model_started = time.monotonic()
            if request.reason == "diagnostic":
                CompanionOrbController._log_spatial_diagnostic(
                    f"model started generation={request.generation} "
                    f"timeout_seconds={timeout_seconds:.1f}"
                )
            finished, payload = CompanionOrbController._run_bounded_daemon_stage(
                ground,
                timeout_seconds=timeout_seconds,
                name="companion-orb-spatial-grounding",
            )
            if request.reason == "diagnostic":
                CompanionOrbController._log_spatial_diagnostic(
                    f"model complete generation={request.generation} "
                    f"finished={finished} elapsed_seconds={time.monotonic() - model_started:.2f}"
                )
            if not finished:
                raise TimeoutError("Auxiliary desktop grounding timed out.")
            raw_payload = dict(payload) if isinstance(payload, Mapping) else {}
            grounded = vision_grounding.normalize_grounding_result(
                raw_payload,
                capture_bounds=capture_bounds,
                max_regions=int(
                    self._last_runtime_config.get("companion_orb_spatial_max_regions", 48)
                    or 48
                ),
            )
            filtered = replace(
                grounded,
                regions=tuple(
                    region
                    for region in grounded.regions
                    if self._spatial_region_allowed(region.kind)
                ),
            )
            keep_capture = bool(
                self._last_runtime_config.get(
                    "companion_orb_spatial_diagnostics_keep_last_capture",
                    True,
                )
            )
            capture_path = str(capture.get("image_path") or "")
            endpoint = str(request_settings.get("base_url") or "primary")
            snapshot = desktop_spatial_map.build_snapshot(
                filtered,
                generation=request.generation,
                captured_at=float(capture.get("captured_at") or time.monotonic()),
                capture_bounds=capture_bounds,
                topology_signature=str(capture.get("topology_signature") or ""),
                endpoint=endpoint,
                model_id=str(request_settings.get("model_id") or ""),
                capture_path=capture_path if keep_capture else "",
                raw_response=raw_payload,
                max_regions=int(
                    self._last_runtime_config.get("companion_orb_spatial_max_regions", 48)
                    or 48
                ),
            )
            if not keep_capture and capture_path:
                try:
                    Path(capture_path).unlink(missing_ok=True)
                except OSError:
                    pass
            self._emit_spatial_scan_result(
                {
                    "generation": request.generation,
                    "ok": True,
                    "snapshot": snapshot,
                    "fingerprint": fingerprint,
                    "change_score": change_score,
                    "unfiltered_region_count": len(grounded.regions),
                    "raw_response": raw_payload,
                    "image_path": capture_path if keep_capture else "",
                }
            )
        except Exception as exc:
            if request.reason == "diagnostic":
                CompanionOrbController._log_spatial_diagnostic(
                    f"worker error generation={request.generation} "
                    f"error_type={type(exc).__name__}"
                )
            self._emit_spatial_scan_result(
                {
                    "generation": request.generation,
                    "ok": False,
                    "error": str(exc),
                    "image_path": str(capture.get("image_path") or ""),
                    "capture_bounds": list(capture.get("capture_bounds") or []),
                    "model_id": str(request_settings.get("model_id") or ""),
                    "endpoint": str(request_settings.get("base_url") or "primary"),
                    "raw_response": raw_payload,
                }
            )
        finally:
            try:
                lock.release()
            except (AttributeError, RuntimeError):
                pass

    def _emit_spatial_scan_result(self, payload: Mapping[str, object]) -> None:
        signal = getattr(
            getattr(self, "_proxy", None),
            "spatial_scan_result_requested",
            None,
        )
        emitter = getattr(signal, "emit", None)
        if callable(emitter):
            emitter(dict(payload or {}))
            return
        self._handle_spatial_scan_result(dict(payload or {}))

    @QtCore.Slot(object)
    def _handle_spatial_scan_result(self, payload: object) -> None:
        data = dict(payload) if isinstance(payload, Mapping) else {}
        was_diagnostic = str(
            (getattr(self, "_spatial_scan_status", {}) or {}).get("reason") or ""
        ) == "diagnostic"
        try:
            generation = int(data.get("generation") or 0)
        except (TypeError, ValueError, OverflowError):
            generation = 0
        coordinator = getattr(self, "_spatial_scan_coordinator", None)
        scan_status = getattr(self, "_spatial_scan_status", {}) or {}
        scan_reason = str(scan_status.get("reason") or "")
        scan_target = str(scan_status.get("action_target") or "")
        accepted = False
        if isinstance(coordinator, spatial_scanning.SpatialScanCoordinator):
            if bool(data.get("ok")):
                accepted = coordinator.complete(generation)
            else:
                accepted = coordinator.fail(generation, now=time.monotonic())
        if not accepted:
            debug_event = getattr(self, "_debug_event", None)
            if callable(debug_event):
                debug_event(
                    "spatial_scan_result_ignored",
                    generation=generation,
                    pending_target=str(
                        getattr(getattr(self, "_pending_spatial_command", None), "target_text", "") or ""
                    ),
                )
            if was_diagnostic:
                CompanionOrbController._log_spatial_diagnostic(
                    f"result ignored generation={generation}"
                )
            finished_event = getattr(self, "_spatial_scan_finished", None)
            if isinstance(finished_event, threading.Event):
                finished_event.set()
            return
        if bool(data.get("ok")):
            snapshot = data.get("snapshot")
            published = False
            if bool(data.get("reused")) and snapshot is None:
                current = self._desktop_spatial_map.current(allow_stale=True)
                if current is not None:
                    snapshot = replace(
                        current,
                        generation=generation,
                        captured_at=float(
                            data.get("captured_at") or time.monotonic()
                        ),
                    )
            if isinstance(snapshot, desktop_spatial_map.SpatialMapSnapshot):
                published = self._desktop_spatial_map.publish(snapshot)
            self._spatial_last_fingerprint = str(data.get("fingerprint") or "")
            previous_status = dict(getattr(self, "_spatial_scan_status", {}) or {})
            started_monotonic = float(
                previous_status.get("started_monotonic") or time.monotonic()
            )
            self._spatial_scan_status = {
                "state": "reused" if data.get("reused") else "ready",
                "generation": generation,
                "published": published,
                "deferred": bool(snapshot is not None and not published),
                "change_score": float(data.get("change_score") or 0.0),
                "unfiltered_region_count": int(
                    data.get("unfiltered_region_count") or 0
                ),
                "image_path": str(data.get("image_path") or ""),
                "raw_response": dict(data.get("raw_response") or {}),
                "duration_seconds": max(
                    0.0,
                    time.monotonic() - started_monotonic,
                ),
                "completed_at": time.time(),
            }
            debug_event = getattr(self, "_debug_event", None)
            if callable(debug_event):
                debug_event(
                    "spatial_scan_result",
                    generation=generation,
                    state=self._spatial_scan_status["state"],
                    published=published,
                    unfiltered_region_count=self._spatial_scan_status["unfiltered_region_count"],
                    regions=[
                        {
                            "label": region.label,
                            "screen_bounds": list(region.screen_bounds),
                            "confidence": region.confidence,
                        }
                        for region in (snapshot.regions if isinstance(snapshot, desktop_spatial_map.SpatialMapSnapshot) else ())
                    ][:16],
                )
            overlay_refresh = getattr(self, "_refresh_spatial_map_overlay", None)
            if callable(overlay_refresh):
                overlay_refresh()
            follow = getattr(self, "_update_followed_spatial_target", None)
            if callable(follow):
                follow()
            pending_command = getattr(self, "_pending_spatial_command", None)
            if (
                isinstance(pending_command, spatial_commands.SpatialCommand)
                and (
                    (scan_reason == "action" and pending_command.target_text == scan_target)
                    or (scan_reason != "action" and not bool(getattr(coordinator, "coalesced", False)))
                )
            ):
                self._pending_spatial_command = None
                retry = self.execute_spatial_command(
                    pending_command, _allow_targeted_retry=False
                )
                if callable(debug_event):
                    debug_event(
                        "spatial_command_retry",
                        action=pending_command.action,
                        target=pending_command.target_text,
                        ok=bool(retry.get("ok")),
                        reason=str(retry.get("reason") or ""),
                        region_id=str(retry.get("region_id") or ""),
                        queued=bool(retry.get("queued")),
                    )
        else:
            pending = getattr(self, "_pending_spatial_command", None)
            if not bool(getattr(coordinator, "coalesced", False)) or (
                scan_reason == "action"
                and isinstance(pending, spatial_commands.SpatialCommand)
                and pending.target_text == scan_target
            ):
                self._pending_spatial_command = None
            error = re.sub(
                r"https?://\S+",
                "[server]",
                str(data.get("error") or "Spatial scan failed."),
                flags=re.IGNORECASE,
            )
            error = re.sub(r"\s+", " ", error).strip()[:320]
            previous_status = dict(getattr(self, "_spatial_scan_status", {}) or {})
            started_monotonic = float(
                previous_status.get("started_monotonic") or time.monotonic()
            )
            self._spatial_scan_status = {
                "state": "error",
                "generation": generation,
                "error": error or "Spatial scan failed.",
                "image_path": str(data.get("image_path") or ""),
                "capture_bounds": list(data.get("capture_bounds") or []),
                "model_id": str(data.get("model_id") or ""),
                "endpoint": str(data.get("endpoint") or ""),
                "raw_response": dict(data.get("raw_response") or {}),
                "duration_seconds": max(
                    0.0,
                    time.monotonic() - started_monotonic,
                ),
                "completed_at": time.time(),
            }
            debug_event = getattr(self, "_debug_event", None)
            if callable(debug_event):
                debug_event(
                    "spatial_scan_result",
                    generation=generation,
                    state="error",
                    error=self._spatial_scan_status["error"],
                )
        finished_event = getattr(self, "_spatial_scan_finished", None)
        if was_diagnostic:
            CompanionOrbController._log_spatial_diagnostic(
                f"result generation={generation} "
                f"state={self._spatial_scan_status.get('state', 'unknown')}"
            )
        if isinstance(finished_event, threading.Event):
            finished_event.set()
        if bool(getattr(self, "_spatial_scan_shutdown", False)):
            return
        queued = coordinator.consume_coalesced(now=time.monotonic())
        if queued is not None:
            self._start_spatial_scan(queued)

    def _shutdown_spatial_scanning(self) -> None:
        self._spatial_scan_shutdown = True
        self._pending_spatial_command = None
        clear_follow = getattr(self, "_clear_spatial_follow_target", None)
        if callable(clear_follow):
            clear_follow()
        timer = getattr(self, "_spatial_scan_timer", None)
        if isinstance(timer, QtCore.QTimer):
            timer.stop()
        coordinator = getattr(self, "_spatial_scan_coordinator", None)
        if isinstance(coordinator, spatial_scanning.SpatialScanCoordinator):
            coordinator.invalidate()

    def _desired_vision_model_spec(
        self,
    ) -> vision_residency.VisionModelSpec | None:
        request = CompanionOrbController._visual_guidance_request_settings(self)
        if not request:
            return None
        endpoint = str(request.get("base_url") or "").strip() or "primary"
        try:
            return vision_residency.VisionModelSpec(
                provider_id=str(request.get("provider_id") or ""),
                endpoint=endpoint,
                model_id=str(request.get("model_id") or ""),
                handling=str(request.get("model_handling") or "parallel_pinned"),
            )
        except ValueError:
            return None

    def _ensure_vision_state(self) -> None:
        if not isinstance(
            getattr(self, "_vision_residency", None),
            vision_residency.VisionResidencyCoordinator,
        ):
            self._vision_residency = vision_residency.VisionResidencyCoordinator()
        if not isinstance(
            getattr(self, "_vision_inference", None),
            vision_inference.VisionInferenceCoordinator,
        ):
            self._vision_inference = vision_inference.VisionInferenceCoordinator()
        if not isinstance(
            getattr(self, "_vision_observation_cache", None),
            visual_observation.VisualObservationCache,
        ):
            self._vision_observation_cache = visual_observation.VisualObservationCache()
        if not isinstance(
            getattr(self, "_vision_pipeline", None),
            vision_pipeline.VisionPipelineTracker,
        ):
            self._vision_pipeline = vision_pipeline.VisionPipelineTracker()
        if not isinstance(
            getattr(self, "_vision_residency_ready", None),
            threading.Event,
        ):
            self._vision_residency_ready = threading.Event()
        if not hasattr(self, "_vision_residency_ensure_started_generation"):
            self._vision_residency_ensure_started_generation = -1
        if not isinstance(getattr(self, "_vision_runtime_events", None), deque):
            self._vision_runtime_events = deque(maxlen=64)

    @staticmethod
    def _bounded_vision_diagnostic_text(value: object, limit: int = 240) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        text = re.sub(
            r"(?i)authorization\s*[:=]\s*(?:bearer\s+)?\S+",
            "authorization=[redacted]",
            text,
        )
        text = re.sub(
            r"(?i)(api[_ -]?key|bearer)\s*[:=]?\s*\S+",
            r"\1=[redacted]",
            text,
        )
        text = re.sub(r"(?i)data:image/[^\s]+", "[image-data]", text)
        return text[: max(1, int(limit))]

    def _record_vision_runtime_event(self, kind: str, **fields: object) -> None:
        CompanionOrbController._ensure_vision_state(self)
        event: dict[str, object] = {
            "at": round(time.time(), 3),
            "kind": CompanionOrbController._bounded_vision_diagnostic_text(
                kind, 60
            ),
        }
        for key in (
            "state",
            "route",
            "model_id",
            "endpoint",
            "reason",
            "error",
            "cache",
        ):
            if key in fields:
                event[key] = CompanionOrbController._bounded_vision_diagnostic_text(
                    fields[key]
                )
        self._vision_runtime_events.append(event)

    def vision_runtime_snapshot(self) -> dict[str, object]:
        CompanionOrbController._ensure_vision_state(self)
        residency = self._vision_residency.snapshot()
        lease = residency.lease
        enabled = CompanionOrbController._desired_vision_model_spec(self) is not None
        route = "lfm_observation_to_main_chat" if enabled else "main_chat_image"
        return {
            "enabled": enabled,
            "route": route,
            "generation": residency.generation,
            "state": residency.state,
            "provider_id": str(residency.spec.provider_id if residency.spec else ""),
            "endpoint": str(residency.spec.endpoint if residency.spec else ""),
            "model_id": str(residency.spec.model_id if residency.spec else ""),
            "resolved_model_key": str(lease.resolved_model_key if lease else ""),
            "identifier": str(lease.identifier if lease else ""),
            "owned": bool(lease.owned if lease else False),
            "message": CompanionOrbController._bounded_vision_diagnostic_text(
                residency.message
            ),
            "active_requests": self._vision_inference.active_count(),
            "cache_entries": len(self._vision_observation_cache),
            "pipeline": self._vision_pipeline.snapshot(),
            "events": tuple(self._vision_runtime_events)[-16:],
        }

    @staticmethod
    def _publish_vision_pipeline_snapshot(
        self, snapshot: Mapping[str, object]
    ) -> None:
        payload = {
            "type": "vision_pipeline",
            "stage": str(snapshot.get("stage") or "idle"),
            "text": str(snapshot.get("status") or "")[:180],
            "color": str(snapshot.get("color") or "#64748b"),
        }
        try:
            self._proxy.vision_pipeline_requested.emit(
                payload["stage"], payload["text"], payload["color"]
            )
        except Exception:
            pass
        sender = getattr(self, "_send_external_runtime", None)
        if callable(sender):
            try:
                sender(payload)
            except Exception:
                pass

    @staticmethod
    def _set_vision_pipeline_stage(
        self,
        stage: str,
        *,
        scope: str = "",
        route: str = "",
        cache: str = "",
        error: str = "",
    ) -> dict[str, object]:
        tracker = getattr(self, "_vision_pipeline", None)
        if not isinstance(tracker, vision_pipeline.VisionPipelineTracker):
            tracker = vision_pipeline.VisionPipelineTracker()
            self._vision_pipeline = tracker
        snapshot = tracker.transition(
            stage,
            scope=scope,
            route=route,
            cache=cache,
            error=error,
        )
        CompanionOrbController._publish_vision_pipeline_snapshot(self, snapshot)
        return snapshot

    @QtCore.Slot(str, str, str)
    def _apply_vision_pipeline_state(self, stage: str, text: str, color: str) -> None:
        self.bridge.setVisionPipelineState(stage, text, color)
        timer = getattr(self, "_vision_pipeline_clear_timer", None)
        if not isinstance(timer, QtCore.QTimer):
            return
        timer.stop()
        normalized = str(stage or "idle").strip().lower()
        if normalized == "capture":
            timer.start(20000)
        elif normalized == "lfm_analysis":
            timer.start(65000)
        elif normalized == "main_chat":
            timer.start(90000)
        elif normalized == "tts":
            timer.start(120000)
        elif normalized == "complete":
            timer.start(4500)
        elif normalized == "error":
            timer.start(7000)

    @QtCore.Slot()
    def _clear_vision_pipeline_indicator(self) -> None:
        self.bridge.setVisionPipelineState("idle", "", "#64748b")
        sender = getattr(self, "_send_external_runtime", None)
        if callable(sender):
            sender(
                {
                    "type": "vision_pipeline",
                    "stage": "idle",
                    "text": "",
                    "color": "#64748b",
                }
            )

    def _sync_vision_residency(self) -> None:
        CompanionOrbController._ensure_vision_state(self)
        coordinator = self._vision_residency
        previous = coordinator.snapshot()
        spec = CompanionOrbController._desired_vision_model_spec(self)
        if spec is None:
            disabled = coordinator.disable()
            self._vision_inference.invalidate(disabled.generation)
            self._vision_observation_cache.clear()
            self._vision_residency_ready.set()
            CompanionOrbController._record_vision_runtime_event(
                self, "residency", state="disabled", route="main_chat_image"
            )
            return

        generation = coordinator.require(spec)
        if generation != previous.generation:
            self._vision_inference.invalidate(generation)
            self._vision_observation_cache.clear()
        if coordinator.snapshot().state == "ready":
            self._vision_residency_ready.set()
            return
        if self._vision_residency_ensure_started_generation == generation:
            return
        self._vision_residency_ensure_started_generation = generation
        self._vision_residency_ready.clear()
        CompanionOrbController._record_vision_runtime_event(
            self,
            "residency",
            state="ensuring",
            model_id=spec.model_id,
            endpoint=spec.endpoint,
        )

        def worker() -> None:
            try:
                result = dict(
                    self.orb_runtime.ensure_vision_model(
                        provider_id=spec.provider_id,
                        model_id=spec.model_id,
                        base_url="" if spec.endpoint == "primary" else spec.endpoint,
                        model_handling=spec.handling,
                    )
                    or {}
                )
                if not bool(result.get("ready")):
                    coordinator.degraded(
                        generation,
                        "The configured LFM vision model is unavailable.",
                    )
                    return
                coordinator.ready(
                    generation,
                    spec,
                    resolved_model_key=str(result.get("resolved_model_key") or ""),
                    identifier=str(result.get("identifier") or ""),
                    owned=bool(result.get("owned")),
                )
                CompanionOrbController._record_vision_runtime_event(
                    self,
                    "residency",
                    state="ready",
                    model_id=spec.model_id,
                    endpoint=spec.endpoint,
                )
            except Exception as exc:
                coordinator.degraded(generation, str(exc))
                CompanionOrbController._record_vision_runtime_event(
                    self,
                    "residency",
                    state="degraded",
                    model_id=spec.model_id,
                    endpoint=spec.endpoint,
                    error=str(exc),
                )
            finally:
                self._vision_residency_ready.set()

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"companion-orb-lfm-residency-{generation}",
        ).start()

    @staticmethod
    def _visual_observation_priority(scope: str) -> int:
        return {
            "diagnostic": 40,
            "drop": 30,
            "gaze": 30,
            "reading": 30,
            "conversation": 20,
            "scan": 10,
        }.get(str(scope or "").strip().lower(), 20)

    def _request_visual_observation(
        self,
        image_path: Path,
        *,
        capture_bounds: Sequence[object] | None,
        scope: str,
        target_text: str = "",
        cancellation: object | None = None,
        trace_id: str = "",
    ) -> Mapping[str, object]:
        CompanionOrbController._ensure_vision_state(self)
        normalized_scope = str(scope or "gaze").strip().lower()
        target = " ".join(str(target_text or "").split())[:120] if normalized_scope == "scan" else ""
        interactive = normalized_scope in {"drop", "gaze", "reading", "conversation"}

        def debug_issue(stage: str, **fields: object) -> None:
            debug_event = getattr(self, "_debug_event", None)
            if target and callable(debug_event):
                debug_event("spatial_vision_issue", stage=stage, **fields)

        request_settings = CompanionOrbController._visual_guidance_request_settings(self)
        if not request_settings:
            debug_issue("settings_unavailable")
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_skipped",
                reason="vision request settings unavailable",
            )
            return {}
        snapshot = self._vision_residency.snapshot()
        desired = CompanionOrbController._desired_vision_model_spec(self)
        if desired is None or snapshot.spec != desired or snapshot.state != "ready":
            CompanionOrbController._sync_vision_residency(self)
            self._vision_residency_ready.wait(
                timeout=min(5.0, float(request_settings["timeout_seconds"]))
            )
            snapshot = self._vision_residency.snapshot()
        if snapshot.state != "ready" or snapshot.spec != desired:
            debug_issue("model_not_ready", residency_state=snapshot.state)
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_not_ready",
                residency_state=snapshot.state,
                desired_spec=desired,
                resident_spec=snapshot.spec,
            )
            return {}

        try:
            bounds = tuple(int(value) for value in tuple(capture_bounds or ())[:4])
        except (TypeError, ValueError):
            bounds = ()
        if len(bounds) != 4 or bounds[2] <= 0 or bounds[3] <= 0:
            bounds = (0, 0, 1000, 1000)
        try:
            fingerprint = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
        except OSError:
            debug_issue("capture_unavailable")
            return {}
        key = visual_observation.VisualObservationKey(
            fingerprint=fingerprint,
            capture_bounds=(
                bounds[0],
                bounds[1],
                bounds[0] + bounds[2],
                bounds[1] + bounds[3],
            ),
            endpoint=desired.endpoint,
            model_id=desired.model_id,
            generation=snapshot.generation,
            capability_mode=str(request_settings.get("capability_mode") or "auto"),
        )
        cached = None if target else self._vision_observation_cache.get(key)
        if cached is not None:
            if interactive:
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "lfm_analysis",
                    scope=normalized_scope,
                    route="lfm_observation_to_main_chat",
                    cache="hit",
                )
            CompanionOrbController._record_vision_runtime_event(
                self, "observation", state="ready", cache="hit", reason=scope
            )
            cached_text = visual_observation.format_visual_observation_evidence(cached)
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_cache_hit",
                model_id=desired.model_id,
                endpoint=desired.endpoint,
                observation=cached,
                evidence_text=cached_text,
            )
            return {
                "observation": cached,
                "text": cached_text,
                "cached": True,
            }

        inference_request = vision_inference.VisionInferenceRequest(
            key=(key, target) if target else key,
            endpoint=desired.endpoint,
            generation=snapshot.generation,
            priority=CompanionOrbController._visual_observation_priority(scope),
            reason=str(scope or "gaze"),
        )
        admission = self._vision_inference.admit(inference_request)
        if admission.action == "rejected":
            debug_issue("inference_rejected")
            if interactive:
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "error",
                    scope=normalized_scope,
                    error="Vision request was rejected",
                )
            CompanionOrbController._record_vision_runtime_event(
                self,
                "observation",
                state="rejected",
                reason=scope,
            )
            return {}
        deadline = time.monotonic() + float(request_settings["timeout_seconds"])
        while True:
            cached = None if target else self._vision_observation_cache.get(key)
            if cached is not None:
                if interactive:
                    CompanionOrbController._set_vision_pipeline_stage(
                        self,
                        "lfm_analysis",
                        scope=normalized_scope,
                        route="lfm_observation_to_main_chat",
                        cache="hit",
                    )
                return {
                    "observation": cached,
                    "text": visual_observation.format_visual_observation_evidence(cached),
                    "cached": True,
                }
            if self._vision_inference.owns_start(admission.request, admission.token):
                break
            if admission.token.is_set() or time.monotonic() >= deadline:
                debug_issue("inference_cancelled_or_timed_out")
                return {}
            time.sleep(0.025)

        combined = _CombinedVisionCancellation(admission.token, cancellation)
        if interactive:
            CompanionOrbController._set_vision_pipeline_stage(
                self,
                "lfm_analysis",
                scope=normalized_scope,
                route="lfm_observation_to_main_chat",
                cache="miss",
            )
        try:
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_dispatch",
                provider_id=desired.provider_id,
                model_id=desired.model_id,
                endpoint=desired.endpoint,
                model_handling=desired.handling,
                capture_bounds=bounds,
                scope=str(scope or "gaze"),
                timeout_seconds=float(request_settings["timeout_seconds"]),
                capability_mode=str(request_settings.get("capability_mode") or "auto"),
            )
            result = dict(
                self.orb_runtime.observe_visual(
                    image_path=str(image_path),
                    provider_id=desired.provider_id,
                    model_id=desired.model_id,
                    base_url="" if desired.endpoint == "primary" else desired.endpoint,
                    model_handling=desired.handling,
                    capture_bounds=list(bounds),
                    reaction_scope=str(scope or "gaze"),
                    capability_mode=str(
                        request_settings.get("capability_mode") or "auto"
                    ),
                    timeout_seconds=float(request_settings["timeout_seconds"]),
                    cancel_token=combined,
                    trace_id=str(trace_id or ""),
                    **({"target_text": target} if target else {}),
                )
                or {}
            )
            payload = result.get("observation")
            observation = visual_observation.normalize_visual_observation(
                payload,
                key=key,
            )
            if self._vision_residency.snapshot().generation != snapshot.generation:
                debug_issue("model_generation_changed")
                return {}
            if not target:
                self._vision_observation_cache.put(observation)
            CompanionOrbController._record_vision_runtime_event(
                self,
                "observation",
                state="ready",
                cache="miss",
                reason=scope,
                model_id=desired.model_id,
                endpoint=desired.endpoint,
            )
            evidence_text = visual_observation.format_visual_observation_evidence(
                observation
            )
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_observation_ready",
                response=result,
                normalized_observation=observation,
                evidence_text=evidence_text,
                cache="miss",
            )
            return {
                "observation": observation,
                "text": evidence_text,
                "cached": False,
                "response_mode": result.get("response_mode"),
                "diagnostic_response_excerpt": result.get(
                    "diagnostic_response_excerpt", ""
                ),
                "diagnostic_response_chars": result.get("diagnostic_response_chars", 0),
                "provider_region_count": result.get("provider_region_count", 0),
            }
        except Exception as exc:
            debug_issue(
                "provider_or_normalization_error",
                error_type=type(exc).__name__,
                error=CompanionOrbController._bounded_vision_diagnostic_text(exc),
            )
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if interactive:
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "error",
                    scope=normalized_scope,
                    error=str(exc),
                )
            CompanionOrbController._record_vision_runtime_event(
                self,
                "observation",
                state="error",
                reason=scope,
                error=str(exc),
            )
            return {}
        finally:
            self._vision_inference.finish(admission.request, admission.token)

    @staticmethod
    def _primary_parallel_vision_release_request(
        settings: Mapping[str, object],
    ) -> dict[str, object]:
        if not vision_guidance.lfm_features_enabled(settings):
            return {}
        provider_id = str(
            settings.get("companion_orb_vision_provider_id") or ""
        ).strip()
        model_id = str(settings.get("companion_orb_vision_model_id") or "").strip()
        if provider_id.lower() != "lmstudio" or not model_id:
            return {}
        location = vision_guidance.normalize_runtime_location(
            settings.get("companion_orb_vision_runtime_location")
        )
        base_url = ""
        if location in {"separate_local", "lan"}:
            try:
                base_url = vision_guidance.normalize_lmstudio_base_url(
                    settings.get("companion_orb_vision_base_url"),
                    required=True,
                )
            except ValueError:
                return {}
        configured = vision_guidance.normalize_model_handling(
            settings.get("companion_orb_vision_model_handling")
        )
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "base_url": base_url,
            "model_handling": (
                "already_loaded"
                if configured == "already_loaded"
                else vision_guidance.PRIMARY_PARALLEL_MODEL_HANDLING
            ),
        }

    def _release_primary_vision_model_async(
        self,
        request: Mapping[str, object],
        reason: str,
    ) -> None:
        payload = {
            "provider_id": str(request.get("provider_id") or "").strip(),
            "model_id": str(request.get("model_id") or "").strip(),
            "base_url": str(request.get("base_url") or "").strip(),
            "model_handling": str(
                request.get("model_handling")
                or vision_guidance.PRIMARY_PARALLEL_MODEL_HANDLING
            ).strip(),
        }
        if not payload["provider_id"] or not payload["model_id"]:
            return
        release = getattr(self.orb_runtime, "release_vision_model", None)
        if not callable(release):
            return
        key = (
            payload["provider_id"],
            payload["model_id"],
            payload["base_url"],
            payload["model_handling"],
        )
        lock = self._vision_model_release_lock
        with lock:
            if key in self._vision_model_release_inflight:
                return
            self._vision_model_release_inflight.add(key)
            self._vision_model_release_generation += 1

        def worker() -> None:
            try:
                inference = getattr(self, "_vision_inference", None)
                deadline = time.monotonic() + 5.0
                while (
                    isinstance(
                        inference,
                        vision_inference.VisionInferenceCoordinator,
                    )
                    and inference.active_count() > 0
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.025)
                if (
                    isinstance(
                        inference,
                        vision_inference.VisionInferenceCoordinator,
                    )
                    and inference.active_count() > 0
                ):
                    self._log(
                        "Deferred LFM release because a cancelled vision request "
                        "has not drained yet."
                    )
                    return
                if not bool(release(**payload)):
                    self._log(
                        "Could not release the preserved LFM vision model; "
                        "it remains loaded safely."
                    )
            except Exception:
                self._log(
                    "Could not release the preserved LFM vision model; "
                    "it remains loaded safely."
                )
            finally:
                with lock:
                    self._vision_model_release_inflight.discard(key)

        try:
            threading.Thread(
                target=worker,
                daemon=True,
                name=(
                    "companion-orb-lfm-release-"
                    f"{self._vision_model_release_generation}"
                ),
            ).start()
        except Exception:
            with lock:
                self._vision_model_release_inflight.discard(key)
            self._log(
                "Could not start LFM vision model cleanup; it remains loaded safely."
            )

    def _report_lfm_prepare_warning(self, message: str) -> None:
        if not str(message or "").strip():
            return
        lowered = str(message or "").lower()
        safe_message = (
            "LFM vision request timed out. Main Chat remains available."
            if "timed out" in lowered
            else "LFM vision model could not be prepared. Main Chat remains available."
        )
        now = time.monotonic()
        warning_lock = getattr(self, "_lfm_prepare_warning_lock", None)
        if warning_lock is None:
            warning_lock = threading.Lock()
            self._lfm_prepare_warning_lock = warning_lock
        with warning_lock:
            if (
                safe_message
                == str(getattr(self, "_last_lfm_prepare_warning", "") or "")
                and now
                - float(getattr(self, "_last_lfm_prepare_warning_at", 0.0) or 0.0)
                < 30.0
            ):
                return
            self._last_lfm_prepare_warning = safe_message
            self._last_lfm_prepare_warning_at = now
        logger = getattr(self, "_log", None)
        if callable(logger):
            logger(safe_message)

    def _visual_guidance_for_image(
        self,
        image_path: Path,
        *,
        scope: str,
        reaction_generation: int | None = None,
        trace_id: str = "",
    ) -> str:
        if not self._visual_guidance_enabled(scope):
            return ""
        normalized_scope = str(scope or "gaze").strip().lower()
        vision_trace_id = str(trace_id or "").strip()
        if not vision_trace_id:
            vision_trace_id = CompanionOrbController._begin_vision_debug_trace(
                self,
                Path(image_path),
                scope=normalized_scope,
            )
        CompanionOrbController._set_vision_pipeline_stage(
            self,
            "capture",
            scope=normalized_scope,
            route="lfm_observation_to_main_chat",
        )
        if not callable(getattr(self.orb_runtime, "observe_visual", None)):
            request_settings = self._visual_guidance_request_settings()
            generate = getattr(self.orb_runtime, "generate_visual_guidance", None)
            if not request_settings or not callable(generate):
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "error",
                    scope=normalized_scope,
                    error="LFM vision model is not configured",
                )
                return ""

            CompanionOrbController._set_vision_pipeline_stage(
                self,
                "lfm_analysis",
                scope=normalized_scope,
                route="lfm_observation_to_main_chat",
            )

            def legacy_stage(cancellation: threading.Event):
                if cancellation.is_set():
                    return {}
                return generate(
                    str(image_path),
                    provider_id=str(request_settings["provider_id"]),
                    model_id=str(request_settings["model_id"]),
                    base_url=str(request_settings["base_url"]),
                    model_handling=str(request_settings["model_handling"]),
                    restore_main_model=bool(request_settings["restore_main_model"]),
                    reaction_scope=str(scope or "gaze"),
                )

            completed, legacy_result = CompanionOrbController._run_bounded_daemon_stage(
                legacy_stage,
                timeout_seconds=float(request_settings["timeout_seconds"]),
                name="companion-orb-legacy-visual-guidance",
            )
            if not completed or not isinstance(legacy_result, Mapping):
                companion_orb_vision_debug.record_event(
                    vision_trace_id,
                    "lfm_legacy_error",
                    completed=bool(completed),
                    result=legacy_result,
                )
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "error",
                    scope=normalized_scope,
                    error="LFM vision request timed out",
                )
                return ""
            if reaction_generation is not None:
                with self._eye_tracking_reaction_lock:
                    if int(reaction_generation) != int(
                        self._eye_tracking_reaction_generation
                    ):
                        return ""
            legacy_text = str(legacy_result.get("text") or "").strip()[:1400]
            companion_orb_vision_debug.record_event(
                vision_trace_id,
                "lfm_legacy_response",
                response=legacy_result,
                evidence_text=legacy_text,
            )
            return legacy_text
        result = CompanionOrbController._request_visual_observation(
            self,
            Path(image_path),
            capture_bounds=None,
            scope=str(scope or "gaze"),
            trace_id=vision_trace_id,
        )
        if not result:
            CompanionOrbController._set_vision_pipeline_stage(
                self,
                "error",
                scope=normalized_scope,
                error="LFM vision model could not be prepared",
            )
            CompanionOrbController._report_lfm_prepare_warning(
                self,
                "LFM vision model could not be prepared.",
            )
            return ""
        if reaction_generation is not None:
            with self._eye_tracking_reaction_lock:
                if int(reaction_generation) != int(
                    self._eye_tracking_reaction_generation
                ):
                    return ""
        return str(result.get("text") or "").strip()[:1400]

    @staticmethod
    def _click_target_native_capture_stage(
        capture_bounds: list[int],
        virtual_bounds: list[int],
        output_dir: Path,
        cancellation: threading.Event,
        *, grabber=None,
    ) -> dict[str, Any]:
        limited = False
        try:
            native_regions = [] if grabber is not None else [
                dict(region)
                for region in list(
                    snapshot_ocr.extract_window_text_regions(
                        list(capture_bounds),
                        max_regions=64,
                    )
                    or []
                )
                if isinstance(region, dict)
            ]
        except Exception:
            native_regions = []
            limited = True
        if cancellation.is_set():
            return {
                "native_regions": [],
                "output_path": None,
                "limited": True,
            }
        try:
            output_path = Path(
                reading_overlay.capture_region_image(
                    list(capture_bounds),
                    Path(output_dir),
                    virtual_bounds=list(virtual_bounds),
                    **({'grabber': grabber} if grabber is not None else {}),
                )
            )
        except Exception:
            output_path = None
            limited = True
        return {
            "native_regions": native_regions,
            "output_path": output_path,
            "limited": bool(limited),
        }

    @staticmethod
    def _click_target_ocr_stage(
        output_path: Path,
        capture_bounds: list[int],
        cancellation: threading.Event,
        *, include_window_text=True,
    ) -> dict[str, Any]:
        if cancellation.is_set():
            return {"regions": [], "limited": True}
        try:
            result = snapshot_ocr.extract_snapshot_regions(
                Path(output_path),
                screen_bounds=list(capture_bounds),
                max_regions=64,
                include_window_text=include_window_text,
            )
            regions = [
                dict(region)
                for region in list((result or {}).get("regions") or [])
                if isinstance(region, dict)
            ]
            return {"regions": regions, "limited": False}
        except Exception:
            return {"regions": [], "limited": True}

    def _click_target_vision_stage(
        self,
        output_path: Path,
        capture_bounds: list[int],
        focus_point: tuple[float, float],
        provider_id: str,
        model_id: str,
        min_confidence: float,
        cancellation: threading.Event,
        base_url: str = "",
        model_handling: str = "auto_load",
    ) -> dict[str, Any]:
        if cancellation.is_set():
            return {"regions": [], "limited": True}
        if not CompanionOrbController._vision_regions_supported(self):
            return {
                "regions": [],
                "limited": True,
                "error": "Selected vision capability does not provide regions.",
            }
        try:
            capture_x, capture_y, capture_width, capture_height = (
                int(value) for value in list(capture_bounds)[:4]
            )
            if capture_width <= 0 or capture_height <= 0:
                return {"regions": [], "limited": True}
            gaze_point = [
                max(0.0, min(1.0, (float(focus_point[0]) - capture_x) / capture_width)),
                max(0.0, min(1.0, (float(focus_point[1]) - capture_y) / capture_height)),
            ]
            unified_available = callable(
                getattr(self.orb_runtime, "observe_visual", None)
            )
            if not unified_available:
                payload = self.orb_runtime.ground_region(
                    str(output_path),
                    provider_id=str(provider_id or "").strip(),
                    model_id=str(model_id or "").strip(),
                    base_url=str(base_url or ""),
                    model_handling=str(model_handling or "auto_load"),
                    capture_bounds=list(capture_bounds),
                    gaze_point=gaze_point,
                )
                observed = {}
                observation = None
            else:
                observed = CompanionOrbController._request_visual_observation(
                    self,
                    Path(output_path),
                    capture_bounds=list(capture_bounds),
                    scope="gaze",
                    cancellation=cancellation,
                )
                observation = observed.get("observation")
            if unified_available and observation is None:
                return {"regions": [], "limited": True}
            if observation is not None and not isinstance(
                observation,
                visual_observation.VisualObservation,
            ):
                return {"regions": [], "limited": True}
            if observation is not None:
                payload = {
                    "scene_summary": observation.scene_summary,
                    "regions": [
                        {
                            "label": region.label,
                            "kind": region.kind,
                            "bbox": list(region.bbox),
                            "confidence": region.confidence,
                            "action_hint": region.action_hint,
                        }
                        for region in observation.regions
                    ],
                    "limitations": observation.limitations,
                }
            if cancellation.is_set():
                return {"regions": [], "limited": True}
            grounded = vision_grounding.normalize_grounding_result(
                payload,
                capture_bounds=list(capture_bounds),
            )
            threshold = max(0.0, min(1.0, float(min_confidence)))
            regions = [
                region
                for region in vision_grounding.region_payloads(grounded)
                if float(region.get("confidence") or 0.0) >= threshold
            ]
            return {"regions": regions, "limited": False}
        except Exception:
            return {
                "regions": [],
                "limited": True,
                "error": "LFM vision model could not be prepared.",
            }

    def _scan_gaze_click_targets(
        self,
        capture_bounds: list[int],
        focus_point: tuple[float, float],
        generation: int,
        virtual_bounds: list[int] | None = None,
    ) -> None:
        def scan_current() -> bool:
            return bool(self._gaze_click_target_enabled()) and int(generation) == int(
                getattr(self, "_gaze_click_scan_generation", -1)
            )

        if not scan_current():
            return
        primitive_virtual_bounds = list(virtual_bounds or capture_bounds)
        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        output_dir = root / "runtime" / "companion_orb" / "click_targets"
        CompanionOrbController._sweep_stale_click_target_captures(output_dir)
        output_path: Path | None = None
        acquired = False
        cloaked = False
        emit_payload = True
        limited = False
        scan_started = False
        stage_completed = False
        stage_result: Any = None
        automation_targets: tuple[eye_tracking.ClickTarget, ...] = ()
        native_regions: list[dict[str, Any]] = []
        ocr_regions: list[dict[str, Any]] = []
        vision_regions: list[dict[str, Any]] = []
        payload: dict[str, Any] = {
            "generation": int(generation),
            "automation_available": False,
            "automation_timed_out": False,
            "automation_provider_error": False,
            "direct": [],
            "visual": [],
        }

        def cleanup_late_stage_result(value: Any) -> None:
            if not isinstance(value, dict):
                return
            candidate = CompanionOrbController._click_target_capture_path(
                value.get("output_path"),
                output_dir,
            )
            if candidate is not None:
                CompanionOrbController._schedule_click_target_capture_cleanup(
                    candidate,
                    output_dir,
                )

        try:
            try:
                acquired = self._snapshot_capture_lock.acquire(blocking=False)
                if not acquired:
                    limited = True
                elif not scan_current():
                    emit_payload = False
                else:
                    cloaked = CompanionOrbController._apply_click_target_scan_cloak_blocking(
                        self
                    )
                    if not cloaked:
                        limited = True
                    else:
                        time.sleep(0.04)
                        if not scan_current():
                            emit_payload = False
                        else:
                            scan_started = True
                            try:
                                if self._last_runtime_config.get('companion_orb_exclude_nc_from_captures', False):
                                    raise RuntimeError('Native window evidence is disabled for excluded captures.')
                                automation = windows_ui_automation.discover_semantic_targets(
                                    capture_bounds,
                                    max_nodes=320,
                                    timeout_seconds=0.45,
                                )
                                automation_targets = tuple(automation.targets)
                                payload["automation_available"] = bool(automation.available)
                                payload["automation_timed_out"] = bool(automation.timed_out)
                                payload["automation_provider_error"] = bool(
                                    str(getattr(automation, "error", "") or "").strip()
                                )
                                if scan_current():
                                    semantic_targets = eye_tracking.aggregate_click_targets(
                                        semantic_targets=automation_targets,
                                        regions=(),
                                        focus_point=focus_point,
                                        capture_bounds=capture_bounds,
                                        direct_limit=8,
                                        visual_limit=12,
                                    )
                                    payload["direct"] = [
                                        self._serialize_click_target(target, None, capture_bounds)
                                        for target in semantic_targets.direct
                                    ]
                                else:
                                    emit_payload = False
                            except Exception:
                                limited = True
                            if not scan_current():
                                emit_payload = False
                            else:
                                stage_completed, stage_result = (
                                    CompanionOrbController._run_bounded_daemon_stage(
                                        lambda cancellation: CompanionOrbController._click_target_native_capture_stage(
                                            list(capture_bounds),
                                            primitive_virtual_bounds,
                                            output_dir,
                                            cancellation,
                                            **CompanionOrbController._nc_grabber_kwargs(self),
                                        ),
                                        timeout_seconds=GAZE_CLICK_NATIVE_CAPTURE_TIMEOUT_SECONDS,
                                        name="companion-orb-click-target-native-capture",
                                        late_result_handler=cleanup_late_stage_result,
                                    )
                                )
                                if not stage_completed:
                                    limited = True
            finally:
                if cloaked:
                    self._apply_snapshot_cloak_blocking(False)
                if acquired:
                    try:
                        self._snapshot_capture_lock.release()
                    except RuntimeError:
                        pass

            if stage_completed and isinstance(stage_result, dict):
                native_regions = [
                    dict(region)
                    for region in list(stage_result.get("native_regions") or [])
                    if isinstance(region, dict)
                ]
                raw_output_path = stage_result.get("output_path")
                output_path = CompanionOrbController._click_target_capture_path(
                    raw_output_path,
                    output_dir,
                )
                if raw_output_path is not None and output_path is None:
                    limited = True
                limited = limited or bool(stage_result.get("limited"))
            elif stage_completed:
                limited = True

            if not scan_current():
                emit_payload = False

            if emit_payload and output_path is not None:
                ocr_completed, ocr_result = CompanionOrbController._run_bounded_daemon_stage(
                    lambda cancellation: CompanionOrbController._click_target_ocr_stage(
                        output_path,
                        list(capture_bounds),
                        cancellation,
                        **({'include_window_text': False} if self._last_runtime_config.get('companion_orb_exclude_nc_from_captures', False) else {}),
                    ),
                    timeout_seconds=GAZE_CLICK_OCR_TIMEOUT_SECONDS,
                    name="companion-orb-click-target-ocr",
                )
                if ocr_completed and isinstance(ocr_result, dict):
                    ocr_regions = [
                        dict(region)
                        for region in list(ocr_result.get("regions") or [])
                        if isinstance(region, dict)
                    ]
                    limited = limited or bool(ocr_result.get("limited"))
                else:
                    limited = True

            if not scan_current():
                emit_payload = False

            vision_enabled = bool(
                self._last_runtime_config.get("companion_orb_vision_enabled", False)
            )
            vision_provider_id = str(
                self._last_runtime_config.get(
                    "companion_orb_vision_provider_id",
                    "lmstudio",
                )
                or ""
            ).strip()
            vision_model_id = str(
                self._last_runtime_config.get("companion_orb_vision_model_id", "")
                or ""
            ).strip()
            vision_request_settings = (
                CompanionOrbController._visual_guidance_request_settings(self)
            )
            vision_fallback_only = bool(
                self._last_runtime_config.get(
                    "companion_orb_vision_target_fallback_only",
                    True,
                )
            )
            try:
                vision_timeout = max(
                    0.5,
                    min(
                        15.0,
                        float(
                            self._last_runtime_config.get(
                                "companion_orb_vision_timeout_seconds",
                                3.0,
                            )
                            or 3.0
                        ),
                    ),
                )
            except (TypeError, ValueError):
                vision_timeout = 3.0
            try:
                vision_min_confidence = max(
                    0.0,
                    min(
                        1.0,
                        float(
                            self._last_runtime_config.get(
                                "companion_orb_vision_min_confidence",
                                0.45,
                            )
                            or 0.0
                        ),
                    ),
                )
            except (TypeError, ValueError):
                vision_min_confidence = 0.45

            existing_regions = bool(automation_targets or native_regions or ocr_regions)
            should_run_vision = bool(
                emit_payload
                and output_path is not None
                and vision_enabled
                and vision_provider_id
                and vision_model_id
                and bool(vision_request_settings)
                and (not vision_fallback_only or not existing_regions)
            )
            if should_run_vision:
                payload["vision_attempted"] = True
                vision_completed, vision_result = (
                    CompanionOrbController._run_bounded_daemon_stage(
                        lambda cancellation: CompanionOrbController._click_target_vision_stage(
                            self,
                            output_path,
                            list(capture_bounds),
                            tuple(focus_point),
                            vision_provider_id,
                            vision_model_id,
                            vision_min_confidence,
                            cancellation,
                            base_url=str(
                                vision_request_settings.get("base_url") or ""
                            ),
                            model_handling=str(
                                vision_request_settings.get("model_handling")
                                or "auto_load"
                            ),
                        ),
                        timeout_seconds=vision_timeout,
                        name="companion-orb-click-target-vision",
                    )
                )
                if vision_completed and isinstance(vision_result, dict):
                    vision_error = str(vision_result.get("error") or "").strip()
                    if vision_error:
                        CompanionOrbController._report_lfm_prepare_warning(
                            self,
                            vision_error,
                        )
                    vision_regions = [
                        dict(region)
                        for region in list(vision_result.get("regions") or [])
                        if isinstance(region, dict)
                    ]
                    payload["vision_limited"] = bool(vision_result.get("limited"))
                else:
                    payload["vision_limited"] = True
                if vision_fallback_only and payload.get("vision_limited"):
                    limited = True

            if emit_payload and scan_started:
                try:
                    target_set = eye_tracking.aggregate_click_targets(
                        semantic_targets=automation_targets,
                        regions=native_regions + ocr_regions + vision_regions,
                        focus_point=focus_point,
                        capture_bounds=capture_bounds,
                        direct_limit=8,
                        visual_limit=12,
                    )
                    visual_targets = tuple(target_set.visual)
                    if output_path is None:
                        visual_targets = tuple(
                            target
                            for target in visual_targets
                            if target.kind != "zoom_tile"
                        )
                    capture_fingerprint = (
                        CompanionOrbController._click_target_capture_fingerprint(output_path)
                    )
                    payload["direct"] = [
                        self._serialize_click_target(
                            target,
                            output_path,
                            capture_bounds,
                            capture_fingerprint=capture_fingerprint,
                        )
                        for target in target_set.direct
                    ]
                    payload["visual"] = [
                        self._serialize_click_target(
                            target,
                            output_path,
                            capture_bounds,
                            enlarged=True,
                            capture_fingerprint=capture_fingerprint,
                        )
                        for target in visual_targets
                    ]
                except Exception:
                    limited = True
        except Exception:
            limited = True
        finally:
            if output_path is not None:
                CompanionOrbController._schedule_click_target_capture_cleanup(
                    output_path,
                    output_dir,
                )
            if limited:
                payload["error"] = "Click targets could not be scanned."
            if emit_payload and scan_current():
                self._proxy.eye_click_targets_requested.emit(payload)

    @QtCore.Slot(dict)
    def _handle_gaze_click_targets_result(self, payload: dict[str, Any]) -> None:
        data = dict(payload or {})
        try:
            generation = int(data.get("generation") or 0)
        except (TypeError, ValueError):
            return
        if (
            generation != int(getattr(self, "_gaze_click_scan_generation", 0))
            or not self._gaze_radial_menu_open
            or not self._gaze_click_target_enabled()
        ):
            return
        self._gaze_click_targets.clear()
        self._gaze_click_target_payloads.clear()
        self._gaze_click_visual_targets.clear()
        self._gaze_click_visual_page = 0
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        self._gaze_click_automation_available = bool(data.get("automation_available"))
        self._gaze_click_automation_timed_out = bool(data.get("automation_timed_out"))
        self._gaze_click_automation_provider_error = bool(
            data.get("automation_provider_error")
        )
        for index, item in enumerate(list(data.get("direct") or [])[:8]):
            target = self._click_target_from_payload(item)
            if not eye_tracking.is_semantic_direct_target(target):
                continue
            action_id = f"click_target:{index}"
            self._gaze_click_targets[action_id] = target
            self._gaze_click_target_payloads[action_id] = dict(item)
        for item in list(data.get("visual") or [])[:12]:
            if self._click_target_from_payload(item) is not None:
                self._gaze_click_visual_targets.append(dict(item))
        self._gaze_click_scan_error = bool(str(data.get("error") or "").strip())
        if self._gaze_click_targets:
            self._show_gaze_click_target_direct_page()
        elif self._gaze_click_visual_targets:
            self._show_gaze_click_target_visual_page(0)
        else:
            self._show_gaze_click_target_direct_page()

    def _show_gaze_click_target_direct_page(self) -> None:
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        actions: list[gaze_radial_menu.RadialAction] = []
        for action_id, target in self._gaze_click_targets.items():
            if not eye_tracking.is_semantic_direct_target(target):
                continue
            item = self._gaze_click_target_payloads.get(action_id, {})
            crosshair_x, crosshair_y = CompanionOrbController._click_target_payload_crosshair(item)
            actions.append(
                gaze_radial_menu.RadialAction(
                    action_id,
                    target.label,
                    tooltip=target.display_label,
                    role=target.role,
                    preview_png=self._click_target_payload_preview(item),
                    crosshair_x=crosshair_x,
                    crosshair_y=crosshair_y,
                )
            )
        if self._gaze_click_visual_targets:
            actions.append(gaze_radial_menu.RadialAction("click_target_inspect", "Inspect nearby"))
        if not actions:
            message = "Scan failed" if getattr(self, "_gaze_click_scan_error", False) else "No targets\nfound"
            actions.append(
                gaze_radial_menu.RadialAction(
                    "click_target_unavailable",
                    message,
                    enabled=False,
                )
            )
        status_action = self._gaze_click_automation_status_action()
        if status_action is not None:
            actions.append(status_action)
        self._show_gaze_radial_actions(
            actions,
            title="Click target",
            center_label="Back",
            center_action_id="back",
            confirmation_lens=True,
        )

    def _gaze_click_automation_status_action(self) -> gaze_radial_menu.RadialAction | None:
        if not bool(getattr(self, "_gaze_click_automation_available", False)):
            label = "App controls unavailable"
        elif bool(getattr(self, "_gaze_click_automation_provider_error", False)):
            label = "App controls limited"
        elif bool(getattr(self, "_gaze_click_automation_timed_out", False)):
            label = "App controls partial"
        else:
            return None
        return gaze_radial_menu.RadialAction(
            "click_target_automation_status",
            label,
            enabled=False,
        )

    def _gaze_click_visual_page_entries(
        self,
    ) -> tuple[tuple[int, dict[str, Any], eye_tracking.ClickTarget], ...]:
        start = max(0, int(getattr(self, "_gaze_click_visual_page", 0))) * 4
        entries: list[tuple[int, dict[str, Any], eye_tracking.ClickTarget]] = []
        for absolute_index, item in enumerate(
            self._gaze_click_visual_targets[start : start + 4],
            start=start,
        ):
            target = self._click_target_from_payload(item)
            if target is not None:
                entries.append((absolute_index, item, target))
        return tuple(entries)

    @staticmethod
    def _gaze_click_visual_role(
        item: Mapping[str, object],
        target: eye_tracking.ClickTarget,
    ) -> str:
        source = str(item.get("source") or target.source or "").strip().lower()
        backend = str(item.get("backend") or target.backend or "").strip().lower()
        if source == "vision" and backend == "lfm_vision":
            return "LFM"
        return str(target.role or "")

    def _lfm_click_enabled(self) -> bool:
        config = self._last_runtime_config
        enabled = bool(
            interaction_settings.boolish(
                config.get("companion_orb_eye_tracking_click_target_enabled", False),
                default=False,
            )
            and interaction_settings.boolish(
                config.get("companion_orb_vision_enabled", False),
                default=False,
            )
            and str(config.get("companion_orb_vision_model_id", "") or "").strip()
            and interaction_settings.boolish(
                config.get("companion_orb_vision_click_enabled", False),
                default=False,
            )
        )
        method = str(
            config.get("companion_orb_vision_click_confirmation_method", "long_gaze")
            or "long_gaze"
        ).strip().lower()
        if method == "double_blink":
            enabled = bool(
                enabled
                and interaction_settings.boolish(
                    config.get("companion_orb_eye_tracking_blink_click_allowed", False),
                    default=False,
                )
            )
        return enabled

    def _lfm_click_minimum_confidence(self) -> float:
        try:
            value = float(
                self._last_runtime_config.get(
                    "companion_orb_vision_min_confidence",
                    0.45,
                )
                or 0.45
            )
        except (TypeError, ValueError, OverflowError):
            value = 0.45
        return max(0.0, min(1.0, value))

    def _show_gaze_click_target_visual_page(self, page: int = 0) -> None:
        count = len(self._gaze_click_visual_targets)
        if count <= 0:
            self._show_gaze_click_target_direct_page()
            return
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        page_count = max(1, math.ceil(count / 4))
        self._gaze_click_visual_page = max(0, min(int(page), page_count - 1))
        self._gaze_click_visual_page_open = True
        entries = self._gaze_click_visual_page_entries()
        actions: list[gaze_radial_menu.RadialAction] = []
        for absolute_index, item, target in entries:
            crosshair_x, crosshair_y = CompanionOrbController._click_target_payload_crosshair(item)
            actions.append(
                gaze_radial_menu.RadialAction(
                    f"click_target_visual:{absolute_index}",
                    target.display_label or f"View {absolute_index + 1}",
                    tooltip=target.display_label or f"Visual target {absolute_index + 1}",
                    role=CompanionOrbController._gaze_click_visual_role(item, target),
                    preview_png=self._click_target_payload_preview(item),
                    crosshair_x=crosshair_x,
                    crosshair_y=crosshair_y,
                )
            )
        status_action = self._gaze_click_automation_status_action()
        if status_action is not None:
            actions.append(status_action)
        if self._gaze_click_visual_page > 0:
            actions.append(gaze_radial_menu.RadialAction("click_target_visual_previous", "Previous"))
        if self._gaze_click_visual_page + 1 < page_count:
            actions.append(gaze_radial_menu.RadialAction("click_target_visual_next", "Next"))
        title = "Inspect nearby" if page_count == 1 else f"Inspect nearby {self._gaze_click_visual_page + 1}/{page_count}"
        self._show_gaze_radial_actions(
            actions,
            title=title,
            center_label="Back",
            center_action_id="back",
            enlarged_visual=True,
        )
        overlay = self._ensure_gaze_click_target_highlight_overlay()
        overlay.show_candidates(
            tuple(
                (
                    f"click_target_visual:{absolute_index}",
                    target.bounds,
                    str(absolute_index + 1),
                )
                for absolute_index, _item, target in entries
            ),
            active_id="",
            theme=self._gaze_radial_theme(),
        )

    def _show_gaze_click_visual_action_menu(
        self,
        index: int,
        failure_reason: str = "",
    ) -> None:
        try:
            selected_index = int(index)
            if selected_index < 0:
                raise IndexError(selected_index)
            item = self._gaze_click_visual_targets[selected_index]
        except (IndexError, TypeError, ValueError):
            self._clear_gaze_click_target_highlight()
            return
        target = CompanionOrbController._click_target_from_payload(item)
        if target is None:
            self._clear_gaze_click_target_highlight()
            return
        self._gaze_click_visual_selected_index = selected_index
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = True
        action_specs = list(GAZE_CLICK_VISUAL_ACTIONS)
        if CompanionOrbController._lfm_click_enabled(
            self
        ) and vision_click_verification.lfm_click_eligible(
            item,
            minimum_confidence=CompanionOrbController._lfm_click_minimum_confidence(
                self
            ),
        ):
            action_specs.insert(0, ("click", "Click"))
        role = CompanionOrbController._gaze_click_visual_role(item, target)
        preview_png = CompanionOrbController._click_target_payload_preview(item)
        crosshair_x, crosshair_y = (
            CompanionOrbController._click_target_payload_crosshair(item)
        )
        actions = tuple(
            gaze_radial_menu.RadialAction(
                f"click_target_visual_action:{action_id}",
                label,
                role=role,
                preview_png=preview_png,
                crosshair_x=crosshair_x,
                crosshair_y=crosshair_y,
            )
            for action_id, label in action_specs
        )
        reason = re.sub(r"\s+", " ", str(failure_reason or "")).strip()[:96]
        if reason:
            actions = actions + (
                gaze_radial_menu.RadialAction(
                    "lfm_click_verification_failed",
                    reason,
                    enabled=False,
                    role=role,
                    preview_png=preview_png,
                    crosshair_x=crosshair_x,
                    crosshair_y=crosshair_y,
                ),
            )
        self._show_gaze_radial_actions(
            actions,
            title="Context action",
            center_label="Back",
            center_action_id="back",
        )
        self._ensure_gaze_click_target_highlight_overlay().show_target(
            target.bounds,
            target.display_label or "Selected context",
            self._gaze_radial_theme(),
        )

    @staticmethod
    def _bounded_lfm_click_float(
        value: object,
        *,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        try:
            normalized = float(value)
        except (TypeError, ValueError, OverflowError):
            normalized = float(default)
        if not math.isfinite(normalized):
            normalized = float(default)
        return max(float(minimum), min(float(maximum), normalized))

    def _lfm_click_endpoint_identity(
        self,
        request: Mapping[str, object],
    ) -> str:
        provider_id = str(request.get("provider_id") or "").strip().lower()
        if not provider_id:
            return ""
        explicit_base_url = str(request.get("base_url") or "").strip()
        if explicit_base_url:
            try:
                normalized_url = vision_guidance.normalize_lmstudio_base_url(
                    explicit_base_url,
                    required=True,
                )
            except ValueError:
                return ""
            return f"explicit:{provider_id}:{normalized_url}"
        provider_settings = self._last_runtime_config.get(
            "chat_provider_settings",
            {},
        )
        provider_config = (
            provider_settings.get(provider_id, {})
            if isinstance(provider_settings, Mapping)
            else {}
        )
        if not isinstance(provider_config, Mapping):
            provider_config = {}
        serialized = json.dumps(
            dict(provider_config),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"primary:{provider_id}:{hashlib.sha256(serialized).hexdigest()}"

    def _begin_lfm_click_confirmation(self) -> dict[str, object]:
        if not self._lfm_click_enabled():
            return {"ok": False, "error": "Confirmed LFM clicks are not enabled."}
        try:
            selected_index = int(self._gaze_click_visual_selected_index)
            if selected_index < 0:
                raise IndexError(selected_index)
            item = self._gaze_click_visual_targets[selected_index]
        except (IndexError, TypeError, ValueError):
            return {"ok": False, "error": "The selected LFM target is no longer available."}
        minimum_confidence = self._lfm_click_minimum_confidence()
        try:
            target = vision_click_verification.freeze_lfm_click_target(
                item,
                minimum_confidence=minimum_confidence,
            )
        except (TypeError, ValueError):
            return {"ok": False, "error": "The selected LFM target is not safe to click."}
        request = self._visual_guidance_request_settings()
        if not request:
            return {"ok": False, "error": "The LFM endpoint or model is unavailable."}
        endpoint_identity = CompanionOrbController._lfm_click_endpoint_identity(
            self,
            request,
        )
        if not endpoint_identity:
            return {"ok": False, "error": "The LFM endpoint identity is unavailable."}
        config = self._last_runtime_config
        method = str(
            config.get("companion_orb_vision_click_confirmation_method", "long_gaze")
            or "long_gaze"
        ).strip().lower()
        if method not in {"long_gaze", "double_blink"}:
            method = "long_gaze"
        try:
            confirmation_dwell_ms = max(
                500,
                min(
                    5000,
                    int(
                        config.get(
                            "companion_orb_vision_click_confirmation_dwell_ms",
                            1200,
                        )
                        or 1200
                    ),
                ),
            )
        except (TypeError, ValueError, OverflowError):
            confirmation_dwell_ms = 1200
        thresholds = vision_click_verification.VerificationThresholds(
            label_similarity=CompanionOrbController._bounded_lfm_click_float(
                config.get("companion_orb_vision_click_label_similarity", 0.80),
                default=0.80,
                minimum=0.0,
                maximum=1.0,
            ),
            bounds_overlap=CompanionOrbController._bounded_lfm_click_float(
                config.get("companion_orb_vision_click_bounds_overlap", 0.35),
                default=0.35,
                minimum=0.0,
                maximum=1.0,
            ),
        )
        self._gaze_lfm_click_confirmation_generation = int(
            getattr(self, "_gaze_lfm_click_confirmation_generation", 0)
        ) + 1
        self._gaze_lfm_click_verifying = False
        self._gaze_lfm_click_pending = (
            vision_click_verification.PendingLfmClickConfirmation(
                target=target,
                selected_index=selected_index,
                scan_generation=int(getattr(self, "_gaze_click_scan_generation", 0)),
                window_hwnd=int(getattr(self, "_gaze_radial_context_hwnd", 0) or 0),
                provider_id=str(request.get("provider_id") or ""),
                model_id=str(request.get("model_id") or ""),
                base_url=str(request.get("base_url") or ""),
                model_handling=str(request.get("model_handling") or "auto_load"),
                minimum_confidence=minimum_confidence,
                thresholds=thresholds,
                timeout_seconds=CompanionOrbController._bounded_lfm_click_float(
                    config.get(
                        "companion_orb_vision_click_verification_timeout_seconds",
                        5.0,
                    ),
                    default=5.0,
                    minimum=1.0,
                    maximum=15.0,
                ),
                confirmation_method=method,
                sound_enabled=interaction_settings.boolish(
                    config.get("companion_orb_vision_click_sound_enabled", True),
                    default=True,
                ),
                confirmation_dwell_ms=confirmation_dwell_ms,
                confirmation_generation=self._gaze_lfm_click_confirmation_generation,
                endpoint_identity=endpoint_identity,
                preview_png=CompanionOrbController._click_target_payload_preview(item),
                preview_crosshair=(
                    CompanionOrbController._click_target_payload_crosshair(item)
                ),
            )
        )
        policy = getattr(self, "_gaze_lfm_double_blink", None)
        if policy is not None:
            policy.reset()
        self._show_lfm_click_confirmation()
        return {"ok": True, "pending": True}

    def _show_lfm_click_confirmation(self) -> None:
        pending = getattr(self, "_gaze_lfm_click_pending", None)
        if not isinstance(
            pending,
            vision_click_verification.PendingLfmClickConfirmation,
        ):
            return
        crosshair_x, crosshair_y = pending.preview_crosshair
        common = {
            "role": "LFM",
            "preview_png": pending.preview_png,
            "crosshair_x": crosshair_x,
            "crosshair_y": crosshair_y,
        }
        if bool(getattr(self, "_gaze_lfm_click_verifying", False)):
            actions = (
                gaze_radial_menu.RadialAction(
                    "lfm_click_verifying",
                    "Verifying target…",
                    enabled=False,
                    **common,
                ),
            )
            title = "Fresh LFM check"
            dwell_ms_override = None
            confirmation_lens = False
        elif pending.confirmation_method == "double_blink":
            actions = (
                gaze_radial_menu.RadialAction(
                    "lfm_click_blink_instruction",
                    "Blink twice",
                    enabled=False,
                    **common,
                ),
            )
            title = "Double blink to confirm"
            dwell_ms_override = None
            confirmation_lens = False
        else:
            actions = (
                gaze_radial_menu.RadialAction(
                    "lfm_click_confirm",
                    "Confirm click",
                    **common,
                ),
            )
            title = "Confirm LFM click"
            dwell_ms_override = pending.confirmation_dwell_ms
            confirmation_lens = True
        self._show_gaze_radial_actions(
            actions,
            title=title,
            center_label="Cancel",
            center_action_id="lfm_click_cancel",
            confirmation_lens=confirmation_lens,
            enlarged_visual=True,
            dwell_ms_override=dwell_ms_override,
        )

    def _cancel_lfm_click_confirmation(self) -> None:
        self._gaze_lfm_click_confirmation_generation = int(
            getattr(self, "_gaze_lfm_click_confirmation_generation", 0)
        ) + 1
        self._gaze_lfm_click_verification_generation = int(
            getattr(self, "_gaze_lfm_click_verification_generation", 0)
        ) + 1
        self._gaze_lfm_click_pending = None
        self._gaze_lfm_click_verifying = False
        policy = getattr(self, "_gaze_lfm_double_blink", None)
        if policy is not None:
            policy.reset()

    def _confirm_pending_lfm_click(self) -> None:
        pending = getattr(self, "_gaze_lfm_click_pending", None)
        if not isinstance(
            pending,
            vision_click_verification.PendingLfmClickConfirmation,
        ) or bool(getattr(self, "_gaze_lfm_click_verifying", False)):
            return
        if pending.sound_enabled:
            self._play_blink_notification(True)
        starter = getattr(self, "_start_lfm_click_verification", None)
        if callable(starter):
            starter()

    def _lfm_click_pending_settings_current(
        self,
        pending: vision_click_verification.PendingLfmClickConfirmation,
    ) -> bool:
        if not self._lfm_click_enabled():
            return False
        request = self._visual_guidance_request_settings()
        if not request:
            return False
        config = self._last_runtime_config
        method = str(
            config.get("companion_orb_vision_click_confirmation_method", "long_gaze")
            or "long_gaze"
        ).strip().lower()
        current_thresholds = vision_click_verification.VerificationThresholds(
            label_similarity=CompanionOrbController._bounded_lfm_click_float(
                config.get("companion_orb_vision_click_label_similarity", 0.80),
                default=0.80,
                minimum=0.0,
                maximum=1.0,
            ),
            bounds_overlap=CompanionOrbController._bounded_lfm_click_float(
                config.get("companion_orb_vision_click_bounds_overlap", 0.35),
                default=0.35,
                minimum=0.0,
                maximum=1.0,
            ),
        )
        timeout_seconds = CompanionOrbController._bounded_lfm_click_float(
            config.get(
                "companion_orb_vision_click_verification_timeout_seconds",
                5.0,
            ),
            default=5.0,
            minimum=1.0,
            maximum=15.0,
        )
        return bool(
            str(request.get("provider_id") or "") == pending.provider_id
            and str(request.get("model_id") or "") == pending.model_id
            and str(request.get("base_url") or "") == pending.base_url
            and str(request.get("model_handling") or "") == pending.model_handling
            and CompanionOrbController._lfm_click_endpoint_identity(self, request)
            == pending.endpoint_identity
            and method == pending.confirmation_method
            and math.isclose(
                self._lfm_click_minimum_confidence(),
                pending.minimum_confidence,
                abs_tol=1e-9,
            )
            and current_thresholds == pending.thresholds
            and math.isclose(
                timeout_seconds,
                pending.timeout_seconds,
                abs_tol=1e-9,
            )
        )

    def _lfm_click_window_current(
        self,
        pending: vision_click_verification.PendingLfmClickConfirmation,
    ) -> bool:
        hwnd = int(pending.window_hwnd or 0)
        if not hwnd or hwnd != int(getattr(self, "_gaze_radial_context_hwnd", 0) or 0):
            return False
        checker = getattr(self, "_lfm_click_foreground_window_matches", None)
        return bool(callable(checker) and checker(hwnd))

    @staticmethod
    def _lfm_click_foreground_window_matches(hwnd: int) -> bool:
        try:
            target = int(hwnd or 0)
            if not target:
                return False
            user32 = ctypes.windll.user32
            if not bool(user32.IsWindow(target)):
                return False
            foreground = int(user32.GetForegroundWindow() or 0)
            if foreground:
                foreground = int(user32.GetAncestor(foreground, 2) or foreground)
            target_root = int(user32.GetAncestor(target, 2) or target)
            return bool(foreground and foreground == target_root)
        except Exception:
            return False

    def _lfm_click_execution_safe(
        self,
        pending: vision_click_verification.PendingLfmClickConfirmation,
    ) -> bool:
        foreground_check = getattr(
            self,
            "_lfm_click_foreground_window_matches",
            None,
        )
        settings_check = getattr(self, "_lfm_click_pending_settings_current", None)
        desktop_check = getattr(self, "_lfm_click_default_input_desktop", None)
        return bool(
            not bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
            and callable(foreground_check)
            and foreground_check(pending.window_hwnd)
            and callable(settings_check)
            and settings_check(pending)
            and callable(desktop_check)
            and desktop_check()
        )

    def _lfm_click_result_is_current(
        self,
        payload: Mapping[str, object],
        pending: vision_click_verification.PendingLfmClickConfirmation,
    ) -> bool:
        try:
            result_confirmation = int(payload.get("confirmation_generation") or 0)
            result_verification = int(payload.get("verification_generation") or 0)
            result_scan = int(payload.get("scan_generation") or 0)
            result_hwnd = int(payload.get("window_hwnd") or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        return bool(
            getattr(self, "_gaze_lfm_click_pending", None) == pending
            and payload.get("target") == pending.target
            and bool(getattr(self, "_gaze_lfm_click_verifying", False))
            and bool(getattr(self, "_gaze_radial_menu_open", False))
            and not bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
            and result_confirmation == pending.confirmation_generation
            and result_confirmation
            == int(getattr(self, "_gaze_lfm_click_confirmation_generation", 0))
            and result_verification
            == int(getattr(self, "_gaze_lfm_click_verification_generation", 0))
            and result_scan == pending.scan_generation
            and result_scan == int(getattr(self, "_gaze_click_scan_generation", 0))
            and result_hwnd == pending.window_hwnd
            and result_hwnd == int(getattr(self, "_gaze_radial_context_hwnd", 0) or 0)
        )

    @staticmethod
    def _lfm_click_default_input_desktop() -> bool:
        handle = None
        try:
            user32 = ctypes.windll.user32
            open_input_desktop = user32.OpenInputDesktop
            open_input_desktop.argtypes = [
                ctypes.c_uint32,
                ctypes.c_bool,
                ctypes.c_uint32,
            ]
            open_input_desktop.restype = ctypes.c_void_p
            close_desktop = user32.CloseDesktop
            close_desktop.argtypes = [ctypes.c_void_p]
            close_desktop.restype = ctypes.c_bool
            get_user_object_information = user32.GetUserObjectInformationW
            get_user_object_information.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_ulong),
            ]
            get_user_object_information.restype = ctypes.c_bool
            handle = open_input_desktop(0, False, 0x0001)
            if not handle:
                return False
            needed = ctypes.c_ulong(0)
            get_user_object_information(
                handle,
                2,
                None,
                0,
                ctypes.byref(needed),
            )
            if needed.value <= 0:
                return False
            character_count = max(
                2,
                int(needed.value) // ctypes.sizeof(ctypes.c_wchar) + 1,
            )
            buffer = ctypes.create_unicode_buffer(character_count)
            if not bool(
                get_user_object_information(
                    handle,
                    2,
                    buffer,
                    ctypes.sizeof(buffer),
                    ctypes.byref(needed),
                )
            ):
                return False
            return buffer.value == "Default"
        except Exception:
            return False
        finally:
            if handle:
                try:
                    ctypes.windll.user32.CloseDesktop(handle)
                except Exception:
                    pass

    def _lfm_click_verification_context_current(
        self,
        pending: vision_click_verification.PendingLfmClickConfirmation,
        confirmation_generation: int,
        verification_generation: int,
        *,
        require_verifying: bool = True,
    ) -> bool:
        window_check = getattr(self, "_lfm_click_window_current", None)
        settings_check = getattr(self, "_lfm_click_pending_settings_current", None)
        return bool(
            getattr(self, "_gaze_lfm_click_pending", None) == pending
            and (not require_verifying or bool(getattr(self, "_gaze_lfm_click_verifying", False)))
            and bool(getattr(self, "_gaze_radial_menu_open", False))
            and not bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
            and int(confirmation_generation) == pending.confirmation_generation
            and int(confirmation_generation)
            == int(getattr(self, "_gaze_lfm_click_confirmation_generation", 0))
            and int(verification_generation)
            == int(getattr(self, "_gaze_lfm_click_verification_generation", 0))
            and pending.scan_generation
            == int(getattr(self, "_gaze_click_scan_generation", 0))
            and pending.window_hwnd
            == int(getattr(self, "_gaze_radial_context_hwnd", 0) or 0)
            and callable(window_check)
            and window_check(pending)
            and callable(settings_check)
            and settings_check(pending)
        )

    def _start_lfm_click_verification(self) -> None:
        pending = getattr(self, "_gaze_lfm_click_pending", None)
        if not isinstance(
            pending,
            vision_click_verification.PendingLfmClickConfirmation,
        ) or bool(getattr(self, "_gaze_lfm_click_verifying", False)):
            return
        confirmation_generation = pending.confirmation_generation
        current_verification = int(
            getattr(self, "_gaze_lfm_click_verification_generation", 0)
        )
        context_check = getattr(self, "_lfm_click_verification_context_current", None)
        if not callable(context_check) or not context_check(
            pending,
            confirmation_generation,
            current_verification,
            require_verifying=False,
        ):
            CompanionOrbController._cancel_lfm_click_confirmation(self)
            return
        verification_generation = current_verification + 1
        self._gaze_lfm_click_verification_generation = verification_generation
        self._gaze_lfm_click_verifying = True
        self._show_lfm_click_confirmation()
        capture_bounds = [int(value) for value in pending.target.capture_bounds]
        virtual_bounds = list(capture_bounds)
        virtual_rect_getter = getattr(self, "_virtual_desktop_rect", None)
        if callable(virtual_rect_getter):
            try:
                virtual_rect = virtual_rect_getter()
                if virtual_rect is not None and not virtual_rect.isEmpty():
                    virtual_bounds = [
                        int(virtual_rect.x()),
                        int(virtual_rect.y()),
                        int(virtual_rect.width()),
                        int(virtual_rect.height()),
                    ]
            except Exception:
                virtual_bounds = list(capture_bounds)
        try:
            threading.Thread(
                target=CompanionOrbController._run_lfm_click_verification,
                args=(
                    self,
                    pending,
                    confirmation_generation,
                    verification_generation,
                    virtual_bounds,
                ),
                daemon=True,
                name="companion-orb-lfm-click-verification",
            ).start()
        except Exception:
            self._gaze_lfm_click_verifying = False
            CompanionOrbController._cancel_lfm_click_confirmation(self)
            if bool(getattr(self, "_gaze_radial_menu_open", False)):
                show_actions = getattr(
                    self,
                    "_show_gaze_click_visual_action_menu",
                    None,
                )
                if callable(show_actions):
                    show_actions(
                        pending.selected_index,
                        "Could not start LFM verification.",
                    )

    def _run_lfm_click_verification(
        self,
        pending: vision_click_verification.PendingLfmClickConfirmation,
        confirmation_generation: int,
        verification_generation: int,
        virtual_bounds: list[int] | None = None,
    ) -> None:
        result: dict[str, object] = {
            "confirmation_generation": int(confirmation_generation),
            "verification_generation": int(verification_generation),
            "scan_generation": int(pending.scan_generation),
            "window_hwnd": int(pending.window_hwnd),
            "target": pending.target,
            "candidates": [],
            "error": "",
        }

        def context_current() -> bool:
            checker = getattr(self, "_lfm_click_verification_context_current", None)
            return bool(
                callable(checker)
                and checker(
                    pending,
                    confirmation_generation,
                    verification_generation,
                )
            )

        def emit() -> None:
            signal = getattr(
                getattr(self, "_proxy", None),
                "eye_lfm_click_verification_requested",
                None,
            )
            emitter = getattr(signal, "emit", None)
            if callable(emitter):
                emitter(dict(result))

        if not context_current():
            result["error"] = "Verification was cancelled."
            emit()
            return
        desktop_check = getattr(self, "_lfm_click_default_input_desktop", None)
        if not callable(desktop_check) or not desktop_check():
            result["error"] = "Computer input is not on the Default desktop."
            emit()
            return

        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        output_dir = root / "runtime" / "companion_orb" / "click_targets"
        capture_bounds = [int(value) for value in pending.target.capture_bounds]
        output_path: Path | None = None
        acquired = False
        cloaked = False
        try:
            acquired = bool(self._snapshot_capture_lock.acquire(blocking=False))
            if not acquired:
                result["error"] = "Screen capture is busy."
                return
            cloak_capture = getattr(
                self,
                "_apply_click_target_scan_cloak_blocking",
                None,
            )
            cloaked = bool(callable(cloak_capture) and cloak_capture())
            if not cloaked:
                result["error"] = (
                    "Could not safely hide the Companion Orb for verification."
                )
                return
            primitive_virtual_bounds = list(virtual_bounds or capture_bounds)
            stage_runner = getattr(self, "_run_bounded_daemon_stage")
            capture_stage = getattr(self, "_click_target_native_capture_stage")

            def cleanup_late_capture(value: object) -> None:
                if not isinstance(value, Mapping):
                    return
                raw_late_path = value.get("output_path")
                if raw_late_path is None:
                    return
                late_path = CompanionOrbController._click_target_capture_path(
                    Path(raw_late_path),
                    output_dir,
                )
                cleanup = getattr(self, "_schedule_click_target_capture_cleanup", None)
                if late_path is not None and callable(cleanup):
                    cleanup(late_path, output_dir)

            completed, captured = stage_runner(
                lambda cancellation: capture_stage(
                    list(capture_bounds),
                    primitive_virtual_bounds,
                    output_dir,
                    cancellation,
                    **CompanionOrbController._nc_grabber_kwargs(self),
                ),
                timeout_seconds=GAZE_CLICK_NATIVE_CAPTURE_TIMEOUT_SECONDS,
                name="companion-orb-lfm-click-capture",
                late_result_handler=cleanup_late_capture,
            )
            if not completed or not isinstance(captured, Mapping):
                result["error"] = "Could not capture the target for verification."
                return
            raw_output_path = captured.get("output_path")
            if raw_output_path is None:
                result["error"] = "Could not capture the target for verification."
                return
            output_path = CompanionOrbController._click_target_capture_path(
                Path(raw_output_path),
                output_dir,
            )
            if output_path is None or not output_path.is_file():
                result["error"] = "The verification capture was outside its owned folder."
                return
        except Exception:
            result["error"] = "Could not capture the target for verification."
            return
        finally:
            if cloaked:
                self._apply_snapshot_cloak_blocking(False)
            if acquired:
                try:
                    self._snapshot_capture_lock.release()
                except RuntimeError:
                    pass
            if result["error"]:
                emit()

        if result["error"]:
            return
        try:
            if not context_current():
                result["error"] = "Verification was cancelled."
                return
            fingerprint = CompanionOrbController._click_target_capture_fingerprint(
                output_path
            )
            if not fingerprint:
                result["error"] = "Could not identify the fresh verification capture."
                return
            focus_point = pending.target.bounds
            left, top, width, height = focus_point
            runner = getattr(self, "_run_bounded_daemon_stage")
            vision_stage = getattr(self, "_click_target_vision_stage")
            completed, grounded = runner(
                lambda cancellation: vision_stage(
                    output_path,
                    list(capture_bounds),
                    (left + width * 0.5, top + height * 0.5),
                    pending.provider_id,
                    pending.model_id,
                    pending.minimum_confidence,
                    cancellation,
                    base_url=pending.base_url,
                    model_handling=pending.model_handling,
                ),
                timeout_seconds=pending.timeout_seconds,
                name="companion-orb-lfm-click-grounding",
            )
            if not completed:
                result["error"] = "LFM verification timed out."
                return
            if not isinstance(grounded, Mapping) or bool(grounded.get("limited")):
                result["error"] = "LFM verification failed."
                return
            candidates: list[dict[str, object]] = []
            for region in list(grounded.get("regions") or ()):
                if not isinstance(region, Mapping):
                    continue
                candidates.append(
                    {
                        "label": str(region.get("text") or ""),
                        "kind": str(region.get("kind") or ""),
                        "bounds": list(region.get("screen_bounds") or ()),
                        "confidence": region.get("confidence", 0.0),
                        "source": str(region.get("source") or ""),
                        "backend": str(region.get("backend") or ""),
                        "capture_bounds": list(capture_bounds),
                        "capture_fingerprint": fingerprint,
                    }
                )
            if not context_current():
                result["error"] = "Verification was cancelled."
                return
            result["candidates"] = candidates
            if not candidates:
                result["error"] = "Could not verify target."
        except Exception:
            result["error"] = "LFM verification failed."
        finally:
            if output_path is not None:
                cleanup = getattr(self, "_schedule_click_target_capture_cleanup", None)
                if callable(cleanup):
                    cleanup(output_path, output_dir)
            emit()

    def _reject_current_lfm_click_verification(
        self,
        pending: vision_click_verification.PendingLfmClickConfirmation,
        reason: str,
    ) -> None:
        selected_index = pending.selected_index
        sound_enabled = pending.sound_enabled
        CompanionOrbController._cancel_lfm_click_confirmation(self)
        if sound_enabled:
            self._play_blink_notification(False)
        if bool(getattr(self, "_gaze_radial_menu_open", False)):
            self._show_gaze_click_visual_action_menu(
                selected_index,
                re.sub(r"\s+", " ", str(reason or "Could not verify target.")).strip()[:96],
            )

    @QtCore.Slot(object)
    def _handle_lfm_click_verification_result(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        pending = getattr(self, "_gaze_lfm_click_pending", None)
        if not isinstance(
            pending,
            vision_click_verification.PendingLfmClickConfirmation,
        ) or not CompanionOrbController._lfm_click_result_is_current(
            self,
            payload,
            pending,
        ):
            return
        window_check = getattr(self, "_lfm_click_window_current", None)
        if not callable(window_check) or not window_check(pending):
            CompanionOrbController._reject_current_lfm_click_verification(
                self,
                pending,
                "Target window changed.",
            )
            return
        settings_check = getattr(self, "_lfm_click_pending_settings_current", None)
        if not callable(settings_check) or not settings_check(pending):
            CompanionOrbController._reject_current_lfm_click_verification(
                self,
                pending,
                "LFM click settings changed.",
            )
            return
        desktop_check = getattr(self, "_lfm_click_default_input_desktop", None)
        if not callable(desktop_check) or not desktop_check():
            CompanionOrbController._reject_current_lfm_click_verification(
                self,
                pending,
                "Computer input is not on the Default desktop.",
            )
            return
        error = re.sub(r"\s+", " ", str(payload.get("error") or "")).strip()
        if error:
            if error in {"LFM verification timed out.", "LFM verification failed."}:
                CompanionOrbController._report_lfm_prepare_warning(
                    self,
                    error,
                )
            verification = vision_click_verification.LfmClickVerification(
                False,
                error[:96],
            )
        else:
            candidates = payload.get("candidates")
            if not isinstance(candidates, (list, tuple)):
                candidates = ()
            verification = vision_click_verification.verify_lfm_click_target(
                pending.target,
                candidates,
                thresholds=pending.thresholds,
                minimum_confidence=pending.minimum_confidence,
            )
        if verification.accepted and verification.click_point is not None:
            click_point = verification.click_point
            execution_preflight = lambda: CompanionOrbController._lfm_click_execution_safe(
                self,
                pending,
            )
            CompanionOrbController._cancel_lfm_click_confirmation(self)
            self._dismiss_gaze_radial_menu()
            self._queue_gaze_left_click(
                click_point,
                require_click_target_enabled=True,
                execution_preflight=execution_preflight,
            )
            return
        CompanionOrbController._reject_current_lfm_click_verification(
            self,
            pending,
            verification.reason or "Could not verify target.",
        )

    def _gaze_click_visual_context_bounds(
        self,
        target: eye_tracking.ClickTarget,
    ) -> list[int]:
        try:
            target_left, target_top, target_width, target_height = (
                int(value) for value in target.bounds
            )
            screen_left, screen_top, screen_width, screen_height = (
                float(value) for value in self._eye_tracking_screen_bounds()
            )
        except (TypeError, ValueError):
            return []
        if (
            target_width <= 0
            or target_height <= 0
            or screen_width <= 0.0
            or screen_height <= 0.0
        ):
            return []
        context_width = min(
            int(round(screen_width)),
            max(180, target_width + 72),
        )
        context_height = min(
            int(round(screen_height)),
            max(108, target_height + 64),
        )
        center_x = float(target_left) + float(target_width) * 0.5
        center_y = float(target_top) + float(target_height) * 0.5
        max_left = screen_left + screen_width - float(context_width)
        max_top = screen_top + screen_height - float(context_height)
        context_left = max(screen_left, min(center_x - context_width * 0.5, max_left))
        context_top = max(screen_top, min(center_y - context_height * 0.5, max_top))
        return [
            int(round(context_left)),
            int(round(context_top)),
            context_width,
            context_height,
        ]

    @QtCore.Slot(str)
    def _handle_gaze_click_candidate_changed(self, action_id: str) -> None:
        if not self._gaze_click_target_enabled():
            self._clear_gaze_click_target_highlight()
            return
        normalized = str(action_id or "").strip().lower()
        target = self._gaze_click_targets.get(normalized)
        if target is not None:
            self._ensure_gaze_click_target_highlight_overlay().show_target(
                target.bounds,
                target.display_label,
                self._gaze_radial_theme(),
            )
            return
        if bool(getattr(self, "_gaze_click_visual_action_menu_open", False)):
            try:
                selected_index = int(self._gaze_click_visual_selected_index)
                item = self._gaze_click_visual_targets[selected_index]
            except (IndexError, TypeError, ValueError):
                self._clear_gaze_click_target_highlight()
                return
            selected_target = CompanionOrbController._click_target_from_payload(item)
            if selected_target is None:
                self._clear_gaze_click_target_highlight()
                return
            self._ensure_gaze_click_target_highlight_overlay().show_target(
                selected_target.bounds,
                selected_target.display_label or "Selected context",
                self._gaze_radial_theme(),
            )
            return
        if bool(getattr(self, "_gaze_click_visual_page_open", False)):
            entries = self._gaze_click_visual_page_entries()
            current_ids = {f"click_target_visual:{index}" for index, _item, _target in entries}
            if not normalized or normalized in current_ids:
                self._ensure_gaze_click_target_highlight_overlay().show_candidates(
                    tuple(
                        (
                            f"click_target_visual:{index}",
                            visual_target.bounds,
                            str(index + 1),
                        )
                        for index, _item, visual_target in entries
                    ),
                    active_id=normalized,
                    theme=self._gaze_radial_theme(),
                )
                return
        self._clear_gaze_click_target_highlight()

    def _show_gaze_voice_menu(self, page: int = 0) -> None:
        voices = self._available_voice_files()
        self._gaze_radial_payloads.clear()
        if not voices:
            actions = (
                gaze_radial_menu.RadialAction(
                    "voice_unavailable",
                    "No voices\nfound",
                    enabled=False,
                ),
            )
            self._show_gaze_radial_actions(
                actions,
                title="Voice",
                center_label="Back",
                center_action_id="back",
            )
            return
        page_count = max(1, math.ceil(len(voices) / GAZE_RADIAL_VOICE_PAGE_SIZE))
        self._gaze_voice_page = max(0, min(page_count - 1, int(page)))
        start = self._gaze_voice_page * GAZE_RADIAL_VOICE_PAGE_SIZE
        selected_voices = voices[start:start + GAZE_RADIAL_VOICE_PAGE_SIZE]
        current_path = self._normalized_voice_config_path(
            self._last_runtime_config.get("voice_path", "")
        )
        actions: list[gaze_radial_menu.RadialAction] = []
        for offset, voice_file in enumerate(selected_voices):
            index = start + offset
            action_id = f"voice_select:{index}"
            self._gaze_radial_payloads[action_id] = Path(voice_file)
            relative = self._voice_config_path(Path(voice_file))
            actions.append(
                gaze_radial_menu.RadialAction(
                    action_id,
                    self._voice_menu_label(Path(voice_file)),
                    checked=self._normalized_voice_config_path(relative) == current_path,
                    tooltip=str(voice_file),
                )
            )
        if self._gaze_voice_page > 0:
            actions.append(gaze_radial_menu.RadialAction("voice_prev", "Previous"))
        if self._gaze_voice_page + 1 < page_count:
            actions.append(gaze_radial_menu.RadialAction("voice_next", "Next"))
        title = "Voice" if page_count == 1 else f"Voice {self._gaze_voice_page + 1}/{page_count}"
        self._show_gaze_radial_actions(
            actions,
            title=title,
            center_label="Back",
            center_action_id="back",
        )

    def _show_gaze_reply_style_menu(self) -> None:
        current = _normalize_orb_response_style(
            self._last_runtime_config.get("companion_orb_response_style", "friendly")
        )
        actions = tuple(
            gaze_radial_menu.RadialAction(
                f"reply_style:{value}",
                label.replace(" / ", "\n"),
                checked=value == current,
            )
            for label, value in ORB_RESPONSE_STYLES
        )
        self._show_gaze_radial_actions(
            actions,
            title="Reply style",
            center_label="Back",
            center_action_id="back",
        )

    def _dispatch_gaze_click_visual_action(self, action_id: str) -> dict[str, Any]:
        normalized = str(action_id or "").strip().lower()
        try:
            selected_index = int(self._gaze_click_visual_selected_index)
            if selected_index < 0:
                raise IndexError(selected_index)
            item = self._gaze_click_visual_targets[selected_index]
        except (IndexError, TypeError, ValueError):
            return {"ok": False, "error": "The selected visual context is no longer available."}
        target = CompanionOrbController._click_target_from_payload(item)
        if target is None:
            return {"ok": False, "error": "The selected visual context is invalid."}
        if normalized == "click":
            return self._begin_lfm_click_confirmation()
        if normalized == "inspect":
            bounds = self._gaze_click_visual_context_bounds(target)
            if not bounds:
                return {
                    "ok": False,
                    "error": "The selected visual context is outside the active display.",
                }
            self._dismiss_gaze_radial_menu()
            return self._queue_gaze_radial_context_action(
                "react",
                target.center,
                bounds_override=bounds,
            )

        reading_action_id = GAZE_CLICK_VISUAL_READING_ACTIONS.get(normalized, "")
        action = reading_actions.action_for_id(reading_action_id)
        if action is None:
            return {"ok": False, "error": "Unknown visual context action."}
        if not self._begin_reading_job(reading_action_id):
            return {
                "ok": False,
                "error": "Another Companion Orb reading action is still running.",
            }
        try:
            bounds = self._gaze_click_visual_context_bounds(target)
            if not bounds:
                raise RuntimeError("The selected visual context is outside the active display.")
            self._dismiss_gaze_radial_menu()
            self._start_reading_worker(
                action,
                selected_text="",
                bounds=bounds,
                private_bounds=True,
            )
        except Exception as exc:
            self._finish_reading_job(reading_action_id, reason="failed")
            return {
                "ok": False,
                "error": f"Could not prepare the selected visual context: {exc}",
            }
        return {"ok": True, "queued": True}

    def _start_gaze_scrolling(self) -> bool:
        target_point = (
            getattr(self, "_gaze_radial_scroll_target_point", None)
            or (float(self._gaze_radial_anchor.x()), float(self._gaze_radial_anchor.y()))
        )
        target_hwnd = int(getattr(self, "_gaze_radial_context_hwnd", 0) or 0)
        if not target_hwnd:
            target_hwnd = self._window_handle_at_point(target_point)
        if not target_hwnd:
            self._eye_tracking_status_message = (
                "Gaze scrolling could not find a target window under the current focus."
            )
            self._play_blink_notification(False)
            return False
        anchor_y = float(target_point[1])
        self._dismiss_gaze_radial_menu()
        self._gaze_scroll_active = True
        self._gaze_scroll_anchor_y = anchor_y
        self._gaze_scroll_target_hwnd = target_hwnd
        self._gaze_scroll_target_point = (float(target_point[0]), float(target_point[1]))
        self._gaze_scroll_policy.reset()
        self._play_blink_notification(True)
        return True

    def _stop_gaze_scrolling(self) -> bool:
        was_active = bool(getattr(self, "_gaze_scroll_active", False))
        self._gaze_scroll_active = False
        self._gaze_scroll_anchor_y = 0.0
        self._gaze_scroll_target_hwnd = 0
        self._gaze_scroll_target_point = None
        policy = getattr(self, "_gaze_scroll_policy", None)
        if policy is not None:
            policy.reset()
        return was_active

    @QtCore.Slot(str)
    def _handle_gaze_radial_action(self, action_id: str) -> None:
        normalized = str(action_id or "").strip().lower()
        if not normalized:
            return
        if normalized.startswith("spatial:"):
            snapshot = self.spatial_map_snapshot()
            region_id = str(getattr(self, "_spatial_menu_region_id", "") or "")
            region = (
                next(
                    (
                        item
                        for item in snapshot.regions
                        if item.region_id == region_id
                    ),
                    None,
                )
                if snapshot is not None
                else None
            )
            result = self._dispatch_spatial_region_action(normalized, region)
            if not bool(result.get("ok")):
                self._eye_tracking_status_message = str(
                    result.get("error") or "The desktop-region action failed."
                )
            return
        if normalized == "scrolling":
            if bool(getattr(self, "_gaze_scroll_active", False)):
                self._stop_gaze_scrolling()
                self._dismiss_gaze_radial_menu()
                self._play_blink_notification(False)
            else:
                self._start_gaze_scrolling()
            return
        if normalized == "action":
            if not self._gaze_click_target_enabled():
                self._clear_gaze_click_target_highlight()
                return
            self._show_gaze_click_target_menu()
            return
        if normalized == "back":
            if isinstance(
                getattr(self, "_gaze_lfm_click_pending", None),
                vision_click_verification.PendingLfmClickConfirmation,
            ):
                selected_index = int(
                    getattr(self._gaze_lfm_click_pending, "selected_index", 0)
                )
                CompanionOrbController._cancel_lfm_click_confirmation(self)
                self._show_gaze_click_visual_action_menu(selected_index)
                return
            if bool(getattr(self, "_gaze_click_visual_action_menu_open", False)):
                self._show_gaze_click_target_visual_page(self._gaze_click_visual_page)
                return
            self._clear_gaze_click_target_highlight()
            if (
                bool(getattr(self, "_gaze_click_visual_page_open", False))
                and bool(getattr(self, "_gaze_click_targets", {}))
            ):
                self._show_gaze_click_target_direct_page()
                return
            self._gaze_click_scan_generation = int(
                getattr(self, "_gaze_click_scan_generation", 0)
            ) + 1
            CompanionOrbController._cancel_gaze_click_validation(self)
            getattr(self, "_gaze_click_targets", {}).clear()
            getattr(self, "_gaze_click_target_payloads", {}).clear()
            getattr(self, "_gaze_click_visual_targets", []).clear()
            self._gaze_click_visual_page_open = False
            self._gaze_click_visual_action_menu_open = False
            self._gaze_click_visual_selected_index = None
            point = self._eye_tracking_latest_point or (self._gaze_radial_anchor.x(), self._gaze_radial_anchor.y())
            self._show_gaze_radial_main_menu(point)
            return
        if normalized.startswith("click_target") and not self._gaze_click_target_enabled():
            self._clear_gaze_click_target_highlight()
            return
        if normalized == "lfm_click_cancel":
            selected_index = int(
                getattr(
                    getattr(self, "_gaze_lfm_click_pending", None),
                    "selected_index",
                    0,
                )
            )
            CompanionOrbController._cancel_lfm_click_confirmation(self)
            self._show_gaze_click_visual_action_menu(selected_index)
            return
        if normalized == "lfm_click_confirm":
            self._confirm_pending_lfm_click()
            return
        if normalized == "click_target":
            self._show_gaze_click_target_menu()
            return
        if normalized == "click_target_inspect":
            self._show_gaze_click_target_visual_page(0)
            return
        if normalized == "click_target_visual_previous":
            self._show_gaze_click_target_visual_page(self._gaze_click_visual_page - 1)
            return
        if normalized == "click_target_visual_next":
            self._show_gaze_click_target_visual_page(self._gaze_click_visual_page + 1)
            return
        if normalized.startswith("click_target_visual_action:"):
            result = self._dispatch_gaze_click_visual_action(
                normalized.split(":", 1)[1],
            )
            if not bool(result.get("ok")):
                self._eye_tracking_status_message = str(
                    result.get("error") or "The selected visual context action failed."
                )
            return
        if normalized.startswith("click_target_visual:"):
            try:
                index = int(normalized.split(":", 1)[1])
                if index < 0:
                    raise IndexError(index)
                item = self._gaze_click_visual_targets[index]
            except (IndexError, TypeError, ValueError):
                self._clear_gaze_click_target_highlight()
                return
            target = self._click_target_from_payload(item)
            if target is None:
                self._clear_gaze_click_target_highlight()
                return
            self._show_gaze_click_visual_action_menu(index)
            return
        if normalized.startswith("click_target:"):
            target = getattr(self, "_gaze_click_targets", {}).get(normalized)
            if isinstance(target, eye_tracking.ClickTarget):
                self._queue_confirmed_target_click(target, action_id=normalized)
            else:
                self._clear_gaze_click_target_highlight()
            return
        if normalized == "voice":
            self._show_gaze_voice_menu(0)
            return
        if normalized == "voice_prev":
            self._show_gaze_voice_menu(self._gaze_voice_page - 1)
            return
        if normalized == "voice_next":
            self._show_gaze_voice_menu(self._gaze_voice_page + 1)
            return
        if normalized == "reply_style":
            self._show_gaze_reply_style_menu()
            return
        if normalized == "chat":
            chat_anchor = QtCore.QPoint(self._gaze_radial_anchor)
            self._dismiss_gaze_radial_menu()
            self._show_chat_input_popup(chat_anchor)
            return
        if normalized.startswith("voice_select:"):
            voice_file = self._gaze_radial_payloads.get(normalized)
            self._dismiss_gaze_radial_menu()
            if isinstance(voice_file, Path):
                self._select_voice_file(voice_file)
            return
        if normalized.startswith("reply_style:"):
            self._dismiss_gaze_radial_menu()
            self._set_response_style(normalized.split(":", 1)[1])
            return
        if normalized == "read_text":
            context_point = self._gaze_radial_context_point
            self._dismiss_gaze_radial_menu()
            result = self._start_gaze_read_text(point=context_point)
            if not bool(result.get("ok")):
                self._eye_tracking_status_message = str(
                    result.get("error") or "The visible text could not be read."
                )
            return
        if normalized in EYE_TRACKING_CONTEXT_PROMPTS:
            context_point = self._gaze_radial_context_point
            self._dismiss_gaze_radial_menu()
            result = self._queue_gaze_radial_context_action(normalized, context_point)
            if not bool(result.get("ok")):
                self._eye_tracking_status_message = str(
                    result.get("error") or "The visual response could not be prepared."
                )

    def _schedule_gaze_context_retry(self, delay_ms: int, callback) -> None:
        QtCore.QTimer.singleShot(max(0, int(delay_ms)), callback)

    def _queue_gaze_radial_context_action(
        self,
        action_id: str,
        point,
        *,
        bounds_override=None,
    ) -> dict[str, Any]:
        normalized = str(action_id or "").strip().lower()
        if normalized not in EYE_TRACKING_CONTEXT_PROMPTS:
            return {"ok": False, "error": "Unknown visual response action."}
        try:
            context_point = (float(point[0]), float(point[1]))
        except (TypeError, ValueError, IndexError):
            return {"ok": False, "error": "No eye-tracker context is available for this action."}
        if bool(getattr(self, "_eye_tracking_reaction_shutting_down", False)):
            return {"ok": False, "error": "Companion Orb is shutting down."}
        private_bounds: list[int] | None = None
        if bounds_override is not None:
            try:
                private_bounds = [
                    int(value) for value in list(bounds_override)[:4]
                ]
            except (TypeError, ValueError):
                return {"ok": False, "error": "The selected visual context bounds are invalid."}
            if (
                len(private_bounds) != 4
                or private_bounds[2] <= 0
                or private_bounds[3] <= 0
            ):
                return {"ok": False, "error": "The selected visual context bounds are invalid."}
        generation = int(getattr(self, "_gaze_context_dispatch_generation", 0)) + 1
        self._gaze_context_dispatch_generation = generation
        if private_bounds is not None:
            return self._try_gaze_radial_context_action(
                normalized,
                context_point,
                generation,
                0,
                bounds_override=private_bounds,
            )
        return self._try_gaze_radial_context_action(
            normalized,
            context_point,
            generation,
            0,
        )

    def _try_gaze_radial_context_action(
        self,
        action_id: str,
        point: tuple[float, float],
        generation: int,
        attempt: int,
        *,
        bounds_override: list[int] | None = None,
    ) -> dict[str, Any]:
        if (
            int(generation) != int(getattr(self, "_gaze_context_dispatch_generation", 0))
            or bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
        ):
            return {"ok": False, "cancelled": True, "error": "Visual response action was cancelled."}
        if bounds_override is None:
            result = self._request_eye_tracking_reaction(
                True,
                action_id=action_id,
                point_override=point,
            )
        else:
            result = self._request_eye_tracking_reaction(
                True,
                action_id=action_id,
                point_override=point,
                bounds_override=list(bounds_override),
            )
        if bool(result.get("ok")):
            self._debug_event("gaze_context_action_dispatched", action_id=action_id)
            return result
        if bool(result.get("busy")) and int(attempt) + 1 < GAZE_CONTEXT_RETRY_ATTEMPTS:
            next_attempt = int(attempt) + 1
            if int(attempt) == 0:
                self._debug_event(
                    "gaze_context_action_waiting",
                    action_id=action_id,
                )
            if bounds_override is None:
                callback = lambda: self._try_gaze_radial_context_action(
                    action_id,
                    point,
                    generation,
                    next_attempt,
                )
            else:
                callback = lambda: self._try_gaze_radial_context_action(
                    action_id,
                    point,
                    generation,
                    next_attempt,
                    bounds_override=list(bounds_override),
                )
            self._schedule_gaze_context_retry(
                GAZE_CONTEXT_RETRY_INTERVAL_MS,
                callback,
            )
            return {"ok": True, "queued": True, "waiting": True}
        error = str(result.get("error") or "The visual response could not be prepared.")
        self._eye_tracking_status_message = error
        self._debug_event(
            "gaze_context_action_failed",
            action_id=action_id,
            error=error,
        )
        return {"ok": False, "error": error}

    def _dismiss_gaze_radial_menu(self) -> None:
        menu = self._gaze_radial_menu
        if menu is not None:
            menu.hide()
        self._finish_gaze_radial_menu()

    @QtCore.Slot()
    def _finish_gaze_radial_menu(self) -> None:
        reset_spatial_gaze = getattr(self, "_reset_spatial_region_gaze", None)
        if callable(reset_spatial_gaze):
            reset_spatial_gaze()
        stop_scrolling = getattr(self, "_stop_gaze_scrolling", None)
        if callable(stop_scrolling):
            stop_scrolling()
        self._gaze_click_scan_generation = int(
            getattr(self, "_gaze_click_scan_generation", 0)
        ) + 1
        CompanionOrbController._cancel_gaze_click_validation(self)
        CompanionOrbController._cancel_lfm_click_confirmation(self)
        getattr(self, "_gaze_click_targets", {}).clear()
        getattr(self, "_gaze_click_target_payloads", {}).clear()
        getattr(self, "_gaze_click_visual_targets", []).clear()
        self._gaze_click_visual_page_open = False
        self._gaze_click_visual_action_menu_open = False
        self._gaze_click_visual_selected_index = None
        self._clear_gaze_click_target_highlight()
        self._gaze_click_target_page_open = False
        self._gaze_radial_menu_open = False
        self._gaze_radial_context_point = None
        self._gaze_radial_context_hwnd = 0
        self._gaze_radial_scroll_target_point = None
        self._gaze_radial_payloads.clear()
        self._set_gaze_timer_state(False, 0.0)
        self._eye_tracking_interaction_target = None
        self._eye_tracking_interaction_until = 0.0
        self._eye_tracking_last_external_target = None
        self._eye_tracking_last_external_sent_at = 0.0
        self._send_external_runtime({"type": "interaction_target_clear"})
        guard = getattr(self, "_sync_external_pointer_clearance_guard", None)
        if callable(guard):
            guard(False)
        self._mark_user_interaction()
        self._sync_drift_timer()

    def _eye_tracking_read_text_bounds(self, point) -> list[int]:
        base_bounds = list(self._eye_tracking_reaction_bounds(point) or [])
        if len(base_bounds) != 4:
            return []
        try:
            left, top, width, height = (int(value) for value in base_bounds)
        except (TypeError, ValueError):
            return []
        if width <= 0 or height <= 0:
            return []
        expand = interaction_settings.boolish(
            self._last_runtime_config.get(
                "companion_orb_eye_tracking_expand_read_text_area",
                True,
            ),
            default=True,
        )
        if not expand:
            return [left, top, width, height]
        screen_left, _screen_top, screen_width, _screen_height = self._eye_tracking_screen_bounds()
        available_width = max(1, int(float(screen_width)))
        if available_width < width:
            return [left, top, width, height]
        expanded_width = min(width * 2, available_width)
        max_left = float(screen_left) + float(screen_width) - expanded_width
        expanded_left = max(float(screen_left), min(float(left), max_left))
        return [int(round(expanded_left)), top, expanded_width, height]

    def _start_gaze_read_text(self, *, point=None) -> dict[str, Any]:
        selected_point = point if point is not None else self._eye_tracking_latest_point
        if selected_point is None or (
            point is None and time.monotonic() - self._eye_tracking_latest_at > 2.5
        ):
            return {"ok": False, "error": "No recent eye-tracker focus is available."}
        action_id = _reading_action_id(GAZE_READ_TEXT_ACTION)
        if not self._begin_reading_job(action_id):
            return {"ok": False, "error": "Another Companion Orb reading action is still running."}
        try:
            bounds = self._eye_tracking_read_text_bounds(selected_point)
            if not bounds:
                raise RuntimeError("The focused screen area is unavailable.")
            self._start_reading_worker(
                GAZE_READ_TEXT_ACTION,
                selected_text="",
                bounds=bounds,
                private_bounds=True,
            )
        except Exception as exc:
            self._finish_reading_job(action_id, reason="failed")
            return {"ok": False, "error": f"Could not prepare visible text reading: {exc}"}
        return {"ok": True, "queued": True}

    def react_at_gaze(self, *, force: bool = True) -> dict[str, Any]:
        with self._eye_tracking_reaction_lock:
            if self._eye_tracking_reaction_shutting_down:
                return {"ok": False, "error": "Companion Orb is shutting down."}
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        if mode == "off":
            return {"ok": False, "error": "Eye tracking is off."}
        if not self._eye_tracking_orb_active():
            return {"ok": False, "error": "Enable and show the Companion Orb first."}
        if self._eye_tracking_latest_point is None or time.monotonic() - self._eye_tracking_latest_at > 2.5:
            return {"ok": False, "error": "No recent eye-tracker focus is available."}
        if self.thread() == QtCore.QThread.currentThread():
            return self._request_eye_tracking_reaction(bool(force))
        self._proxy.eye_react_requested.emit(bool(force))
        return {"ok": True, "queued": True}

    def _eye_tracking_reaction_is_current(self, generation: int, *, force: bool) -> bool:
        with self._eye_tracking_reaction_lock:
            if self._eye_tracking_reaction_shutting_down:
                return False
            if int(generation) != int(self._eye_tracking_reaction_generation):
                return False
        mode = eye_tracking.normalize_tracking_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_mode", "dwell")
        )
        if mode == "off" or not self._eye_tracking_orb_active():
            return False
        if not force:
            reaction_mode = eye_tracking.normalize_reaction_mode(
                self._last_runtime_config.get("companion_orb_eye_tracking_reaction_mode", "meaningful")
            )
            if mode == "manual" or reaction_mode == "off":
                return False
        return True

    @QtCore.Slot(bool)
    def _request_eye_tracking_reaction(
        self,
        force: bool = False,
        *,
        action_id: str = "react",
        point_override=None,
        bounds_override=None,
    ) -> dict[str, Any]:
        reaction_mode = eye_tracking.normalize_reaction_mode(
            self._last_runtime_config.get("companion_orb_eye_tracking_reaction_mode", "meaningful")
        )
        if not force and reaction_mode == "off":
            return {"ok": False, "error": "Automatic eye-tracker comments are off."}
        point = point_override if point_override is not None else self._eye_tracking_latest_point
        if point is None or (
            point_override is None and time.monotonic() - self._eye_tracking_latest_at > 2.5
        ):
            return {"ok": False, "error": "No recent eye-tracker focus is available."}
        with self._eye_tracking_reaction_lock:
            if self._eye_tracking_reaction_shutting_down:
                return {"ok": False, "error": "Companion Orb is shutting down."}
            if self._eye_tracking_reaction_active:
                return {
                    "ok": False,
                    "busy": True,
                    "error": "An eye-tracker visual reaction is already being prepared.",
                }
            self._eye_tracking_reaction_active = True
            reaction_generation = int(self._eye_tracking_reaction_generation)
        try:
            self._set_eye_tracking_interaction_target(point, duration_seconds=4.0)
            if bounds_override is None:
                capture_bounds = self._eye_tracking_reaction_bounds(point)
            else:
                capture_bounds = [
                    int(value) for value in list(bounds_override)[:4]
                ]
                if (
                    len(capture_bounds) != 4
                    or capture_bounds[2] <= 0
                    or capture_bounds[3] <= 0
                ):
                    raise RuntimeError("The selected visual context bounds are invalid.")
            virtual_rect = self._virtual_desktop_rect()
            if virtual_rect is not None:
                virtual_rect = QtCore.QRect(virtual_rect)
            worker = threading.Thread(
                target=self._capture_eye_tracking_reaction,
                args=(
                    capture_bounds,
                    virtual_rect,
                    bool(force),
                    reaction_generation,
                    _eye_tracking_context_prompt(action_id),
                ),
                daemon=True,
                name="companion-orb-eye-reaction",
            )
            worker.start()
        except Exception as exc:
            with self._eye_tracking_reaction_lock:
                self._eye_tracking_reaction_active = False
            return {"ok": False, "error": f"Could not prepare the visual reaction: {exc}"}
        return {"ok": True, "queued": True}

    def _eye_tracking_reaction_bounds(self, point) -> list[int]:
        left, top, screen_width, screen_height = self._eye_tracking_screen_bounds()
        width = int(max(320.0, min(720.0, screen_width)))
        height = int(max(240.0, min(520.0, screen_height)))
        center_x, center_y = float(point[0]), float(point[1])
        crop_left = max(left, min(center_x - width * 0.5, left + screen_width - width))
        crop_top = max(top, min(center_y - height * 0.5, top + screen_height - height))
        return [int(round(crop_left)), int(round(crop_top)), width, height]

    def _capture_eye_tracking_reaction(
        self,
        capture_bounds: list[int],
        virtual_rect,
        force: bool,
        reaction_generation: int,
        request_content: str = "",
    ) -> None:
        from PIL import ImageGrab

        acquired = False
        output_path: Path | None = None
        try:
            if not self._eye_tracking_reaction_is_current(reaction_generation, force=bool(force)):
                return
            acquired = self._snapshot_capture_lock.acquire(blocking=False)
            if not acquired:
                self._proxy.eye_reaction_result_requested.emit(False, "Another Companion Orb capture is already running.")
                return
            cloaked = self._apply_snapshot_cloak_blocking(True)
            if cloaked:
                time.sleep(0.04)
            try:
                with CompanionOrbController._nc_capture_exclusion_scope(self):
                    desktop = ImageGrab.grab(all_screens=True).convert("RGB")
            finally:
                if cloaked:
                    self._apply_snapshot_cloak_blocking(False)
            if not self._eye_tracking_reaction_is_current(reaction_generation, force=bool(force)):
                return

            crop, crop_box = self._crop_desktop_image_to_bounds(
                desktop,
                capture_bounds,
                virtual_rect,
            )
            if not crop_box or crop.width < 2 or crop.height < 2:
                raise RuntimeError("The selected screen area could not be captured.")
            signature = eye_tracking.average_image_hash(crop)
            if not self._eye_tracking_reaction_is_current(reaction_generation, force=bool(force)):
                return
            reaction_mode = eye_tracking.normalize_reaction_mode(
                self._last_runtime_config.get("companion_orb_eye_tracking_reaction_mode", "meaningful")
            )
            accepted = self._eye_tracking_reaction_gate.accept(
                signature,
                now=time.monotonic(),
                meaningful=reaction_mode == "meaningful",
                force=bool(force),
            )
            if not accepted:
                return
            if not self._eye_tracking_reaction_is_current(reaction_generation, force=bool(force)):
                return

            output_root = (
                Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
                / "runtime"
                / "companion_orb"
                / "visual_reactions"
            )
            output_root.mkdir(parents=True, exist_ok=True)
            output_path = output_root / f"companion_orb_reaction_{time.time_ns()}.jpg"
            crop.save(output_path, format="JPEG", quality=100, optimize=True)
            if not self._eye_tracking_reaction_is_current(reaction_generation, force=bool(force)):
                output_path.unlink(missing_ok=True)
                output_path = None
                return
            content = str(request_content or "").strip() or _eye_tracking_context_prompt("react")
            guidance_text = ""
            guidance_requested = CompanionOrbController._visual_guidance_enabled(
                self,
                "gaze",
            )
            vision_trace_id = ""
            if guidance_requested:
                vision_trace_id = CompanionOrbController._begin_vision_debug_trace(
                    self,
                    output_path,
                    scope="gaze",
                )
                guidance_text = CompanionOrbController._visual_guidance_for_image(
                    self,
                    output_path,
                    scope="gaze",
                    reaction_generation=reaction_generation,
                    trace_id=vision_trace_id,
                )
            if not guidance_text:
                fallback_route = (
                    "main_chat_fallback" if guidance_requested else "main_chat_image"
                )
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "capture",
                    scope="gaze",
                    route=fallback_route,
                )
                _guidance, guidance_text = (
                    CompanionOrbController._main_chat_visual_guidance_for_image(
                        self,
                        str(output_path),
                        {},
                    )
                )
            if not self._eye_tracking_reaction_is_current(
                reaction_generation,
                force=bool(force),
            ):
                output_path.unlink(missing_ok=True)
                output_path = None
                return
            if not guidance_text:
                interpreter = (
                    "LFM visual interpreter"
                    if guidance_requested
                    else "Main Chat visual interpreter"
                )
                raise RuntimeError(f"The {interpreter} did not return usable evidence.")
            CompanionOrbController._submit_guided_orb_response(
                self,
                content,
                guidance_text,
                trace_id=vision_trace_id,
            )
            output_path.unlink(missing_ok=True)
            output_path = None
            self._proxy.eye_reaction_result_requested.emit(True, "Visual reaction queued in Main Chat.")
        except Exception as exc:
            if output_path is not None:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
            self._proxy.eye_reaction_result_requested.emit(False, f"Eye-tracker visual reaction failed: {exc}")
        finally:
            if acquired:
                try:
                    self._snapshot_capture_lock.release()
                except RuntimeError:
                    pass
            with self._eye_tracking_reaction_lock:
                self._eye_tracking_reaction_active = False

    def _submit_guided_orb_response(
        self,
        content: str,
        guidance_text: str,
        *,
        trace_id: str = "",
    ) -> None:
        guidance = str(guidance_text or "").strip()
        if not guidance:
            raise RuntimeError("The visual interpreter did not return usable evidence.")
        accepted_turns = getattr(self, "accepted_turns", None)
        submit = getattr(accepted_turns, "submit", None)
        if not callable(submit):
            raise RuntimeError("The main chat text pipeline is unavailable.")
        tracker = getattr(self, "_vision_pipeline", None)
        route = (
            str(tracker.snapshot().get("route") or "main_chat_image")
            if isinstance(tracker, vision_pipeline.VisionPipelineTracker)
            else "main_chat_image"
        )
        CompanionOrbController._set_vision_pipeline_stage(
            self,
            "main_chat",
            route=route,
        )
        companion_orb_vision_debug.record_event(
            trace_id,
            "main_chat_handoff",
            route=route,
            user_content=str(content or "").strip(),
            hidden_visual_guidance=guidance[:1400],
            output_token_cap=ORB_RESPONSE_MAX_OUTPUT_TOKENS,
            image_attached=False,
        )
        submitted = dict(
            submit(
                str(content or "").strip(),
                role="user",
                metadata={
                    "nc_skip_image_attachment": True,
                    "normal_chat_output_token_cap": ORB_RESPONSE_MAX_OUTPUT_TOKENS,
                    "companion_orb_response_guidance": guidance[:1400],
                    "companion_orb_debug_trace_id": str(trace_id or ""),
                },
            )
            or {}
        )
        if not bool(submitted.get("queued", False)):
            companion_orb_vision_debug.record_event(
                trace_id,
                "main_chat_handoff_rejected",
                result=submitted,
            )
            CompanionOrbController._set_vision_pipeline_stage(
                self,
                "error",
                error=str(submitted.get("reason") or "Main Chat rejected the response"),
            )
            raise RuntimeError(
                str(
                    submitted.get("reason")
                    or "Main Chat did not accept the visual response."
                )
            )

    @QtCore.Slot(bool, str)
    def _handle_eye_tracking_reaction_result(self, success: bool, message: str) -> None:
        self._eye_tracking_status_message = str(message or "").strip()
        if not success:
            self._eye_tracking_status_code = "reaction_error"

    def _apply_window_settings(self):
        window = self._window
        if window is None:
            return
        if self._external_runtime_enabled():
            if window.isVisible():
                window.hide()
            self._apply_click_through(True)
            return
        size = self._window_size()
        if window.width() != size or window.height() != size:
            window.resize(size, size)
        try:
            window.setFlags(self._window_flags())
        except Exception:
            pass
        click_through = interaction_settings.effective_click_through(
            self._last_runtime_config,
            edit_mode=bool(self.bridge.editMode),
            placement_mode=bool(self.bridge.placementMode),
        )
        self.bridge.set_modes(click_through=click_through)
        self._apply_click_through(click_through)
        self._apply_mouse_near_opacity()
        if not self._custom_position:
            self._return_home(animate=window.isVisible())

    def _window_size(self) -> int:
        orb_size = int(self._last_runtime_config.get("companion_orb_size", 92) or 92)
        return max(96, int(orb_size * 2.25))

    def _dock_position(self) -> QtCore.QPoint:
        window_size = self._window_size()
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        margin = 28
        position = str(self._last_runtime_config.get("companion_orb_position", "top-center") or "top-center").strip().lower()
        if position in {"top-center", "bottom-right"}:
            return QtCore.QPoint(geometry.center().x() - int(window_size / 2), geometry.top() + margin)
        if position == "bottom-left":
            return QtCore.QPoint(geometry.left() + margin, geometry.bottom() - window_size - margin)
        if position == "top-left":
            return QtCore.QPoint(geometry.left() + margin, geometry.top() + margin)
        if position == "top-right":
            return QtCore.QPoint(geometry.right() - window_size - margin, geometry.top() + margin)
        return QtCore.QPoint(geometry.center().x() - int(window_size / 2), geometry.top() + margin)

    def _refresh_visibility(self):
        window = self._window
        if window is None:
            return
        if self._external_runtime_enabled():
            if window.isVisible():
                window.hide()
            self._drift_timer.stop()
            self._motion_timer.stop()
            self._menu_poll_timer.stop()
            self._last_drift_tick_at = 0.0
            self._send_external_runtime_snapshot()
            return
        if self._snapshot_cloak_count > 0:
            if window.isVisible():
                window.hide()
            self._sync_menu_poll_timer()
            return
        enabled = bool(self._last_runtime_config.get("companion_orb_enabled", False))
        mode = str(self._last_runtime_config.get("companion_orb_display_mode", "off") or "off").strip().lower()
        if not enabled or mode == "off":
            window.hide()
            self._drift_timer.stop()
            self._reset_drift_target()
            self._menu_poll_timer.stop()
            self._harassment_active = False
            self._clear_poll_drag()
            return
        active = self.bridge.aiState in {"listening", "thinking", "speaking"} or self.bridge.audioLevel > 0.025
        visible = mode in {"docked", "always"} or (mode == "interaction" and active) or self.bridge.editMode or self.bridge.placementMode
        if visible and not window.isVisible():
            window.show()
        elif not visible and window.isVisible():
            window.hide()
        self._sync_drift_timer()
        self._sync_menu_poll_timer()

    def _schedule_return_home(self):
        if not bool(self._last_runtime_config.get("companion_orb_movement_enabled", True)):
            return
        try:
            delay_ms = int(float(self._last_runtime_config.get("companion_orb_return_home_delay", 2.5) or 2.5) * 1000)
        except Exception:
            delay_ms = 2500
        self._return_home_timer.start(max(250, min(30000, delay_ms)))

    def _home_position(self) -> QtCore.QPoint:
        self._custom_position = list(self._last_runtime_config.get("companion_orb_custom_position", []) or [])
        if len(self._custom_position) == 2:
            try:
                return QtCore.QPoint(int(self._custom_position[0]), int(self._custom_position[1]))
            except Exception:
                pass
        return self._dock_position()

    def _return_home(self, *, animate: bool = True):
        window = self._window
        if window is None or self.bridge.editMode or self.bridge.placementMode:
            return
        point = self._home_position()
        self._base_position = QtCore.QPoint(point)
        self._reset_drift_target()
        if animate and window.isVisible():
            self._start_motion_to(point)
        else:
            self._motion_timer.stop()
            window.move(point)
            self._drift_current_point = QtCore.QPointF(float(point.x()), float(point.y()))
            self._sync_drift_timer()

    def _movement_range(self) -> int:
        try:
            return max(0, min(90, int(self._last_runtime_config.get("companion_orb_movement_range", 18) or 0)))
        except Exception:
            return 18

    def _movement_speed(self) -> float:
        try:
            return max(0.10, min(1.75, float(self._last_runtime_config.get("companion_orb_movement_speed", 0.65) or 0.65)))
        except Exception:
            return 0.65

    def _clamped_float_setting(self, key: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(self._last_runtime_config.get(key, default))
        except Exception:
            value = float(default)
        return max(float(minimum), min(float(maximum), value))

    def _aware_motion_enabled(self) -> bool:
        return bool(self._last_runtime_config.get("companion_orb_aware_motion_enabled", True))

    def _awareness_level(self) -> float:
        return self._clamped_float_setting("companion_orb_awareness", 0.55, 0.0, 1.0)

    def _focus_pull(self) -> float:
        return self._clamped_float_setting("companion_orb_focus_pull", 0.65, 0.0, 1.0)

    def _idle_pause_strength(self) -> float:
        return self._clamped_float_setting("companion_orb_idle_pause", 0.45, 0.0, 1.0)

    def _orb_frame_rate(self) -> int:
        try:
            fps = int(self._last_runtime_config.get("companion_orb_frame_rate", 60) or 60)
        except Exception:
            fps = 60
        return min((30, 60, 90, 120), key=lambda candidate: abs(candidate - fps))

    def _timer_interval_ms(self) -> int:
        return max(8, min(33, int(1000 / max(30, self._orb_frame_rate()))))

    def _apply_timer_intervals(self):
        interval = self._timer_interval_ms()
        for timer in (self._drift_timer, self._motion_timer, self._menu_poll_timer):
            if timer.interval() != interval:
                timer.setInterval(interval)
        self._debug_event("timer_interval_applied", frame_rate=self._orb_frame_rate(), interval_ms=interval)

    def _time_scaled_blend(self, blend: float, frame_scale: float) -> float:
        base = max(0.0, min(0.98, float(blend)))
        scale = max(0.10, min(6.0, float(frame_scale)))
        return max(0.0, min(0.98, 1.0 - pow(1.0 - base, scale)))

    def _reset_drift_target(self):
        self._drift_target_point = None
        self._drift_target_kind = ""
        self._aware_idle_pause_until = 0.0
        self._aware_idle_next_pause_at = time.monotonic() + 2.5
        self._aware_idle_pause_point = None

    def _set_manual_drop_anchor(self, point: QtCore.QPoint | QtCore.QPointF, *, duration_seconds: float = DROP_ANCHOR_HOVER_SECONDS):
        anchor = self._clamp_top_left_to_screen(QtCore.QPointF(point))
        self._manual_drop_anchor_point = QtCore.QPoint(int(round(anchor.x())), int(round(anchor.y())))
        self._manual_drop_anchor_until = time.monotonic() + max(2.0, min(60.0, float(duration_seconds)))
        self._debug_event(
            "drop_anchor_set",
            console=True,
            anchor=self._manual_drop_anchor_point,
            duration_seconds=round(float(duration_seconds), 2),
        )
        self._send_external_runtime(
            {
                "type": "drop_anchor",
                "point": [int(self._manual_drop_anchor_point.x()), int(self._manual_drop_anchor_point.y())],
                "duration_seconds": duration_seconds,
            }
        )

    def _manual_drop_anchor_ready(self) -> bool:
        if self._manual_drop_anchor_point is None:
            return False
        if time.monotonic() <= float(self._manual_drop_anchor_until or 0.0):
            return True
        self._manual_drop_anchor_point = None
        self._manual_drop_anchor_until = 0.0
        return False

    def _clear_manual_drop_anchor(self):
        self._manual_drop_anchor_point = None
        self._manual_drop_anchor_until = 0.0

    def _manual_drop_anchor_target(self) -> QtCore.QPointF:
        anchor = self._manual_drop_anchor_point
        if anchor is None:
            return self._clamp_top_left_to_screen(QtCore.QPointF(self._home_position()))
        amount = min(18.0, max(4.0, float(self._movement_range()) * 0.35))
        t = time.monotonic() * max(0.2, self._movement_speed())
        x = float(anchor.x()) + math.sin(t * 0.47) * amount + math.sin(t * 0.19 + 1.3) * amount * 0.35
        y = float(anchor.y()) + math.cos(t * 0.41 + 0.6) * amount * 0.55 + math.sin(t * 0.21 + 2.0) * amount * 0.25
        return self._clamp_top_left_to_screen(QtCore.QPointF(x, y))

    def _current_orb_top_left_for_drop(self) -> QtCore.QPoint | None:
        if self._external_runtime_enabled() and self._external_orb_top_left is not None:
            return QtCore.QPoint(self._external_orb_top_left)
        if self._window is not None:
            return self._window.frameGeometry().topLeft()
        return None

    def _comment_focus_matches_manual_drop_region(self) -> bool:
        if not self._manual_drop_anchor_ready() or not self._manual_inspection_active():
            return False
        focus = self._normalize_bounds(self._comment_focus_bounds)
        manual = self._normalize_bounds(self._manual_inspection_bounds)
        if not focus or not manual:
            return False
        focus_area = max(1.0, float(focus[2]) * float(focus[3]))
        manual_area = max(1.0, float(manual[2]) * float(manual[3]))
        overlap = self._bounds_overlap_area(focus, manual)
        # The broad initial drop-focus uses the full manual crop. Keep that anchored
        # so the orb hovers where the user released it; tighter OCR/object bounds
        # are still allowed to pull the orb toward the detail being discussed.
        return bool(overlap / manual_area >= 0.72 and focus_area >= manual_area * 0.55)

    def _stable_drift_target(
        self,
        kind: str,
        desired: QtCore.QPointF | QtCore.QPoint,
        *,
        deadzone: float,
        blend: float,
        frame_scale: float = 1.0,
    ) -> QtCore.QPointF:
        desired_point = self._clamp_top_left_to_screen(QtCore.QPointF(desired))
        current = self._drift_target_point
        normalized_kind = str(kind or "idle")
        if current is None or self._drift_target_kind != normalized_kind:
            self._drift_target_point = QtCore.QPointF(desired_point)
            self._drift_target_kind = normalized_kind
            return QtCore.QPointF(desired_point)
        distance = math.hypot(desired_point.x() - current.x(), desired_point.y() - current.y())
        if distance <= max(0.0, float(deadzone)):
            return QtCore.QPointF(current)
        factor = max(0.04, min(0.85, self._time_scaled_blend(float(blend), frame_scale)))
        if distance > 420.0 and normalized_kind in {"comment", "harassment"}:
            factor = max(factor, 0.34)
        next_point = QtCore.QPointF(
            current.x() + (desired_point.x() - current.x()) * factor,
            current.y() + (desired_point.y() - current.y()) * factor,
        )
        self._drift_target_point = next_point
        return QtCore.QPointF(next_point)

    def _sync_drift_timer(self):
        if self._window is None:
            self._drift_timer.stop()
            self._last_drift_tick_at = 0.0
            return
        harassment_enabled = bool(self._last_runtime_config.get("companion_orb_harassment_enabled", False))
        comment_focus_enabled = self._comment_focus_ready()
        eye_interaction_enabled = self._eye_tracking_interaction_ready()
        enabled = (
            (
                bool(self._last_runtime_config.get("companion_orb_movement_enabled", True))
                and self._movement_range() > 0
            )
            or harassment_enabled
            or comment_focus_enabled
            or eye_interaction_enabled
            or bool(self._last_runtime_config.get("companion_orb_mouse_near_fade", False))
            or bool(self._last_runtime_config.get("companion_orb_avoid_mouse", False))
        ) and (
            self._window.isVisible()
            and not self.bridge.editMode
            and not self.bridge.placementMode
            and not self._motion_timer.isActive()
            and not self._menu_open
            and self._drag_offset is None
            and not self._poll_drag_active
        )
        if self._debug_last_timer_enabled is None or self._debug_last_timer_enabled != bool(enabled):
            self._debug_last_timer_enabled = bool(enabled)
            self._debug_event(
                "drift_timer_state",
                enabled=bool(enabled),
                visible=bool(self._window.isVisible()),
                edit_mode=bool(self.bridge.editMode),
                placement_mode=bool(self.bridge.placementMode),
                motion_active=bool(self._motion_timer.isActive()),
                comment_focus=bool(comment_focus_enabled),
                harassment=bool(harassment_enabled),
            )
        if enabled:
            if self._base_position is None:
                self._base_position = self._home_position()
            if self._drift_current_point is None:
                top_left = self._window.frameGeometry().topLeft()
                self._drift_current_point = QtCore.QPointF(float(top_left.x()), float(top_left.y()))
            if not self._drift_timer.isActive():
                self._last_drift_tick_at = time.monotonic()
                self._drift_timer.start()
        else:
            self._drift_timer.stop()
            self._last_drift_tick_at = 0.0
            self._reset_drift_target()
            self._harassment_active = False
            if not comment_focus_enabled:
                self._clear_comment_focus()
            self._apply_mouse_near_opacity(reset=True)

    def _sync_menu_poll_timer(self):
        window = self._window
        should_run = bool(window is not None and window.isVisible() and self.bridge.clickThrough and not self._menu_open)
        if should_run:
            if not self._menu_poll_timer.isActive():
                self._menu_poll_timer.start()
        elif self._menu_poll_timer.isActive():
            self._menu_poll_timer.stop()

    def _harassment_delay_seconds(self) -> float:
        try:
            return max(5.0, min(300.0, float(self._last_runtime_config.get("companion_orb_harassment_timer_seconds", 45) or 45)))
        except Exception:
            return 45.0

    def _harassment_ready(self) -> bool:
        if not bool(self._last_runtime_config.get("companion_orb_harassment_enabled", False)):
            self._harassment_active = False
            return False
        if self._menu_open or self._drag_offset is not None or self._poll_drag_active:
            return False
        if self._comment_focus_ready():
            return False
        return (time.monotonic() - self._last_user_interaction_at) >= self._harassment_delay_seconds()

    @QtCore.Slot(dict)
    def _set_comment_focus(self, payload):
        data = dict(payload or {})
        drop = getattr(self, '_drop_capture', None)
        trace = str(data.get('drop_trace_id') or '')
        if drop is not None and trace and (
            trace != getattr(self, '_active_drop_trace_id', '') or not drop.active
        ):
            return
        is_current=data.pop('_is_current',None)
        if callable(is_current) and not is_current():
            return
        target = data.get("target")
        explicit_bounds = self._normalize_bounds(data.get("focus_bounds"))
        fallback_bounds = self._normalize_bounds(data.get("bounds")) or target_bounds(target if isinstance(target, dict) else None)
        bounds = list(explicit_bounds or fallback_bounds)
        focus_text = " ".join(
            str(data.get(key) or "").strip()
            for key in ("focus_text", "text", "comment", "message", "candidate", "summary", "attention")
            if str(data.get(key) or "").strip()
        )
        label = str(data.get("focus_label") or data.get("label") or data.get("attention") or "").strip()
        text = " ".join(part for part in (focus_text, label) if part)
        if focus_text:
            self._pending_comment_focus_text = focus_text
            self._pending_comment_focus_label = label[:120]
        focus_source = "explicit" if explicit_bounds else ("fallback" if fallback_bounds else "none")
        if not explicit_bounds:
            if self._drop_focus_text_is_stale(text, label):
                self._debug_event(
                    "focus_rejected",
                    console=True,
                    source=focus_source,
                    reason="stale_drop_inspection_text",
                    focus_text=text,
                    fallback_bounds=fallback_bounds,
                )
                return
            ocr_focus = self._ocr_focus_bounds_for_text(text, fallback_bounds=bounds)
            if ocr_focus:
                bounds = ocr_focus
                focus_source = "ocr" if self._last_snapshot_ocr_regions else "fallback"
            elif self._last_snapshot_ocr_regions:
                self._debug_event(
                    "focus_ocr_no_match",
                    focus_text=text,
                    fallback_bounds=bounds,
                    ocr_region_count=len(self._last_snapshot_ocr_regions or []),
                    ocr_text=str(self._last_snapshot_text or ""),
                )
        normalized = self._normalize_bounds(bounds)
        if not normalized:
            self._debug_event(
                "focus_rejected",
                console=True,
                source=focus_source,
                focus_text=text,
                explicit_bounds=explicit_bounds,
                fallback_bounds=fallback_bounds,
                target=target if isinstance(target, dict) else {},
            )
            self._clear_comment_focus()
            return
        clipped = self._clip_bounds_to_virtual_desktop(normalized)
        if clipped and clipped != normalized:
            self._debug_event(
                "focus_bounds_clipped",
                original_bounds=normalized,
                clipped_bounds=clipped,
                source=focus_source,
                text=text,
            )
            normalized = clipped
        focus_grid = self._focus_grid_for_bounds(normalized)
        try:
            duration = float(data.get("duration_seconds", COMMENT_FOCUS_DEFAULT_SECONDS) or COMMENT_FOCUS_DEFAULT_SECONDS)
        except Exception:
            duration = COMMENT_FOCUS_DEFAULT_SECONDS
        try:
            hover_offset = max(
                0.0,
                min(300.0, float(data.get("hover_offset_px", 0.0) or 0.0)),
            )
        except (TypeError, ValueError, OverflowError):
            hover_offset = 0.0
        stay_during_speech = bool(data.get("stay_during_speech", False))
        return_behavior = str(
            data.get("return_behavior") or "after_delay"
        ).strip().lower()
        if return_behavior not in {"after_speech", "after_delay", "stay"}:
            return_behavior = "after_delay"
        if self._manual_inspection_active() and any(
            marker in f"{text or ''} {label or ''}".lower()
            for marker in ("drop inspection", "dropped companion orb", "snapshot", "manual")
        ):
            duration = max(duration, DROP_FOCUS_SECONDS)
        signature = self._comment_focus_signature(normalized, text)
        now = time.monotonic()
        if signature == self._last_comment_focus_signature and self._comment_focus_ready():
            self._comment_focus_until = max(
                self._comment_focus_until,
                now + max(2.0, min(45.0, duration)),
            )
            if focus_grid:
                self._comment_focus_grid = dict(focus_grid)
            self._comment_focus_hover_offset_px = hover_offset
            self._comment_focus_stay_during_speech = stay_during_speech
            self._comment_focus_return_behavior = return_behavior
            self._debug_event(
                "focus_extended",
                bounds=normalized,
                label=label[:120],
                source=focus_source,
                duration_seconds=duration,
                text=text,
                focus_grid=focus_grid,
            )
            return
        self._comment_focus_bounds = normalized
        self._comment_focus_grid = dict(focus_grid or {})
        self._comment_focus_until = now + max(2.0, min(45.0, duration))
        self._comment_focus_label = label[:120]
        self._comment_focus_hover_offset_px = hover_offset
        self._comment_focus_stay_during_speech = stay_during_speech
        self._comment_focus_return_behavior = return_behavior
        self._comment_focus_seen_speech = False
        self._last_comment_focus_signature = signature
        self._last_comment_focus_set_at = now
        self._reset_drift_target()
        self._harassment_active = False
        self._debug_event(
            "focus_set",
            console=True,
            bounds=normalized,
            label=label[:120],
            source=focus_source,
            duration_seconds=duration,
            text=text,
            focus_grid=focus_grid,
            snapshot_bounds=list(self._last_snapshot_bounds or []),
            ocr_region_count=len(self._last_snapshot_ocr_regions or []),
        )
        self._send_external_runtime(
            {
                "type": "comment_focus",
                "payload": {
                    "bounds": list(normalized),
                    "focus_bounds": list(normalized),
                    "label": label[:120],
                    "focus_text": focus_text,
                    "duration_seconds": duration,
                    "hover_offset_px": hover_offset,
                    "stay_during_speech": stay_during_speech,
                    "return_behavior": return_behavior,
                    "manual_drop": bool(data.get("manual_drop", False)),
                    "drop_anchor": list(data.get("drop_anchor") or []),
                    "drop_trace_id": str(data.get("drop_trace_id") or self._active_drop_trace_id or ""),
                },
            }
        )
        self._sync_drift_timer()

    def _clip_bounds_to_virtual_desktop(self, bounds, *, virtual_rect=None, image_size=None) -> list[int]:
        normalized = self._normalize_bounds(bounds)
        if not normalized:
            return []
        left, top, width, height = normalized
        if virtual_rect is None:
            virtual_rect = self._virtual_desktop_rect()
        if virtual_rect is not None and virtual_rect.width() > 0 and virtual_rect.height() > 0:
            clip_left = int(virtual_rect.x())
            clip_top = int(virtual_rect.y())
            clip_width = int(virtual_rect.width())
            clip_height = int(virtual_rect.height())
        elif image_size:
            try:
                clip_width, clip_height = [int(value) for value in list(image_size or [])[:2]]
            except Exception:
                return normalized
            clip_left = 0
            clip_top = 0
        else:
            return normalized
        right = min(left + width, clip_left + clip_width)
        bottom = min(top + height, clip_top + clip_height)
        clipped_left = max(left, clip_left)
        clipped_top = max(top, clip_top)
        if right <= clipped_left or bottom <= clipped_top:
            return []
        return [int(clipped_left), int(clipped_top), int(right - clipped_left), int(bottom - clipped_top)]

    @QtCore.Slot(dict)
    def _remember_snapshot_context(self, payload):
        snapshots = list((payload or {}).get("snapshots") or [])
        if not snapshots and isinstance(payload, dict):
            snapshots = [payload]
        best_regions: list[dict[str, Any]] = []
        best_bounds: list[int] = []
        best_text = ""
        best_image_path = ""
        ocr_image_path = ""
        ocr_bounds: list[int] = []
        found_context = False
        active_inspection_id = int(self._active_snapshot_inspection_id or 0)
        for snapshot in reversed(snapshots):
            if not isinstance(snapshot, dict):
                continue
            metadata = dict(snapshot.get("metadata") or {})
            try:
                snapshot_inspection_id = int(metadata.get("manual_inspection_id") or snapshot.get("manual_inspection_id") or 0)
            except Exception:
                snapshot_inspection_id = 0
            drop = getattr(self, '_drop_capture', None)
            if drop is not None and snapshot_inspection_id and (
                snapshot_inspection_id != drop.inspection_id or not drop.active
            ):
                continue
            if active_inspection_id and not snapshot_inspection_id and self._manual_inspection_active():
                self._debug_event(
                    "snapshot_context_untracked_ignored",
                    active_inspection_id=active_inspection_id,
                    image_path=str(snapshot.get("image_path") or metadata.get("image_path") or ""),
                )
                continue
            if snapshot_inspection_id and active_inspection_id and snapshot_inspection_id < active_inspection_id:
                self._debug_event(
                    "snapshot_context_stale_ignored",
                    snapshot_inspection_id=snapshot_inspection_id,
                    active_inspection_id=active_inspection_id,
                    image_path=str(snapshot.get("image_path") or metadata.get("image_path") or ""),
                )
                continue
            lfm_context = metadata.get("lfm_visual_context")
            lfm_context = dict(lfm_context) if isinstance(lfm_context, Mapping) else {}
            lfm_regions = list(lfm_context.get("regions") or [])
            ocr_regions = list(
                metadata.get("ocr_regions") or snapshot.get("ocr_regions") or []
            )
            regions = lfm_regions + ocr_regions
            image_path = str(snapshot.get("image_path") or metadata.get("image_path") or "").strip()
            bounds = self._normalize_bounds(
                snapshot.get("bounds")
                or metadata.get("screen_bounds")
                or target_bounds(metadata.get("target") if isinstance(metadata.get("target"), dict) else None)
                or target_bounds(snapshot.get("target") if isinstance(snapshot.get("target"), dict) else None)
            )
            if regions or bounds:
                best_regions = [dict(item or {}) for item in regions if isinstance(item, dict)]
                best_bounds = bounds
                best_text = str(
                    metadata.get("ocr_text")
                    or snapshot.get("ocr_text")
                    or lfm_context.get("user_focus")
                    or lfm_context.get("scene_summary")
                    or ""
                ).strip()
                if not best_text:
                    best_text = " ".join(str(item.get("text") or "") for item in best_regions if item.get("text"))
                if image_path and bounds and not best_regions:
                    ocr_image_path = image_path
                    ocr_bounds = list(bounds)
                best_image_path = str(image_path or "")
                found_context = True
                break
        if not found_context:
            self._debug_event("snapshot_context_empty", active_inspection_id=active_inspection_id)
            return
        self._last_snapshot_ocr_regions = best_regions
        self._last_snapshot_bounds = best_bounds
        self._last_snapshot_text = best_text.strip()
        if best_bounds:
            self._last_snapshot_image_path = best_image_path
        self._debug_event(
            "snapshot_context_received",
            image_path=best_image_path,
            bounds=best_bounds,
            ocr_region_count=len(best_regions),
            ocr_text=best_text.strip(),
            active_inspection_id=active_inspection_id,
        )
        if ocr_image_path and ocr_bounds:
            self._start_snapshot_ocr_worker(ocr_image_path, ocr_bounds)
        if self._pending_comment_focus_text and best_bounds:
            self._set_comment_focus(
                {
                    "text": self._pending_comment_focus_text,
                    "label": self._pending_comment_focus_label or "comment",
                    "bounds": list(best_bounds),
                    "duration_seconds": COMMENT_FOCUS_DEFAULT_SECONDS,
                }
            )

    def _start_snapshot_ocr_worker(self, image_path, bounds):
        screen_bounds = self._normalize_bounds(bounds)
        path = str(Path(str(image_path or "")))
        if not path or not screen_bounds:
            return
        key = f"{path}|{','.join(str(value) for value in screen_bounds)}"
        if key in self._ocr_jobs:
            return
        if len(self._ocr_jobs) >= OCR_MAX_BACKGROUND_JOBS:
            self._debug_event("ocr_worker_skipped", reason="max_jobs", image_path=path, bounds=screen_bounds)
            return
        self._ocr_jobs.add(key)
        self._debug_event("ocr_worker_started", image_path=path, bounds=screen_bounds)

        def worker():
            payload = {
                "key": key,
                "image_path": path,
                "bounds": list(screen_bounds),
                "ocr": {"regions": [], "text": "", "backend": "none"},
                "error": "",
            }
            try:
                deferred_attempts = 0
                for _attempt in range(OCR_BUSY_DEFER_ATTEMPTS):
                    if not self._engine_busy_for_background_ocr():
                        break
                    deferred_attempts += 1
                    time.sleep(OCR_BUSY_DEFER_SECONDS)
                if self._last_snapshot_image_path and path != self._last_snapshot_image_path:
                    self._debug_event("ocr_worker_stale", image_path=path, latest_image_path=self._last_snapshot_image_path)
                    self._proxy.ocr_result_requested.emit(payload)
                    return
                result = snapshot_ocr.extract_snapshot_regions(path, screen_bounds=screen_bounds, max_regions=OCR_MAX_REGIONS,
                    include_window_text=not self._last_runtime_config.get('companion_orb_exclude_nc_from_captures', False))
                sidecar = snapshot_ocr.write_sidecar(path, result)
                if sidecar:
                    result["sidecar"] = sidecar
                payload["ocr"] = dict(result or {})
                self._debug_event(
                    "ocr_worker_finished",
                    image_path=path,
                    bounds=screen_bounds,
                    backend=str(result.get("backend") or "none"),
                    region_count=len(result.get("regions") or []),
                    deferred_attempts=deferred_attempts,
                )
            except Exception as exc:
                payload["error"] = str(exc)
                self._debug_event("ocr_worker_failed", console=True, image_path=path, bounds=screen_bounds, error=str(exc))
            self._proxy.ocr_result_requested.emit(payload)

        threading.Thread(target=worker, daemon=True, name="companion-orb-ocr").start()

    def _engine_busy_for_background_ocr(self) -> bool:
        try:
            snapshot = self.orb_runtime.busy_snapshot()
        except Exception:
            return False
        return any(bool(value) for value in dict(snapshot or {}).values())

    @QtCore.Slot(dict)
    def _apply_snapshot_ocr_result(self, payload):
        data = dict(payload or {})
        key = str(data.get("key") or "")
        if key:
            self._ocr_jobs.discard(key)
        image_path = str(data.get("image_path") or "")
        if self._last_snapshot_image_path and image_path and image_path != self._last_snapshot_image_path:
            return
        result = dict(data.get("ocr") or {})
        bounds = self._normalize_bounds(result.get("screen_bounds") or data.get("bounds"))
        regions = [dict(item or {}) for item in list(result.get("regions") or []) if isinstance(item, dict)]
        self._last_snapshot_ocr_regions = regions
        if bounds:
            self._last_snapshot_bounds = bounds
        self._last_snapshot_text = str(result.get("text") or "").strip()
        if data.get("error"):
            self._log(f"Companion Orb OCR failed: {data.get('error')}")
            return
        if regions:
            self._log(
                f"Companion Orb OCR stored {len(regions)} region(s) "
                f"using {result.get('backend') or 'unknown'}."
            )
        self._debug_event(
            "ocr_result_applied",
            image_path=image_path,
            bounds=bounds,
            backend=str(result.get("backend") or "none"),
            region_count=len(regions),
            text=self._last_snapshot_text,
        )
        if self._pending_comment_focus_text and self._last_snapshot_bounds:
            self._set_comment_focus(
                {
                    "text": self._pending_comment_focus_text,
                    "label": self._pending_comment_focus_label or "comment",
                    "bounds": list(self._last_snapshot_bounds),
                    "duration_seconds": COMMENT_FOCUS_DEFAULT_SECONDS,
                }
            )

    def focus_comment_text(self, payload):
        self.request_comment_text_focus(payload)

    @QtCore.Slot(dict)
    def _focus_comment_text(self, payload):
        request = dict(payload or {})
        text = " ".join(
            str(request.get(key) or "").strip()
            for key in ("focus_text", "candidate", "summary", "attention", "message", "comment", "text")
            if str(request.get(key) or "").strip()
        )
        explicit_bounds = self._normalize_bounds(request.get("focus_bounds"))
        fallback_bounds = self._normalize_bounds(request.get("bounds"))
        if not text and not explicit_bounds and not fallback_bounds:
            return
        self._pending_comment_focus_text = text
        self._pending_comment_focus_label = str(request.get("focus_label") or request.get("attention") or request.get("source") or "comment").strip()[:120]
        self.request_comment_focus(
            {
                "focus_bounds": list(explicit_bounds or []),
                "focus_text": str(request.get("focus_text") or text or ""),
                "focus_label": self._pending_comment_focus_label,
                "text": text,
                "label": self._pending_comment_focus_label,
                "bounds": list(explicit_bounds or fallback_bounds or self._last_snapshot_bounds or []),
                "duration_seconds": COMMENT_FOCUS_DEFAULT_SECONDS,
                "stay_during_speech": bool(request.get("stay_during_speech", False)),
                "return_behavior": str(
                    request.get("return_behavior") or "after_delay"
                ),
            }
        )

    def _ocr_focus_bounds_for_text(self, text: str, *, fallback_bounds=None) -> list[int]:
        fallback = self._normalize_bounds(fallback_bounds) or list(self._last_snapshot_bounds or [])
        regions = list(self._last_snapshot_ocr_regions or [])
        if self._drop_focus_text_is_stale(text, ""):
            self._debug_event("ocr_focus_miss", text=text, reason="stale_drop_inspection_text")
            return []
        if not regions and not fallback:
            self._debug_event("ocr_focus_miss", text=text, reason="no_regions_or_fallback")
            return []
        match = snapshot_ocr.best_region_for_text(text, regions, fallback_bounds=fallback)
        if isinstance(match, dict) and str(match.get("kind") or "") == "fallback" and regions:
            visual_match = self._visual_focus_region_for_text(text, regions, fallback_bounds=fallback)
            if visual_match:
                match = visual_match
        bounds = self._normalize_bounds(match.get("screen_bounds") if isinstance(match, dict) else None)
        self._debug_event(
            "ocr_focus_resolved" if bounds else "ocr_focus_miss",
            console=bool(bounds),
            text=text,
            resolved_bounds=bounds,
            fallback_bounds=fallback,
            match_text=str(match.get("text") or "") if isinstance(match, dict) else "",
            match_kind=str(match.get("kind") or "") if isinstance(match, dict) else "",
            match_backend=str(match.get("backend") or "") if isinstance(match, dict) else "",
            match_score=match.get("match_score") if isinstance(match, dict) else None,
            focus_grid=self._focus_grid_for_bounds(bounds) if bounds else {},
            region_count=len(regions),
        )
        return bounds or fallback

    def _drop_focus_text_is_stale(self, text: str, label: str = "") -> bool:
        haystack = f"{text or ''} {label or ''}".strip().lower()
        if not any(
            marker in haystack
            for marker in (
                "drop inspection",
                "dropped companion orb",
                "dropped orb",
                "dropped content",
                "manual drop",
                "sensory ping",
                "point of interest",
            )
        ):
            return False
        return not self._manual_inspection_active()

    def _manual_inspection_active(self) -> bool:
        bounds = self._normalize_bounds(self._manual_inspection_bounds)
        return bool(bounds and time.monotonic() <= float(self._manual_inspection_until or 0.0))

    def _clear_comment_focus(self):
        had_focus = bool(self._comment_focus_bounds)
        previous_bounds = list(self._comment_focus_bounds or [])
        previous_label = str(self._comment_focus_label or "")
        self._comment_focus_bounds = []
        self._comment_focus_grid = {}
        self._comment_focus_until = 0.0
        self._comment_focus_label = ""
        self._comment_focus_hover_offset_px = 0.0
        self._comment_focus_stay_during_speech = False
        self._comment_focus_return_behavior = "after_delay"
        self._comment_focus_seen_speech = False
        self._last_comment_focus_signature = ""
        clear_follow = getattr(self, "_clear_spatial_follow_target", None)
        if callable(clear_follow):
            clear_follow()
        self._reset_drift_target()
        if had_focus:
            self._debug_event("focus_cleared", bounds=previous_bounds, label=previous_label)

    def _clear_snapshot_context(self, *, reason: str = "manual_inspection"):
        had_context = bool(self._last_snapshot_bounds or self._last_snapshot_ocr_regions or self._last_snapshot_image_path)
        previous_image = str(self._last_snapshot_image_path or "")
        self._last_snapshot_ocr_regions = []
        self._last_snapshot_bounds = []
        self._last_snapshot_text = ""
        self._last_snapshot_image_path = ""
        self._pending_comment_focus_text = ""
        self._pending_comment_focus_label = ""
        if had_context:
            self._debug_event("snapshot_context_cleared", reason=reason, previous_image_path=previous_image)

    def _comment_focus_ready(self) -> bool:
        if not self._comment_focus_bounds:
            return False
        now = time.monotonic()
        return_behavior = str(
            getattr(self, "_comment_focus_return_behavior", "after_delay")
            or "after_delay"
        ).strip().lower()
        if return_behavior == "stay":
            return True
        speaking = bool(
            self.bridge.aiState == "speaking" or self.bridge.audioLevel > 0.025
        )
        if speaking:
            self._comment_focus_seen_speech = True
            if bool(getattr(self, "_comment_focus_stay_during_speech", False)) or return_behavior == "after_speech":
                self._comment_focus_until = max(self._comment_focus_until, now + 1.25)
        elif return_behavior == "after_speech" and bool(
            getattr(self, "_comment_focus_seen_speech", False)
        ):
            self._clear_comment_focus()
            return False
        if now > self._comment_focus_until:
            self._clear_comment_focus()
            return False
        return True

    def _normalize_bounds(self, bounds) -> list[int]:
        try:
            values = [int(value) for value in list(bounds or [])[:4]]
        except Exception:
            return []
        if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
            return []
        return values

    def _comment_focus_signature(self, bounds, text: str = "") -> str:
        normalized = self._normalize_bounds(bounds)
        if not normalized:
            return ""
        snapped = [int(round(float(value) / 12.0) * 12) for value in normalized]
        label = " ".join(str(text or "").strip().lower().split())[:180]
        return f"{','.join(str(value) for value in snapped)}|{label}"

    def _screen_rect_for_bounds(self, bounds) -> QtCore.QRect:
        normalized = self._normalize_bounds(bounds)
        if normalized:
            left, top, width, height = normalized
            center = QtCore.QPoint(int(round(left + width * 0.5)), int(round(top + height * 0.5)))
            top_left = QtCore.QPoint(int(left), int(top))
        else:
            center = QtGui.QCursor.pos()
            top_left = center
        app = QtGui.QGuiApplication.instance()
        screen = None
        if app is not None:
            screen = (
                QtGui.QGuiApplication.screenAt(center)
                or QtGui.QGuiApplication.screenAt(top_left)
                or (self._window.screen() if self._window is not None else None)
                or QtGui.QGuiApplication.primaryScreen()
            )
        if screen is not None:
            geometry = screen.availableGeometry()
            if geometry.width() > 0 and geometry.height() > 0:
                return QtCore.QRect(geometry)
        virtual_rect = self._virtual_desktop_rect()
        if virtual_rect is not None and virtual_rect.width() > 0 and virtual_rect.height() > 0:
            return QtCore.QRect(virtual_rect)
        return QtCore.QRect(0, 0, 1280, 720)

    def _focus_grid_for_bounds(self, bounds) -> dict[str, Any]:
        normalized = self._normalize_bounds(bounds)
        if not normalized:
            return {}
        screen_rect = self._screen_rect_for_bounds(normalized)
        if screen_rect.width() <= 0 or screen_rect.height() <= 0:
            return {}
        columns = FOCUS_GRID_COLUMNS
        rows = FOCUS_GRID_ROWS
        left, top, width, height = normalized
        center_x = float(left) + float(width) * 0.5
        center_y = float(top) + float(height) * 0.5
        rel_x = max(0.0, min(float(screen_rect.width()) - 1.0, center_x - float(screen_rect.left())))
        rel_y = max(0.0, min(float(screen_rect.height()) - 1.0, center_y - float(screen_rect.top())))
        col = max(0, min(columns - 1, int(rel_x / max(1.0, float(screen_rect.width()) / columns))))
        row = max(0, min(rows - 1, int(rel_y / max(1.0, float(screen_rect.height()) / rows))))
        cell_left = int(round(screen_rect.left() + (screen_rect.width() * col / columns)))
        cell_top = int(round(screen_rect.top() + (screen_rect.height() * row / rows)))
        cell_right = int(round(screen_rect.left() + (screen_rect.width() * (col + 1) / columns)))
        cell_bottom = int(round(screen_rect.top() + (screen_rect.height() * (row + 1) / rows)))
        lanes = self._focus_grid_lane_order(col, row, columns, rows, center_x, screen_rect)
        return {
            "columns": columns,
            "rows": rows,
            "cell": [col + 1, row + 1],
            "cell_index": [col, row],
            "cell_bounds": [cell_left, cell_top, max(1, cell_right - cell_left), max(1, cell_bottom - cell_top)],
            "screen_bounds": [int(screen_rect.left()), int(screen_rect.top()), int(screen_rect.width()), int(screen_rect.height())],
            "focus_bounds": list(normalized),
            "target_center": [round(center_x, 2), round(center_y, 2)],
            "lane_order": lanes,
        }

    def _focus_grid_lane_order(self, col: int, row: int, columns: int, rows: int, center_x: float, screen_rect: QtCore.QRect) -> list[str]:
        lanes: list[str] = []

        def add(value: str):
            if value not in lanes:
                lanes.append(value)

        if col <= 1:
            add("right")
        elif col >= columns - 2:
            add("left")
        elif row <= 0:
            add("below")
        elif row >= rows - 1:
            add("above")
        elif bool(self._last_runtime_config.get("companion_orb_avoid_center", True)):
            screen_center_x = float(screen_rect.left()) + float(screen_rect.width()) * 0.5
            add("left" if center_x >= screen_center_x else "right")
        else:
            add("right")
        if row <= 1:
            add("below")
        if row >= rows - 2:
            add("above")
        if col < columns // 2:
            add("right")
            add("left")
        else:
            add("left")
            add("right")
        add("below")
        add("above")
        return lanes

    def _clamp_top_left_to_rect(self, point: QtCore.QPointF, rect: QtCore.QRect) -> QtCore.QPointF:
        window = self._window
        if window is None or rect.width() <= 0 or rect.height() <= 0:
            return QtCore.QPointF(point)
        max_x = float(rect.right() - window.width())
        max_y = float(rect.bottom() - window.height())
        x = max(float(rect.left()), min(float(point.x()), max_x))
        y = max(float(rect.top()), min(float(point.y()), max_y))
        return QtCore.QPointF(x, y)

    def _bounds_overlap_area(self, left_bounds, right_bounds) -> float:
        left = self._normalize_bounds(left_bounds)
        right = self._normalize_bounds(right_bounds)
        if not left or not right:
            return 0.0
        ax, ay, aw, ah = left
        bx, by, bw, bh = right
        overlap_w = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        overlap_h = max(0, min(ay + ah, by + bh) - max(ay, by))
        return float(overlap_w * overlap_h)

    def _comment_focus_grid_target(self, grid: dict[str, Any]) -> QtCore.QPointF:
        window = self._window
        if window is None:
            return self._clamp_top_left_to_screen(QtCore.QPointF(0.0, 0.0))
        focus_bounds = self._normalize_bounds(grid.get("focus_bounds")) or self._normalize_bounds(self._comment_focus_bounds)
        cell_bounds = self._normalize_bounds(grid.get("cell_bounds")) or focus_bounds
        screen_bounds = self._normalize_bounds(grid.get("screen_bounds"))
        screen_rect = QtCore.QRect(*screen_bounds) if screen_bounds else self._screen_rect_for_bounds(focus_bounds)
        left, top, width, height = focus_bounds
        cell_left, cell_top, cell_width, cell_height = cell_bounds
        focus_center_x = float(left) + float(width) * 0.5
        focus_center_y = float(top) + float(height) * 0.5
        screen_area = max(1.0, float(screen_rect.width()) * float(screen_rect.height()))
        focus_area = max(1.0, float(width) * float(height))
        if focus_area / screen_area > 0.28:
            anchor_x = float(cell_left) + float(cell_width) * 0.5
            anchor_y = float(cell_top) + float(cell_height) * 0.5
        else:
            anchor_x = focus_center_x
            anchor_y = focus_center_y
        gap = max(20.0, min(72.0, float(window.width()) * 0.16)) + max(
            0.0,
            float(getattr(self, "_comment_focus_hover_offset_px", 0.0) or 0.0),
        )
        candidates: list[tuple[str, QtCore.QPointF, QtCore.QPointF, float]] = []
        lane_order = list(grid.get("lane_order") or ["right", "left", "below", "above"])
        for index, lane in enumerate(lane_order):
            if lane == "right":
                raw = QtCore.QPointF(max(float(left + width) + gap, float(cell_left + cell_width) + gap), anchor_y - window.height() * 0.5)
            elif lane == "left":
                raw = QtCore.QPointF(min(float(left) - window.width() - gap, float(cell_left) - window.width() - gap), anchor_y - window.height() * 0.5)
            elif lane == "below":
                raw = QtCore.QPointF(anchor_x - window.width() * 0.5, max(float(top + height) + gap, float(cell_top + cell_height) + gap))
            else:
                raw = QtCore.QPointF(anchor_x - window.width() * 0.5, min(float(top) - window.height() - gap, float(cell_top) - window.height() - gap))
            clamped = self._clamp_top_left_to_rect(raw, screen_rect)
            orb_bounds = [int(round(clamped.x())), int(round(clamped.y())), int(window.width()), int(window.height())]
            overlap = self._bounds_overlap_area(orb_bounds, focus_bounds)
            clamp_distance = math.hypot(raw.x() - clamped.x(), raw.y() - clamped.y())
            target_distance = math.hypot(
                (clamped.x() + window.width() * 0.5) - focus_center_x,
                (clamped.y() + window.height() * 0.5) - focus_center_y,
            )
            score = index * 80.0 + clamp_distance * 2.4 + overlap * 0.04 + target_distance * 0.025
            candidates.append((str(lane), raw, clamped, score))
        if not candidates:
            return self._clamp_top_left_to_screen(QtCore.QPointF(anchor_x - window.width() * 0.5, anchor_y - window.height() * 0.5))
        lane, raw, point, score = min(candidates, key=lambda item: item[3])
        phase = 0.0
        try:
            col, row = [int(value) for value in list(grid.get("cell_index") or [0, 0])[:2]]
            phase = (col + row * FOCUS_GRID_COLUMNS) * 0.73
        except Exception:
            pass
        t = time.monotonic()
        wobble_x = math.sin(t * 0.72 + phase) * min(10.0, max(3.0, float(cell_width) * 0.025))
        wobble_y = math.cos(t * 0.64 + phase) * min(8.0, max(2.0, float(cell_height) * 0.025))
        point = self._clamp_top_left_to_rect(QtCore.QPointF(point.x() + wobble_x, point.y() + wobble_y), screen_rect)
        self._debug_event(
            "focus_grid_target",
            grid=grid,
            chosen_lane=lane,
            raw_target=raw,
            target=point,
            score=round(float(score), 3),
        )
        return point

    def _comment_focus_target(self) -> QtCore.QPointF:
        window = self._window
        if window is None or not self._comment_focus_bounds:
            return self._clamp_top_left_to_screen(QtCore.QPointF(0.0, 0.0))
        if self._comment_focus_matches_manual_drop_region():
            return self._manual_drop_anchor_target()
        grid = dict(self._comment_focus_grid or {})
        if not grid:
            grid = self._focus_grid_for_bounds(self._comment_focus_bounds)
            self._comment_focus_grid = dict(grid or {})
        if grid:
            return self._comment_focus_grid_target(grid)
        left, top, width, height = self._comment_focus_bounds
        center_x = float(left) + float(width) * 0.5
        center_y = float(top) + float(height) * 0.5
        side_bias = -1.0 if center_x > self._virtual_desktop_center_x() else 1.0
        offset = max(
            0.0,
            float(getattr(self, "_comment_focus_hover_offset_px", 0.0) or 0.0),
        )
        x = center_x + side_bias * (58.0 + offset) - window.width() * 0.5
        y = center_y - window.height() * 0.5
        return self._clamp_top_left_to_screen(QtCore.QPointF(x, y))

    def _visual_focus_region_for_text(self, text: str, regions, fallback_bounds=None) -> dict[str, Any]:
        fallback = self._normalize_bounds(fallback_bounds) or list(self._last_snapshot_bounds or [])
        candidates = []
        fallback_center = None
        fallback_area = 0.0
        if fallback:
            fallback_center = (float(fallback[0]) + fallback[2] * 0.5, float(fallback[1]) + fallback[3] * 0.5)
            fallback_area = float(fallback[2]) * float(fallback[3])
        text_tokens = set(re.findall(r"[a-z0-9_./:-]{3,}", str(text or "").lower()))
        visual_cues = {
            "alert",
            "button",
            "chart",
            "control",
            "diagram",
            "document",
            "icon",
            "image",
            "map",
            "panel",
            "photo",
            "picture",
            "thumbnail",
            "video",
            "window",
        }
        screen_rect = self._screen_rect_for_bounds(fallback)
        screen_area = max(1.0, float(screen_rect.width()) * float(screen_rect.height()))
        allow_broad_visual_pick = bool(text_tokens.intersection(visual_cues))
        allow_region_pick = bool(
            self._manual_inspection_active()
            or (fallback and fallback_area / screen_area <= 0.55)
            or allow_broad_visual_pick
        )
        if not allow_region_pick:
            return {}
        for region in list(regions or []):
            if not isinstance(region, dict):
                continue
            bounds = self._normalize_bounds(region.get("screen_bounds"))
            if not bounds:
                continue
            if fallback and self._bounds_overlap_area(bounds, fallback) <= 0.0:
                continue
            area = float(bounds[2]) * float(bounds[3])
            if area <= 0.0:
                continue
            center_x = float(bounds[0]) + bounds[2] * 0.5
            center_y = float(bounds[1]) + bounds[3] * 0.5
            distance = 0.0
            if fallback_center is not None:
                distance = math.hypot(center_x - fallback_center[0], center_y - fallback_center[1])
            kind = str(region.get("kind") or "")
            blank_region_bonus = 160.0 if kind == "text_region" and not str(region.get("text") or "").strip() else 0.0
            score = blank_region_bonus + min(120.0, area / 1800.0) - min(140.0, distance / 5.0)
            candidates.append((score, dict(region)))
        if not candidates:
            return {}
        best = max(candidates, key=lambda item: item[0])[1]
        best["match_score"] = round(float(max(candidates, key=lambda item: item[0])[0]), 3)
        best["backend"] = str(best.get("backend") or "grid_visual_region")
        best["kind"] = str(best.get("kind") or "visual_region")
        return best

    def _virtual_desktop_center_x(self) -> float:
        rect = self._virtual_desktop_rect()
        if rect is not None:
            return float(rect.x()) + float(rect.width()) * 0.5
        screen = QtGui.QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        return float(geometry.x()) + float(geometry.width()) * 0.5

    def _clamp_top_left_to_screen(self, point: QtCore.QPointF | QtCore.QPoint) -> QtCore.QPointF:
        window = self._window
        if window is None:
            return QtCore.QPointF(point)
        target_center = QtCore.QPoint(
            int(round(float(point.x()) + window.width() * 0.5)),
            int(round(float(point.y()) + window.height() * 0.5)),
        )
        target_top_left = QtCore.QPoint(int(round(float(point.x()))), int(round(float(point.y()))))
        screen = (
            QtGui.QGuiApplication.screenAt(target_center)
            or QtGui.QGuiApplication.screenAt(target_top_left)
            or window.screen()
            or QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
            or QtGui.QGuiApplication.primaryScreen()
        )
        available = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        x = max(float(available.left()), min(float(point.x()), float(available.right() - window.width())))
        y = max(float(available.top()), min(float(point.y()), float(available.bottom() - window.height())))
        return QtCore.QPointF(x, y)

    def _debug_move_sample(
        self,
        *,
        kind: str,
        desired: QtCore.QPointF,
        stable: QtCore.QPointF,
        current: QtCore.QPointF,
        next_point: QtCore.QPointF,
        smoothing: float,
        moved: bool,
        elapsed: float = 0.0,
        frame_scale: float = 1.0,
    ):
        if not self._debug_enabled():
            return
        now = time.monotonic()
        focus_key = self._last_comment_focus_signature if str(kind) == "comment" else ""
        signature = (
            f"{kind}|{int(round(stable.x() / 12.0))}|{int(round(stable.y() / 12.0))}|"
            f"{int(round(next_point.x() / 12.0))}|{int(round(next_point.y() / 12.0))}|{focus_key}"
        )
        min_interval = 0.75 if str(kind) in {"comment", "harassment"} else 4.0
        if signature == self._debug_last_move_signature and now - self._debug_last_move_log_at < min_interval:
            return
        self._debug_last_move_signature = signature
        self._debug_last_move_log_at = now
        distance_to_target = math.hypot(stable.x() - next_point.x(), stable.y() - next_point.y())
        geometry = self._window.frameGeometry() if self._window is not None else QtCore.QRect()
        self._debug_event(
            "movement_step",
            kind=kind,
            desired=desired,
            stable_target=stable,
            current=current,
            next=next_point,
            moved=bool(moved),
            smoothing=round(float(smoothing), 4),
            elapsed=round(float(elapsed), 4),
            frame_scale=round(float(frame_scale), 3),
            distance_to_target=round(float(distance_to_target), 2),
            focus_bounds=list(self._comment_focus_bounds or []),
            focus_grid=dict(self._comment_focus_grid or {}) if str(kind) == "comment" else {},
            focus_label=str(self._comment_focus_label or ""),
            window_geometry=geometry,
        )

    def _harassment_target(self) -> QtCore.QPointF:
        window = self._window
        cursor = QtGui.QCursor.pos()
        if window is None:
            return QtCore.QPointF(float(cursor.x()), float(cursor.y()))
        t = time.monotonic()
        orbit_x = math.sin(t * 0.82) * 68.0 + math.sin(t * 0.31 + 1.4) * 22.0
        orbit_y = math.cos(t * 0.70 + 0.8) * 46.0 + math.sin(t * 0.43) * 14.0
        target_x = float(cursor.x()) + orbit_x - window.width() * 0.5
        target_y = float(cursor.y()) + orbit_y - window.height() * 0.5
        return self._clamp_top_left_to_screen(QtCore.QPointF(target_x, target_y))

    def _mark_user_interaction(self):
        self._last_user_interaction_at = time.monotonic()
        if self._harassment_active:
            self._harassment_active = False
            self._schedule_return_home()

    def _mouse_fade_distance(self) -> float:
        try:
            return max(24.0, min(420.0, float(self._last_runtime_config.get("companion_orb_mouse_near_fade_distance", 120) or 120)))
        except Exception:
            return 120.0

    def _apply_mouse_near_opacity(self, *, reset: bool = False):
        window = self._window
        if window is None:
            return
        opacity = (
            1.0
            if reset
            else max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(
                            self,
                            "_eye_tracking_pointer_clearance_opacity",
                            1.0,
                        )
                    ),
                ),
            )
        )
        if (
            opacity > 0.0
            and not reset
            and bool(self._last_runtime_config.get("companion_orb_mouse_near_fade", False))
        ):
            cursor = QtGui.QCursor.pos()
            center = window.frameGeometry().center()
            distance = math.hypot(float(center.x() - cursor.x()), float(center.y() - cursor.y()))
            fade_distance = self._mouse_fade_distance()
            try:
                near_opacity = max(0.05, min(1.0, float(self._last_runtime_config.get("companion_orb_mouse_near_opacity", 0.28) or 0.28)))
            except Exception:
                near_opacity = 0.28
            if distance < fade_distance:
                mix = max(0.0, min(1.0, distance / fade_distance))
                opacity = min(
                    opacity,
                    near_opacity + (1.0 - near_opacity) * mix,
                )
        try:
            window.setOpacity(opacity)
        except Exception:
            pass

    def _aware_focus_hover_target(self, target: QtCore.QPointF, *, now: float, amount: float) -> QtCore.QPointF:
        if not self._aware_motion_enabled():
            return QtCore.QPointF(target)
        awareness = self._awareness_level()
        focus_pull = self._focus_pull()
        if awareness <= 0.0 or focus_pull <= 0.0:
            return QtCore.QPointF(target)
        hover = min(7.0, max(1.5, max(4.0, float(amount)) * 0.12)) * awareness * (0.45 + focus_pull * 0.55)
        x = target.x() + math.sin(now * 0.58 + 1.2) * hover
        y = target.y() + math.cos(now * 0.47 + 0.4) * hover * 0.62
        return self._clamp_top_left_to_screen(QtCore.QPointF(x, y))

    def _aware_idle_target(
        self,
        *,
        base: QtCore.QPoint,
        target_x: float,
        target_y: float,
        now: float,
        amount: float,
        speed: float,
    ) -> tuple[float, float, float, float]:
        if not self._aware_motion_enabled():
            return target_x, target_y, 1.5, 0.40
        awareness = self._awareness_level()
        pause_strength = self._idle_pause_strength()
        if awareness <= 0.0 and pause_strength <= 0.0:
            return target_x, target_y, 1.5, 0.40

        t = now * max(0.15, speed)
        calm_scale = 1.0 - pause_strength * 0.10
        target_x = float(base.x()) + (target_x - float(base.x())) * calm_scale
        target_y = float(base.y()) + (target_y - float(base.y())) * calm_scale
        target_x += math.sin(t * 0.09 + 2.1) * amount * 0.08 * awareness
        target_y += math.cos(t * 0.075 + 0.5) * amount * 0.055 * awareness

        current = self._drift_current_point or QtCore.QPointF(target_x, target_y)
        if (
            pause_strength > 0.0
            and now >= self._aware_idle_next_pause_at
            and now >= self._aware_idle_pause_until
        ):
            self._aware_idle_pause_point = QtCore.QPointF(current)
            hold_seconds = 0.35 + pause_strength * (0.75 + awareness * 0.55)
            rest_seconds = 2.4 + (1.0 - pause_strength) * 2.4 + (1.0 - awareness) * 1.2
            self._aware_idle_pause_until = now + hold_seconds
            self._aware_idle_next_pause_at = self._aware_idle_pause_until + rest_seconds

        if pause_strength > 0.0 and now < self._aware_idle_pause_until and self._aware_idle_pause_point is not None:
            anchor = self._aware_idle_pause_point
            observe = min(3.8, max(0.8, amount * 0.06)) * awareness
            target_x = anchor.x() + math.sin(now * 0.82) * observe
            target_y = anchor.y() + math.cos(now * 0.71 + 0.8) * observe * 0.55
            deadzone = 3.0 + pause_strength * 5.0
            blend = 0.22 + awareness * 0.06
            return target_x, target_y, deadzone, blend

        deadzone = 1.8 + pause_strength * 2.4
        blend = max(0.22, 0.40 - pause_strength * 0.12)
        return target_x, target_y, deadzone, blend

    def _on_drift_tick(self):
        window = self._window
        if window is None or self.bridge.editMode or self.bridge.placementMode or self._motion_timer.isActive():
            self._drift_timer.stop()
            self._last_drift_tick_at = 0.0
            return
        if self._drag_offset is not None or self._poll_drag_active:
            self._drift_timer.stop()
            self._last_drift_tick_at = 0.0
            return
        if not window.isVisible():
            self._drift_timer.stop()
            self._last_drift_tick_at = 0.0
            return
        now = time.monotonic()
        previous_tick = self._last_drift_tick_at or now
        elapsed = max(0.0, min(0.12, now - previous_tick))
        self._last_drift_tick_at = now
        frame_scale = max(0.25, min(5.0, elapsed / (1.0 / 60.0))) if elapsed > 0.0 else 1.0
        base = self._base_position or self._home_position()
        self._base_position = QtCore.QPoint(base)
        movement_enabled = bool(self._last_runtime_config.get("companion_orb_movement_enabled", True))
        amount = float(self._movement_range()) if movement_enabled else 0.0
        speed = self._movement_speed()
        comment_focus_ready = self._comment_focus_ready()
        eye_interaction_ready = self._eye_tracking_interaction_ready()
        if not eye_interaction_ready:
            self._reset_eye_tracking_pointer_clearance()
        harassment_ready = False if eye_interaction_ready else self._harassment_ready()
        if eye_interaction_ready:
            target = self._eye_tracking_interaction_target or QtCore.QPointF(base)
            cleared_target = self._apply_eye_tracking_pointer_clearance(
                QtCore.QPointF(target),
                current_top_left=QtCore.QPointF(
                    float(window.x()),
                    float(window.y()),
                ),
                now=now,
            )
            target_x = cleared_target.x()
            target_y = cleared_target.y()
            target_kind = "interaction"
            target_deadzone = 3.0
            target_blend = 0.34
            if self._harassment_active:
                self._harassment_active = False
        elif comment_focus_ready:
            target = self._aware_focus_hover_target(self._comment_focus_target(), now=now, amount=max(amount, float(self._movement_range())))
            target_x = target.x()
            target_y = target.y()
            target_kind = "comment"
            focus_pull = self._focus_pull() if self._aware_motion_enabled() else 0.65
            target_deadzone = 4.5 + (1.0 - focus_pull) * 4.0
            target_blend = 0.19 + focus_pull * 0.09
            if self._harassment_active:
                self._harassment_active = False
        elif harassment_ready:
            target = self._harassment_target()
            target_x = target.x()
            target_y = target.y()
            target_kind = "harassment"
            target_deadzone = 22.0
            target_blend = 0.20
            if not self._harassment_active:
                self._harassment_active = True
                self._announce_harassment()
            else:
                self._harassment_active = True
        else:
            if self._harassment_active:
                self._harassment_active = False
                self._schedule_return_home()
            t = now * speed
            x_offset = math.sin(t * 0.42) * amount + math.sin(t * 0.17 + 1.9) * amount * 0.34
            y_offset = math.cos(t * 0.36 + 0.7) * amount * 0.58 + math.sin(t * 0.13 + 2.4) * amount * 0.26
            target_x = float(base.x()) + x_offset
            target_y = float(base.y()) + y_offset
            target_kind = "idle"
            target_deadzone = 1.5
            target_blend = 0.40
            target_x, target_y, target_deadzone, target_blend = self._aware_idle_target(
                base=base,
                target_x=target_x,
                target_y=target_y,
                now=now,
                amount=amount,
                speed=speed,
            )
        if (
            bool(self._last_runtime_config.get("companion_orb_avoid_mouse", False))
            and not harassment_ready
            and not comment_focus_ready
            and not eye_interaction_ready
        ):
            cursor = QtGui.QCursor.pos()
            center_x = target_x + window.width() * 0.5
            center_y = target_y + window.height() * 0.5
            dx = center_x - float(cursor.x())
            dy = center_y - float(cursor.y())
            distance = max(1.0, math.hypot(dx, dy))
            fade_distance = self._mouse_fade_distance()
            if distance < fade_distance:
                push = (fade_distance - distance) / fade_distance
                target_x += (dx / distance) * push * min(90.0, fade_distance * 0.32)
                target_y += (dy / distance) * push * min(90.0, fade_distance * 0.32)
        stable_target = self._stable_drift_target(
            target_kind,
            QtCore.QPointF(target_x, target_y),
            deadzone=target_deadzone,
            blend=target_blend,
            frame_scale=frame_scale,
        )
        desired_target = QtCore.QPointF(float(target_x), float(target_y))
        target_x = stable_target.x()
        target_y = stable_target.y()
        current = self._drift_current_point
        if current is None:
            current = QtCore.QPointF(float(window.x()), float(window.y()))
        smoothing = (
            0.16
            if target_kind == "interaction"
            else (0.14 if target_kind == "comment" else (0.11 if harassment_ready else max(0.055, min(0.18, 0.055 + speed * 0.055))))
        )
        smoothing = self._time_scaled_blend(smoothing, frame_scale)
        next_x = current.x() + (target_x - current.x()) * smoothing
        next_y = current.y() + (target_y - current.y()) * smoothing
        self._drift_current_point = QtCore.QPointF(next_x, next_y)
        should_move = (
            comment_focus_ready
            or eye_interaction_ready
            or harassment_ready
            or movement_enabled
            or bool(self._last_runtime_config.get("companion_orb_avoid_mouse", False))
        )
        if should_move:
            window.move(QtCore.QPoint(int(round(next_x)), int(round(next_y))))
        if target_kind != "interaction" and (target_kind in {"comment", "harassment"} or should_move):
            self._debug_move_sample(
                kind=target_kind,
                desired=desired_target,
                stable=stable_target,
                current=current,
                next_point=QtCore.QPointF(next_x, next_y),
                smoothing=smoothing,
                elapsed=round(float(elapsed), 4),
                frame_scale=round(float(frame_scale), 3),
                moved=should_move,
            )
        if harassment_ready:
            self._maybe_capture_pointer_snapshot()
        self._apply_mouse_near_opacity()

    def _start_motion_to(self, target: QtCore.QPoint):
        window = self._window
        if window is None:
            return
        self._drift_timer.stop()
        self._reset_drift_target()
        start = window.frameGeometry().topLeft()
        self._move_start_point = QtCore.QPoint(start)
        self._move_target_point = QtCore.QPoint(target)
        self._move_started_at = time.monotonic()
        distance = math.hypot(float(target.x() - start.x()), float(target.y() - start.y()))
        speed = self._movement_speed()
        self._move_duration = max(0.65, min(3.6, distance / max(120.0, 360.0 * speed)))
        self._move_curve_sign = -1.0 if int(self._move_started_at * 1000) % 2 else 1.0
        self._debug_event(
            "motion_started",
            console=True,
            start=start,
            target=target,
            distance=round(float(distance), 2),
            duration_seconds=round(float(self._move_duration), 2),
            speed=round(float(speed), 3),
        )
        self._motion_timer.start()

    def _on_motion_tick(self):
        window = self._window
        start = self._move_start_point
        target = self._move_target_point
        if window is None or start is None or target is None:
            self._motion_timer.stop()
            self._sync_drift_timer()
            return
        elapsed = max(0.0, time.monotonic() - self._move_started_at)
        progress = min(1.0, elapsed / max(0.05, self._move_duration))
        eased = 1.0 - pow(1.0 - progress, 3.0)
        dx = float(target.x() - start.x())
        dy = float(target.y() - start.y())
        distance = max(1.0, math.hypot(dx, dy))
        curve = math.sin(progress * math.pi) * min(96.0, max(18.0, distance * 0.18)) * self._move_curve_sign
        perp_x = -dy / distance
        perp_y = dx / distance
        x = start.x() + dx * eased + perp_x * curve
        y = start.y() + dy * eased + perp_y * curve
        window.move(QtCore.QPoint(int(round(x)), int(round(y))))
        if self._debug_enabled() and time.monotonic() - self._debug_last_move_log_at >= 0.75:
            self._debug_last_move_log_at = time.monotonic()
            self._debug_event(
                "motion_step",
                start=start,
                target=target,
                position=[round(float(x), 2), round(float(y), 2)],
                progress=round(float(progress), 3),
            )
        if progress >= 1.0:
            self._motion_timer.stop()
            window.move(target)
            self._base_position = QtCore.QPoint(target)
            self._drift_current_point = QtCore.QPointF(float(target.x()), float(target.y()))
            self._reset_drift_target()
            self._debug_event("motion_finished", console=True, target=target)
            self._sync_drift_timer()

    @QtCore.Slot(bool)
    def set_edit_mode(self, enabled):
        enabled = bool(enabled)
        if enabled:
            self._drift_timer.stop()
            self._motion_timer.stop()
        self.bridge.set_modes(edit_mode=enabled, placement_mode=False if enabled else self.bridge.placementMode)
        self._send_external_runtime(
            {
                "type": "modes",
                "edit_mode": enabled,
                "placement_mode": False if enabled else bool(self.bridge.placementMode),
                "click_through": bool(self.bridge.clickThrough),
            }
        )
        self._apply_window_settings()
        self._refresh_visibility()
        self._log(f"Edit mode {'enabled' if enabled else 'disabled'}.")

    @QtCore.Slot(bool)
    def set_placement_mode(self, enabled):
        enabled = bool(enabled)
        if enabled:
            self._drift_timer.stop()
            self._motion_timer.stop()
        self.bridge.set_modes(placement_mode=enabled, edit_mode=False if enabled else self.bridge.editMode)
        self._send_external_runtime(
            {
                "type": "modes",
                "placement_mode": enabled,
                "edit_mode": False if enabled else bool(self.bridge.editMode),
                "click_through": bool(self.bridge.clickThrough),
            }
        )
        self._apply_window_settings()
        self._refresh_visibility()
        self._log(f"Placement mode {'enabled' if enabled else 'disabled'}.")

    @QtCore.Slot(bool)
    def set_click_through(self, enabled):
        self._last_runtime_config["companion_orb_click_through_default"] = bool(enabled)
        self._last_runtime_config["companion_orb_interaction_defaults_version"] = (
            interaction_settings.CURRENT_INTERACTION_DEFAULTS_VERSION
        )
        self._last_runtime_config["companion_orb_click_through_explicit"] = bool(enabled)
        effective_enabled = interaction_settings.effective_click_through(
            self._last_runtime_config,
            edit_mode=bool(self.bridge.editMode),
            placement_mode=bool(self.bridge.placementMode),
        )
        self.bridge.set_modes(click_through=effective_enabled)
        self._send_external_runtime({"type": "settings", "settings": dict(self._last_runtime_config or {})})
        self._send_external_runtime(
            {
                "type": "modes",
                "edit_mode": bool(self.bridge.editMode),
                "placement_mode": bool(self.bridge.placementMode),
                "click_through": bool(effective_enabled),
            }
        )
        self._apply_click_through(bool(effective_enabled))
        self._save_runtime_setting(
            "companion_orb_interaction_defaults_version",
            interaction_settings.CURRENT_INTERACTION_DEFAULTS_VERSION,
        )
        self._save_runtime_setting("companion_orb_click_through_explicit", bool(enabled))
        self._save_runtime_setting("companion_orb_click_through_default", bool(enabled))

    def _persist_interaction_defaults_migration(self) -> None:
        self._save_runtime_setting("companion_orb_click_through_default", False)
        self._save_runtime_setting("companion_orb_right_drag_focus_enabled", True)
        self._save_runtime_setting("companion_orb_click_through_explicit", False)
        self._save_runtime_setting(
            "companion_orb_interaction_defaults_version",
            interaction_settings.CURRENT_INTERACTION_DEFAULTS_VERSION,
        )

    def _apply_click_through(self, enabled: bool):
        for widget in (self._window, self._quick):
            if widget is None:
                continue
            try:
                widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, bool(enabled))
            except Exception:
                pass
        self._apply_windows_click_through(bool(enabled))
        self._apply_orb_cursor(click_through=bool(enabled))
        self._sync_menu_poll_timer()

    def _apply_orb_cursor(self, *, click_through: bool, dragging: bool = False) -> None:
        for widget in (self._window, self._quick):
            if widget is None:
                continue
            try:
                if bool(click_through):
                    widget.unsetCursor()
                else:
                    cursor_shape = QtCore.Qt.ClosedHandCursor if bool(dragging) else QtCore.Qt.OpenHandCursor
                    widget.setCursor(QtGui.QCursor(cursor_shape))
            except Exception:
                pass

    def _apply_windows_click_through(self, enabled: bool):
        if self._window is None or not sys_platform_windows():
            return
        try:
            import ctypes

            hwnd = int(self._window.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            current = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            next_style = current | WS_EX_LAYERED
            if enabled:
                next_style |= WS_EX_TRANSPARENT
            else:
                next_style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, next_style)
        except Exception as exc:
            self._log(f"Click-through style update failed: {exc}")

    @QtCore.Slot()
    def clear_target(self):
        self._target_info = {}
        target_display = CompanionOrbController._capture_target_presentation(self)
        self.bridge.set_target_info(target_display)
        self._send_external_runtime({"type": "target_info", "target": target_display})
        self._clear_manual_drop_anchor()
        self._save_runtime_setting("companion_orb_target_info", {})
        self._publish_target_event({}, cleared=True)
        self._log("Companion Orb target cleared.")

    def _store_target_info(self, target: dict[str, Any]) -> None:
        self._target_info = dict(target or {})
        target_display = CompanionOrbController._capture_target_presentation(self)
        self.bridge.set_target_info(target_display)
        self._send_external_runtime({"type": "target_info", "target": target_display})
        self._save_runtime_setting("companion_orb_target_info", dict(self._target_info))
        self._publish_target_event(self._target_for_output(self._target_info))

    def _target_region_size(self) -> tuple[int, int]:
        width = int(self._last_runtime_config.get("companion_orb_target_region_width", 640) or 640)
        height = int(self._last_runtime_config.get("companion_orb_target_region_height", 420) or 420)
        return width, height

    def _resolve_current_orb_target_for_mode(self, mode: str) -> dict[str, Any]:
        width, height = self._target_region_size()
        target = self._resolve_target_at(self._orb_center_global(), width=width, height=height, mode=mode)
        if str(mode or "").strip().lower() == "window" and str((target or {}).get("target_type") or "") != "window":
            return {}
        return dict(target or {}) if target_bounds(target) else {}

    def _refresh_target_for_mode_change(self, mode: str) -> None:
        if not self._target_info:
            return
        target = self._resolve_current_orb_target_for_mode(mode)
        if not target:
            self._debug_event("target_mode_reselect_skipped", reason="no_target_under_orb", mode=str(mode or ""))
            return
        if self._target_signature(target) != self._target_signature(self._target_info):
            self._store_target_info(target)
            self._debug_event(
                "target_mode_reselected",
                console=True,
                mode=str(mode or ""),
                target=self._target_for_output(target),
                bounds=target_bounds(target),
            )

    def _capture_target_for_current_mode(self) -> tuple[dict[str, Any], str]:
        mode = str(self._last_runtime_config.get("companion_orb_target_mode", "window") or "window").strip().lower()
        target = dict(self._target_info or {})
        if mode == "region":
            region_target = self._resolve_current_orb_target_for_mode("region")
            if region_target:
                if self._target_signature(region_target) != self._target_signature(target):
                    self._store_target_info(region_target)
                return region_target, ""
            return {}, "missing_target"
        if not target:
            return {}, "missing_target"
        if str(target.get("target_type") or "").strip().lower() == "window":
            refreshed = refresh_window_target(target)
            if refreshed and target_bounds(refreshed):
                if self._target_signature(refreshed) != self._target_signature(target):
                    self._store_target_info(refreshed)
                return dict(refreshed), ""
            fallback = self._resolve_current_orb_target_for_mode("window")
            if fallback:
                self._store_target_info(fallback)
                self._debug_event(
                    "target_window_replaced",
                    console=True,
                    target=self._target_for_output(fallback),
                    bounds=target_bounds(fallback),
                )
                return fallback, ""
            self.clear_target()
            return {}, "target_lost"
        fallback = self._resolve_current_orb_target_for_mode("window")
        if fallback:
            self._store_target_info(fallback)
            return fallback, ""
        return {}, "target_lost"

    @QtCore.Slot()
    def reset_position(self):
        self._custom_position = []
        self._last_runtime_config["companion_orb_custom_position"] = []
        self._save_runtime_setting("companion_orb_custom_position", [])
        self._base_position = self._dock_position()
        self._clear_manual_drop_anchor()
        self._send_external_runtime({"type": "reset_position"})
        self._return_home(animate=True)

    def target_info(self) -> dict[str, Any]:
        return dict(self._target_info or {})

    def eventFilter(self, watched, event):
        try:
            if event.type() == QtCore.QEvent.KeyPress and self._hotkeys_enabled() and not self._focus_is_text_input():
                handled = self._handle_hotkey(event)
                if handled:
                    event.accept()
                    return True
            if watched in (self._window, self._quick) and self._window is not None:
                return self._handle_window_event(event)
        except Exception as exc:
            self._log(f"Orb event handling failed: {exc}")
        return super().eventFilter(watched, event)

    def _handle_window_event(self, event):
        if event.type() == QtCore.QEvent.Move:
            try:
                delta = event.pos() - event.oldPos()
                self.bridge.setSilkTravel(float(delta.x()), float(delta.y()))
            except Exception:
                pass
            return False
        if event.type() == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.RightButton:
            self._mark_user_interaction()
            self._show_command_menu(self._event_global_pos(event))
            return True
        if event.type() == QtCore.QEvent.MouseButtonPress:
            self._mark_user_interaction()
            right_drag_focus = interaction_settings.right_drag_focus_enabled(self._last_runtime_config)
            event_pos = self._event_global_pos(event)
            if (self.bridge.placementMode or right_drag_focus) and event.button() == QtCore.Qt.RightButton:
                self._drift_timer.stop()
                self._motion_timer.stop()
                self._drag_offset = event_pos - self._window.frameGeometry().topLeft()
                self._drag_start_global_pos = QtCore.QPoint(event_pos)
                self._drag_moved = False
                self._set_silk_grab(event_pos, True)
                self._apply_orb_cursor(click_through=False, dragging=True)
                return True
            if event.button() == QtCore.Qt.RightButton:
                self._show_command_menu(event_pos)
                return True
            if event.button() == QtCore.Qt.LeftButton and (self.bridge.editMode or not self.bridge.clickThrough):
                self._drift_timer.stop()
                self._motion_timer.stop()
                self._drag_offset = event_pos - self._window.frameGeometry().topLeft()
                self._drag_start_global_pos = QtCore.QPoint(event_pos)
                self._drag_moved = False
                self._set_silk_grab(event_pos, True)
                self._apply_orb_cursor(click_through=False, dragging=True)
                return True
        if event.type() == QtCore.QEvent.MouseMove and self._drag_offset is not None:
            self._mark_user_interaction()
            event_pos = self._event_global_pos(event)
            if self._drag_start_global_pos is not None:
                dx = float(event_pos.x() - self._drag_start_global_pos.x())
                dy = float(event_pos.y() - self._drag_start_global_pos.y())
                if math.hypot(dx, dy) >= POLL_DRAG_THRESHOLD_PX:
                    self._drag_moved = True
            point = event_pos - self._drag_offset
            self._window.move(point)
            self._record_drag_position(point)
            return True
        if event.type() == QtCore.QEvent.MouseButtonRelease:
            self._mark_user_interaction()
            event_pos = self._event_global_pos(event)
            had_drag = self._drag_offset is not None
            drag_moved = bool(self._drag_moved)
            if self._drag_start_global_pos is not None:
                dx = float(event_pos.x() - self._drag_start_global_pos.x())
                dy = float(event_pos.y() - self._drag_start_global_pos.y())
                drag_moved = drag_moved or math.hypot(dx, dy) >= POLL_DRAG_THRESHOLD_PX
            if self._drag_offset is not None:
                self._record_drag_position(self._window.frameGeometry().topLeft())
                self._save_runtime_setting("companion_orb_custom_position", list(self._custom_position))
            self._drag_offset = None
            self._drag_start_global_pos = None
            self._drag_moved = False
            self._set_silk_grab(event_pos, False)
            self._apply_orb_cursor(click_through=bool(self.bridge.clickThrough), dragging=False)
            right_drag_focus = interaction_settings.right_drag_focus_enabled(self._last_runtime_config)
            if (self.bridge.placementMode or right_drag_focus) and event.button() == QtCore.Qt.RightButton:
                if not drag_moved:
                    self._apply_window_settings()
                    self._sync_drift_timer()
                    self._show_command_menu(event_pos)
                    return True
                self._inspect_drop_target(self._orb_center_global(), reason="right_drag_drop")
                if self.bridge.placementMode:
                    self.set_placement_mode(False)
                else:
                    self._apply_window_settings()
                    self._sync_drift_timer()
                return True
            if had_drag and drag_moved and event.button() in (QtCore.Qt.LeftButton, QtCore.Qt.RightButton):
                button = "left" if event.button() == QtCore.Qt.LeftButton else "right"
                self._inspect_drop_target(self._orb_center_global(), reason=f"{button}_drag_drop")
                return True
        return False

    def _poll_right_double_click(self):
        window = self._window
        if window is None or self._menu_open or not window.isVisible():
            return
        if not self.bridge.clickThrough:
            self._right_button_was_down = False
            self._left_button_was_down = False
            self._clear_poll_drag()
            return
        right_down = self._mouse_button_down("right")
        left_down = self._mouse_button_down("left")
        cursor = QtGui.QCursor.pos()
        if self._poll_drag_active:
            drag_down = right_down if self._poll_drag_button == "right" else left_down
            if drag_down:
                self._move_poll_drag(cursor)
            else:
                self._finish_poll_drag()
            self._right_button_was_down = right_down
            self._left_button_was_down = left_down
            return
        if not right_down and not left_down:
            if self._right_button_was_down and self._poll_drag_button == "right" and self._poll_drag_start_pos is not None:
                point = QtCore.QPoint(cursor)
                self._clear_poll_drag()
                self._right_button_was_down = False
                self._left_button_was_down = False
                self._mark_user_interaction()
                self._show_command_menu(point)
                return
            self._clear_poll_drag()
            self._right_button_was_down = False
            self._left_button_was_down = False
            return
        if not window.frameGeometry().contains(cursor):
            self._right_button_was_down = right_down
            self._left_button_was_down = left_down
            return
        if right_down and not self._right_button_was_down:
            self._last_right_click_at = 0.0
            self._poll_drag_start_pos = QtCore.QPoint(cursor)
            self._poll_drag_offset = cursor - window.frameGeometry().topLeft()
            self._poll_drag_button = "right"
        elif left_down and not self._left_button_was_down:
            self._poll_drag_start_pos = QtCore.QPoint(cursor)
            self._poll_drag_offset = cursor - window.frameGeometry().topLeft()
            self._poll_drag_button = "left"
        elif self._poll_drag_start_pos is not None:
            dx = float(cursor.x() - self._poll_drag_start_pos.x())
            dy = float(cursor.y() - self._poll_drag_start_pos.y())
            if math.hypot(dx, dy) >= POLL_DRAG_THRESHOLD_PX:
                self._start_poll_drag(cursor)
        self._right_button_was_down = right_down
        self._left_button_was_down = left_down

    def _start_poll_drag(self, cursor: QtCore.QPoint):
        window = self._window
        if window is None:
            return
        if self._poll_drag_offset is None:
            self._poll_drag_offset = cursor - window.frameGeometry().topLeft()
        self._poll_drag_active = True
        self._drift_timer.stop()
        self._motion_timer.stop()
        self._return_home_timer.stop()
        self._mark_user_interaction()
        self._set_silk_grab(cursor, True)
        self._move_poll_drag(cursor)

    def _move_poll_drag(self, cursor: QtCore.QPoint):
        window = self._window
        if window is None or self._poll_drag_offset is None:
            return
        point = cursor - self._poll_drag_offset
        window.move(point)
        self._record_drag_position(point)
        self._apply_mouse_near_opacity()

    def _finish_poll_drag(self):
        window = self._window
        if window is None:
            self._clear_poll_drag()
            return
        button = str(self._poll_drag_button or "")
        self._record_drag_position(window.frameGeometry().topLeft())
        self._save_runtime_setting("companion_orb_custom_position", list(self._custom_position))
        self._last_right_click_at = 0.0
        self._mark_user_interaction()
        self._clear_poll_drag()
        if button in {"left", "right"}:
            self._inspect_drop_target(self._orb_center_global(), reason=f"{button}_drag_drop")
        self._sync_drift_timer()

    def _clear_poll_drag(self):
        if self._poll_drag_active:
            self._set_silk_grab(QtGui.QCursor.pos(), False)
        self._poll_drag_start_pos = None
        self._poll_drag_offset = None
        self._poll_drag_button = ""
        self._poll_drag_active = False

    def _set_silk_grab(self, global_pos: QtCore.QPoint, active: bool) -> None:
        window = self._window
        if window is None:
            return
        geometry = window.frameGeometry()
        width = max(1.0, float(geometry.width()))
        height = max(1.0, float(geometry.height()))
        local_x = (float(global_pos.x()) - float(geometry.left())) / width
        local_y = (
            (float(global_pos.y()) - float(geometry.top())) / height * 2.0 - 1.0
        )
        self.bridge.setSilkGrabState(local_x, local_y, bool(active))

    def _record_drag_position(self, point: QtCore.QPoint):
        self._custom_position = [int(point.x()), int(point.y())]
        self._last_runtime_config["companion_orb_custom_position"] = list(self._custom_position)
        self._base_position = QtCore.QPoint(int(point.x()), int(point.y()))
        self._drift_current_point = QtCore.QPointF(float(point.x()), float(point.y()))
        self._reset_drift_target()

    def _right_button_down(self) -> bool:
        return self._mouse_button_down("right")

    def _mouse_button_down(self, button: str) -> bool:
        normalized = str(button or "").strip().lower()
        if sys_platform_windows():
            try:
                import ctypes

                vk_code = 0x02 if normalized == "right" else 0x01
                return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)
            except Exception:
                pass
        try:
            qt_button = QtCore.Qt.RightButton if normalized == "right" else QtCore.Qt.LeftButton
            return bool(QtGui.QGuiApplication.mouseButtons() & qt_button)
        except Exception:
            return False

    def _has_visible_pinned_popup(self) -> bool:
        popup = self._orb_popup
        return bool(
            popup is not None
            and popup.view.isVisible()
            and popup.bridge.mode == "menu"
            and popup.bridge.pinned
        )

    def _show_command_menu(self, global_pos: QtCore.QPoint | None = None):
        if self._has_visible_pinned_popup():
            return
        if self._window is None or self._menu_open or self._gaze_radial_menu_open:
            return
        previous_click_through = bool(self.bridge.clickThrough)
        self._menu_open = True
        self._orb_popup_previous_click_through = previous_click_through
        self._drift_timer.stop()
        self._motion_timer.stop()
        if previous_click_through:
            self._apply_click_through(False)
        point = global_pos if isinstance(global_pos, QtCore.QPoint) else QtGui.QCursor.pos()
        quick_personas: list[dict[str, Any]] = []
        persona_state = getattr(self.remote_commands, "quick_persona_state", None)
        if callable(persona_state):
            try:
                quick_personas = [
                    dict(item or {}) for item in list(persona_state() or [])
                ]
            except Exception as exc:
                self._log(f"Companion Orb quick persona list unavailable: {exc}")
        items = _command_menu_items(quick_personas, watch_status=self.watch_status_snapshot(),
            drop_watch_prompt_enabled=bool(self._last_runtime_config.get('companion_orb_drop_watch_prompt_enabled', False)))

        def activate(item_id: str) -> None:
            if item_id == 'drop_watch_prompt':
                self._set_drop_watch_prompt_enabled(not self._last_runtime_config.get('companion_orb_drop_watch_prompt_enabled', False))
                return
            if item_id in {'watch_setup', 'watch_list'}:
                self._activate_floating_workspace('orb_watches', False)
                return
            if item_id == "region_size":
                self._show_region_size_editor()
                return
            if item_id == "chat":
                self._handle_menu_command("Chat text input", QtCore.QPoint(point))
                return
            if item_id.startswith("persona:"):
                apply_persona = getattr(
                    self.remote_commands,
                    "quick_persona_apply",
                    None,
                )
                if not callable(apply_persona):
                    self._log("Companion Orb quick persona controls are unavailable.")
                    return
                try:
                    persona_slot = int(item_id.partition(":")[2])
                except ValueError:
                    return
                try:
                    result = dict(apply_persona(persona_slot) or {})
                except Exception as exc:
                    self._log(f"Companion Orb quick persona selection failed: {exc}")
                    return
                if not bool(result.get("accepted")):
                    self._log(
                        "Companion Orb quick persona selection was rejected: "
                        f"{result.get('message') or 'unknown reason'}"
                    )
                return
            if item_id.startswith("reading:"):
                self._handle_reading_menu_action(item_id.partition(":")[2])

        try:
            popup = self._ensure_orb_popup()
            popup.show_menu(
                QtCore.QPoint(point),
                items,
                activate,
                compact_mode=True,
                set_compact_mode=self._set_orb_popup_compact_mode,
                pinned=bool(
                    self._last_runtime_config.get(
                        "companion_orb_popup_pinned",
                        False,
                    )
                ),
                set_pinned=self._set_orb_popup_pinned,
                pinned_position=self._last_runtime_config.get(
                    "companion_orb_popup_position",
                    [],
                ),
                menu_width=int(
                    self._last_runtime_config.get(
                        "companion_orb_popup_width",
                        520,
                    )
                ),
                set_menu_width=self._set_orb_popup_width,
                reduced_effects=bool(
                    self._last_runtime_config.get(
                        "companion_orb_reduced_effects",
                        False,
                    )
                ),
                theme_preset=str(
                    self._last_runtime_config.get(
                        "ui_theme_preset",
                        "midnight",
                    )
                ),
            )
            if popup.bridge.pinned and self._menu_open:
                self._finish_command_menu(previous_click_through)
        except Exception as exc:
            self._log(f"Companion Orb command popup failed: {exc}")
            self._finish_command_menu(previous_click_through)

    def _region_preview_center(self) -> QtCore.QPoint:
        if self._external_runtime_enabled():
            # Sample autonomous renderer movement only while editing. Unlike a
            # user drop, these reports must not persist/re-anchor Orb position.
            self._send_external_runtime({"type": "report_position"})
        top_left = self._current_orb_top_left_for_drop()
        if top_left is not None:
            half = self._window_size() // 2
            return top_left + QtCore.QPoint(half, half)
        return self._orb_center_global()

    def _show_region_size_editor(self) -> None:
        from .region_editor import RegionSizeEditor

        editor = getattr(self, "_region_size_editor", None)
        if editor is not None:
            editor.view.requestActivate()
            return

        width, height = self._target_region_size()
        editor = RegionSizeEditor(self._region_preview_center(), width, height, self,
                                  center_provider=self._region_preview_center)
        self._region_size_editor = editor
        editor.accepted.connect(self._apply_region_size)

        def finished() -> None:
            self._region_size_editor = None
            editor.deleteLater()

        editor.finished.connect(finished)
        editor.show()

    def _apply_region_size(self, width: int, height: int) -> None:
        for key, value in (("companion_orb_target_region_width", width),
                           ("companion_orb_target_region_height", height)):
            self._last_runtime_config[key] = value
            self._save_runtime_setting(key, value)
        # Resize an existing region without creating a target, changing mode,
        # starting a watch, or sending a model request.
        if str(self._target_info.get("target_type") or "") == "region":
            bounds = target_bounds(self._target_info)
            if bounds:
                target = dict(self._target_info)
                center = self._region_preview_center()
                target["bounds"] = [center.x() - width // 2, center.y() - height // 2, width, height]
                self._store_target_info(target)

    def _ensure_orb_popup(self) -> OrbPopupWindow:
        popup = self._orb_popup
        if popup is None:
            popup = OrbPopupWindow(
                self,
                toggle_main_window=self._toggle_main_window,
                initialize_runtime=self._initialize_main_runtime,
                terminate_runtime=self._terminate_main_runtime,
                runtime_state=self._main_runtime_state,
                activate_workspace=self._activate_floating_workspace,
                save_position=self._save_orb_popup_position,
            )
            popup.closed.connect(self._on_orb_popup_closed)
            self._orb_popup = popup
        return popup

    def _toggle_main_window(self) -> bool:
        shell = getattr(
            getattr(self.context, "capabilities", None),
            "shell",
            None,
        )
        toggle = getattr(shell, "toggle_main_window", None)
        if not callable(toggle):
            self._log("NeuralCompanion main-window toggle is unavailable.")
            return False
        try:
            return bool(toggle())
        except Exception as exc:
            self._log(f"Could not toggle NeuralCompanion: {exc}")
            return False

    def _initialize_main_runtime(self) -> bool:
        shell = getattr(
            getattr(self.context, "capabilities", None),
            "shell",
            None,
        )
        initialize = getattr(shell, "initialize_system", None)
        if not callable(initialize):
            self._log("NeuralCompanion runtime initialization is unavailable.")
            return False
        try:
            return bool(initialize())
        except Exception as exc:
            self._log(f"Could not initialize NeuralCompanion: {exc}")
            return False

    def _terminate_main_runtime(self) -> bool:
        shell = getattr(
            getattr(self.context, "capabilities", None),
            "shell",
            None,
        )
        terminate = getattr(shell, "terminate_system", None)
        if not callable(terminate):
            self._log("NeuralCompanion runtime termination is unavailable.")
            return False
        try:
            return bool(terminate())
        except Exception as exc:
            self._log(f"Could not terminate NeuralCompanion: {exc}")
            return False

    def _main_runtime_state(self) -> dict[str, bool]:
        shell = getattr(
            getattr(self.context, "capabilities", None),
            "shell",
            None,
        )
        snapshot = getattr(shell, "runtime_state", None)
        if not callable(snapshot):
            return {"running": False, "starting": False}
        try:
            state = dict(snapshot() or {})
        except Exception as exc:
            self._log(f"Could not read NeuralCompanion runtime state: {exc}")
            return {"running": False, "starting": False}
        config = getattr(self, "_last_runtime_config", {})
        bridge = getattr(self, "bridge", None)
        return {
            "running": bool(state.get("running", False)),
            "starting": bool(state.get("starting", False)),
            "fault": bool(state.get("cleanup_pending", False)),
            "ai_state": str(getattr(bridge, "aiState", "idle") or "idle"),
            "idle_color": str(
                config.get("companion_orb_idle_color", "#38bdf8")
                or "#38bdf8"
            ),
            "thinking_color": str(
                config.get("companion_orb_thinking_color", "#a78bfa")
                or "#a78bfa"
            ),
            "speaking_color": str(
                config.get("companion_orb_speaking_color", "#f472b6")
                or "#f472b6"
            ),
            "theme_preset": str(
                state.get("theme_preset")
                or config.get("ui_theme_preset", "midnight")
                or "midnight"
            ),
        }

    def _activate_floating_workspace(
        self,
        workspace_key: str,
        close_if_floating: bool,
    ) -> bool:
        shell = getattr(
            getattr(self.context, "capabilities", None),
            "shell",
            None,
        )
        activate = getattr(shell, "activate_floating_workspace", None)
        if not callable(activate):
            self._log("NeuralCompanion floating workspaces are unavailable.")
            return False
        try:
            return bool(
                activate(
                    str(workspace_key or ""),
                    bool(close_if_floating),
                )
            )
        except Exception as exc:
            self._log(f"Could not activate floating workspace: {exc}")
            return False

    def _set_orb_popup_compact_mode(self, compact: bool) -> None:
        value = bool(compact)
        self._last_runtime_config["companion_orb_popup_compact_mode"] = value
        self._save_runtime_setting("companion_orb_popup_compact_mode", value)

    def _set_orb_popup_pinned(self, pinned: bool) -> None:
        value = bool(pinned)
        self._last_runtime_config["companion_orb_popup_pinned"] = value
        self._save_runtime_setting("companion_orb_popup_pinned", value)
        if value:
            self._last_runtime_config["companion_orb_popup_compact_mode"] = True
            self._save_runtime_setting("companion_orb_popup_compact_mode", True)
            if self._menu_open:
                self._finish_command_menu(
                    self._orb_popup_previous_click_through
                )

    def _set_orb_popup_width(self, width: int) -> None:
        value = max(440, min(760, int(width)))
        self._last_runtime_config["companion_orb_popup_width"] = value
        self._save_runtime_setting("companion_orb_popup_width", value)

    def _save_orb_popup_position(self, position: list[int]) -> None:
        try:
            values = [int(position[0]), int(position[1])]
        except (TypeError, ValueError, IndexError, OverflowError):
            return
        self._last_runtime_config["companion_orb_popup_position"] = values
        self._save_runtime_setting("companion_orb_popup_position", values)

    def _sync_pinned_popup_visibility(self) -> None:
        if bool(getattr(self, "_eye_tracking_reaction_shutting_down", False)):
            return
        pinned = bool(
            self._last_runtime_config.get("companion_orb_popup_pinned", False)
        )
        popup = self._orb_popup
        if not pinned:
            if (
                popup is not None
                and popup.view.isVisible()
                and popup.bridge.mode == "menu"
                and popup.bridge.pinned
            ):
                popup.close()
            return
        if popup is not None and popup.view.isVisible():
            return
        QtCore.QTimer.singleShot(0, self._restore_pinned_command_menu)

    def _restore_pinned_command_menu(self) -> None:
        if (
            bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
            or not bool(
                self._last_runtime_config.get(
                    "companion_orb_popup_pinned",
                    False,
                )
            )
        ):
            return
        popup = self._orb_popup
        if popup is not None and popup.view.isVisible():
            return
        self._show_command_menu()

    def _on_orb_popup_closed(self) -> None:
        if self._menu_open:
            self._finish_command_menu(
                self._orb_popup_previous_click_through
            )
        if (
            not bool(getattr(self, "_eye_tracking_reaction_shutting_down", False))
            and bool(
                self._last_runtime_config.get(
                    "companion_orb_popup_pinned",
                    False,
                )
            )
        ):
            QtCore.QTimer.singleShot(80, self._restore_pinned_command_menu)

    def _finish_command_menu(self, previous_click_through: bool):
        self._menu_open = False
        self._mark_user_interaction()
        self._apply_click_through(bool(previous_click_through))
        self._sync_drift_timer()

    def _handle_menu_command(self, command: str, global_pos: QtCore.QPoint | None = None):
        self._mark_user_interaction()
        normalized = str(command or "").strip().lower()
        if normalized == "chat text input":
            self._show_chat_input_popup(global_pos)
            return
        self._log(f"Companion Orb menu command selected: {command}")

    def _handle_reading_menu_action(self, action_id: str):
        self._mark_user_interaction()
        action = reading_actions.action_for_id(action_id)
        if action is None:
            self._debug_event("reading_action_rejected", action_id=str(action_id or ""), reason="unknown_action")
            self._log(f"Companion Orb reading action ignored: unknown action id {action_id!r}.")
            return
        normalized_action_id = _reading_action_id(action)
        if not self._begin_reading_job(normalized_action_id):
            return
        try:
            source = str(getattr(action, "text_source", "") or "").strip().lower()
            if source == "clipboard":
                text = self._read_clipboard_text()
                cleaned = reading_actions.clean_readable_text(text)
                if not cleaned:
                    self._debug_event("reading_action_cancelled", action_id=normalized_action_id, reason="empty_clipboard")
                    self._log("Companion Orb clipboard read skipped because the clipboard has no readable text.")
                    self._finish_reading_job(normalized_action_id, reason="empty_clipboard")
                    return
                self._start_reading_worker(action, selected_text=cleaned, bounds=[])
                return
            if source == "selection":
                bounds = self._select_reading_region(normalized_action_id)
                if not bounds:
                    self._debug_event("reading_action_cancelled", action_id=normalized_action_id, reason="selection_cancelled")
                    self._finish_reading_job(normalized_action_id, reason="selection_cancelled")
                    return
                self._start_reading_worker(action, selected_text="", bounds=bounds)
                return
            self._debug_event("reading_action_rejected", action_id=normalized_action_id, reason="unsupported_source", text_source=source)
            self._log(f"Companion Orb reading action ignored: unsupported source {source!r}.")
            self._finish_reading_job(normalized_action_id, reason="unsupported_source")
        except Exception as exc:
            self._debug_event("reading_action_failed", console=True, action_id=normalized_action_id, error=str(exc))
            self._log(f"Companion Orb reading action failed: {exc}")
            self._finish_reading_job(normalized_action_id, reason="failed")

    def _begin_reading_job(self, action_id: str) -> bool:
        with self._reading_job_lock:
            if self._reading_job_active:
                self._debug_event("reading_action_skipped", action_id=str(action_id or ""), reason="busy")
                self._log("Companion Orb reading action skipped because another reading action is still running.")
                return False
            self._reading_job_active = True
        self._debug_event("reading_action_started", action_id=str(action_id or ""))
        return True

    def _finish_reading_job(self, action_id: str, *, reason: str = "finished") -> None:
        with self._reading_job_lock:
            self._reading_job_active = False
        self._debug_event("reading_action_finished", action_id=str(action_id or ""), reason=str(reason or "finished"))

    def _read_clipboard_text(self) -> str:
        app = QtGui.QGuiApplication.instance()
        if app is None:
            return ""
        try:
            return str(app.clipboard().text() or "")
        except Exception as exc:
            self._debug_event("reading_clipboard_failed", console=True, error=str(exc))
            self._log(f"Companion Orb clipboard read failed: {exc}")
            return ""

    def _select_reading_region(self, action_id: str = "") -> list[int]:
        safe_action_id = str(action_id or "").strip()
        try:
            bounds = self._normalize_bounds(reading_overlay.select_region(self._window))
        except Exception as exc:
            self._debug_event("reading_selection_failed", console=True, action_id=safe_action_id, error=str(exc))
            self._log(f"Companion Orb reading area selection failed: {exc}")
            return []
        if bounds:
            self._debug_event("reading_region_selected", action_id=safe_action_id, bounds=bounds)
        else:
            self._debug_event("reading_region_cancelled", action_id=safe_action_id)
        return bounds

    def _start_reading_worker(
        self,
        action: Any,
        *,
        selected_text: str,
        bounds: list[int],
        private_bounds: bool = False,
    ) -> None:
        action_id = _reading_action_id(action)
        safe_bounds = self._normalize_bounds(bounds)
        diagnostic_bounds = [] if private_bounds else safe_bounds
        initial_text = reading_actions.clean_readable_text(selected_text)

        def worker() -> None:
            finish_reason = "finished"
            try:
                text = initial_text
                if str(getattr(action, "text_source", "") or "").strip().lower() == "selection":
                    if private_bounds:
                        text = self._extract_selected_reading_text(
                            safe_bounds,
                            action_id,
                            private_bounds=True,
                        )
                    else:
                        text = self._extract_selected_reading_text(safe_bounds, action_id)
                if not text:
                    finish_reason = "empty_text"
                    self._debug_event("reading_action_no_text", action_id=action_id, bounds=diagnostic_bounds)
                    self._log("Companion Orb reading action found no readable text.")
                    return
                guidance_text = ""
                if (
                    str(getattr(action, "text_source", "") or "").strip().lower()
                    == "selection"
                    and bool(getattr(action, "requests_comment", False))
                    and CompanionOrbController._visual_guidance_enabled(
                        self,
                        "reading",
                    )
                ):
                    guidance_text = self._capture_reading_visual_guidance(
                        safe_bounds,
                        action_id,
                    )
                speech_ctrl = None
                if bool(getattr(action, "speaks_text", False)):
                    speech_ctrl = self._speak_reading_text(text, action_id=action_id, phase="selected_text")
                if bool(getattr(action, "requests_comment", False)):
                    if speech_ctrl is not None:
                        self._wait_for_reading_speech(speech_ctrl, action_id=action_id, phase="selected_text")
                    comment = self._generate_reading_comment(
                        text,
                        action,
                        guidance_text=guidance_text,
                    )
                    if comment:
                        self._speak_reading_text(comment, action_id=action_id, phase="comment")
            except Exception as exc:
                finish_reason = "failed"
                self._debug_event(
                    "reading_worker_failed",
                    console=True,
                    action_id=action_id,
                    bounds=diagnostic_bounds,
                    error=str(exc),
                )
                self._log(f"Companion Orb reading worker failed: {exc}")
            finally:
                self._finish_reading_job(action_id, reason=finish_reason)

        threading.Thread(target=worker, daemon=True, name="companion-orb-reading").start()

    def _extract_selected_reading_text(
        self,
        bounds: list[int],
        action_id: str,
        *,
        private_bounds: bool = False,
    ) -> str:
        if not bounds:
            return ""
        diagnostic_bounds = [] if private_bounds else bounds
        window_regions: list[dict[str, Any]] = []
        window_backend = "none"
        try:
            window_regions = [] if self._last_runtime_config.get('companion_orb_exclude_nc_from_captures', False) else list(snapshot_ocr.extract_window_text_regions(bounds) or [])
            if window_regions:
                window_backend = "win32_window_text"
        except Exception as exc:
            self._debug_event(
                "reading_text_extract_failed",
                action_id=action_id,
                bounds=diagnostic_bounds,
                error=str(exc),
            )
        window_text = reading_actions.clean_readable_text(snapshot_ocr.readable_text_from_regions(window_regions))
        window_score = self._selected_reading_text_score(window_text)
        self._debug_event(
            "reading_window_text_probe",
            action_id=action_id,
            bounds=diagnostic_bounds,
            backend=window_backend,
            region_count=len(window_regions),
            char_count=len(window_text),
            score=window_score,
        )
        ocr_result = self._extract_selected_reading_ocr(
            bounds,
            action_id,
            allow_vision_fallback=window_score < 120,
            private_bounds=private_bounds,
        )
        ocr_regions = list((ocr_result or {}).get("regions") or [])
        ocr_backend = str((ocr_result or {}).get("backend") or "none")
        ocr_text = reading_actions.clean_readable_text(
            snapshot_ocr.readable_text_from_regions(ocr_regions)
            or str((ocr_result or {}).get("text") or "")
        )
        ocr_score = self._selected_reading_text_score(ocr_text)
        if ocr_text and (not window_text or window_score < 120 or ocr_score >= window_score):
            text = ocr_text
            regions = ocr_regions
            backend = ocr_backend
        else:
            text = window_text
            regions = window_regions
            backend = window_backend
        self._debug_event(
            "reading_text_extracted",
            action_id=action_id,
            bounds=diagnostic_bounds,
            backend=backend,
            region_count=len(regions),
            char_count=len(text),
            window_char_count=len(window_text),
            ocr_char_count=len(ocr_text),
        )
        return text

    @staticmethod
    def _selected_reading_text_score(text: str) -> int:
        cleaned = reading_actions.clean_readable_text(str(text or ""))
        if not cleaned:
            return 0
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        words = re.findall(r"\w+", cleaned)
        long_lines = sum(1 for line in lines if len(line) >= 24)
        sentence_marks = len(re.findall(r"[.!?;:]", cleaned))
        return len(cleaned) + (len(words) * 6) + (long_lines * 24) + (sentence_marks * 8)

    def _extract_selected_reading_ocr(
        self,
        bounds: list[int],
        action_id: str,
        *,
        allow_vision_fallback: bool = True,
        private_bounds: bool = False,
    ) -> dict[str, Any]:
        output_path: Path | None = None
        diagnostic_bounds = [] if private_bounds else bounds
        try:
            root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
            keep_debug_crop = self._keep_reading_debug_crops()
            output_dir = (
                root / "runtime" / "companion_orb" / "debug" / "reading_crops"
                if keep_debug_crop
                else root / "runtime" / "companion_orb" / "reading_ocr"
            )
            cloaked = bool(private_bounds and self._apply_snapshot_cloak_blocking(True))
            if cloaked:
                time.sleep(0.04)
            try:
                output_path = reading_overlay.capture_region_image(bounds, output_dir,
                    **CompanionOrbController._nc_grabber_kwargs(self))
            finally:
                if cloaked:
                    self._apply_snapshot_cloak_blocking(False)
            self._debug_event(
                "reading_ocr_capture_saved",
                action_id=action_id,
                bounds=diagnostic_bounds,
                image_path=output_path,
                allow_vision_fallback=bool(allow_vision_fallback),
            )
            result = snapshot_ocr.extract_snapshot_regions(
                output_path,
                screen_bounds=bounds,
                max_regions=OCR_MAX_REGIONS,
                include_window_text=not self._last_runtime_config.get('companion_orb_exclude_nc_from_captures', False),
            )
            readable_text = reading_actions.clean_readable_text(
                snapshot_ocr.readable_text_from_regions((result or {}).get("regions") or [])
                or str((result or {}).get("text") or "")
            )
            if not readable_text and allow_vision_fallback:
                vision_text = self._extract_selected_reading_text_with_vision_llm(
                    output_path,
                    bounds,
                    action_id,
                    private_bounds=private_bounds,
                )
                if vision_text:
                    result = dict(result or {})
                    result["backend"] = "vision_llm"
                    result["text"] = vision_text
                    result["regions"] = []
            self._debug_event(
                "reading_ocr_extract_finished",
                action_id=action_id,
                bounds=diagnostic_bounds,
                image_path=output_path,
                backend=str((result or {}).get("backend") or "none"),
                region_count=len((result or {}).get("regions") or []),
                char_count=len(readable_text or str((result or {}).get("text") or "")),
                allow_vision_fallback=bool(allow_vision_fallback),
            )
            return dict(result or {})
        except Exception as exc:
            self._debug_event(
                "reading_ocr_extract_failed",
                action_id=action_id,
                bounds=diagnostic_bounds,
                image_path=output_path,
                error=str(exc),
            )
            return {}
        finally:
            if output_path is not None:
                if self._keep_reading_debug_crops():
                    self._debug_event(
                        "reading_ocr_debug_crop_kept",
                        action_id=action_id,
                        bounds=diagnostic_bounds,
                        image_path=output_path,
                    )
                else:
                    try:
                        Path(output_path).unlink(missing_ok=True)
                    except Exception:
                        pass

    def _capture_reading_visual_guidance(
        self,
        bounds: list[int],
        action_id: str,
    ) -> str:
        del action_id
        safe_bounds = self._normalize_bounds(bounds)
        if not safe_bounds or not CompanionOrbController._visual_guidance_enabled(
            self,
            "reading",
        ):
            return ""
        output_path: Path | None = None
        cloaked = False
        try:
            root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
            keep_debug_crop = self._keep_reading_debug_crops()
            output_dir = (
                root / "runtime" / "companion_orb" / "debug" / "reading_guidance"
                if keep_debug_crop
                else root / "runtime" / "companion_orb" / "reading_guidance"
            )
            cloaked = bool(self._apply_snapshot_cloak_blocking(True))
            if cloaked:
                time.sleep(0.04)
            output_path = Path(
                reading_overlay.capture_region_image(safe_bounds, output_dir,
                    **CompanionOrbController._nc_grabber_kwargs(self))
            )
            return self._visual_guidance_for_image(
                output_path,
                scope="reading",
            )
        except Exception:
            return ""
        finally:
            if cloaked:
                self._apply_snapshot_cloak_blocking(False)
            if output_path is not None and not self._keep_reading_debug_crops():
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _extract_selected_reading_text_with_vision_llm(
        self,
        image_path: Path,
        bounds: list[int],
        action_id: str,
        *,
        private_bounds: bool = False,
    ) -> str:
        diagnostic_bounds = [] if private_bounds else bounds
        try:
            text = self.orb_runtime.extract_selected_text(
                str(image_path),
                screen_bounds=[] if private_bounds else list(bounds or []),
            )
            cleaned = reading_actions.clean_readable_text(str(text or ""))
            self._debug_event(
                "reading_vision_text_extracted" if cleaned else "reading_vision_text_empty",
                action_id=action_id,
                bounds=diagnostic_bounds,
                image_path=image_path,
                char_count=len(cleaned),
            )
            return cleaned
        except Exception as exc:
            self._debug_event(
                "reading_vision_text_failed",
                action_id=action_id,
                bounds=diagnostic_bounds,
                image_path=image_path,
                error=str(exc),
            )
            return ""

    def _reading_max_chunk_chars(self) -> int | None:
        raw_value = self._last_runtime_config.get("companion_orb_reading_max_chunk_chars", None)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        return value if 100 <= value <= 5000 else None

    def _reading_chunks(self, text: str) -> list[str]:
        max_chars = self._reading_max_chunk_chars()
        if max_chars is None:
            return reading_actions.chunk_text_for_tts(text)
        return reading_actions.chunk_text_for_tts(text, max_chars=max_chars)

    def _keep_reading_debug_crops(self) -> bool:
        settings = dict(getattr(self, "_last_runtime_config", {}) or {})
        if not bool(settings.get("companion_orb_debug_enabled", False)):
            return False
        value = settings.get("companion_orb_reading_keep_debug_crops", False)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _interrupt_audio_for_reading_action(self, *, action_id: str, phase: str) -> None:
        try:
            result = self.playback.interrupt(
                reason=f"companion_orb_reading:{action_id}:{phase}",
                cancel_llm_streams=True,
            )
            self._debug_event(
                "reading_audio_interrupted",
                action_id=action_id,
                phase=phase,
                cancelled_controllers=int(dict(result or {}).get("cancelled_controllers", 0) or 0),
                cancelled_streams=int(dict(result or {}).get("cancelled_streams", 0) or 0),
            )
            return
        except Exception as exc:
            self._debug_event("reading_audio_interrupt_failed", action_id=action_id, phase=phase, error=str(exc))

    def _speak_reading_text(self, text: str, *, action_id: str, phase: str):
        chunks = self._reading_chunks(text)
        if not chunks:
            self._debug_event("reading_speech_skipped", action_id=action_id, phase=phase, reason="empty_text")
            return None
        speech_text = " ".join(
            str(chunk or "").strip()
            for chunk in chunks
            if str(chunk or "").strip()
        )
        if not self._ensure_reading_tts_runtime_ready():
            self._debug_event("reading_speech_skipped", console=True, action_id=action_id, phase=phase, reason="tts_not_ready")
            self._log("Companion Orb reading speech skipped because TTS is not initialized yet.")
            return None
        try:
            self._interrupt_audio_for_reading_action(action_id=action_id, phase=phase)
            ctrl = self.speech.speak(speech_text)
            self._debug_event(
                "reading_speech_queued",
                action_id=action_id,
                phase=phase,
                chunk_count=len(chunks),
                char_count=len(speech_text),
            )
            return ctrl
        except Exception as exc:
            self._debug_event("reading_speech_failed", console=True, action_id=action_id, phase=phase, error=str(exc))
            self._log(f"Companion Orb reading speech failed: {exc}")
            return None

    def _wait_for_reading_speech(self, ctrl, *, action_id: str, phase: str) -> None:
        done = getattr(ctrl, "done", None)
        wait = getattr(done, "wait", None)
        if not callable(wait):
            return
        self._debug_event("reading_speech_wait_started", action_id=action_id, phase=phase)
        try:
            while True:
                if wait(timeout=0.25):
                    break
        except Exception as exc:
            self._debug_event("reading_speech_wait_failed", action_id=action_id, phase=phase, error=str(exc))
            return
        self._debug_event("reading_speech_wait_finished", action_id=action_id, phase=phase)

    def _reading_runtime_setting(self, primary_key: str, legacy_key: str, default: Any) -> Any:
        settings = self._last_runtime_config
        if primary_key in settings:
            return settings.get(primary_key)
        if legacy_key in settings:
            return settings.get(legacy_key)
        return reading_actions.READING_SETTINGS_DEFAULTS.get(primary_key, default)

    def _reading_exclude_from_memory(self) -> bool:
        value = self._reading_runtime_setting(
            "companion_orb_reader_exclude_from_memory",
            "companion_orb_reading_exclude_from_memory",
            True,
        )
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _reading_comment_prompt(self) -> str:
        default_prompt = str(
            reading_actions.READING_SETTINGS_DEFAULTS.get(
                "companion_orb_reader_commentary_prompt",
                reading_actions.DEFAULT_COMMENTARY_PROMPT,
            )
            or reading_actions.DEFAULT_COMMENTARY_PROMPT
        )
        prompt = str(
            self._reading_runtime_setting(
                "companion_orb_reader_commentary_prompt",
                "companion_orb_reading_comment_prompt",
                default_prompt,
            )
            or ""
        ).strip()
        return prompt or default_prompt

    def _generate_reading_comment(
        self,
        selected_text: str,
        action: Any,
        *,
        guidance_text: str = "",
    ) -> str:
        action_id = _reading_action_id(action)
        if not self._ensure_reading_tts_runtime_ready():
            self._debug_event("reading_comment_skipped", console=True, action_id=action_id, reason="tts_not_ready")
            self._log("Companion Orb reading comment skipped because TTS is not initialized yet.")
            return ""
        try:
            behavior_prompt = self._reading_comment_prompt()
            bounded_guidance = str(guidance_text or "").strip()[:1400]
            if bounded_guidance:
                behavior_prompt += (
                    "\n\nTemporary visual evidence for this one reading comment:\n"
                    + bounded_guidance
                )
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "main_chat",
                    scope="reading",
                    route="lfm_observation_to_main_chat",
                )
            comment = self.orb_runtime.ephemeral_comment(
                selected_text=selected_text,
                behavior_prompt=behavior_prompt,
                response_style_label=self._response_style_label(),
                exclude_from_memory=self._reading_exclude_from_memory(),
                mode=_reading_action_comment_mode(action),
            )
            cleaned = reading_actions.clean_readable_text(comment)
            self._debug_event("reading_comment_generated", action_id=action_id, char_count=len(cleaned))
            return cleaned
        except Exception as exc:
            if str(guidance_text or "").strip():
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "error",
                    scope="reading",
                    error=str(exc),
                )
            self._debug_event("reading_comment_failed", console=True, action_id=action_id, error=str(exc))
            self._log(f"Companion Orb reading comment failed: {exc}")
            return ""

    def _set_response_style(self, style: str):
        value = _normalize_orb_response_style(style)
        self._last_runtime_config["companion_orb_response_style"] = value
        self._save_runtime_setting("companion_orb_response_style", value)
        label = next((item_label for item_label, item_value in ORB_RESPONSE_STYLES if item_value == value), "Very friendly")
        self._debug_event("response_style_changed", console=True, response_style=value, label=label)
        self._log(f"Companion Orb response style set to: {label}")

    def _show_chat_input_popup(
        self,
        global_pos: QtCore.QPoint | None = None,
        *,
        context_label: str = "",
    ):
        compact_context = re.sub(r"\s+", " ", str(context_label or "")).strip()[:120]
        title = (
            f"Ask about: {compact_context}"
            if compact_context
            else "Companion Orb Chat"
        )
        placeholder = (
            f"Ask NC about {compact_context}..."
            if compact_context
            else "Type a message to NC..."
        )
        point = QtCore.QPoint(global_pos) if isinstance(global_pos, QtCore.QPoint) else QtGui.QCursor.pos()
        popup = self._orb_popup
        if (
            bool(self._last_runtime_config.get("companion_orb_popup_pinned", False))
            and popup is not None
            and popup.view.isVisible()
        ):
            point = QtCore.QPoint(popup.view.position())
        try:
            self._ensure_orb_popup().show_input(
                point,
                title=title,
                placeholder=placeholder,
                submit=self._send_orb_chat_message,
                theme_preset=str(
                    self._last_runtime_config.get(
                        "ui_theme_preset",
                        "midnight",
                    )
                ),
            )
        except Exception as exc:
            self._log(f"Companion Orb chat popup failed: {exc}")

    def _send_orb_chat_message(self, message: str) -> tuple[bool, str]:
        text = str(message or "").strip()
        if not text:
            return False, "Type a message first."
        try:
            result = self.accepted_turns.submit(text, role="user")
            if bool(dict(result or {}).get("queued", False)):
                self._log("Companion Orb queued chat text input through the accepted-turn port.")
                return True, "Message sent."
            reason = str(dict(result or {}).get("reason") or "not queued")
            return False, f"Message was not queued: {reason}."
        except Exception as exc:
            self._log(f"Companion Orb chat send failed: {exc}")
            return False, "Message was not queued. Initialize NC first."

    def _available_voice_files(self) -> list[Path]:
        voices_dir = self._voices_dir()
        try:
            if not voices_dir.exists():
                return []
            return sorted(
                (
                    path
                    for path in voices_dir.rglob("*")
                    if path.is_file() and path.suffix.lower() in VOICE_FILE_SUFFIXES
                ),
                key=lambda path: self._voice_menu_label(path).lower(),
            )
        except Exception:
            return []

    def _voices_dir(self) -> Path:
        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        return root / "voices"

    def _voice_config_path(self, voice_file: Path) -> str:
        path = Path(voice_file)
        try:
            relative = path.resolve().relative_to(self._voices_dir().resolve())
        except Exception:
            relative = Path(path.name)
        return str(Path("voices") / relative)

    def _normalized_voice_config_path(self, value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            path = Path(raw)
            if path.is_absolute():
                raw = self._voice_config_path(path)
        except Exception:
            pass
        return raw.replace("\\", "/").lower()

    def _voice_menu_label(self, voice_file: Path) -> str:
        path = Path(voice_file)
        try:
            relative = path.resolve().relative_to(self._voices_dir().resolve())
        except Exception:
            relative = Path(path.name)
        return str(relative.with_suffix("")).replace("\\", " / ")

    def _select_voice_file(self, voice_file: Path):
        path = Path(voice_file)
        if not path.exists():
            self._log(f"Voice file is missing: {path}")
            return
        relative = self._voice_config_path(path)
        updates = {
            "voice_path": relative,
            "tts_use_cloned_voice": True,
            "pocket_tts_use_cloned_voice": True,
        }
        for key, value in updates.items():
            self._last_runtime_config[key] = value
            try:
                self.runtime_config.update(key, value)
            except Exception:
                pass
        self._save_timer.start()
        self._log(f"Companion Orb selected TTS voice reference: {relative}")

    def _announce_drop_inspection(self, target: dict[str, Any] | None, *, reason: str):
        now = time.monotonic()
        if now - self._last_drop_ack_at < DROP_ACK_COOLDOWN_SECONDS:
            self._debug_event("drop_ack_skipped", reason=reason, skip_reason="cooldown")
            return
        self._last_drop_ack_at = now
        message = self._build_drop_ack_message(target)
        self._debug_event(
            "drop_ack_started",
            console=True,
            reason=reason,
            message=message,
            target=self._target_for_output(target if isinstance(target, dict) else {}),
        )
        try:
            self.context.events.publish(
                "companion_orb_drop_inspection_started",
                {
                    "message": str(message or ""),
                    "target": self._target_for_output(target if isinstance(target, dict) else {}),
                    "reason": str(reason or "drag_drop"),
                    "source": "companion_orb",
                },
            )
        except Exception:
            pass
        if bool(self._last_runtime_config.get("companion_orb_speak_drop_acknowledgement", False)):
            self._speak_drop_ack_message(message)
        else:
            self._debug_event("drop_ack_speech_skipped", reason=reason, skip_reason="content_comment_priority", message=message)

    def _build_drop_ack_message(self, target: dict[str, Any] | None = None) -> str:
        title = self._target_title_from_info(target if isinstance(target, dict) else None)
        return self._style_orb_canned_message(random.choice(DROP_ACK_MESSAGES), kind="drop", target_title=title)

    def _speak_drop_ack_message(self, message: str):
        if not self._tts_runtime_ready():
            self._log("Companion Orb drop acknowledgement held until TTS is initialized.")
            self._debug_event("drop_ack_skipped", console=True, skip_reason="tts_not_ready", message=message)
            return

        def speaker():
            try:
                is_audio_active = bool(self.playback.snapshot().get("speech_playing", False))
                if is_audio_active:
                    self.playback.interrupt(reason="companion_orb_drop_ack")
                    time.sleep(0.12)
                self.speech.speak(str(message or "").strip())
                self._debug_event("drop_ack_spoken", message=message, interrupted_audio=bool(is_audio_active))
                return
            except Exception as exc:
                self._debug_event("drop_ack_failed", console=True, message=message, error=str(exc))
                self._log(f"Could not speak Companion Orb drop acknowledgement: {exc}")
            self._log(f"Companion Orb drop acknowledgement: {message}")

        threading.Thread(target=speaker, daemon=True, name="companion-orb-drop-ack").start()

    def _announce_harassment(self):
        now = time.monotonic()
        if now - self._last_harassment_message_at < HARASSMENT_SPEECH_COOLDOWN_SECONDS:
            return
        if not self._tts_runtime_ready():
            self._log("Companion Orb harassment speech held until TTS is initialized.")
            return
        target_info = self._pointer_target_info()
        target_title = self._target_title_from_info(target_info)
        message = self._build_harassment_message(target_title)
        self._last_harassment_message_at = now
        if target_info:
            self._set_comment_focus({"target": target_info, "label": target_title or "pointer focus", "duration_seconds": 10.0})
        self._publish_harassment_event(message, target_title)
        if self._nudge_should_defer_to_pointer_snapshot():
            self._debug_event("companion_orb_harassment_deferred_to_snapshot", message=message, target_title=target_title)
            return
        if self._queue_llm_harassment_candidate(message, target_title, target_info):
            self._debug_event("companion_orb_harassment_queued_hidden", message=message, target_title=target_title)
            return
        self._speak_harassment_message(message)

    def _nudge_should_defer_to_pointer_snapshot(self) -> bool:
        return bool(self._last_runtime_config.get("companion_orb_snapshot_on_pointer_reached", False))

    def _tts_runtime_ready(self) -> bool:
        try:
            return bool(self.speech.snapshot().get("ready", False))
        except Exception:
            return False

    def _ensure_reading_tts_runtime_ready(self) -> bool:
        if self._tts_runtime_ready():
            return True
        try:
            ready = bool(self.speech.ensure_ready())
        except Exception as exc:
            self._debug_event(
                "reading_tts_prepare_failed",
                console=True,
                error=str(exc),
            )
            self._log(f"Companion Orb could not prepare TTS for reading: {exc}")
            return False
        self._debug_event(
            "reading_tts_prepared" if ready else "reading_tts_prepare_failed",
            console=not ready,
        )
        return ready

    def _build_harassment_message(self, target_title: str = "") -> str:
        title = str(target_title or "").strip()
        if title:
            try:
                message = random.choice(HARASSMENT_CONTEXT_MESSAGES).format(target=title[:80])
                return self._style_orb_canned_message(message, kind="harassment_context", target_title=title)
            except Exception:
                pass
        return self._style_orb_canned_message(random.choice(HARASSMENT_MESSAGES), kind="harassment", target_title=title)

    def _current_response_style(self) -> str:
        return _normalize_orb_response_style(self._last_runtime_config.get("companion_orb_response_style", "friendly"))

    def _response_style_label(self) -> str:
        current = self._current_response_style()
        return next((label for label, value in ORB_RESPONSE_STYLES if value == current), "Very friendly")

    def _style_response_pool(self, style: str, kind: str) -> tuple[str, ...]:
        normalized_style = _normalize_orb_response_style(style)
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind == "drop":
            return DROP_ACK_STYLE_MESSAGES.get(normalized_style, DROP_ACK_STYLE_MESSAGES["friendly"])
        if normalized_kind == "harassment_context":
            return HARASSMENT_CONTEXT_STYLE_MESSAGES.get(normalized_style, HARASSMENT_CONTEXT_STYLE_MESSAGES["friendly"])
        if normalized_kind == "harassment":
            return HARASSMENT_STYLE_MESSAGES.get(normalized_style, HARASSMENT_STYLE_MESSAGES["friendly"])
        return ()

    def _choose_style_response_template(self, style: str, kind: str) -> str:
        pool = self._style_response_pool(style, kind)
        if not pool:
            return ""
        key = f"{_normalize_orb_response_style(style)}:{str(kind or '').strip().lower()}"
        recent_map = getattr(self, "_recent_canned_response_templates", None)
        if not isinstance(recent_map, dict):
            recent_map = {}
            self._recent_canned_response_templates = recent_map
        recent = [item for item in recent_map.get(key, []) if item in pool]
        candidates = [item for item in pool if item not in recent]
        template = random.choice(candidates or list(pool))
        recent.append(template)
        recent_map[key] = recent[-4:]
        return template

    def _style_orb_canned_message(self, message: str, *, kind: str = "message", target_title: str = "") -> str:
        text = str(message or "").strip()
        style = self._current_response_style()
        template = self._choose_style_response_template(style, kind)
        if template:
            target = str(target_title or "").strip()[:80] or "that spot"
            try:
                return template.format(target=target)
            except Exception:
                return template
        if not text:
            return ""
        if style == "loving":
            suffix = " I am right here with you."
        elif style == "sarcastic":
            suffix = " Naturally, this is all extremely normal."
        elif style == "roast":
            suffix = " The evidence is doing its best, which is frankly brave."
        elif style == "sensual_non_explicit":
            suffix = " Lead me closer, slowly. I will keep it tasteful."
        else:
            return text
        if text.endswith(suffix.strip()):
            return text
        return f"{text}{suffix}"

    def _pointer_target_title(self) -> str:
        return self._target_title_from_info(self._pointer_target_info())

    def _pointer_target_info(self) -> dict[str, Any]:
        cursor = QtGui.QCursor.pos()
        try:
            target = self._resolve_target_at(cursor, width=360, height=220, mode="window")
        except Exception:
            target = None
        if not target or self._is_own_target(target):
            return {}
        return dict(target or {})

    def _target_title_from_info(self, target: dict[str, Any] | None) -> str:
        if not target:
            return ""
        title = str(target.get("title") or "").strip()
        process_name = str(target.get("process_name") or "").strip() if self._include_process_name() else ""
        if process_name and title:
            return f"{title} - {process_name}"
        return title

    def _include_process_name(self) -> bool:
        return bool(self._last_runtime_config.get("companion_orb_include_process_name", True))

    def _target_for_output(self, target: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(target or {})
        if not self._include_process_name():
            payload["process_name"] = ""
        return payload

    def _publish_harassment_event(self, message: str, target_title: str = ""):
        try:
            self.context.events.publish(
                "companion_orb_harassment_started",
                {
                    "message": str(message or ""),
                    "target_title": str(target_title or ""),
                    "source": "companion_orb",
                    "llm_instruction": (
                        f"If responding, create one brief line relevant to the current user activity. "
                        f"Use the Companion Orb response style '{self._response_style_label()}'. "
                        "Keep it non-disruptive and grounded in the visible context."
                    ),
                },
            )
        except Exception:
            pass

    def _queue_llm_harassment_candidate(self, message: str, target_title: str = "", target_info: dict[str, Any] | None = None) -> bool:
        try:
            if not self._tts_runtime_ready():
                return False
            if not bool(self.runtime_config.get("sensory_allow_hidden_proactive_speech", False)):
                return False
            return self.orb_runtime.submit_proactive(
                str(message or ""),
                summary="Companion Orb started playful pointer harassment.",
                attention=str(target_title or "pointer"),
                source="companion_orb",
                allow_repeated_candidate=False,
                focus_bounds=target_bounds(target_info),
                focus_label=str(target_title or "pointer"),
                focus_duration_seconds=COMMENT_FOCUS_DEFAULT_SECONDS,
            )
        except Exception:
            pass
        return False

    def _speak_harassment_message(self, message: str):
        if not self._tts_runtime_ready():
            self._log("Companion Orb harassment message skipped because TTS is not initialized yet.")
            return
        if self.bridge.aiState == "speaking" or self.bridge.audioLevel > 0.035:
            self._log(f"Companion Orb harassment message queued while TTS is active: {message}")
            return
        try:
            self.speech.speak(str(message or "").strip())
            return
        except Exception as exc:
            self._log(f"Could not speak Companion Orb harassment message: {exc}")
        self._log(f"Companion Orb harassment message: {message}")

    def _maybe_capture_pointer_snapshot(self):
        if not bool(self._last_runtime_config.get("companion_orb_snapshot_on_pointer_reached", False)):
            return
        window = self._window
        if window is None:
            return
        cursor = QtGui.QCursor.pos()
        center = window.frameGeometry().center()
        reach_distance = max(48.0, min(150.0, float(window.width()) * 0.36))
        distance = math.hypot(float(center.x() - cursor.x()), float(center.y() - cursor.y()))
        if distance > reach_distance:
            return
        now = time.monotonic()
        if now - self._last_pointer_snapshot_at < POINTER_SNAPSHOT_COOLDOWN_SECONDS:
            return
        self._last_pointer_snapshot_at = now
        self._capture_pointer_snapshot(cursor)

    def _capture_pointer_snapshot(self, cursor: QtCore.QPoint):
        self._capture_pointer_snapshot_async(cursor, reason="pointer_reached")

    def _capture_pointer_snapshot_async(
        self,
        cursor: QtCore.QPoint,
        *,
        reason: str = "pointer_reached",
        inspection_id: int | None = None,
        trace_id: str = "",
        target_override: dict[str, Any] | None = None,
        release_drop_inspection: bool = False,
    ):
        cursor_point = QtCore.QPoint(cursor)
        trace = str(trace_id or self._active_drop_trace_id or "").strip()
        selected_target = dict(target_override or {})
        self._drop_trace_event("snapshot_pointer_queued", trace, console=True, cursor=cursor_point, reason=reason, inspection_id=inspection_id or 0)

        def worker():
            try:
                target = dict(selected_target)
                if not target:
                    width = int(self._last_runtime_config.get("companion_orb_target_region_width", 640) or 640)
                    height = int(self._last_runtime_config.get("companion_orb_target_region_height", 420) or 420)
                    target = resolve_target_at(cursor_point.x(), cursor_point.y(), region_width=width, region_height=height, mode="region")
                self._drop_trace_event(
                    "snapshot_pointer_resolved",
                    trace,
                    cursor=cursor_point,
                    reason=reason,
                    target=self._target_for_output(target if isinstance(target, dict) else {}),
                    bounds=target_bounds(target if isinstance(target, dict) else None),
                    inspection_id=inspection_id or 0,
                )
                self._capture_inspection_snapshot(target, reason=reason, inspection_id=inspection_id, trace_id=trace)
            except Exception as exc:
                self._drop_trace_event("snapshot_pointer_failed", trace, console=True, cursor=cursor_point, reason=reason, error=str(exc))
                CompanionOrbController._request_drop_capture_finish(self, int(inspection_id or 0))
                self._log(f"Companion Orb pointer snapshot failed: {exc}")
            finally:
                if release_drop_inspection:
                    self._end_drop_inspection()

        threading.Thread(target=worker, daemon=True, name="companion-orb-pointer-snapshot").start()

    def _inspect_drop_target(self, point: QtCore.QPoint, *, reason: str = "drag_drop"):
        now = time.monotonic()
        if now - self._last_drop_inspection_at < DROP_INSPECTION_COOLDOWN_SECONDS:
            return
        if not self._drop_inspection_lock.acquire(blocking=False):
            self._debug_event(
                "drop_inspection_busy_skipped",
                console=True,
                point=point,
                reason=reason,
            )
            self._log("Companion Orb drop ignored while the previous drop is still being prepared.")
            return
        release_drop_inspection = True
        try:
            if self._drop_model_request_active():
                self._debug_event(
                    "drop_inspection_busy_skipped",
                    console=True,
                    point=point,
                    reason=reason,
                    busy_reason="llm_request_active",
                )
                self._log("Companion Orb drop ignored while a model request is already active.")
                return
            self._last_drop_inspection_at = now
            width = int(self._last_runtime_config.get("companion_orb_target_region_width", 640) or 640)
            height = int(self._last_runtime_config.get("companion_orb_target_region_height", 420) or 420)
            mode = str(self._last_runtime_config.get("companion_orb_target_mode", "window") or "window")
            drop_mode = {"left_drag_drop": "region", "right_drag_drop": "window"}.get(reason)
            mode = drop_mode or mode
            target = self._resolve_target_at(point, width=width, height=height, mode=mode)
            if drop_mode == 'window' and target.get('desktop_background'):
                monitors = capture_scope.monitor_snapshot()
                monitor = capture_scope.select_screen((point.x(), point.y()), monitors)
                if monitor is None:
                    return
                target = dict(target_type='screen', title='Entire screen — ' + monitor['label'],
                              bounds=monitor['logical_bounds'], screen_identity=monitor['identity'],
                              capture_monitors=monitors, process_name='')
            bounds = target_bounds(target)
            if not bounds:
                self._debug_event("drop_inspection_rejected", console=True, point=point, reason=reason, width=width, height=height, mode=mode)
                return
            self._manual_inspection_id += 1
            inspection_id = int(self._manual_inspection_id)
            self._active_snapshot_inspection_id = inspection_id
            trace_id = self._new_drop_trace_id(inspection_id)
            self._active_drop_trace_id = trace_id
            self._drop_trace_starts[trace_id] = time.monotonic()
            for stale_trace, started_at in list(self._drop_trace_starts.items()):
                if stale_trace != trace_id and (time.monotonic() - float(started_at or 0.0)) > 300.0:
                    self._drop_trace_starts.pop(stale_trace, None)
            self._clear_snapshot_context(reason=reason)
            self._clear_comment_focus()
            self._drop_trace_event("drop_inspection_started", trace_id, console=True, point=point, reason=reason, bounds=bounds)
            anchor_point = self._current_orb_top_left_for_drop()
            if anchor_point is not None:
                self._set_manual_drop_anchor(anchor_point, duration_seconds=DROP_ANCHOR_HOVER_SECONDS)
            self._set_manual_inspection(target, reason=reason, inspection_id=inspection_id)
            self._drop_capture = DropCapture(inspection_id, target, deadline=time.monotonic() + MANUAL_INSPECTION_SECONDS)
            CompanionOrbController._prepare_drop_watch_offer(self, inspection_id, target, reason)
            target_display = CompanionOrbController._capture_target_presentation(self)
            self.bridge.set_target_info(target_display)
            self._send_external_runtime({"type": "target_info", "target": target_display})
            self._interrupt_audio_for_drop_comment(reason=reason)
            self.request_comment_focus(
                {
                    "bounds": list(bounds),
                    "label": "selected content",
                    "text": "inspect the visible content inside the selected focus area",
                    "duration_seconds": DROP_FOCUS_SECONDS,
                    "manual_drop": True,
                    "drop_trace_id": trace_id,
                    "drop_anchor": [
                        int(self._manual_drop_anchor_point.x()),
                        int(self._manual_drop_anchor_point.y()),
                    ]
                    if self._manual_drop_anchor_point is not None
                    else [],
                }
            )
            self._announce_drop_inspection(target, reason=reason)
            self._capture_pointer_snapshot_async(
                point,
                reason=reason,
                inspection_id=inspection_id,
                trace_id=trace_id,
                target_override=target,
                release_drop_inspection=True,
            )
            release_drop_inspection = False
        finally:
            if release_drop_inspection:
                self._end_drop_inspection()

    def _drop_model_request_active(self) -> bool:
        try:
            snapshot = dict(self.orb_runtime.busy_snapshot() or {})
        except Exception:
            return False
        return bool(snapshot.get("_llm_request_active", False))

    def _end_drop_inspection(self) -> None:
        try:
            self._drop_inspection_lock.release()
        except RuntimeError:
            pass

    def _drop_inspection_is_current(self, inspection_id: int | None) -> bool:
        try:
            expected = int(inspection_id or 0)
            active = int(self._active_snapshot_inspection_id or 0)
        except Exception:
            return False
        return not expected or expected == active

    def _set_manual_inspection(self, target: dict[str, Any] | None, *, reason: str, inspection_id: int | None = None):
        bounds = self._normalize_bounds(target_bounds(target if isinstance(target, dict) else None))
        if inspection_id:
            self._active_snapshot_inspection_id = int(inspection_id)
        self._manual_inspection_bounds = list(bounds or [])
        self._manual_inspection_reason = str(reason or "manual_inspection")
        self._manual_inspection_until = time.monotonic() + MANUAL_INSPECTION_SECONDS
        self._debug_event(
            "manual_inspection_set",
            console=bool(bounds),
            reason=self._manual_inspection_reason,
            bounds=bounds,
            target=self._target_for_output(target if isinstance(target, dict) else {}),
            inspection_id=int(self._active_snapshot_inspection_id or 0),
        )

    def _manual_inspection_payload(self) -> dict[str, Any]:
        if not self._manual_inspection_active():
            if self._manual_inspection_bounds:
                self._debug_event(
                    "manual_inspection_expired",
                    reason=str(self._manual_inspection_reason or "manual_inspection"),
                    bounds=list(self._manual_inspection_bounds or []),
                )
            if self._drop_focus_text_is_stale(self._pending_comment_focus_text, self._pending_comment_focus_label):
                self._pending_comment_focus_text = ""
                self._pending_comment_focus_label = ""
            self._manual_inspection_bounds = []
            self._manual_inspection_reason = ""
            self._active_snapshot_inspection_id = 0
            return {}
        bounds = self._normalize_bounds(self._manual_inspection_bounds)
        return {
            "reason": str(self._manual_inspection_reason or "manual_inspection"),
            "primary": True,
            "inspection_id": int(self._active_snapshot_inspection_id or 0),
            "focus_bounds": list(bounds),
            "instruction": (
                "The user deliberately placed the Companion Orb on this point of interest. Inspect the actual visible "
                "content inside or near these bounds. Do not describe the placement action, and do not summarize unrelated "
                "desktop windows. Comment on the crop content and return focus_bounds for the exact visible thing being discussed."
            ),
            "required_response_focus": "visible_content_inside_drop_crop",
        }

    def _request_hidden_pingpong_cycle_async(self, *, reason: str = "manual_inspection", snapshots=None, trace_id: str = ""):
        trace = str(trace_id or self._active_drop_trace_id or "").strip()
        snapshot_payload = [dict(item) for item in list(snapshots or []) if isinstance(item, dict)]
        inspection_id = 0
        for snapshot in snapshot_payload:
            metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}
            try:
                inspection_id = max(
                    inspection_id,
                    int(metadata.get("manual_inspection_id") or snapshot.get("manual_inspection_id") or 0),
                )
            except Exception:
                continue
        manual_priority = any(
            bool(((item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}).get("manual_inspection_primary"))
            for item in snapshot_payload
        )
        max_attempts = 80 if manual_priority else (16 if snapshot_payload else 6)
        retry_delay = 0.12 if manual_priority else (0.18 if snapshot_payload else 0.5)
        self._drop_trace_event(
            "hidden_ping_requested",
            trace,
            console=True,
            reason=reason,
            snapshot_count=len(snapshot_payload),
            manual_priority=bool(manual_priority),
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay,
        )

        def worker():
            try:
                if not snapshot_payload:
                    time.sleep(0.03)
                for attempt in range(max_attempts):
                    if inspection_id and not self._drop_inspection_is_current(inspection_id):
                        self._drop_trace_event(
                            "hidden_ping_stale_cancelled",
                            trace,
                            console=True,
                            reason=reason,
                            inspection_id=inspection_id,
                            attempt=attempt + 1,
                        )
                        return
                    request = {"force": True}
                    if snapshot_payload:
                        request.update(
                            snapshots_override=snapshot_payload,
                            priority=bool(manual_priority),
                            priority_source="companion_orb_drop" if manual_priority else "",
                            trace_id=trace,
                        )
                    accepted = bool(self.orb_runtime.run_sensory_cycle(**request))
                    self._drop_trace_event("hidden_ping_attempt", trace, reason=reason, attempt=attempt + 1, accepted=accepted)
                    if accepted:
                        CompanionOrbController._mark_drop_response_submitted(self, trace)
                        self._drop_trace_event("hidden_ping_accepted", trace, console=True, reason=reason, attempt=attempt + 1)
                        return
                    time.sleep(retry_delay)
                self._drop_trace_event("hidden_ping_gave_up", trace, console=True, reason=reason, attempts=max_attempts)
                CompanionOrbController._request_drop_capture_finish(self, inspection_id)
            except Exception as exc:
                self._drop_trace_event("hidden_ping_failed", trace, console=True, reason=reason, error=str(exc))
                CompanionOrbController._request_drop_capture_finish(self, inspection_id)
                self._log(f"Companion Orb could not request hidden sensory inspection ({reason}): {exc}")

        threading.Thread(target=worker, daemon=True, name="companion-orb-hidden-inspection").start()

    def _smart_drop_guidance_mode(self) -> str:
        if not bool(self._last_runtime_config.get("companion_orb_smart_drop_guidance_enabled", False)):
            return "off"
        mode = str(self._last_runtime_config.get("companion_orb_smart_drop_guidance_mode", "off") or "off").strip().lower()
        return mode if mode in VALID_SMART_DROP_GUIDANCE_MODES else "off"

    def _fast_drop_guidance_payload(self, metadata: dict[str, Any]) -> dict[str, str]:
        metadata = dict(metadata or {})
        ocr_text = re.sub(r"\s+", " ", str(metadata.get("ocr_text") or "").strip())
        target = dict(metadata.get("target") or {}) if isinstance(metadata.get("target"), dict) else {}
        target_title = re.sub(r"\s+", " ", str(target.get("title") or "").strip())
        subject = ocr_text[:160] if ocr_text else (target_title[:160] if target_title else "the selected screen crop")
        return {
            "scene_type": "desktop_crop",
            "main_subject": subject,
            "mood": "observant",
            "response_style_hint": f"short natural Companion Orb comment in {self._response_style_label()} style",
            "what_to_comment_on": "the most useful visible detail in the selected crop",
            "what_to_avoid": "do not mention dragging, dropping, screenshots, coordinates, or hidden delivery mechanics",
        }

    def _prepare_drop_response_guidance(self, image_path: str, metadata: dict[str, Any], *, trace_id: str = "") -> tuple[dict[str, str], str]:
        if CompanionOrbController._visual_guidance_enabled(self, "drop"):
            vision_trace_id = CompanionOrbController._begin_vision_debug_trace(
                self,
                Path(str(image_path or "")),
                scope="drop",
                trace_id=str(trace_id or ""),
            )
            guidance_text = CompanionOrbController._visual_guidance_for_image(
                self,
                Path(str(image_path or "")),
                scope="drop",
                trace_id=vision_trace_id,
            )
            if guidance_text:
                return {"scene_type": "lfm_visual_guidance"}, guidance_text
            self._drop_trace_event(
                "lfm_guidance_fallback_to_main_chat",
                str(trace_id or ""),
                console=True,
                reason="lfm_evidence_unusable",
            )
            CompanionOrbController._set_vision_pipeline_stage(
                self,
                "main_chat",
                scope="drop",
                route="main_chat_fallback",
            )
            return CompanionOrbController._main_chat_visual_guidance_for_image(
                self,
                str(image_path or ""),
                metadata,
            )
        # With LFM disabled, the snapshot itself is sent to Main Chat exactly
        # once. Do not spend a separate Main Chat request generating guidance.
        return {}, ""

    def _main_chat_visual_guidance_for_image(
        self,
        image_path: str,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, str], str]:
        """Return bounded private evidence when LFM cannot serve an Orb action."""

        try:
            result = dict(
                self.orb_runtime.drop_guidance(
                    image_path=str(image_path or ""),
                    snapshot_metadata=dict(metadata or {}),
                    response_style_label=self._response_style_label(),
                )
                or {}
            )
        except Exception as exc:
            logger = getattr(self, "_log", None)
            if callable(logger):
                logger(f"Companion Orb Main Chat vision fallback failed: {exc}")
            return {}, ""
        guidance = dict(result.get("guidance") or {})
        text = str(result.get("text") or "").strip()
        return guidance, text

    def _deliver_drop_snapshot_immediately(self, image_path: str, *, reason: str, trace_id: str = "", guidance_text: str = "") -> bool:
        path = str(image_path or "").strip()
        trace = str(trace_id or self._active_drop_trace_id or "").strip()
        if not path or not Path(path).is_file():
            self._drop_trace_event("drop_immediate_image_skipped", trace, reason=reason, image_path=path, skipped_reason="missing_image")
            return False
        content = "Please respond to the image I just sent you."
        one_shot_guidance = str(guidance_text or "").strip()
        if not CompanionOrbController._visual_guidance_enabled(self, "drop"):
            queue_image = getattr(
                getattr(self, "user_image_turns", None),
                "queue_image_turn",
                None,
            )
            if not callable(queue_image):
                return False
            CompanionOrbController._set_vision_pipeline_stage(
                self,
                "capture",
                scope="drop",
                route="main_chat_image",
            )
            try:
                CompanionOrbController._mark_drop_response_submitted(self, trace, image_path=path)
                queue_image(
                    path,
                    content=content,
                    source="companion_orb",
                    max_output_tokens=ORB_RESPONSE_MAX_OUTPUT_TOKENS,
                )
            except Exception as exc:
                CompanionOrbController._set_vision_pipeline_stage(
                    self,
                    "error",
                    scope="drop",
                    route="main_chat_image",
                    error=str(exc),
                )
                self._drop_trace_event(
                    "drop_immediate_image_failed",
                    trace,
                    console=True,
                    reason=reason,
                    image_path=path,
                    error=str(exc),
                )
                return False
            CompanionOrbController._set_vision_pipeline_stage(
                self,
                "main_chat",
                scope="drop",
                route="main_chat_image",
            )
            self._drop_trace_event(
                "drop_immediate_image_queued",
                trace,
                console=True,
                reason=reason,
                image_path=path,
                route="main_chat_image",
            )
            return True
        if not one_shot_guidance:
            self._drop_trace_event(
                "drop_immediate_image_skipped",
                trace,
                reason=reason,
                image_path=path,
                skipped_reason="visual_guidance_unavailable",
            )
            return False
        try:
            CompanionOrbController._mark_drop_response_submitted(self, trace)
            CompanionOrbController._submit_guided_orb_response(
                self,
                content,
                one_shot_guidance,
                trace_id=trace,
            )
        except Exception as exc:
            self._drop_trace_event("drop_immediate_image_failed", trace, console=True, reason=reason, image_path=path, error=str(exc))
            return False
        self._drop_trace_event("drop_immediate_image_queued", trace, console=True, reason=reason, image_path=path)
        return True

    def _capture_inspection_snapshot(self, target: dict[str, Any], *, reason: str, inspection_id: int | None = None, trace_id: str = ""):
        try:
            inspection_id = int(inspection_id or self._active_snapshot_inspection_id or 0)
            trace = str(trace_id or self._active_drop_trace_id or "").strip()
            response_requested = str(reason or "").strip().lower() != "pointer_reached"
            if inspection_id and self._active_snapshot_inspection_id and inspection_id < int(self._active_snapshot_inspection_id):
                self._drop_trace_event(
                    "snapshot_inspection_stale_skipped",
                    trace,
                    console=True,
                    reason=reason,
                    inspection_id=inspection_id,
                    active_inspection_id=int(self._active_snapshot_inspection_id or 0),
                )
                return
            bounds = target_bounds(target)
            if not bounds:
                self._drop_trace_event("snapshot_inspection_rejected", trace, console=True, reason=reason, target=target if isinstance(target, dict) else {})
                CompanionOrbController._request_drop_capture_finish(self, inspection_id)
                return
            self._drop_trace_event(
                "snapshot_inspection_start",
                trace,
                console=True,
                reason=reason,
                bounds=bounds,
                target=self._target_for_output(target),
                inspection_id=inspection_id,
            )
            output_root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd()) / "runtime" / "companion_orb" / "pointer_snapshots"
            result = self._capture_target_region(
                bounds,
                target,
                {
                    "output_dir": output_root,
                    "eager_ocr": True,
                    "manual_inspection": self._manual_inspection_payload(),
                    "inspection_reason": str(reason or "manual_inspection"),
                    "manual_inspection_id": inspection_id,
                    "drop_trace_id": trace,
                    "priority_drop": True,
                    "snapshot_cloak_delay_seconds": 0.035,
                },
            )
            if not self._drop_inspection_is_current(inspection_id):
                self._drop_trace_event(
                    "snapshot_inspection_stale_cancelled",
                    trace,
                    console=True,
                    reason=reason,
                    inspection_id=inspection_id,
                    phase="after_capture",
                )
                return
            image_path = str(result.get("image_path") or "")
            if reason == 'right_drag_drop' and image_path:
                proxy = getattr(self, '_proxy', None)
                if proxy is not None:
                    proxy.drop_watch_ready.emit(inspection_id)
            metadata = dict(result.get("metadata") or {})
            metadata["manual_inspection_id"] = inspection_id
            metadata["drop_trace_id"] = trace
            metadata["priority_drop"] = True
            guidance: dict[str, str] = {}
            guidance_text = ""
            if response_requested:
                guidance, guidance_text = self._prepare_drop_response_guidance(
                    image_path,
                    metadata,
                    trace_id=trace,
                )
            if not self._drop_inspection_is_current(inspection_id):
                self._drop_trace_event(
                    "snapshot_inspection_stale_cancelled",
                    trace,
                    console=True,
                    reason=reason,
                    inspection_id=inspection_id,
                    phase="after_guidance",
                )
                return
            if guidance:
                metadata["smart_drop_guidance"] = guidance
            if guidance_text:
                metadata["smart_drop_guidance_text"] = guidance_text[:1400]
            immediate_delivery = False
            if response_requested:
                immediate_delivery = self._deliver_drop_snapshot_immediately(
                    image_path,
                    reason=reason,
                    trace_id=trace,
                    guidance_text=guidance_text,
                )
            metadata["immediate_image_delivery"] = bool(immediate_delivery)
            metadata["suppress_hidden_proactive"] = bool(immediate_delivery)
            result["metadata"] = metadata
            self.request_snapshot_context({"snapshots": [dict(result)]})
            self.request_comment_focus(
                {
                    "target": target,
                    "bounds": list(bounds),
                    "label": "current snapshot",
                    "text": "comment on the visible content in this fresh drop snapshot",
                    "duration_seconds": COMMENT_FOCUS_DEFAULT_SECONDS,
                    "drop_trace_id": trace,
                }
            )
            if response_requested and not immediate_delivery:
                self._request_hidden_pingpong_cycle_async(
                    reason=reason,
                    snapshots=[dict(result)],
                    trace_id=trace,
                )
            elif response_requested:
                self._drop_trace_event(
                    "hidden_ping_suppressed",
                    trace,
                    console=True,
                    reason=reason,
                    suppression="immediate_image_delivery",
                )
            self._log(f"Companion Orb pointer snapshot saved: {image_path}")
            self._drop_trace_event(
                "snapshot_inspection_saved",
                trace,
                console=True,
                reason=reason,
                image_path=image_path,
                bounds=bounds,
                inspection_id=inspection_id,
                ocr_backend=str(metadata.get("ocr_backend") or ""),
                ocr_region_count=len(metadata.get("ocr_regions") or []),
                ocr_text=str(metadata.get("ocr_text") or ""),
            )
            try:
                self.context.events.publish(
                    "companion_orb_pointer_snapshot",
                    {
                        "image_path": image_path,
                        "target": self._target_for_output(target),
                        "bounds": list(bounds or []),
                        "ocr_regions": list(metadata.get("ocr_regions") or []),
                        "ocr_text": str(metadata.get("ocr_text") or ""),
                        "ocr_backend": str(metadata.get("ocr_backend") or ""),
                        "manual_inspection_id": inspection_id,
                        "drop_trace_id": trace,
                        "focus": {"bounds": list(bounds or []), "label": "snapshot"},
                        "source": "companion_orb",
                    },
                )
            except Exception:
                pass
        except Exception as exc:
            self._drop_trace_event("snapshot_inspection_failed", trace_id, console=True, reason=reason, error=str(exc))
            CompanionOrbController._request_drop_capture_finish(self, int(inspection_id or 0))
            self._log(f"Companion Orb pointer snapshot failed: {exc}")

    def _interrupt_audio_for_drop_comment(self, *, reason: str = "manual_inspection"):
        if not bool(self._last_runtime_config.get("companion_orb_interrupt_for_drop_comment", True)):
            return
        try:
            self.playback.interrupt(reason=f"companion_orb_drop:{reason}")
            self._debug_event("drop_audio_interrupted", console=True, reason=reason)
        except Exception as exc:
            self._debug_event("drop_audio_interrupt_failed", console=True, reason=reason, error=str(exc))

    def _select_target_under_orb(self):
        center = self._orb_center_global()
        mode = str(self._last_runtime_config.get("companion_orb_target_mode", "window") or "window")
        width = int(self._last_runtime_config.get("companion_orb_target_region_width", 640) or 640)
        height = int(self._last_runtime_config.get("companion_orb_target_region_height", 420) or 420)
        target = self._resolve_target_at(center, width=width, height=height, mode=mode)
        if not target:
            self._last_target_warning = "Could not resolve target window or region. Companion Orb Target will report a warning until a new target is selected."
            self._log(self._last_target_warning)
            return
        if self._target_requires_confirmation(target) and not self._confirm_target_change(target):
            self._log("Companion Orb target selection cancelled.")
            return
        self._target_info = dict(target)
        target_display = CompanionOrbController._capture_target_presentation(self)
        self.bridge.set_target_info(target_display)
        self._send_external_runtime({"type": "target_info", "target": target_display})
        self._save_runtime_setting("companion_orb_target_info", dict(self._target_info))
        self._publish_target_event(self._target_for_output(self._target_info))
        title = str(target.get("title") or target.get("target_type") or "target")
        self._log(f"Selected Companion Orb target: {title}")

    def _resolve_target_at(self, point: QtCore.QPoint, *, width: int, height: int, mode: str):
        normalized_mode = str(mode or "window").strip().lower()
        if normalized_mode == "window":
            previous_click_through = bool(self.bridge.clickThrough)
            cloaked = self._apply_snapshot_cloak_blocking(True)
            try:
                try:
                    self._apply_click_through(True)
                    QtGui.QGuiApplication.processEvents(QtCore.QEventLoop.AllEvents, 25)
                except Exception:
                    pass
                QtCore.QThread.msleep(45 if cloaked else 35)
                target = resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode=mode)
                if cloaked and self._is_own_target(target):
                    QtCore.QThread.msleep(35)
                    target = resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode=mode)
            finally:
                try:
                    self._apply_click_through(previous_click_through)
                finally:
                    if cloaked:
                        self._apply_snapshot_cloak_blocking(False)
        else:
            target = resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode=mode)
        if normalized_mode != "window" or not self._is_own_target(target):
            return target
        return resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode="region")

    def _is_own_target(self, target) -> bool:
        if not target:
            return False
        title = str(target.get("title") or "").strip().casefold()
        if title in {"companion orb", "companion orb external runtime"}:
            return True
        if self._window is None:
            return False
        try:
            own_id = int(self._window.winId())
            target_id = int(str(target.get("window_id") or "0"), 0)
            if target_id and target_id == own_id:
                return True
        except Exception:
            pass
        return False

    def _target_requires_confirmation(self, target) -> bool:
        if not bool(self._last_runtime_config.get("companion_orb_require_target_confirmation", True)):
            return False
        if str(target.get("target_type") or "").strip().lower() == "window":
            return True
        return self._target_signature(target) != self._target_signature(self._target_info)

    def _target_signature(self, target) -> tuple:
        payload = dict(target or {})
        return (
            str(payload.get("target_type") or ""),
            str(payload.get("window_id") or ""),
            tuple(target_bounds(payload) or []),
            str(payload.get("title") or ""),
        )

    def _confirm_target_change(self, target) -> bool:
        title = str(target.get("title") or "Untitled window").strip()
        process_name = str(target.get("process_name") or "").strip() if self._include_process_name() else ""
        target_type = str(target.get("target_type") or "target").strip().title()
        details = f"{target_type}: {title}" if not process_name else f"{target_type}: {title}\n{process_name}"
        if not sys_platform_windows():
            return False
        try:
            hwnd = int(self._window.winId()) if self._window is not None else 0
            flags = 0x00000004 | 0x00000020 | 0x00040000
            result = ctypes.windll.user32.MessageBoxW(
                hwnd,
                f"Use this as the Companion Orb Hidden Sensory target?\n\n{details}",
                "Use Companion Orb Target?",
                flags,
            )
            return int(result) == 6
        except Exception:
            return False

    def _orb_center_global(self) -> QtCore.QPoint:
        if self._window is None:
            return QtGui.QCursor.pos()
        geometry = self._window.frameGeometry()
        return geometry.center()

    def _event_global_pos(self, event):
        try:
            return event.globalPosition().toPoint()
        except Exception:
            try:
                return event.globalPos()
            except Exception:
                return QtCore.QPoint(0, 0)

    def _hotkeys_enabled(self):
        return bool(self._last_runtime_config.get("companion_orb_hotkeys_enabled", True))

    def _focus_is_text_input(self):
        app = QtGui.QGuiApplication.instance()
        focus = app.focusObject() if app is not None else None
        if focus is None:
            return False
        try:
            class_name = str(focus.metaObject().className() or "").lower()
        except Exception:
            class_name = type(focus).__name__.lower()
        return any(
            token in class_name
            for token in ("textinput", "textarea", "lineedit", "textedit", "spinbox", "combobox")
        )

    def _handle_hotkey(self, event):
        checks = [
            ("companion_orb_toggle_hotkey", "Ctrl+Alt+O", self.toggle_enabled),
            ("companion_orb_edit_hotkey", "Ctrl+Alt+Shift+O", lambda: self.set_edit_mode(not self.bridge.editMode)),
            ("companion_orb_placement_hotkey", "Ctrl+Alt+P", lambda: self.set_placement_mode(not self.bridge.placementMode)),
            ("companion_orb_clear_target_hotkey", "Ctrl+Alt+Backspace", self.clear_target),
            ("companion_orb_click_through_hotkey", "Ctrl+Alt+C", lambda: self.set_click_through(not self.bridge.clickThrough)),
            ("companion_orb_reset_position_hotkey", "Ctrl+Alt+R", self.reset_position),
            ("companion_orb_eye_tracking_hotkey", "Ctrl+Alt+G", lambda: self.react_at_gaze(force=True)),
        ]
        for key, default, callback in checks:
            if self._event_matches_sequence(event, str(self._last_runtime_config.get(key, default) or default)):
                callback()
                return True
        if event.key() == QtCore.Qt.Key_Escape and (self.bridge.editMode or self.bridge.placementMode or self._orb_visible()):
            if self.bridge.placementMode:
                self.set_placement_mode(False)
            elif self.bridge.editMode:
                self.set_edit_mode(False)
            else:
                self._window.hide()
            return True
        return False

    def _event_matches_sequence(self, event, sequence_text: str) -> bool:
        text = str(sequence_text or "").strip()
        if not text:
            return False
        sequence = QtGui.QKeySequence(text)
        try:
            modifier_value = int(event.modifiers())
        except TypeError:
            modifier_value = int(getattr(event.modifiers(), "value", 0) or 0)
        event_sequence = QtGui.QKeySequence(modifier_value | int(event.key()))
        return sequence.matches(event_sequence) == QtGui.QKeySequence.ExactMatch

    def _orb_visible(self):
        return bool(self._window is not None and self._window.isVisible())

    @QtCore.Slot(bool)
    def _set_snapshot_cloak(self, enabled: bool):
        window = self._window
        if enabled:
            self._clear_gaze_click_target_highlight()
            if self._snapshot_cloak_count <= 0:
                CompanionOrbController._prepare_external_cloak_ack(self, True)
                self._send_external_runtime({"type": "cloak", "enabled": True})
                self._snapshot_restore_visible = bool(window is not None and window.isVisible())
                if window is not None and window.isVisible():
                    window.hide()
                self._debug_event("snapshot_cloak_enabled", visible_before=bool(self._snapshot_restore_visible))
            self._snapshot_cloak_count += 1
        else:
            self._snapshot_cloak_count = max(0, int(self._snapshot_cloak_count or 0) - 1)
            if self._snapshot_cloak_count <= 0:
                restore_visible = bool(self._snapshot_restore_visible)
                self._snapshot_restore_visible = False
                CompanionOrbController._prepare_external_cloak_ack(self, False)
                self._send_external_runtime({"type": "cloak", "enabled": False})
                self._debug_event("snapshot_cloak_disabled", restore_visible=restore_visible)
                self._refresh_visibility()
        app = QtGui.QGuiApplication.instance()
        if app is not None:
            try:
                app.processEvents(QtCore.QEventLoop.AllEvents, 35)
            except Exception:
                pass

    def _apply_snapshot_cloak_blocking(self, enabled: bool) -> bool:
        app = QtGui.QGuiApplication.instance()
        if app is None:
            return False
        try:
            if self.thread() == QtCore.QThread.currentThread():
                self._set_snapshot_cloak(bool(enabled))
            else:
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_set_snapshot_cloak",
                    QtCore.Qt.BlockingQueuedConnection,
                    QtCore.Q_ARG(bool, bool(enabled)),
                )
            return True
        except Exception as exc:
            self._debug_event("snapshot_cloak_failed", console=True, enabled=bool(enabled), error=str(exc))
            return False

    def _apply_click_target_scan_cloak_blocking(
        self,
        *,
        timeout_seconds: float = GAZE_CLICK_CLOAK_ACK_TIMEOUT_SECONDS,
    ) -> bool:
        external_required = CompanionOrbController._external_runtime_enabled(self)
        if not self._apply_snapshot_cloak_blocking(True):
            return False
        if not external_required:
            return True
        thread_method = getattr(self, "thread", None)
        if callable(thread_method):
            try:
                if thread_method() == QtCore.QThread.currentThread():
                    self._apply_snapshot_cloak_blocking(False)
                    return False
            except Exception:
                pass
        event = getattr(self, "_external_cloak_ack_event", None)
        ready = CompanionOrbController._external_cloak_ack_ready(self, True)
        if not ready and isinstance(event, threading.Event):
            event.wait(max(0.01, float(timeout_seconds)))
            ready = CompanionOrbController._external_cloak_ack_ready(self, True)
        if ready:
            return True
        self._apply_snapshot_cloak_blocking(False)
        return False

    def _grab_desktop_without_orb(self, image_grab, *, cloak_delay_seconds: float = 0.08, trace_id: str = ""):
        started_at = time.monotonic()
        cloaked = self._apply_snapshot_cloak_blocking(True)
        if cloaked:
            time.sleep(max(0.0, min(0.15, float(cloak_delay_seconds))))
        try:
            with CompanionOrbController._nc_capture_exclusion_scope(self):
                image = image_grab.grab(all_screens=True).convert("RGB")
            self._drop_trace_event(
                "desktop_grabbed",
                trace_id,
                cloaked=bool(cloaked),
                cloak_delay_seconds=round(float(cloak_delay_seconds), 3),
                grab_elapsed_ms=round((time.monotonic() - started_at) * 1000.0, 1),
                image_size=[int(image.width), int(image.height)],
            )
            return image
        finally:
            if cloaked:
                self._apply_snapshot_cloak_blocking(False)

    def _nc_capture_exclusion_scope(self):
        from contextlib import nullcontext
        enabled = bool(getattr(self, '_last_runtime_config', {}).get('companion_orb_exclude_nc_from_captures', False))
        if not enabled:
            return nullcontext()
        adapter = getattr(self, '_nc_capture_exclusion', None)
        if adapter is None:
            raise RuntimeError('NC capture exclusion is unavailable.')
        return adapter.capture_scope(True)

    def _grab_excluding_nc(self, **kwargs):
        from PIL import ImageGrab
        with CompanionOrbController._nc_capture_exclusion_scope(self):
            return ImageGrab.grab(**kwargs)

    def _nc_grabber_kwargs(self):
        if getattr(self, '_last_runtime_config', {}).get('companion_orb_exclude_nc_from_captures', False):
            return {'grabber': lambda **kw: CompanionOrbController._grab_excluding_nc(self, **kw)}
        return {}

    def capture_exclusion_status_snapshot(self):
        adapter = getattr(self, '_nc_capture_exclusion', None)
        return adapter.status_snapshot() if adapter else {'message': 'NC capture exclusion unavailable.'}

    def toggle_enabled(self):
        enabled = not bool(self._last_runtime_config.get("companion_orb_enabled", False))
        self._last_runtime_config["companion_orb_enabled"] = enabled
        if enabled and str(self._last_runtime_config.get("companion_orb_display_mode", "off")) == "off":
            self._last_runtime_config["companion_orb_display_mode"] = "docked"
            self._save_runtime_setting("companion_orb_display_mode", "docked")
        self._save_runtime_setting("companion_orb_enabled", enabled)
        self.apply_runtime_config(self._last_runtime_config)

    def _save_runtime_setting(self, key, value):
        try:
            self.runtime_config.update(str(key), value)
        except Exception:
            pass
        self._save_timer.start()

    def _save_session(self):
        app = QtGui.QGuiApplication.instance()
        if app is None:
            return
        top_level_widgets = getattr(app, "topLevelWidgets", None)
        if not callable(top_level_widgets):
            return
        try:
            widgets = list(top_level_widgets() or [])
        except Exception:
            return
        for widget in widgets:
            callback = getattr(widget, "save_session", None)
            if callable(callback):
                try:
                    callback()
                    return
                except Exception:
                    return

    def _publish_target_event(self, target_info: dict[str, Any], *, cleared: bool = False):
        CompanionOrbController._refresh_watch_capture_hint(self)
        try:
            self.context.events.publish(
                "companion_orb_target_selected",
                {"target": dict(target_info or {}), "cleared": bool(cleared), "source": "companion_orb"},
            )
        except Exception:
            pass

    def _watch_capture_target_available(self) -> bool:
        settings = self._last_runtime_config
        if settings.get('companion_orb_full_screen_context_enabled', False):
            return CompanionOrbController.capture_scope_snapshot(self)['available']
        mode = str(settings.get('companion_orb_target_mode', 'window') or 'window').strip().lower()
        # Region mode is the area around the Orb; it needs no saved selection.
        if mode == 'region':
            return True
        target = dict(self._target_info or {})
        target = refresh_window_target(target) if target.get('target_type') == 'window' else None
        return bool(target_bounds(target))

    def _refresh_watch_capture_hint(self) -> None:
        popup = getattr(self, '_drop_watch_popup', None)
        if popup is not None:
            owner = getattr(self, 'watch_context', None)
            current = owner.current(self._last_runtime_config) if owner is not None else {}
            if (current.get('session_key') != self._drop_watch_popup_session
                    or 'conversation scope unavailable' in current.get('paused_reasons', [])):
                CompanionOrbController._clear_drop_watch_offer(self)
            else:
                popup.set_scope(CompanionOrbController.capture_scope_snapshot(self)['label'])
        drop = getattr(self, '_drop_capture', None)
        if drop is not None and drop.active:
            completed = False
            runtime = getattr(self, 'orb_runtime', None)
            if runtime is not None:
                try:
                    completed = drop.response_completed(list(runtime.busy_snapshot().get('orb_completed_responses') or []))
                except (AttributeError, TypeError, ValueError):
                    pass
            if completed or time.monotonic() >= drop.deadline:
                CompanionOrbController._finish_drop_capture(self, drop.inspection_id)
        if hasattr(self, '_capture_monitors'):
            self._capture_monitors = capture_scope.monitor_snapshot()
            if (self._last_runtime_config.get('companion_orb_full_screen_context_enabled')
                    and not self._last_runtime_config.get('companion_orb_screen_target')
                    and not self._last_runtime_config.get('companion_orb_include_all_monitors')):
                self._bind_capture_screen()
            target = CompanionOrbController._capture_target_presentation(self)
            if target != self.bridge.target_info():
                self.bridge.set_target_info(target)
                self._send_external_runtime({'type': 'target_info', 'target': target})
        owner = getattr(self, 'watch_context', None)
        state = owner.state.snapshot() if owner is not None else {}
        needs_capture = (any(row['status'] == 'watching' for row in state.get('watches', []))
            if state.get('schema_version') == 2 else state.get('active', False))
        settings = self._last_runtime_config
        waiting = False
        if needs_capture and settings.get('companion_orb_enabled'):
            waiting = not CompanionOrbController._watch_capture_target_available(self)
        if waiting != self.bridge.watchWaitingForTarget:
            self.bridge.setWatchWaitingForTarget(waiting)
            self._send_external_runtime({'type': 'watch_capture_hint', 'waiting': waiting})
            changed = getattr(owner, 'on_change', None)
            if callable(changed):
                changed()

    def _capture_target_presentation(self) -> dict[str, Any]:
        """One projection for local/external labels, including config refreshes."""
        scope = CompanionOrbController.capture_scope_snapshot(self)
        target = (dict(getattr(self, '_target_info', {}) or {})
                  if scope['mode'] == 'window' and scope['available']
                  else {'target_type': scope['mode'], 'title': scope['label']})
        drop = getattr(self, '_drop_capture', None)
        if drop is not None and drop.active:
            target = dict(drop.target)
            target.pop('capture_monitors', None)
            label = str(target.get('title') or target.get('target_type') or 'drop target')
            target['title'] = f"Temporary: {label}\nCapture: {scope['label']}"
            target['process_name'] = ''
        if not self._last_runtime_config.get('companion_orb_include_process_name', True):
            target['process_name'] = ''
        return target

    @QtCore.Slot(int)
    def _finish_drop_capture(self, inspection_id: int) -> None:
        drop = getattr(self, '_drop_capture', None)
        if drop is None or not drop.finish(inspection_id):
            return
        self._manual_inspection_until = 0.0
        self._manual_inspection_bounds = []
        self._manual_inspection_reason = ''
        self._active_snapshot_inspection_id = 0
        self._clear_snapshot_context(reason='drop_finished')
        self._clear_comment_focus()
        target = CompanionOrbController._capture_target_presentation(self)
        self.bridge.set_target_info(target)
        self._send_external_runtime({'type': 'target_info', 'target': target})

    def _request_drop_capture_finish(self, inspection_id: int) -> None:
        """Worker completion is delivered to the GUI, guarded by inspection ID."""
        proxy = getattr(self, '_proxy', None)
        if proxy is not None:
            proxy.drop_capture_finished.emit(int(inspection_id))

    def _mark_drop_response_submitted(self, trace_id: str, *, image_path: str = '') -> None:
        drop = getattr(self, '_drop_capture', None)
        if drop is not None and trace_id and trace_id == getattr(self, '_active_drop_trace_id', ''):
            drop.submitted(drop.inspection_id, trace_id=trace_id, image_path=image_path)

    def _bind_capture_screen(self, point=None):
        if point is None:
            top_left = self._current_orb_top_left_for_drop()
            if top_left is None:
                return
            size = self._window_size() / 2
            point = QtCore.QPointF(top_left.x() + size, top_left.y() + size)
        self._capture_monitors = capture_scope.monitor_snapshot()
        monitor = capture_scope.select_screen((point.x(), point.y()), self._capture_monitors)
        identity = monitor['identity'] if monitor else {}
        self._last_runtime_config['companion_orb_screen_target'] = identity
        self._save_runtime_setting('companion_orb_screen_target', identity)

    def select_capture_mode(self, mode: str) -> dict:
        if mode not in {'window', 'region', 'screen'}:
            raise ValueError('Choose window, region, or screen.')
        drop = getattr(self, '_drop_capture', None)
        if drop is not None:
            CompanionOrbController._finish_drop_capture(self, drop.inspection_id)
        if mode == 'screen':
            self._bind_capture_screen()
        values = {'companion_orb_full_screen_context_enabled': mode == 'screen'}
        if mode != 'screen':
            values['companion_orb_target_mode'] = mode
        self._last_runtime_config.update(values)
        for key, value in values.items():
            self._save_runtime_setting(key, value)
        self._refresh_watch_capture_hint()
        return self.capture_scope_snapshot()

    def capture_scope_snapshot(self) -> dict:
        settings = self._last_runtime_config
        mode = capture_scope.capture_mode(settings)
        monitors = getattr(self, '_capture_monitors', [])
        identity = settings.get('companion_orb_screen_target') or {}
        all_monitors = bool(settings.get('companion_orb_include_all_monitors', False))
        bounds, label, available = [], '', False
        if mode == 'screen':
            monitor = capture_scope.resolve_screen(identity, monitors)
            if all_monitors:
                bounds = capture_scope.union_bounds(monitors, 'logical_bounds')
                label, available = 'All monitors', bool(bounds)
            elif monitor:
                bounds = monitor['logical_bounds']
                label, available = 'Entire screen — ' + monitor['label'], True
            else:
                label = 'Entire screen — choose a target'
        elif mode == 'region':
            label = 'Region around Orb — {} × {}'.format(settings.get('companion_orb_target_region_width', 640),
                                                        settings.get('companion_orb_target_region_height', 420))
            available = True
        else:
            target = dict(getattr(self, '_target_info', {}) or {})
            target = refresh_window_target(target) if target.get('target_type') == 'window' else None
            bounds = target_bounds(target)
            available = bool(bounds)
            label = 'Window under Orb' + (': ' + str(target.get('title', '')) if available else ' — choose a target')
        return dict(mode=mode, available=available, label=label, bounds=list(bounds),
                    screen_identity=dict(identity), include_all_monitors=all_monitors)

    def watch_status_snapshot(self):
        from .watch_panel import panel_status
        owner = getattr(self, 'watch_context', None)
        if owner is None:
            return panel_status({'active': False})
        return panel_status(owner.current(self._last_runtime_config))

    def _clear_drop_watch_offer(self) -> None:
        self._drop_watch_offer = None
        popup = getattr(self, '_drop_watch_popup', None)
        if popup is not None:
            popup.cancel()

    def _set_drop_watch_prompt_enabled(self, enabled: bool) -> None:
        from .drop_watch import SETTING
        self._last_runtime_config[SETTING] = bool(enabled)
        self._save_runtime_setting(SETTING, bool(enabled))
        popup = getattr(self, '_orb_popup', None)
        if popup is not None:
            popup.bridge.update_menu_item('drop_watch_prompt', checked=bool(enabled),
                                          detail='On' if enabled else 'Off')
        if not enabled:
            self._clear_drop_watch_offer()

    def _prepare_drop_watch_offer(self, inspection_id: int, target: dict, reason: str) -> None:
        from .drop_watch import SETTING, DropWatchOffer, target_subject
        CompanionOrbController._clear_drop_watch_offer(self)
        if reason != 'right_drag_drop' or not self._last_runtime_config.get(SETTING, False):
            return
        owner = getattr(self, 'watch_context', None)
        if owner is None:
            return
        try:
            current = owner.current(self._last_runtime_config)
            session = current.get('session_key', '')
            if session and 'conversation scope unavailable' not in current.get('paused_reasons', []):
                self._drop_watch_offer = DropWatchOffer(inspection_id, session, target_subject(target))
        except Exception as exc:
            self._log(f'Companion Orb watch offer unavailable: {type(exc).__name__}')

    @QtCore.Slot(int)
    def _show_drop_watch_offer(self, inspection_id: int) -> None:
        from .drop_watch import SETTING, register_drop_watch
        from .drop_watch_popup import DropWatchPopup
        offer = getattr(self, '_drop_watch_offer', None)
        if (offer is None or offer.inspection_id != inspection_id
                or getattr(self, '_drop_watch_closed', False)):
            return
        self._drop_watch_offer = None  # Consume this worker notification once.
        owner = getattr(self, 'watch_context', None)
        if (owner is None or not self._last_runtime_config.get(SETTING, False)
                or not self._last_runtime_config.get('companion_orb_enabled')):
            return
        try:
            current = owner.current(self._last_runtime_config)
            if (current.get('session_key') != offer.session_key
                    or 'conversation scope unavailable' in current.get('paused_reasons', [])):
                return

            def add_watch() -> dict:
                if not self._last_runtime_config.get(SETTING, False) or self._drop_watch_closed:
                    return dict(ok=False, receipt='Watch offers are off. No watch was added.')
                return register_drop_watch(owner, self._last_runtime_config, offer)

            popup = DropWatchPopup(offer.subject, self.capture_scope_snapshot()['label'],
                self._orb_center_global() + QtCore.QPoint(36, 36), self,
                add_watch=add_watch,
                open_watches=lambda: self._activate_floating_workspace('orb_watches', False))
            self._drop_watch_popup = popup
            self._drop_watch_popup_session = offer.session_key

            def finished() -> None:
                if self._drop_watch_popup is popup:
                    self._drop_watch_popup = None
                popup.deleteLater()

            popup.finished.connect(finished)
            popup.show()
        except Exception as exc:
            self._log(f'Companion Orb watch popup unavailable: {type(exc).__name__}')

    def stop_conversational_watch(self, watch_id='', expected_revision=None, session_key=''):
        owner = getattr(self, 'watch_context', None)
        if owner is not None:
            current = owner.current(self._last_runtime_config)
            if current.get('schema_version') == 2:
                if not owner.state.remove_watch(watch_id,expected_revision,session_key=session_key):
                    latest = owner.state.snapshot()
                    row = next((r for r in latest.get('watches', []) if r['id'] == watch_id), {})
                    raise RuntimeError('This watch row changed. Refresh and try again. '
                        f'(watch_id={watch_id!r}, expected_revision={expected_revision!r}, '
                        f'revision_type={type(expected_revision).__name__}, '
                        f'current_revision={row.get("revision")!r}, '
                        f'session_changed={session_key != latest.get("session_key")})')
                owner.record('watch.removed_by_ui',dict(watch_id=watch_id,revision=expected_revision),session_key=session_key)
                owner.on_change()
            else:
                owner.clear('manual_stop')
        return self.watch_status_snapshot()

    def watch_capture_snapshot(self, watch_id='', expected_revision=None, session_key=''):
        from .watch_panel import verified_capture_path
        status=self.watch_status_snapshot()
        if status.get('schema_version') == 2:
            status=next((r for r in status['rows'] if r['id']==watch_id and r['revision']==expected_revision
                and r['session_key']==session_key),None)
            if status is None:
                raise RuntimeError('This watch row changed. Refresh and try again.')
        return {'image_path': verified_capture_path(status)}

    def capture_sensory_snapshot(self, capture_context=None):
        owner = getattr(self, 'watch_context', None)
        if owner is None:
            return self._capture_sensory_snapshot_unwatched(capture_context)
        task = owner.current(self._last_runtime_config)
        owner.on_change()
        pending_only = (task.get('schema_version') == 2 and task.get('active') and
            not any(row['status'] == 'watching' for row in task.get('watches', [])) and
            not self._manual_inspection_payload())
        waiting = ('waiting for a capture target' in task.get('paused_reasons', [])
            and not self._manual_inspection_payload())
        record = ({'source': PROVIDER_ID, 'captured_at': time.time(), 'metadata': {}}
            if pending_only or waiting else self._capture_sensory_snapshot_unwatched(capture_context))
        if not record or (record.get('metadata') or {}).get('manual_inspection'):
            return record
        from .watch_evidence import collect_watch_evidence
        record = collect_watch_evidence(record, task, owner.state, self.orb_runtime, self._last_runtime_config,
            vision_settings=self._visual_guidance_request_settings())
        owner.current(self._last_runtime_config)
        owner.on_change()
        self._debug_event('orb_watch_observed', watch=record.get('metadata',{}).get('orb_watch',{}))
        owner.record('watch.evaluated',record.get('metadata',{}),session_key=task.get('session_key',''))
        return record

    def _capture_sensory_snapshot_unwatched(self, capture_context=None):
        settings = self._last_runtime_config
        watch_owner = getattr(self, 'watch_context', None)
        watch = watch_owner.current(settings) if watch_owner is not None else {}
        if not (settings.get("companion_orb_supervisor_enabled", False) or watch.get('active')):
            self._debug_event(
                "sensory_capture_skipped",
                reason="no_active_supervisor_or_watch",
            )
            return None
        if not bool(settings.get("companion_orb_sensory_target_enabled", False)):
            self._debug_event("sensory_capture_skipped", reason="disabled")
            return {
                "captured_at": time.time(),
                "source": PROVIDER_ID,
                "content_text": "Companion Orb Target is selected, but orb sensory targeting is disabled in Companion Orb Overlay.",
                "metadata": {"target_available": False, "reason": "disabled"},
            }
        if bool(settings.get("companion_orb_full_screen_context_enabled", False)):
            try:
                self._debug_event("sensory_capture_start", console=True, mode="full_screen")
                return self._capture_full_screen_context(capture_context)
            except Exception as exc:
                self._debug_event("sensory_capture_failed", console=True, mode="full_screen", error=str(exc))
                return {
                    "captured_at": time.time(),
                    "source": PROVIDER_ID,
                    "content_text": f"Companion Orb full-screen context capture failed: {exc}",
                    "metadata": {"target_available": False, "reason": "full_screen_capture_failed"},
                }
        target, target_reason = self._capture_target_for_current_mode()
        if not target:
            reason = str(target_reason or "missing_target")
            self._debug_event("sensory_capture_skipped", console=(reason == "target_lost"), reason=reason)
            content_text = (
                "Companion Orb target lost. Select a new target before using targeted hidden sensory feedback."
                if reason == "target_lost"
                else "Companion Orb Target is selected, but no orb target has been selected yet."
            )
            return {
                "captured_at": time.time(),
                "source": PROVIDER_ID,
                "content_text": content_text,
                "metadata": {"target_available": False, "reason": reason},
            }
        bounds = target_bounds(target)
        if not bounds:
            self._debug_event("sensory_capture_skipped", console=True, reason="invalid_bounds", target=self._target_for_output(target))
            return {
                "captured_at": time.time(),
                "source": PROVIDER_ID,
                "content_text": "Companion Orb target has no valid capture bounds.",
                "metadata": {"target_available": False, "reason": "invalid_bounds", "target": self._target_for_output(target)},
            }
        try:
            self._debug_event("sensory_capture_start", console=True, mode=str(target.get("target_type") or "target"), bounds=bounds)
            return self._capture_target_region(bounds, target, capture_context)
        except Exception as exc:
            self._debug_event("sensory_capture_failed", console=True, mode=str(target.get("target_type") or "target"), bounds=bounds, error=str(exc))
            return {
                "captured_at": time.time(),
                "source": PROVIDER_ID,
                "content_text": f"Companion Orb target capture failed: {exc}",
                "metadata": {"target_available": False, "reason": "capture_failed", "target": self._target_for_output(target)},
            }

    def _begin_snapshot_capture(self, *, trace_id: str = "", reason: str = "", bounds=None) -> bool:
        if self._snapshot_capture_lock.acquire(blocking=False):
            return True
        self._drop_trace_event(
            "snapshot_capture_busy_skipped",
            trace_id,
            console=True,
            reason=str(reason or "snapshot_capture_busy"),
            bounds=list(bounds or []),
        )
        return False

    def _end_snapshot_capture(self) -> None:
        try:
            self._snapshot_capture_lock.release()
        except RuntimeError:
            pass

    def _capture_full_screen_context(self, capture_context=None):
        trace_id = str((capture_context or {}).get("drop_trace_id") or self._active_drop_trace_id or "")
        if not self._begin_snapshot_capture(trace_id=trace_id, reason="full_screen_context"):
            raise RuntimeError("Companion Orb snapshot capture already in progress.")
        try:
            return self._capture_full_screen_context_unlocked(capture_context)
        finally:
            self._end_snapshot_capture()

    @staticmethod
    def _lfm_sensory_context_from_observation(
        observation: object,
        capture_bounds: Sequence[object],
    ) -> dict[str, object]:
        if not isinstance(observation, visual_observation.VisualObservation):
            return {}
        raw_payload = {
            "scene_summary": observation.scene_summary,
            "regions": [
                {
                    "label": region.label,
                    "kind": region.kind,
                    "bbox": list(region.bbox),
                    "confidence": region.confidence,
                    "action_hint": region.action_hint,
                }
                for region in observation.regions
            ],
            "limitations": observation.limitations,
        }
        try:
            grounded = vision_grounding.normalize_grounding_result(
                raw_payload,
                capture_bounds=capture_bounds,
                max_regions=48,
            )
        except (TypeError, ValueError):
            return {}
        regions = [
            {
                "text": region.label,
                "kind": region.kind,
                "screen_bounds": list(region.screen_bounds),
                "confidence": region.confidence,
                "action_hint": region.action_hint,
                "source": "vision",
                "backend": "lfm_vision",
            }
            for region in grounded.regions
        ]
        context: dict[str, object] = {
            "scene_summary": grounded.scene_summary,
            "user_focus": observation.user_focus,
            "visible_evidence": list(observation.visible_evidence),
            "suggested_topics": list(observation.suggested_topics),
            "regions": regions,
            "limitations": grounded.limitations,
        }
        return context if any(context.values()) else {}

    def _lfm_background_awareness_context(
        self,
        image_path: Path,
        capture_bounds: Sequence[object],
        *,
        trace_id: str = "",
    ) -> dict[str, object]:
        settings = dict(getattr(self, "_last_runtime_config", {}) or {})
        if not vision_guidance.lfm_features_enabled(settings):
            return {}
        try:
            result = CompanionOrbController._request_visual_observation(
                self,
                image_path,
                capture_bounds=capture_bounds,
                scope="conversation",
                trace_id=str(trace_id or ""),
            )
            context = CompanionOrbController._lfm_sensory_context_from_observation(
                result.get("observation") if isinstance(result, Mapping) else None,
                capture_bounds,
            )
        except Exception as exc:
            self._debug_event(
                "background_lfm_context_failed",
                error=str(exc),
                image_path=str(image_path),
            )
            return {}
        if context:
            self._debug_event(
                "background_lfm_context_ready",
                image_path=str(image_path),
                scene_summary=str(context.get("scene_summary") or ""),
                region_count=len(list(context.get("regions") or [])),
            )
        return context

    def _capture_full_screen_context_unlocked(self, capture_context=None):
        from PIL import ImageGrab

        scope = dict((capture_context or {}).get('screen_scope_override') or self.capture_scope_snapshot())
        if not scope['available']:
            raise ValueError('Waiting for a capture target')
        monitors = list((capture_context or {}).get('capture_monitors_override') or self._capture_monitors)
        if not capture_scope.monitor_map_is_current(monitors):
            raise ValueError('Display geometry changed; waiting for a fresh monitor map.')

        output_root = Path(str((capture_context or {}).get("output_dir") or (self.context.app_root / "runtime" / "sensory_feedback")))
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time() * 1000)
        output_path = output_root / f"companion_orb_full_screen_{timestamp}.jpg"
        self._debug_event("snapshot_full_screen_start", console=True, image_path=str(output_path))
        trace_id = str((capture_context or {}).get("drop_trace_id") or self._active_drop_trace_id or "")
        image = self._grab_desktop_without_orb(ImageGrab, trace_id=trace_id)
        if not capture_scope.monitor_map_is_current(monitors):
            raise ValueError('Display geometry changed during capture; discarded the image.')
        desktop_image_size = [int(image.width), int(image.height)]
        virtual_rect = self._virtual_desktop_rect()
        if virtual_rect is not None and virtual_rect.width() > 0 and virtual_rect.height() > 0:
            screen_bounds = [
                int(virtual_rect.x()),
                int(virtual_rect.y()),
                int(virtual_rect.width()),
                int(virtual_rect.height()),
            ]
        else:
            screen_bounds = [0, 0, int(image.width), int(image.height)]
        screen_source_index = -1  # Orb capture no longer inherits the separate Screen sensor.
        selected_screen_bounds = scope['bounds']
        crop = []
        capture_mode = "full_screen"
        target_title = scope['label']
        if selected_screen_bounds:
            image, screen_bounds = capture_scope.crop_screen(image, monitors, scope['screen_identity'], scope['include_all_monitors'])
            capture_mode = 'full_screen' if scope['include_all_monitors'] else 'selected_screen'
        original_size = [int(image.width), int(image.height)]
        vision_tiles: list[dict[str, object]] = []
        image.save(output_path, format="JPEG", quality=100, optimize=True)
        manual_inspection = self._manual_inspection_payload()
        manual_inspection_id = int(manual_inspection.get("inspection_id") or 0) if isinstance(manual_inspection, dict) else 0
        target = {
            "target_type": "screen",
            "title": target_title,
            "process_name": "",
            "bounds": list(screen_bounds),
        }
        ocr_result = self._extract_snapshot_ocr(
            output_path,
            screen_bounds,
            eager=True,
            image_tiles=vision_tiles,
        )
        watching = getattr(self, 'watch_context', None)
        lfm_visual_context = {} if watching and watching.state.snapshot()['active'] else self._lfm_background_awareness_context(
            output_path,
            screen_bounds,
            trace_id=trace_id,
        )
        context_scope = "the selected monitor" if capture_mode == "selected_screen" else "the desktop"
        content_text = (
            f"Hidden sensory feedback only, not a user request. Source: Companion Orb full-screen context map for {context_scope}. "
            "Identify concrete visible content, not just window names."
        )
        if lfm_visual_context:
            content_text += (
                " Private LFM scene grounding is attached in metadata.lfm_visual_context; "
                "use its labelled regions as exact movement guidance for the subject mentioned."
            )
        if manual_inspection:
            content_text += (
                f" Manual inspection is active; this selected crop is the primary evidence. "
                f"Inspect focus_bounds={manual_inspection.get('focus_bounds')} first. "
                "Do not describe the selection action or return a broad desktop/window list; "
                "return focus_bounds for the visible thing being discussed."
            )
        result = {
            "captured_at": time.time(),
            "image_path": str(output_path),
            "image_tiles": vision_tiles,
            "source": PROVIDER_ID,
            "content_text": content_text,
            "metadata": {
                "target_available": True,
                "target": target,
                "width": int(image.width),
                "height": int(image.height),
                "original_width": original_size[0],
                "original_height": original_size[1],
                "desktop_width": desktop_image_size[0],
                "desktop_height": desktop_image_size[1],
                "capture_mode": capture_mode,
                "full_screen_context": True,
                "vision_tile_count": len(vision_tiles),
                "vision_tile_bounds": [
                    list(tile.get("screen_bounds") or []) for tile in vision_tiles
                ],
                "screen_source_capture_screen_index": int(screen_source_index),
                "screen_bounds": list(screen_bounds),
                "crop": list(crop),
                "manual_inspection": dict(manual_inspection or {}),
                "manual_inspection_id": manual_inspection_id,
                "manual_inspection_primary": bool(manual_inspection),
                "drop_focus_bounds": list(manual_inspection.get("focus_bounds") or []) if manual_inspection else [],
                "visual_fingerprint": _sensory_visual_fingerprint(image),
                "ocr_backend": str(ocr_result.get("backend") or "none"),
                "ocr_text": str(ocr_result.get("text") or ""),
                "ocr_regions": list(ocr_result.get("regions") or []),
                "ocr_sidecar": str(ocr_result.get("sidecar") or ""),
                "ocr_text_recognized": bool(ocr_result.get("text_recognized", False)),
                "ocr_region_detection_only": bool(ocr_result.get("region_detection_only", False)),
                "ocr_text_recognition_available": bool(
                    dict(ocr_result.get("text_recognition_runtime") or {}).get("available", False)
                ),
                "lfm_visual_context": lfm_visual_context,
            },
        }
        self._debug_event(
            "snapshot_full_screen_saved",
            console=True,
            image_path=str(output_path),
            screen_bounds=screen_bounds,
            screen_source_capture_screen_index=screen_source_index,
            virtual_desktop=virtual_rect if virtual_rect is not None else [],
            desktop_image_size=desktop_image_size,
            crop=crop,
            capture_mode=capture_mode,
            original_size=original_size,
            saved_size=[int(image.width), int(image.height)],
            vision_tile_count=len(vision_tiles),
            vision_tiles=vision_tiles,
            ocr_backend=str(ocr_result.get("backend") or "none"),
            ocr_region_count=len(ocr_result.get("regions") or []),
            lfm_region_count=len(list(lfm_visual_context.get("regions") or [])),
            manual_inspection=manual_inspection,
        )
        return result

    def _screen_source_capture_index(self) -> int:
        if "screen_source_capture_screen_index" in self._last_runtime_config:
            value = self._last_runtime_config.get("screen_source_capture_screen_index", -1)
        else:
            try:
                value = self.runtime_config.get("screen_source_capture_screen_index", -1)
            except Exception:
                value = -1
        try:
            number = int(value)
        except Exception:
            number = -1
        return number if number >= 0 else -1

    def _configured_screen_source_bounds(self, screen_index: int | None = None) -> list[int]:
        try:
            index = self._screen_source_capture_index() if screen_index is None else int(screen_index)
        except Exception:
            index = -1
        if index < 0:
            return []
        try:
            screens = list(QtGui.QGuiApplication.screens() or [])
            if index >= len(screens):
                return []
            geometry = screens[index].geometry()
            return [int(geometry.x()), int(geometry.y()), int(geometry.width()), int(geometry.height())]
        except Exception:
            return []

    def _crop_desktop_image_to_bounds(self, image, bounds, virtual_rect):
        normalized = self._normalize_bounds(bounds)
        if not normalized:
            return image, []
        left, top, width, height = normalized
        if virtual_rect is not None and virtual_rect.width() > 0 and virtual_rect.height() > 0:
            x_scale = image.width / max(1, int(virtual_rect.width()))
            y_scale = image.height / max(1, int(virtual_rect.height()))
            crop = (
                int(round((left - int(virtual_rect.x())) * x_scale)),
                int(round((top - int(virtual_rect.y())) * y_scale)),
                int(round((left + width - int(virtual_rect.x())) * x_scale)),
                int(round((top + height - int(virtual_rect.y())) * y_scale)),
            )
        else:
            crop = (left, top, left + width, top + height)
        crop = (
            max(0, min(image.width - 1, crop[0])),
            max(0, min(image.height - 1, crop[1])),
            max(1, min(image.width, crop[2])),
            max(1, min(image.height, crop[3])),
        )
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            return image, []
        return image.crop(crop), [int(value) for value in crop]

    def _capture_target_region(self, bounds, target, capture_context=None):
        trace_id = str((capture_context or {}).get("drop_trace_id") or self._active_drop_trace_id or "")
        if not self._begin_snapshot_capture(trace_id=trace_id, reason="target_region", bounds=bounds):
            raise RuntimeError("Companion Orb snapshot capture already in progress.")
        try:
            return self._capture_target_region_unlocked(bounds, target, capture_context)
        finally:
            self._end_snapshot_capture()

    def _capture_target_region_unlocked(self, bounds, target, capture_context=None):
        from PIL import ImageGrab

        if target.get('target_type') == 'screen':
            context = dict(capture_context or {})
            if target.get('screen_identity'):
                context['screen_scope_override'] = dict(available=True, mode='screen',
                    label=target.get('title', 'Entire screen'), bounds=list(target.get('bounds') or []),
                    screen_identity=dict(target['screen_identity']), include_all_monitors=False)
                context['capture_monitors_override'] = list(target.get('capture_monitors') or self._capture_monitors)
            return self._capture_full_screen_context_unlocked(context)

        output_root = Path(str((capture_context or {}).get("output_dir") or (self.context.app_root / "runtime" / "sensory_feedback")))
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time() * 1000)
        output_path = output_root / f"companion_orb_target_{timestamp}.jpg"
        trace_id = str((capture_context or {}).get("drop_trace_id") or self._active_drop_trace_id or "")
        capture_started_at = time.monotonic()
        self._drop_trace_event(
            "snapshot_target_start",
            trace_id,
            console=True,
            image_path=str(output_path),
            bounds=bounds,
            target=self._target_for_output(target if isinstance(target, dict) else {}),
            capture_context={key: value for key, value in dict(capture_context or {}).items() if key != "output_dir"},
        )
        image = self._grab_desktop_without_orb(
            ImageGrab,
            cloak_delay_seconds=float((capture_context or {}).get("snapshot_cloak_delay_seconds", 0.08) or 0.08),
            trace_id=trace_id,
        )
        desktop_image_size = [int(image.width), int(image.height)]
        requested_bounds = [int(value) for value in bounds]
        virtual_rect = self._virtual_desktop_rect()
        capture_bounds = self._clip_bounds_to_virtual_desktop(requested_bounds, virtual_rect=virtual_rect, image_size=desktop_image_size)
        if not capture_bounds:
            raise RuntimeError("target crop is outside the available desktop capture")
        left, top, width, height = [int(value) for value in capture_bounds]
        if virtual_rect is not None and virtual_rect.width() > 0 and virtual_rect.height() > 0:
            x_scale = image.width / max(1, int(virtual_rect.width()))
            y_scale = image.height / max(1, int(virtual_rect.height()))
            crop = (
                int(round((left - int(virtual_rect.x())) * x_scale)),
                int(round((top - int(virtual_rect.y())) * y_scale)),
                int(round((left + width - int(virtual_rect.x())) * x_scale)),
                int(round((top + height - int(virtual_rect.y())) * y_scale)),
            )
        else:
            crop = (left, top, left + width, top + height)
        crop = (
            max(0, min(image.width - 1, crop[0])),
            max(0, min(image.height - 1, crop[1])),
            max(1, min(image.width, crop[2])),
            max(1, min(image.height, crop[3])),
        )
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            raise RuntimeError("target crop is outside the available desktop capture")
        image = image.crop(crop)
        # Keep the selected desktop pixels for readable model input and OCR.
        save_started_at = time.monotonic()
        image.save(output_path, format="JPEG", quality=100, optimize=True)
        save_elapsed_ms = round((time.monotonic() - save_started_at) * 1000.0, 1)
        manual_inspection = dict((capture_context or {}).get("manual_inspection") or self._manual_inspection_payload() or {})
        try:
            manual_inspection_id = int((capture_context or {}).get("manual_inspection_id") or manual_inspection.get("inspection_id") or 0)
        except Exception:
            manual_inspection_id = 0
        eager_ocr = bool((capture_context or {}).get("eager_ocr", True))
        ocr_result = self._extract_snapshot_ocr(output_path, capture_bounds, eager=eager_ocr)
        content_text = (
            "Hidden sensory feedback only, not a user request. Source: Companion Orb selected target. "
            "Describe the actual visible content inside this captured region, not just the containing window."
        )
        if manual_inspection:
            content_text += (
                f" Manual inspection is active; this captured crop is the primary evidence. "
                f"Inspect focus_bounds={manual_inspection.get('focus_bounds')} first. "
                "Do not describe the selection action or return a broad desktop/window list; "
                "return focus_bounds for the exact visible content being discussed."
            )
        result = {
            "captured_at": time.time(),
            "image_path": str(output_path),
            "source": PROVIDER_ID,
            "content_text": content_text,
            "metadata": {
                "target_available": True,
                "target": self._target_for_output(target),
                "width": int(image.width),
                "height": int(image.height),
                "capture_mode": str(target.get("target_type") or "target"),
                "screen_bounds": [int(value) for value in capture_bounds],
                "requested_screen_bounds": [int(value) for value in requested_bounds],
                "manual_inspection": dict(manual_inspection or {}),
                "manual_inspection_id": manual_inspection_id,
                "drop_trace_id": trace_id,
                "priority_drop": bool((capture_context or {}).get("priority_drop", False)),
                "manual_inspection_primary": bool(manual_inspection),
                "drop_focus_bounds": [int(value) for value in capture_bounds] if manual_inspection else [],
                "visual_fingerprint": _sensory_visual_fingerprint(image),
                "ocr_backend": str(ocr_result.get("backend") or "none"),
                "ocr_text": str(ocr_result.get("text") or ""),
                "ocr_regions": list(ocr_result.get("regions") or []),
                "ocr_sidecar": str(ocr_result.get("sidecar") or ""),
                "ocr_text_recognized": bool(ocr_result.get("text_recognized", False)),
                "ocr_region_detection_only": bool(ocr_result.get("region_detection_only", False)),
                "ocr_text_recognition_available": bool(
                    dict(ocr_result.get("text_recognition_runtime") or {}).get("available", False)
                ),
            },
        }
        self._drop_trace_event(
            "snapshot_target_saved",
            trace_id,
            console=True,
            image_path=str(output_path),
            screen_bounds=[int(value) for value in capture_bounds],
            requested_screen_bounds=[int(value) for value in requested_bounds],
            bounds_were_clipped=bool(capture_bounds != requested_bounds),
            virtual_desktop=virtual_rect if virtual_rect is not None else [],
            desktop_image_size=desktop_image_size,
            crop=crop,
            saved_size=[int(image.width), int(image.height)],
            target=self._target_for_output(target if isinstance(target, dict) else {}),
            manual_inspection=manual_inspection,
            manual_inspection_id=manual_inspection_id,
            drop_trace_id=trace_id,
            total_elapsed_ms=round((time.monotonic() - capture_started_at) * 1000.0, 1),
            save_elapsed_ms=save_elapsed_ms,
            ocr_backend=str(ocr_result.get("backend") or "none"),
            ocr_region_count=len(ocr_result.get("regions") or []),
            ocr_text=str(ocr_result.get("text") or ""),
        )
        return result

    def _extract_snapshot_ocr(
        self,
        image_path: Path,
        bounds,
        *,
        eager: bool = False,
        image_tiles=None,
    ) -> dict[str, Any]:
        screen_bounds = self._normalize_bounds(bounds)
        trace_id = str(self._active_drop_trace_id or "")
        if eager and screen_bounds:
            try:
                started_at = time.monotonic()
                tiles = [
                    dict(item)
                    for item in list(image_tiles or [])
                    if isinstance(item, dict)
                ]
                input_mode = "tiles" if tiles else "overview"
                self._drop_trace_event(
                    "ocr_extract_start",
                    trace_id,
                    image_path=str(image_path),
                    bounds=screen_bounds,
                    eager=True,
                    input_mode=input_mode,
                    tile_count=len(tiles),
                )
                if tiles:
                    result = snapshot_ocr.extract_tiled_snapshot_regions(
                        tiles,
                        screen_bounds=screen_bounds,
                        max_regions=OCR_MAX_REGIONS,
                    )
                else:
                    result = snapshot_ocr.extract_snapshot_regions(
                        image_path,
                        screen_bounds=screen_bounds,
                        max_regions=OCR_MAX_REGIONS,
                        include_window_text=not self._last_runtime_config.get('companion_orb_exclude_nc_from_captures', False),
                    )
                sidecar = snapshot_ocr.write_sidecar(image_path, result)
                if sidecar:
                    result["sidecar"] = sidecar
                self.request_snapshot_context(
                    {
                        "image_path": str(image_path),
                        "bounds": list(screen_bounds or []),
                        "metadata": {
                            "screen_bounds": list(screen_bounds or []),
                            "ocr_backend": str(result.get("backend") or "none"),
                            "ocr_regions": list(result.get("regions") or []),
                            "ocr_text": str(result.get("text") or ""),
                            "ocr_text_recognized": bool(result.get("text_recognized", False)),
                            "ocr_region_detection_only": bool(result.get("region_detection_only", False)),
                            "ocr_text_recognition_available": bool(
                                dict(result.get("text_recognition_runtime") or {}).get("available", False)
                            ),
                            "drop_trace_id": trace_id,
                        },
                    }
                )
                self._drop_trace_event(
                    "ocr_extract_finished",
                    trace_id,
                    image_path=str(image_path),
                    bounds=screen_bounds,
                    backend=str(result.get("backend") or "none"),
                    input_mode=input_mode,
                    tile_count=len(tiles),
                    region_count=len(result.get("regions") or []),
                    sidecar=str(result.get("sidecar") or ""),
                    text=str(result.get("text") or ""),
                    ocr_elapsed_ms=round((time.monotonic() - started_at) * 1000.0, 1),
                )
                return dict(result or {})
            except Exception as exc:
                self._drop_trace_event("ocr_extract_failed", trace_id, console=True, image_path=str(image_path), bounds=screen_bounds, error=str(exc))
                self._log(f"Companion Orb eager OCR failed: {exc}")
        self._drop_trace_event("ocr_extract_pending", trace_id, image_path=str(image_path), bounds=screen_bounds, eager=bool(eager))
        self.request_snapshot_context(
            {
                "image_path": str(image_path),
                "bounds": list(screen_bounds or []),
                "metadata": {
                    "screen_bounds": list(screen_bounds or []),
                    "ocr_backend": "pending",
                    "ocr_regions": [],
                    "ocr_text": "",
                    "ocr_text_recognized": False,
                    "ocr_region_detection_only": False,
                    "ocr_text_recognition_available": bool(
                        snapshot_ocr.text_recognition_runtime().get("available", False)
                    ),
                    "drop_trace_id": trace_id,
                },
            }
        )
        return {
            "regions": [],
            "text": "",
            "backend": "pending",
            "sidecar": "",
            "text_recognized": False,
            "region_detection_only": False,
            "text_recognition_runtime": snapshot_ocr.text_recognition_runtime(),
        }

    def _virtual_desktop_rect(self):
        app = QtGui.QGuiApplication.instance()
        if app is None:
            return None
        screens = list(QtGui.QGuiApplication.screens() or [])
        if not screens:
            return None
        rect = QtCore.QRect(screens[0].geometry())
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        return rect

    def export_session_state(self) -> dict[str, Any]:
        return {
            "companion_orb_target_info": dict(self._target_info or {}),
        }

    def import_session_state(self, session):
        payload = dict(session or {})
        target = payload.get("companion_orb_target_info")
        if isinstance(target, dict):
            self._target_info = dict(target)
            target_display = CompanionOrbController._capture_target_presentation(self)
            self.bridge.set_target_info(target_display)
            self._send_external_runtime({"type": "target_info", "target": target_display})
            self._save_runtime_setting("companion_orb_target_info", dict(self._target_info))
        return None

    def shutdown(self):
        self._drop_watch_closed = True
        CompanionOrbController._clear_drop_watch_offer(self)
        editor = getattr(self, "_region_size_editor", None)
        if editor is not None:
            editor.cancel()
        exclusion = getattr(self, '_nc_capture_exclusion', None)
        if exclusion is not None:
            try:
                exclusion.shutdown()
            except Exception as exc:
                self._log(f'NC capture exclusion cleanup failed: {exc}')
        watch = getattr(self, 'watch_context', None)
        if watch is not None:
            watch.clear('shutdown')
        CompanionOrbController._ensure_vision_state(self)
        residency = self._vision_residency.disable()
        self._vision_inference.invalidate(residency.generation)
        self._vision_observation_cache.clear()
        shutdown_spatial_scanning = getattr(
            self,
            "_shutdown_spatial_scanning",
            None,
        )
        if callable(shutdown_spatial_scanning):
            shutdown_spatial_scanning()
        current_primary_vision_request = (
            CompanionOrbController._primary_parallel_vision_release_request(
                getattr(self, "_last_runtime_config", {})
            )
        )
        if current_primary_vision_request:
            CompanionOrbController._release_primary_vision_model_async(
                self,
                current_primary_vision_request,
                "Companion Orb shutdown",
            )
        with self._eye_tracking_reaction_lock:
            self._eye_tracking_reaction_shutting_down = True
            self._eye_tracking_reaction_generation += 1
        self._gaze_context_dispatch_generation += 1
        CompanionOrbController._cancel_lfm_click_confirmation(self)
        self._eye_tracking_connection_key = ("off", "")
        calibration_overlay = getattr(
            self,
            "_eye_tracking_calibration_overlay",
            None,
        )
        if bool(getattr(self, "_eye_tracking_calibration_active", False)):
            self._finish_eye_tracking_calibration(
                restore_saved_status=False,
            )
        if calibration_overlay is not None:
            calibration_overlay.finish()
            calibration_overlay.deleteLater()
            self._eye_tracking_calibration_overlay = None
        self._clear_eye_tracking_state(send_external=True)
        spatial_overlay = getattr(self, "_spatial_map_overlay", None)
        self._spatial_map_overlay = None
        if spatial_overlay is not None:
            try:
                spatial_overlay.clear_regions()
                spatial_overlay.deleteLater()
            except Exception:
                pass
        self._eye_tracking_provider.stop(timeout_seconds=1.25)
        self._drift_timer.stop()
        self._motion_timer.stop()
        self._return_home_timer.stop()
        self._menu_poll_timer.stop()
        self._save_timer.stop()
        self._vision_pipeline_clear_timer.stop()
        self._watch_capture_hint_timer.stop()
        radial_menu = self._gaze_radial_menu
        self._gaze_radial_menu = None
        if radial_menu is not None:
            try:
                radial_menu.hide()
                radial_menu.deleteLater()
            except Exception:
                pass
        highlight = self._gaze_click_target_highlight
        self._gaze_click_target_highlight = None
        if highlight is not None:
            try:
                highlight.clear_target()
                highlight.deleteLater()
            except Exception:
                pass
        self._stop_external_runtime()
        popup = self._orb_popup
        self._orb_popup = None
        if popup is not None:
            try:
                popup.close()
                popup.view.close()
                popup.view.deleteLater()
            except Exception:
                pass
        self._unregister_sensory_provider()
        try:
            from visual_presence import runtime as presence_runtime

            presence_runtime.unregister_orb_controller(self)
        except Exception:
            pass
        app = QtGui.QGuiApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        if self._window is not None:
            try:
                self._window.hide()
                self._window.deleteLater()
            except Exception:
                pass
        self._window = None
        self._quick = None


def sys_platform_windows() -> bool:
    import sys

    return sys.platform.startswith("win")
