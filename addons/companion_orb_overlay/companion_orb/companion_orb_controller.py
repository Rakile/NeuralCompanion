from __future__ import annotations

import json
import math
import random
import re
import threading
import time
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

try:
    from PySide6.QtQuickWidgets import QQuickWidget
except Exception:  # pragma: no cover
    QQuickWidget = None

from .companion_orb_bridge import CompanionOrbBridge
from .external_runtime_client import ExternalOrbRuntimeClient
from . import snapshot_ocr
from .sensory_source import COMPANION_ORB_TARGET_METADATA, COMPANION_ORB_TARGET_PINGPONG_PROMPT, PROVIDER_ID
from .window_target_resolver import resolve_target_at, target_bounds, target_is_available


VALID_DISPLAY_MODES = {"off", "docked", "interaction", "always"}
ORB_COMMAND_MENU_ACTIONS = ("Change Voice", "Response Style", "Chat text input")
VOICE_FILE_SUFFIXES = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma")
ORB_RESPONSE_STYLES = (
    ("Very friendly", "friendly"),
    ("Very loving", "loving"),
    ("Sarcastic / ironic", "sarcastic"),
    ("Roast mode", "roast"),
    ("Sensual / non-explicit", "sensual_non_explicit"),
)
VALID_ORB_RESPONSE_STYLES = {value for _label, value in ORB_RESPONSE_STYLES}
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
FOCUS_GRID_COLUMNS = 12
FOCUS_GRID_ROWS = 8
FULL_SCREEN_CONTEXT_THUMBNAIL_SIZE = (1920, 1440)
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


def _normalize_orb_response_style(value) -> str:
    style = str(value or "").strip().lower()
    return style if style in VALID_ORB_RESPONSE_STYLES else "friendly"


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


