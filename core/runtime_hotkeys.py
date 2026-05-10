"""Runtime hotkey parsing and polling helpers.

This module keeps keyboard-specific state out of the main engine
orchestration file while preserving the same behavior and defaults.
"""

from __future__ import annotations

import re
import threading

import keyboard

from core.runtime_contracts import RuntimeCapability, RuntimeService, RuntimeStatus

try:
    from pynput import keyboard as pynput_keyboard
except Exception:
    pynput_keyboard = None


DEFAULT_PUSH_TO_TALK_HOTKEY = "Right Ctrl"
DEFAULT_MANUAL_ACTION_HOTKEYS = {
    "regenerate_response": "Alt+R",
    "retry_user_input": "Alt+Y",
    "pause_speech": "Alt+P",
    "skip_speech": "Alt+Enter",
    "skip_user_reply": "Alt+U",
    "replay_last_assistant": "Alt+L",
    "replay_chat_session": "Alt+J",
}
DEFAULT_UI_ACTION_HOTKEYS = {
    "start_engine": "",
    "stop_engine": "",
    "reset_chat_session": "",
    "clear_console": "",
    "clear_chat": "",
}
HOTKEY_ACTION_LABELS = {
    "push_to_talk": "Push-to-Talk",
    "regenerate_response": "Regenerate Response",
    "retry_user_input": "Retry Input",
    "pause_speech": "Pause / Resume Speech",
    "skip_speech": "Skip Speech",
    "skip_user_reply": "Skip User Reply",
    "replay_last_assistant": "Replay Last Assistant Reply",
    "replay_chat_session": "Replay Chat Session",
    "start_engine": "Start Engine",
    "stop_engine": "Stop Engine",
    "reset_chat_session": "Reset Chat Memory",
    "clear_console": "Clear Console",
    "clear_chat": "Clear Chat",
}

PYNPUT_HOTKEY_AVAILABLE = pynput_keyboard is not None
EXACT_HOTKEY_SCAN_CODES = {
    "left ctrl": (29,),
    "right ctrl": (3613,),
    "left alt": (56,),
    "right alt": (3640,),
    "left shift": (42,),
    "right shift": (54,),
    "left enter": (28,),
    "right enter": (3612,),
    "enter": (28, 3612),
    "left windows": (3675,),
    "right windows": (3676,),
}

if PYNPUT_HOTKEY_AVAILABLE:
    PYNPUT_EXACT_KEY_NAMES = {
        pynput_keyboard.Key.ctrl_l: "left ctrl",
        pynput_keyboard.Key.ctrl_r: "right ctrl",
        pynput_keyboard.Key.alt_l: "left alt",
        pynput_keyboard.Key.alt_r: "right alt",
        pynput_keyboard.Key.shift_l: "left shift",
        pynput_keyboard.Key.shift_r: "right shift",
        pynput_keyboard.Key.cmd_l: "left windows",
        pynput_keyboard.Key.cmd_r: "right windows",
        pynput_keyboard.Key.enter: "enter",
    }
else:
    PYNPUT_EXACT_KEY_NAMES = {}

_pynput_hotkey_state_tracker = None


def normalize_hotkey_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s*\+\s*", "+", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _hotkey_variants(binding_text):
    text = normalize_hotkey_text(binding_text).lower()
    if not text:
        return ()
    alias_groups = {
        "right ctrl": ("right ctrl", "ctrl right", "right control", "control right"),
        "ctrl right": ("right ctrl", "ctrl right", "right control", "control right"),
        "right control": ("right ctrl", "ctrl right", "right control", "control right"),
        "control right": ("right ctrl", "ctrl right", "right control", "control right"),
        "left ctrl": ("left ctrl", "ctrl left", "left control", "control left"),
        "ctrl left": ("left ctrl", "ctrl left", "left control", "control left"),
        "left control": ("left ctrl", "ctrl left", "left control", "control left"),
        "control left": ("left ctrl", "ctrl left", "left control", "control left"),
        "ctrl": ("ctrl", "control"),
        "control": ("ctrl", "control"),
        "enter": ("enter", "return"),
        "return": ("return", "enter"),
    }
    parts = [part.strip() for part in text.split("+") if str(part or "").strip()]
    if not parts:
        return ()
    variants = [""]
    for part in parts:
        part_variants = alias_groups.get(part, (part,))
        expanded = []
        for prefix in variants:
            for option in part_variants:
                expanded.append(f"{prefix}+{option}" if prefix else option)
        variants = expanded
    return tuple(dict.fromkeys(item for item in variants if item))


