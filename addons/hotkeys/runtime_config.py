"""Addon-local hotkey defaults and normalized configuration helpers."""

from __future__ import annotations

from collections.abc import Mapping


DEFAULT_PUSH_TO_TALK_HOTKEY = "Right Ctrl"
DEFAULT_MANUAL_ACTION_HOTKEYS = {
    "regenerate_response": "Alt+R",
    "retry_user_input": "Alt+Y",
    "pause_speech": "Alt+P",
    "skip_speech": "Alt+Enter",
    "skip_user_reply": "Alt+U",
}
DEFAULT_UI_ACTION_HOTKEYS = {
    "start_engine": "",
    "stop_engine": "",
    "reset_chat_session": "",
    "clear_console": "",
    "clear_chat": "",
    "show_musetalk_preview": "",
    "toggle_musetalk_avatar_focus": "",
    "show_visual_reply": "",
}
HOTKEY_ACTION_LABELS = {
    "push_to_talk": "Push-to-Talk",
    "regenerate_response": "Regenerate response",
    "retry_user_input": "Retry user input",
    "pause_speech": "Pause or resume speech",
    "skip_speech": "Skip speech",
    "skip_user_reply": "Skip user reply",
    "start_engine": "Start runtime",
    "stop_engine": "Stop runtime",
    "reset_chat_session": "Reset chat session",
    "clear_console": "Clear console",
    "clear_chat": "Clear chat",
    "show_musetalk_preview": "Show MuseTalk Preview",
    "toggle_musetalk_avatar_focus": "Toggle MuseTalk Avatar Focus",
    "show_visual_reply": "Show Visual Reply",
}
HOTKEY_ACTION_DESCRIPTIONS = {
    "push_to_talk": "Hold this key to record speech while input mode is Push-to-Talk.",
    "regenerate_response": "Replace the latest assistant reply using the current chat context.",
    "retry_user_input": "Remove the latest user turn and listen for or accept that input again.",
    "pause_speech": "Pause the current speech playback, or resume it when already paused.",
    "skip_speech": "Stop the current speech playback without removing the accepted reply from chat.",
    "skip_user_reply": "Ask the assistant to continue from the current context without a new visible user message.",
    "start_engine": "Start the companion runtime using the current Host settings.",
    "stop_engine": "Cleanly stop the active companion runtime.",
    "reset_chat_session": "Start a fresh conversation by clearing the active chat context and visible transcript.",
    "clear_console": "Clear only the visible System Console log; the runtime and chat context are unchanged.",
    "clear_chat": "Clear only the visible Chat transcript; the underlying conversation context is unchanged.",
    "show_musetalk_preview": "Show or bring forward the MuseTalk avatar preview window.",
    "toggle_musetalk_avatar_focus": "Toggle keyboard focus behavior for the MuseTalk avatar window.",
    "show_visual_reply": "Show or bring forward the latest Visual Reply window.",
}


def normalize_hotkey_text(value) -> str:
    return " ".join(str(value or "").replace("+", " + ").split()).replace(" + ", "+")


def settings(config):
    raw = config.get("hotkeys", {}) if config is not None else {}
    payload = dict(raw) if isinstance(raw, Mapping) else {}
    push_value = payload.get(
        "push_to_talk",
        config.get("push_to_talk_hotkey", DEFAULT_PUSH_TO_TALK_HOTKEY)
        if config is not None
        else DEFAULT_PUSH_TO_TALK_HOTKEY,
    )
    manual_value = payload.get(
        "manual_actions",
        config.get("manual_action_hotkeys", {}) if config is not None else {},
    )
    ui_value = payload.get(
        "ui_actions",
        config.get("ui_action_hotkeys", {}) if config is not None else {},
    )
    return {
        "push_to_talk": normalize_hotkey_text(push_value)
        or DEFAULT_PUSH_TO_TALK_HOTKEY,
        "manual_actions": _normalized_mapping(manual_value, DEFAULT_MANUAL_ACTION_HOTKEYS),
        "ui_actions": _normalized_mapping(ui_value, DEFAULT_UI_ACTION_HOTKEYS),
    }


def _normalized_mapping(raw, defaults):
    merged = dict(defaults)
    if isinstance(raw, Mapping):
        for action, binding in raw.items():
            action_key = str(action or "").strip()
            if action_key in merged:
                merged[action_key] = normalize_hotkey_text(binding)
    return merged


def push_to_talk(config) -> str:
    return str(settings(config)["push_to_talk"])


def manual_actions(config):
    return dict(settings(config)["manual_actions"])


def ui_actions(config):
    return dict(settings(config)["ui_actions"])