class CompanionOrbController(QtCore.QObject):
    def __init__(self, context, runtime_config=None):
        super().__init__()
        self.context = context
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
        self._chat_input_popup = None
        self._chat_input_widget = None
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
        self._manual_inspection_bounds: list[int] = []
        self._manual_inspection_reason = ""
        self._manual_inspection_id = 0
        self._manual_drop_anchor_point: QtCore.QPoint | None = None
        self._manual_drop_anchor_until = 0.0
        self._external_orb_top_left: QtCore.QPoint | None = None
        self._active_snapshot_inspection_id = 0
        self._active_drop_trace_id = ""
        self._drop_trace_starts: dict[str, float] = {}
        self._last_harassment_message_at = 0.0
        self._last_drop_ack_at = 0.0
        self._recent_canned_response_templates: dict[str, list[str]] = {}
        self._comment_focus_bounds: list[int] = []
        self._comment_focus_until = 0.0
        self._comment_focus_label = ""
        self._comment_focus_grid: dict[str, Any] = {}
        self._last_comment_focus_signature = ""
        self._last_comment_focus_set_at = 0.0
        self._last_snapshot_ocr_regions: list[dict[str, Any]] = []
        self._last_snapshot_bounds: list[int] = []
        self._last_snapshot_text = ""
        self._last_snapshot_image_path = ""
        self._snapshot_cloak_count = 0
        self._snapshot_restore_visible = False
        self._debug_lock = threading.Lock()
        self._debug_last_timer_enabled: bool | None = None
        self._debug_last_move_log_at = 0.0
        self._debug_last_move_signature = ""
        self._ocr_jobs: set[str] = set()
        self._pending_comment_focus_text = ""
        self._pending_comment_focus_label = ""
        self._target_info: dict[str, Any] = {}
        self._last_target_warning = ""
        self._external_runtime: ExternalOrbRuntimeClient | None = None
        self._proxy = _OrbCommandProxy(self)
        self._proxy.state_requested.connect(self._set_ai_state, QtCore.Qt.QueuedConnection)
        self._proxy.level_requested.connect(self._set_audio_level, QtCore.Qt.QueuedConnection)
        self._proxy.music_level_requested.connect(lambda _level: None, QtCore.Qt.QueuedConnection)
        self._proxy.mood_requested.connect(self._set_presence_mood, QtCore.Qt.QueuedConnection)
        self._proxy.settings_requested.connect(self.apply_runtime_config, QtCore.Qt.QueuedConnection)
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

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_session)

        self._install_key_filter()
        self._create_window()
        self.apply_runtime_config(self._last_runtime_config)
        self._register_runtime_bridge()
        self._register_sensory_provider()

    def _install_key_filter(self):
        app = QtWidgets.QApplication.instance()
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
        service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if service is None:
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
        service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
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

    def _debug_enabled(self) -> bool:
        return bool(self._last_runtime_config.get("companion_orb_debug_enabled", False))

    def _debug_log_path(self) -> Path:
        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        return root / "runtime" / "companion_orb" / "debug" / "companion_orb_debug.log"

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
        if QQuickWidget is None:
            self.error = "Qt Quick Widgets are not available."
            self._log(self.error)
            return
        try:
            window = QtWidgets.QWidget(None, self._window_flags())
            window.setObjectName("ai_presence_companion_orb_window")
            window.setWindowTitle("Companion Orb")
            window.setFocusPolicy(QtCore.Qt.NoFocus)
            window.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            window.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
            layout = QtWidgets.QVBoxLayout(window)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            quick = QQuickWidget(window)
            quick.setObjectName("ai_presence_companion_orb_quick")
            quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
            quick.setClearColor(QtGui.QColor(0, 0, 0, 0))
            quick.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            quick.rootContext().setContextProperty("companionOrbBridge", self.bridge)
            quick.setSource(QtCore.QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "CompanionOrbOverlay.qml")))
            if quick.status() == QQuickWidget.Error:
                errors = "; ".join(str(error.toString()) for error in quick.errors())
                raise RuntimeError(errors or "Companion Orb QML load failed")
            layout.addWidget(quick)
            for obj in (window, quick):
                obj.installEventFilter(self)
            self._window = window
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
        return bool(self._last_runtime_config.get("companion_orb_external_runtime_enabled", True))

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
        elif event_type in {"orb.ready", "orb.cloak_changed"}:
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
        self._mark_user_interaction()
        self._inspect_drop_target(point, reason=reason)

    def _stop_external_runtime(self) -> None:
        runtime = self._external_runtime
        self._external_runtime = None
        if runtime is not None:
            runtime.stop()

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
                "type": "modes",
                "edit_mode": bool(self.bridge.editMode),
                "placement_mode": bool(self.bridge.placementMode),
                "click_through": bool(self.bridge.clickThrough),
            }
        )
        self._send_external_runtime({"type": "target_info", "target": self._target_for_output(self._target_info)})

    @QtCore.Slot(str)
    def _set_ai_state(self, state):
        self.bridge.setAiState(state)
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
        previous_include_process_name = bool(self._last_runtime_config.get("companion_orb_include_process_name", True))
        previous_debug_enabled = bool(self._last_runtime_config.get("companion_orb_debug_enabled", False))
        self._last_runtime_config = dict(runtime_config or {})
        self.bridge.apply_settings(self._last_runtime_config)
        self._apply_timer_intervals()
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
            self.bridge.set_target_info(self._target_for_output(self._target_info))
            self._send_external_runtime({"type": "target_info", "target": self._target_for_output(self._target_info)})
        self._apply_window_settings()
        self._refresh_visibility()
        self._sync_drift_timer()

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
            window.setWindowFlags(self._window_flags())
        except Exception:
            pass
        click_through = bool(self._last_runtime_config.get("companion_orb_click_through_default", True))
        right_drag_focus = bool(self._last_runtime_config.get("companion_orb_right_drag_focus_enabled", False))
        if self.bridge.editMode or self.bridge.placementMode or right_drag_focus:
            click_through = False
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
        screen = QtWidgets.QApplication.screenAt(QtGui.QCursor.pos()) or QtWidgets.QApplication.primaryScreen()
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
        enabled = (
            (
                bool(self._last_runtime_config.get("companion_orb_movement_enabled", True))
                and self._movement_range() > 0
            )
            or harassment_enabled
            or comment_focus_enabled
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
            regions = list(metadata.get("ocr_regions") or snapshot.get("ocr_regions") or [])
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
                best_text = str(metadata.get("ocr_text") or snapshot.get("ocr_text") or "").strip()
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
                result = snapshot_ocr.extract_snapshot_regions(path, screen_bounds=screen_bounds, max_regions=OCR_MAX_REGIONS)
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
            import engine
        except Exception:
            return False
        for name in ("_llm_request_active", "audio_playing", "microphone_active"):
            event = getattr(engine, name, None)
            is_set = getattr(event, "is_set", None)
            if callable(is_set):
                try:
                    if bool(is_set()):
                        return True
                except Exception:
                    pass
        return False

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
        self._last_comment_focus_signature = ""
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
        if time.monotonic() > self._comment_focus_until:
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
        app = QtWidgets.QApplication.instance()
        screen = None
        if app is not None:
            screen = (
                QtWidgets.QApplication.screenAt(center)
                or QtWidgets.QApplication.screenAt(top_left)
                or (self._window.screen() if self._window is not None else None)
                or QtWidgets.QApplication.primaryScreen()
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
        gap = max(20.0, min(72.0, float(window.width()) * 0.16))
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
        x = center_x + side_bias * 58.0 - window.width() * 0.5
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
        screen = QtWidgets.QApplication.primaryScreen()
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
            QtWidgets.QApplication.screenAt(target_center)
            or QtWidgets.QApplication.screenAt(target_top_left)
            or window.screen()
            or QtWidgets.QApplication.screenAt(QtGui.QCursor.pos())
            or QtWidgets.QApplication.primaryScreen()
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
        opacity = 1.0
        if not reset and bool(self._last_runtime_config.get("companion_orb_mouse_near_fade", False)):
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
                opacity = near_opacity + (1.0 - near_opacity) * mix
        try:
            window.setWindowOpacity(opacity)
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
        harassment_ready = self._harassment_ready()
        if comment_focus_ready:
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
        if bool(self._last_runtime_config.get("companion_orb_avoid_mouse", False)) and not harassment_ready and not comment_focus_ready:
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
        smoothing = 0.14 if comment_focus_ready else (0.11 if harassment_ready else max(0.055, min(0.18, 0.055 + speed * 0.055)))
        smoothing = self._time_scaled_blend(smoothing, frame_scale)
        next_x = current.x() + (target_x - current.x()) * smoothing
        next_y = current.y() + (target_y - current.y()) * smoothing
        self._drift_current_point = QtCore.QPointF(next_x, next_y)
        should_move = comment_focus_ready or harassment_ready or movement_enabled or bool(self._last_runtime_config.get("companion_orb_avoid_mouse", False))
        if should_move:
            window.move(QtCore.QPoint(int(round(next_x)), int(round(next_y))))
        if target_kind in {"comment", "harassment"} or should_move:
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
        self.bridge.set_modes(click_through=bool(enabled))
        self._send_external_runtime(
            {
                "type": "modes",
                "edit_mode": bool(self.bridge.editMode),
                "placement_mode": bool(self.bridge.placementMode),
                "click_through": bool(enabled),
            }
        )
        self._apply_click_through(bool(enabled))
        self._save_runtime_setting("companion_orb_click_through_default", bool(enabled))

    def _apply_click_through(self, enabled: bool):
        for widget in (self._window, self._quick):
            if widget is None:
                continue
            try:
                widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, bool(enabled))
            except Exception:
                pass
        self._apply_windows_click_through(bool(enabled))
        self._sync_menu_poll_timer()

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
        self.bridge.set_target_info({})
        self._send_external_runtime({"type": "clear_target"})
        self._clear_manual_drop_anchor()
        self._save_runtime_setting("companion_orb_target_info", {})
        self._publish_target_event({}, cleared=True)
        self._log("Companion Orb target cleared.")

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
        if event.type() == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.RightButton:
            self._mark_user_interaction()
            self._show_command_menu(self._event_global_pos(event))
            return True
        if event.type() == QtCore.QEvent.MouseButtonPress:
            self._mark_user_interaction()
            right_drag_focus = bool(self._last_runtime_config.get("companion_orb_right_drag_focus_enabled", False))
            event_pos = self._event_global_pos(event)
            if (self.bridge.placementMode or right_drag_focus) and event.button() == QtCore.Qt.RightButton:
                self._drift_timer.stop()
                self._motion_timer.stop()
                self._drag_offset = event_pos - self._window.frameGeometry().topLeft()
                self._drag_start_global_pos = QtCore.QPoint(event_pos)
                self._drag_moved = False
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
            right_drag_focus = bool(self._last_runtime_config.get("companion_orb_right_drag_focus_enabled", False))
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
            if had_drag and event.button() in (QtCore.Qt.LeftButton, QtCore.Qt.RightButton):
                self._inspect_drop_target(self._orb_center_global(), reason="drag_drop")
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
        self._poll_drag_start_pos = None
        self._poll_drag_offset = None
        self._poll_drag_button = ""
        self._poll_drag_active = False

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

    def _show_command_menu(self, global_pos: QtCore.QPoint | None = None):
        if self._window is None or self._menu_open:
            return
        previous_click_through = bool(self.bridge.clickThrough)
        self._menu_open = True
        self._drift_timer.stop()
        self._motion_timer.stop()
        if previous_click_through:
            self._apply_click_through(False)
        menu = QtWidgets.QMenu(self._window)
        menu.setObjectName("companion_orb_command_menu")
        point = global_pos if isinstance(global_pos, QtCore.QPoint) else QtGui.QCursor.pos()
        for label in ORB_COMMAND_MENU_ACTIONS:
            if label == "Change Voice":
                submenu = menu.addMenu(label)
                submenu.setObjectName("companion_orb_voice_menu")
                submenu.aboutToShow.connect(lambda submenu=submenu: self._populate_voice_menu(submenu))
                self._populate_voice_menu(submenu)
                continue
            if label == "Response Style":
                submenu = menu.addMenu(label)
                submenu.setObjectName("companion_orb_response_style_menu")
                self._populate_response_style_menu(submenu)
                continue
            action = menu.addAction(label)
            action.triggered.connect(lambda _checked=False, command=label, anchor=QtCore.QPoint(point): self._handle_menu_command(command, anchor))
        menu.aboutToHide.connect(lambda: self._finish_command_menu(previous_click_through))
        try:
            menu.popup(point)
        except Exception:
            self._finish_command_menu(previous_click_through)

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

    def _populate_response_style_menu(self, menu: QtWidgets.QMenu):
        current = _normalize_orb_response_style(self._last_runtime_config.get("companion_orb_response_style", "friendly"))
        for label, value in ORB_RESPONSE_STYLES:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current)
            action.triggered.connect(lambda _checked=False, style=value: self._set_response_style(style))

    def _set_response_style(self, style: str):
        value = _normalize_orb_response_style(style)
        self._last_runtime_config["companion_orb_response_style"] = value
        self._save_runtime_setting("companion_orb_response_style", value)
        label = next((item_label for item_label, item_value in ORB_RESPONSE_STYLES if item_value == value), "Very friendly")
        self._debug_event("response_style_changed", console=True, response_style=value, label=label)
        self._log(f"Companion Orb response style set to: {label}")

    def _show_chat_input_popup(self, global_pos: QtCore.QPoint | None = None):
        if self._chat_input_popup is not None:
            try:
                self._chat_input_popup.show()
                self._chat_input_popup.raise_()
                self._chat_input_popup.activateWindow()
                if self._chat_input_widget is not None:
                    self._chat_input_widget.setFocus(QtCore.Qt.PopupFocusReason)
                return
            except Exception:
                self._chat_input_popup = None
                self._chat_input_widget = None

        popup = QtWidgets.QWidget(None, QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
        popup.setObjectName("companion_orb_chat_input_popup")
        popup.setWindowTitle("Companion Orb Chat")
        popup.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        popup.setStyleSheet(
            "QWidget#companion_orb_chat_input_popup {"
            "  background: #0b1420;"
            "  border: 1px solid #365472;"
            "  border-radius: 8px;"
            "}"
            "QLabel { color: #cfe7ff; font-size: 11px; font-weight: 700; }"
            "QPushButton { min-height: 26px; padding: 3px 10px; }"
        )
        layout = QtWidgets.QVBoxLayout(popup)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(7)

        title = QtWidgets.QLabel("Companion Orb Chat")
        title.setObjectName("companion_orb_chat_input_title")
        layout.addWidget(title)

        try:
            from ui.runtime.spellcheck import ChatMessageInput, attach_spellcheck

            input_widget = ChatMessageInput(popup)
            attach_spellcheck(input_widget)
        except Exception:
            input_widget = QtWidgets.QLineEdit(popup)
        input_widget.setObjectName("companion_orb_chat_input")
        input_widget.setPlaceholderText("Type a message to NC...")
        input_widget.setMinimumWidth(340)
        layout.addWidget(input_widget)

        status = QtWidgets.QLabel("")
        status.setObjectName("companion_orb_chat_input_status")
        status.setStyleSheet("color: #8ea3b8; font-size: 11px; font-weight: 500;")
        status.setWordWrap(True)
        layout.addWidget(status)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        send_button = QtWidgets.QPushButton("Send")
        cancel_button = QtWidgets.QPushButton("Close")
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        button_row.addWidget(send_button)
        layout.addLayout(button_row)

        def read_text():
            if hasattr(input_widget, "text"):
                return str(input_widget.text() or "")
            if hasattr(input_widget, "toPlainText"):
                return str(input_widget.toPlainText() or "")
            return ""

        def submit():
            message = read_text().strip()
            if not message:
                status.setText("Type a message first.")
                return
            sent, reason = self._send_orb_chat_message(message)
            status.setText(reason)
            if sent:
                popup.close()

        send_button.clicked.connect(submit)
        cancel_button.clicked.connect(popup.close)
        if hasattr(input_widget, "sendRequested"):
            input_widget.sendRequested.connect(submit)
        elif hasattr(input_widget, "returnPressed"):
            input_widget.returnPressed.connect(submit)
        popup.destroyed.connect(lambda *_args, widget=popup: self._clear_chat_input_popup(widget))

        self._chat_input_popup = popup
        self._chat_input_widget = input_widget
        popup.adjustSize()
        popup.resize(max(380, popup.width()), popup.height())
        self._position_chat_input_popup(popup, global_pos)
        popup.show()
        popup.raise_()
        popup.activateWindow()
        input_widget.setFocus(QtCore.Qt.PopupFocusReason)

    def _position_chat_input_popup(self, popup: QtWidgets.QWidget, global_pos: QtCore.QPoint | None = None):
        point = QtCore.QPoint(global_pos) if isinstance(global_pos, QtCore.QPoint) else QtGui.QCursor.pos()
        screen = QtWidgets.QApplication.screenAt(point) or QtWidgets.QApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        x = max(geometry.left() + 8, min(point.x(), geometry.right() - popup.width() - 8))
        y = max(geometry.top() + 8, min(point.y(), geometry.bottom() - popup.height() - 8))
        popup.move(x, y)

    def _clear_chat_input_popup(self, popup: QtWidgets.QWidget):
        if popup is self._chat_input_popup:
            self._chat_input_popup = None
            self._chat_input_widget = None

    def _send_orb_chat_message(self, message: str) -> tuple[bool, str]:
        text = str(message or "").strip()
        if not text:
            return False, "Type a message first."
        attempted_sender = False
        for candidate in self._chat_sender_candidates():
            sender = getattr(candidate, "send_typed_chat_message", None)
            if not callable(sender):
                continue
            attempted_sender = True
            try:
                sent = bool(sender(text=text))
            except TypeError:
                try:
                    sent = bool(sender(text))
                except Exception as exc:
                    self._log(f"Companion Orb chat send failed: {exc}")
                    sent = False
            except Exception as exc:
                self._log(f"Companion Orb chat send failed: {exc}")
                sent = False
            if sent:
                self._sync_chat_ui(candidate)
                self._log("Companion Orb queued chat text input.")
                return True, "Message sent."
        if attempted_sender:
            return False, "Message was not queued. Initialize NC first."
        try:
            import engine

            result = engine.queue_typed_chat_message(text)
            if bool(dict(result or {}).get("queued", False)):
                self._log("Companion Orb queued chat text input through engine fallback.")
                return True, "Message sent."
            reason = str(dict(result or {}).get("reason") or "not queued")
            return False, f"Message was not queued: {reason}."
        except Exception as exc:
            self._log(f"Companion Orb chat fallback failed: {exc}")
            return False, "Message was not queued. Initialize NC first."

    def _chat_sender_candidates(self) -> list[Any]:
        candidates: list[Any] = []

        def add(candidate):
            if candidate is not None and candidate not in candidates:
                candidates.append(candidate)

        shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
        shell_window = getattr(shell, "_window", None)
        add(shell)
        add(shell_window)
        add(getattr(shell_window, "backend", None))
        add(getattr(shell_window, "_backend", None))
        app = QtWidgets.QApplication.instance()
        if app is not None:
            for widget in list(app.topLevelWidgets() or []):
                add(widget)
                add(getattr(widget, "backend", None))
                add(getattr(widget, "_backend", None))
        return candidates

    def _sync_chat_ui(self, candidate):
        for target in (candidate, getattr(candidate, "backend", None), getattr(candidate, "_backend", None)):
            if target is None:
                continue
            rebuild = getattr(target, "_rebuild_chat_view_from_history", None)
            if callable(rebuild):
                try:
                    rebuild(force=True)
                except Exception:
                    pass
        shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
        shell_window = getattr(shell, "_window", None)
        sync = getattr(shell_window, "_sync_backend_to_ui", None)
        if callable(sync):
            try:
                sync(force=True)
            except Exception:
                pass

    def _populate_voice_menu(self, menu: QtWidgets.QMenu):
        menu.clear()
        voices = self._available_voice_files()
        if not voices:
            action = menu.addAction("No voice files found")
            action.setEnabled(False)
            return
        current_path = self._normalized_voice_config_path(self._last_runtime_config.get("voice_path", ""))
        for voice_file in voices:
            relative = self._voice_config_path(voice_file)
            label = self._voice_menu_label(voice_file)
            action = menu.addAction(label)
            action.setToolTip(str(voice_file))
            action.setCheckable(True)
            action.setChecked(self._normalized_voice_config_path(relative) == current_path)
            action.triggered.connect(lambda _checked=False, path=voice_file: self._select_voice_file(path))

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
                from ui.runtime.engine_access import update_runtime_config

                update_runtime_config(key, value)
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
                import engine

                stop_playback = getattr(engine, "stop_playback", None)
                audio_playing = getattr(engine, "audio_playing", None)
                is_audio_active = bool(getattr(audio_playing, "is_set", lambda: False)())
                if is_audio_active and getattr(stop_playback, "set", None):
                    stop_playback.set()
                    try:
                        getattr(engine, "sd").stop()
                    except Exception:
                        pass
                    time.sleep(0.12)
                speak_async = getattr(engine, "speak_async", None)
                if callable(speak_async):
                    speak_async(str(message or "").strip())
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
        self._queue_llm_harassment_candidate(message, target_title, target_info)
        self._speak_harassment_message(message)

    def _tts_runtime_ready(self) -> bool:
        try:
            import engine

            return getattr(engine, "tts_model", None) is not None
        except Exception:
            return False

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

    def _queue_llm_harassment_candidate(self, message: str, target_title: str = "", target_info: dict[str, Any] | None = None):
        try:
            import engine

            if getattr(engine, "tts_model", None) is None:
                return
            runtime_config = getattr(engine, "RUNTIME_CONFIG", {}) or {}
            if not bool(runtime_config.get("sensory_allow_hidden_proactive_speech", False)):
                return
            queue_candidate = getattr(engine, "_queue_hidden_proactive_candidate", None)
            if callable(queue_candidate):
                queue_candidate(
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

    def _speak_harassment_message(self, message: str):
        if not self._tts_runtime_ready():
            self._log("Companion Orb harassment message skipped because TTS is not initialized yet.")
            return
        if self.bridge.aiState == "speaking" or self.bridge.audioLevel > 0.035:
            self._log(f"Companion Orb harassment message queued while TTS is active: {message}")
            return
        try:
            import engine

            speak_async = getattr(engine, "speak_async", None)
            if callable(speak_async):
                speak_async(str(message or "").strip())
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
    ):
        cursor_point = QtCore.QPoint(cursor)
        trace = str(trace_id or self._active_drop_trace_id or "").strip()
        self._drop_trace_event("snapshot_pointer_queued", trace, console=True, cursor=cursor_point, reason=reason, inspection_id=inspection_id or 0)

        def worker():
            try:
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
                self._log(f"Companion Orb pointer snapshot failed: {exc}")

        threading.Thread(target=worker, daemon=True, name="companion-orb-pointer-snapshot").start()

    def _inspect_drop_target(self, point: QtCore.QPoint, *, reason: str = "drag_drop"):
        now = time.monotonic()
        if now - self._last_drop_inspection_at < DROP_INSPECTION_COOLDOWN_SECONDS:
            return
        self._last_drop_inspection_at = now
        width = int(self._last_runtime_config.get("companion_orb_target_region_width", 640) or 640)
        height = int(self._last_runtime_config.get("companion_orb_target_region_height", 420) or 420)
        target = resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode="region")
        bounds = target_bounds(target)
        if not bounds:
            self._debug_event("drop_inspection_rejected", console=True, point=point, reason=reason, width=width, height=height)
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
        self._target_info = dict(target)
        self.bridge.set_target_info(self._target_for_output(self._target_info))
        self._send_external_runtime({"type": "target_info", "target": self._target_for_output(self._target_info)})
        self._save_runtime_setting("companion_orb_target_info", dict(self._target_info))
        self._publish_target_event(self._target_for_output(self._target_info))
        self._set_manual_inspection(target, reason=reason, inspection_id=inspection_id)
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
        self._capture_pointer_snapshot_async(point, reason=reason, inspection_id=inspection_id, trace_id=trace_id)

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
                import engine

                runner = getattr(engine, "run_hidden_sensory_pingpong_cycle", None)
                if not callable(runner):
                    self._drop_trace_event("hidden_ping_unavailable", trace, console=True, reason=reason)
                    return
                for attempt in range(max_attempts):
                    try:
                        if snapshot_payload:
                            accepted = bool(
                                runner(
                                    force=True,
                                    snapshots_override=snapshot_payload,
                                    priority=bool(manual_priority),
                                    priority_source="companion_orb_drop" if manual_priority else "",
                                    trace_id=trace,
                                )
                            )
                        else:
                            accepted = bool(runner(force=True))
                    except TypeError:
                        accepted = bool(runner(force=True))
                    self._drop_trace_event("hidden_ping_attempt", trace, reason=reason, attempt=attempt + 1, accepted=accepted)
                    if accepted:
                        self._drop_trace_event("hidden_ping_accepted", trace, console=True, reason=reason, attempt=attempt + 1)
                        return
                    time.sleep(retry_delay)
                self._drop_trace_event("hidden_ping_gave_up", trace, console=True, reason=reason, attempts=max_attempts)
            except Exception as exc:
                self._drop_trace_event("hidden_ping_failed", trace, console=True, reason=reason, error=str(exc))
                self._log(f"Companion Orb could not request hidden sensory inspection ({reason}): {exc}")

        threading.Thread(target=worker, daemon=True, name="companion-orb-hidden-inspection").start()

    def _deliver_drop_snapshot_immediately(self, image_path: str, *, reason: str, trace_id: str = "") -> bool:
        path = str(image_path or "").strip()
        trace = str(trace_id or self._active_drop_trace_id or "").strip()
        if not path or not Path(path).is_file():
            self._drop_trace_event("drop_immediate_image_skipped", trace, reason=reason, image_path=path, skipped_reason="missing_image")
            return False
        service = None
        try:
            service = self.context.get_service("qt.user_image_turns") if getattr(self, "context", None) is not None else None
        except Exception:
            service = None
        if service is None or not callable(getattr(service, "queue_image_turn", None)):
            self._drop_trace_event("drop_immediate_image_skipped", trace, reason=reason, image_path=path, skipped_reason="service_unavailable")
            return False
        content = (
            "React through the Companion Orb to this fresh selected snapshot. "
            "Focus only on the visible content inside the crop. "
            "Do not describe the drag/drop action or the upload itself. Keep the reply short."
        )
        try:
            service.queue_image_turn(
                path,
                content=content,
                source="companion_orb_target",
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
            image_path = str(result.get("image_path") or "")
            metadata = dict(result.get("metadata") or {})
            metadata["manual_inspection_id"] = inspection_id
            metadata["drop_trace_id"] = trace
            metadata["priority_drop"] = True
            immediate_delivery = self._deliver_drop_snapshot_immediately(image_path, reason=reason, trace_id=trace)
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
            self._request_hidden_pingpong_cycle_async(reason=reason, snapshots=[dict(result)], trace_id=trace)
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
            self._log(f"Companion Orb pointer snapshot failed: {exc}")

    def _interrupt_audio_for_drop_comment(self, *, reason: str = "manual_inspection"):
        if not bool(self._last_runtime_config.get("companion_orb_interrupt_for_drop_comment", True)):
            return
        try:
            import engine

            stop_playback = getattr(engine, "stop_playback", None)
            if getattr(stop_playback, "set", None):
                stop_playback.set()
            try:
                getattr(engine, "sd").stop()
            except Exception:
                pass
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
        self.bridge.set_target_info(self._target_for_output(self._target_info))
        self._send_external_runtime({"type": "target_info", "target": self._target_for_output(self._target_info)})
        self._save_runtime_setting("companion_orb_target_info", dict(self._target_info))
        self._publish_target_event(self._target_for_output(self._target_info))
        title = str(target.get("title") or target.get("target_type") or "target")
        self._log(f"Selected Companion Orb target: {title}")

    def _resolve_target_at(self, point: QtCore.QPoint, *, width: int, height: int, mode: str):
        normalized_mode = str(mode or "window").strip().lower()
        previous_click_through = bool(self.bridge.clickThrough)
        if normalized_mode == "window":
            try:
                self._apply_click_through(True)
                QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 25)
                QtCore.QThread.msleep(35)
            except Exception:
                pass
            target = resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode=mode)
            try:
                self._apply_click_through(previous_click_through)
            except Exception:
                pass
        else:
            target = resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode=mode)
        if normalized_mode != "window" or not self._is_own_target(target):
            return target
        if self._is_own_target(target):
            return resolve_target_at(point.x(), point.y(), region_width=width, region_height=height, mode="region")
        return target

    def _is_own_target(self, target) -> bool:
        if not target or self._window is None:
            return False
        try:
            own_id = int(self._window.winId())
            target_id = int(str(target.get("window_id") or "0"), 0)
            if target_id and target_id == own_id:
                return True
        except Exception:
            pass
        return str(target.get("title") or "").strip().lower() == "companion orb"

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
        try:
            result = QtWidgets.QMessageBox.question(
                self._window,
                "Use Companion Orb Target?",
                f"Use this as the Companion Orb Hidden Sensory target?\n\n{details}",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            return result == QtWidgets.QMessageBox.Yes
        except Exception:
            return True

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
        app = QtWidgets.QApplication.instance()
        focus = app.focusWidget() if app is not None else None
        return isinstance(
            focus,
            (
                QtWidgets.QLineEdit,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QComboBox,
            ),
        )

    def _handle_hotkey(self, event):
        checks = [
            ("companion_orb_toggle_hotkey", "Ctrl+Alt+O", self.toggle_enabled),
            ("companion_orb_edit_hotkey", "Ctrl+Alt+Shift+O", lambda: self.set_edit_mode(not self.bridge.editMode)),
            ("companion_orb_placement_hotkey", "Ctrl+Alt+P", lambda: self.set_placement_mode(not self.bridge.placementMode)),
            ("companion_orb_clear_target_hotkey", "Ctrl+Alt+Backspace", self.clear_target),
            ("companion_orb_click_through_hotkey", "Ctrl+Alt+C", lambda: self.set_click_through(not self.bridge.clickThrough)),
            ("companion_orb_reset_position_hotkey", "Ctrl+Alt+R", self.reset_position),
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
            if self._snapshot_cloak_count <= 0:
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
                self._send_external_runtime({"type": "cloak", "enabled": False})
                self._debug_event("snapshot_cloak_disabled", restore_visible=restore_visible)
                self._refresh_visibility()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            try:
                app.processEvents(QtCore.QEventLoop.AllEvents, 35)
            except Exception:
                pass

    def _apply_snapshot_cloak_blocking(self, enabled: bool) -> bool:
        app = QtWidgets.QApplication.instance()
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

    def _grab_desktop_without_orb(self, image_grab, *, cloak_delay_seconds: float = 0.08, trace_id: str = ""):
        started_at = time.monotonic()
        cloaked = self._apply_snapshot_cloak_blocking(True)
        if cloaked:
            time.sleep(max(0.0, min(0.15, float(cloak_delay_seconds))))
        try:
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
            from ui.runtime.engine_access import update_runtime_config

            update_runtime_config(str(key), value)
        except Exception:
            pass
        self._save_timer.start()

    def _save_session(self):
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        for widget in list(app.topLevelWidgets() or []):
            callback = getattr(widget, "save_session", None)
            if callable(callback):
                try:
                    callback()
                    return
                except Exception:
                    return

    def _publish_target_event(self, target_info: dict[str, Any], *, cleared: bool = False):
        try:
            self.context.events.publish(
                "companion_orb_target_selected",
                {"target": dict(target_info or {}), "cleared": bool(cleared), "source": "companion_orb"},
            )
        except Exception:
            pass

    def capture_sensory_snapshot(self, capture_context=None):
        settings = self._last_runtime_config
        if not bool(settings.get("companion_orb_sensory_target_enabled", False)):
            self._debug_event("sensory_capture_skipped", reason="disabled")
            return {
                "captured_at": time.time(),
                "source": PROVIDER_ID,
                "content_text": "Companion Orb Target is selected, but orb sensory targeting is disabled in Companion Orb Overlay.",
                "metadata": {"target_available": False, "reason": "disabled"},
            }
        if bool(settings.get("companion_orb_full_screen_context_enabled", False)):
            manual_inspection = self._manual_inspection_payload()
            manual_bounds = self._normalize_bounds(manual_inspection.get("focus_bounds") if isinstance(manual_inspection, dict) else None)
            if manual_bounds:
                target = {
                    "target_type": "region",
                    "title": "Companion Orb selected focus area",
                    "process_name": "",
                    "bounds": list(manual_bounds),
                }
                try:
                    self._debug_event(
                        "sensory_capture_start",
                        console=True,
                        mode="manual_drop_region",
                        bounds=manual_bounds,
                    )
                    return self._capture_target_region(
                        manual_bounds,
                        target,
                        dict(capture_context or {}, manual_inspection=manual_inspection),
                    )
                except Exception as exc:
                    self._debug_event("sensory_capture_failed", console=True, mode="manual_drop_region", bounds=manual_bounds, error=str(exc))
                    return {
                        "captured_at": time.time(),
                        "source": PROVIDER_ID,
                        "content_text": f"Companion Orb selected region capture failed: {exc}",
                        "metadata": {"target_available": False, "reason": "manual_drop_capture_failed"},
                    }
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
        target = dict(self._target_info or {})
        if not target:
            self._debug_event("sensory_capture_skipped", reason="missing_target")
            return {
                "captured_at": time.time(),
                "source": PROVIDER_ID,
                "content_text": "Companion Orb Target is selected, but no orb target has been selected yet.",
                "metadata": {"target_available": False, "reason": "missing_target"},
            }
        if not target_is_available(target):
            self.clear_target()
            self._debug_event("sensory_capture_skipped", console=True, reason="target_lost", target=self._target_for_output(target))
            return {
                "captured_at": time.time(),
                "source": PROVIDER_ID,
                "content_text": "Companion Orb target lost. Select a new target before using targeted hidden sensory feedback.",
                "metadata": {"target_available": False, "reason": "target_lost"},
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

    def _capture_full_screen_context(self, capture_context=None):
        from PIL import ImageGrab

        output_root = Path(str((capture_context or {}).get("output_dir") or (self.context.app_root / "runtime" / "sensory_feedback")))
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time() * 1000)
        output_path = output_root / f"companion_orb_full_screen_{timestamp}.jpg"
        self._debug_event("snapshot_full_screen_start", console=True, image_path=str(output_path))
        trace_id = str((capture_context or {}).get("drop_trace_id") or self._active_drop_trace_id or "")
        image = self._grab_desktop_without_orb(ImageGrab, trace_id=trace_id)
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
        screen_source_index = self._screen_source_capture_index()
        selected_screen_bounds = self._configured_screen_source_bounds(screen_source_index)
        crop = []
        capture_mode = "full_screen"
        target_title = "Full desktop context"
        if selected_screen_bounds:
            cropped_image, crop = self._crop_desktop_image_to_bounds(image, selected_screen_bounds, virtual_rect)
            if crop:
                image = cropped_image
                screen_bounds = list(selected_screen_bounds)
                capture_mode = "selected_screen"
                target_title = f"Selected screen {screen_source_index + 1} context"
        original_size = [int(image.width), int(image.height)]
        image.thumbnail(FULL_SCREEN_CONTEXT_THUMBNAIL_SIZE)
        image.save(output_path, format="JPEG", quality=82, optimize=True)
        manual_inspection = self._manual_inspection_payload()
        manual_inspection_id = int(manual_inspection.get("inspection_id") or 0) if isinstance(manual_inspection, dict) else 0
        target = {
            "target_type": "screen",
            "title": target_title,
            "process_name": "",
            "bounds": list(screen_bounds),
        }
        ocr_result = self._extract_snapshot_ocr(output_path, screen_bounds, eager=True)
        context_scope = "the selected monitor" if capture_mode == "selected_screen" else "the desktop"
        content_text = (
            f"Hidden sensory feedback only, not a user request. Source: Companion Orb full-screen context map for {context_scope}. "
            "Identify concrete visible content, not just window names."
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
                "screen_source_capture_screen_index": int(screen_source_index),
                "screen_bounds": list(screen_bounds),
                "crop": list(crop),
                "manual_inspection": dict(manual_inspection or {}),
                "manual_inspection_id": manual_inspection_id,
                "manual_inspection_primary": bool(manual_inspection),
                "drop_focus_bounds": list(manual_inspection.get("focus_bounds") or []) if manual_inspection else [],
                "ocr_backend": str(ocr_result.get("backend") or "none"),
                "ocr_text": str(ocr_result.get("text") or ""),
                "ocr_regions": list(ocr_result.get("regions") or []),
                "ocr_sidecar": str(ocr_result.get("sidecar") or ""),
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
            thumbnail_limit=list(FULL_SCREEN_CONTEXT_THUMBNAIL_SIZE),
            ocr_backend=str(ocr_result.get("backend") or "none"),
            ocr_region_count=len(ocr_result.get("regions") or []),
            manual_inspection=manual_inspection,
        )
        return result

    def _screen_source_capture_index(self) -> int:
        if "screen_source_capture_screen_index" in self._last_runtime_config:
            value = self._last_runtime_config.get("screen_source_capture_screen_index", -1)
        else:
            try:
                import engine

                value = (getattr(engine, "RUNTIME_CONFIG", {}) or {}).get("screen_source_capture_screen_index", -1)
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
            screens = list(QtWidgets.QApplication.screens() or [])
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
        from PIL import ImageGrab

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
        image.thumbnail((960, 720))
        save_started_at = time.monotonic()
        image.save(output_path, format="JPEG", quality=85, optimize=True)
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
                "ocr_backend": str(ocr_result.get("backend") or "none"),
                "ocr_text": str(ocr_result.get("text") or ""),
                "ocr_regions": list(ocr_result.get("regions") or []),
                "ocr_sidecar": str(ocr_result.get("sidecar") or ""),
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

    def _extract_snapshot_ocr(self, image_path: Path, bounds, *, eager: bool = False) -> dict[str, Any]:
        screen_bounds = self._normalize_bounds(bounds)
        trace_id = str(self._active_drop_trace_id or "")
        if eager and screen_bounds:
            try:
                started_at = time.monotonic()
                self._drop_trace_event("ocr_extract_start", trace_id, image_path=str(image_path), bounds=screen_bounds, eager=True)
                result = snapshot_ocr.extract_snapshot_regions(image_path, screen_bounds=screen_bounds, max_regions=OCR_MAX_REGIONS)
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
                    "drop_trace_id": trace_id,
                },
            }
        )
        return {"regions": [], "text": "", "backend": "pending", "sidecar": ""}

    def _virtual_desktop_rect(self):
        app = QtWidgets.QApplication.instance()
        if app is None:
            return None
        screens = list(QtWidgets.QApplication.screens() or [])
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
            self.bridge.set_target_info(self._target_for_output(self._target_info))
            self._send_external_runtime({"type": "target_info", "target": self._target_for_output(self._target_info)})
            self._save_runtime_setting("companion_orb_target_info", dict(self._target_info))
        return None

    def shutdown(self):
        self._drift_timer.stop()
        self._motion_timer.stop()
        self._return_home_timer.stop()
        self._menu_poll_timer.stop()
        self._save_timer.stop()
        self._stop_external_runtime()
        self._unregister_sensory_provider()
        try:
            from visual_presence import runtime as presence_runtime

            presence_runtime.unregister_orb_controller(self)
        except Exception:
            pass
        app = QtWidgets.QApplication.instance()
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