def _binding_parts(binding_text):
    return [part.strip() for part in normalize_hotkey_text(binding_text).split("+") if str(part or "").strip()]


def _scan_code_groups_for_binding(binding_text):
    groups = []
    for part in _binding_parts(binding_text):
        lowered = normalize_hotkey_text(part).lower()
        scan_codes = list(EXACT_HOTKEY_SCAN_CODES.get(lowered, ()))
        if not scan_codes:
            try:
                scan_codes = list(keyboard.key_to_scan_codes(part))
            except Exception:
                scan_codes = []
        normalized_codes = []
        seen = set()
        for code in scan_codes:
            try:
                value = int(code)
            except Exception:
                continue
            if value in seen:
                continue
            seen.add(value)
            normalized_codes.append(value)
        groups.append(tuple(normalized_codes))
    return tuple(groups)


def canonicalize_pynput_key(key):
    if not PYNPUT_HOTKEY_AVAILABLE:
        return ""
    try:
        explicit = PYNPUT_EXACT_KEY_NAMES.get(key, "")
        if explicit:
            return explicit
    except Exception:
        pass
    try:
        if key == pynput_keyboard.Key.ctrl:
            return "ctrl"
        if key == pynput_keyboard.Key.alt:
            return "alt"
        if key == pynput_keyboard.Key.shift:
            return "shift"
        if key == pynput_keyboard.Key.cmd:
            return "windows"
    except Exception:
        pass
    try:
        char = getattr(key, "char", None)
        if char:
            if len(char) == 1:
                codepoint = ord(char)
                if 1 <= codepoint <= 26:
                    return chr(codepoint + 96)
            return normalize_hotkey_text(char).lower()
    except Exception:
        pass
    try:
        vk = getattr(key, "vk", None)
        if isinstance(vk, int):
            if 65 <= vk <= 90:
                return chr(vk + 32)
            if 48 <= vk <= 57:
                return chr(vk)
    except Exception:
        pass
    try:
        name = getattr(key, "name", None)
        if name:
            return normalize_hotkey_text(name).lower()
    except Exception:
        pass
    return ""


def _required_binding_part_matches(required, pressed_names):
    required_name = normalize_hotkey_text(required).lower()
    if not required_name:
        return False
    pressed = {normalize_hotkey_text(item).lower() for item in set(pressed_names or set()) if str(item or "").strip()}
    alias_groups = {
        "ctrl": {"ctrl", "control", "left ctrl", "right ctrl"},
        "control": {"ctrl", "control", "left ctrl", "right ctrl"},
        "alt": {"alt", "left alt", "right alt"},
        "shift": {"shift", "left shift", "right shift"},
        "windows": {"windows", "win", "left windows", "right windows"},
        "win": {"windows", "win", "left windows", "right windows"},
        "enter": {"enter", "left enter", "right enter", "return"},
        "return": {"enter", "left enter", "right enter", "return"},
    }
    valid = alias_groups.get(required_name, {required_name})
    return any(item in pressed for item in valid)


def _binding_matches_pressed_names(binding_text, pressed_names):
    parts = _binding_parts(binding_text)
    if not parts:
        return False
    return all(_required_binding_part_matches(part, pressed_names) for part in parts)


class _PynputHotkeyStateTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._pressed = set()
        self._listener = None

    def start(self):
        if not PYNPUT_HOTKEY_AVAILABLE:
            return False
        if self._listener is not None:
            return True

        def on_press(key):
            name = canonicalize_pynput_key(key)
            if not name:
                return
            with self._lock:
                self._pressed.add(name)

        def on_release(key):
            name = canonicalize_pynput_key(key)
            if not name:
                return
            with self._lock:
                self._pressed.discard(name)

        listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        self._listener = listener
        return True

    def snapshot_pressed(self):
        with self._lock:
            return set(self._pressed)


def _ensure_pynput_hotkey_state_tracker():
    global _pynput_hotkey_state_tracker
    if not PYNPUT_HOTKEY_AVAILABLE:
        return None
    if _pynput_hotkey_state_tracker is None:
        tracker = _PynputHotkeyStateTracker()
        if tracker.start():
            _pynput_hotkey_state_tracker = tracker
        else:
            return None
    return _pynput_hotkey_state_tracker


def is_hotkey_binding_pressed(binding_text):
    text = normalize_hotkey_text(binding_text)
    if not text:
        return False
    tracker = _ensure_pynput_hotkey_state_tracker()
    if tracker is not None:
        pressed_names = tracker.snapshot_pressed()
        if _binding_matches_pressed_names(text, pressed_names):
            return True
    scan_code_groups = _scan_code_groups_for_binding(text)
    if scan_code_groups and all(group for group in scan_code_groups):
        for group in scan_code_groups:
            pressed = False
            for scan_code in group:
                try:
                    if keyboard.is_pressed(scan_code):
                        pressed = True
                        break
                except Exception:
                    continue
            if not pressed:
                return False
        return True
    for key_name in _hotkey_variants(text):
        try:
            if keyboard.is_pressed(key_name):
                return True
        except Exception:
            continue
    return False


def normalize_manual_action_hotkeys(raw):
    result = dict(DEFAULT_MANUAL_ACTION_HOTKEYS)
    if isinstance(raw, dict):
        for action, binding in raw.items():
            key = str(action or "").strip()
            if key not in DEFAULT_MANUAL_ACTION_HOTKEYS:
                continue
            normalized = normalize_hotkey_text(binding)
            result[key] = normalized
    return result


def normalize_ui_action_hotkeys(raw):
    result = dict(DEFAULT_UI_ACTION_HOTKEYS)
    if isinstance(raw, dict):
        for action, binding in raw.items():
            key = str(action or "").strip()
            if key not in DEFAULT_UI_ACTION_HOTKEYS:
                continue
            result[key] = normalize_hotkey_text(binding)
    return result


def register_ui_action_hotkeys(actions=None, labels=None):
    for action, default_binding in dict(actions or {}).items():
        key = str(action or "").strip()
        if not key:
            continue
        DEFAULT_UI_ACTION_HOTKEYS[key] = normalize_hotkey_text(default_binding)
    for action, label in dict(labels or {}).items():
        key = str(action or "").strip()
        if not key:
            continue
        HOTKEY_ACTION_LABELS[key] = str(label or key)
    return dict(DEFAULT_UI_ACTION_HOTKEYS)


class HotkeyRuntimeService(RuntimeService):
    """Reusable hotkey service facade used by runtime/UI adapters."""

    @property
    def service_id(self) -> str:
        return "runtime.hotkeys"

    @property
    def capabilities(self) -> tuple[RuntimeCapability, ...]:
        return (
            RuntimeCapability(
                id="hotkeys.normalize",
                label="Normalize hotkey text",
                description="Canonicalizes user-facing keyboard shortcut text.",
            ),
            RuntimeCapability(
                id="hotkeys.poll",
                label="Poll hotkey state",
                description="Checks whether a configured keyboard shortcut is currently pressed.",
            ),
        )

    def start(self) -> RuntimeStatus:
        if PYNPUT_HOTKEY_AVAILABLE:
            _ensure_pynput_hotkey_state_tracker()
        return RuntimeStatus(
            ok=True,
            label="Hotkeys",
            metadata={"pynput_available": bool(PYNPUT_HOTKEY_AVAILABLE)},
        )

    def normalize(self, binding: str) -> str:
        return normalize_hotkey_text(binding)

    def is_pressed(self, binding: str) -> bool:
        return is_hotkey_binding_pressed(binding)

    def normalize_manual_bindings(self, raw) -> dict[str, str]:
        return normalize_manual_action_hotkeys(raw)

    def normalize_ui_bindings(self, raw) -> dict[str, str]:
        return normalize_ui_action_hotkeys(raw)
