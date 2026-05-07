"""Grouped shell-preview services extracted from shell_services.py."""

import json
from collections import OrderedDict
from pathlib import Path

from addons.audio_story_mode.shell_preview import AudioStoryShellPreview
from addons.chat_session_player.shell_service import _UiShellChatReplayService


def configure_shell_services_actions_dependencies(namespace):
    globals().update(dict(namespace or {}))


class _UiShellInputActionService:
    """Shell-safe input/runtime-adjacent control facade."""

    AUDIO_STORY_PLAYBACK_MODES = AudioStoryShellPreview.PLAYBACK_MODES
    AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS = AudioStoryShellPreview.DEFAULT_TRANSCRIBE_SECONDS

    def __init__(self, window):
        self._window = window
        self._last_action = ""
        self._push_to_talk_held = False
        self._audio_story = AudioStoryShellPreview(window)

    def _push_to_talk_enabled(self) -> bool:
        session = dict(_read_ui_shell_session_snapshot() or {})
        input_mode = _ui_shell_combo_text_value(self._window, "input_mode_combo", str(session.get("input_mode", "Voice Activation") or "Voice Activation"))
        dry_run_state = str(_ui_shell_dry_run_service(self._window).snapshot().get("state") or "idle").strip().lower()
        return input_mode == "Push-to-Talk" and dry_run_state != "armed"

    def _push_to_talk_hotkey(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        return str(session.get("push_to_talk_hotkey", "Right Ctrl") or "Right Ctrl").strip() or "Right Ctrl"

    def snapshot(self):
        push_enabled = self._push_to_talk_enabled()
        if not push_enabled:
            self._push_to_talk_held = False
        payload = {
            "last_action": self._last_action,
            "push_to_talk_enabled": push_enabled,
            "push_to_talk_held": bool(self._push_to_talk_held and push_enabled),
            "push_to_talk_hotkey": self._push_to_talk_hotkey(),
            "shell_mode": True,
            "message": "Input/runtime-adjacent actions are shell-local previews only.",
            "source": "ui_shell",
        }
        payload.update(self._audio_story.snapshot())
        return payload

    def set_push_to_talk_hold(self, held: bool):
        self._last_action = "push_to_talk_press" if held else "push_to_talk_release"
        if held and not self._push_to_talk_enabled():
            self._push_to_talk_held = False
            payload = self.snapshot()
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Push-to-Talk preview is available only when Input Mode is Push-to-Talk and Dry Run preview is idle.",
            })
            return payload
        self._push_to_talk_held = bool(held) and self._push_to_talk_enabled()
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Push-to-Talk hold preview toggled locally only. No microphone capture started." if held else "Push-to-Talk released in shell preview. No microphone capture was active.",
        })
        return payload

    def set_audio_file_path(self, path: str):
        self._last_action = "set_audio_file_path"
        payload = self._audio_story.set_audio_file_path(path)
        payload.update({"last_action": self._last_action, "shell_mode": True, "source": "ui_shell"})
        return payload

    def request_audio_import(self):
        self._last_action = "request_audio_import"
        payload = self._audio_story.request_audio_import()
        payload.update({"last_action": self._last_action, "shell_mode": True, "source": "ui_shell"})
        return payload

    def request_audio_transcription(self):
        self._last_action = "request_audio_transcription"
        payload = self._audio_story.request_audio_transcription()
        payload.update({"last_action": self._last_action, "shell_mode": True, "source": "ui_shell"})
        return payload

    def play_audio_story(self):
        self._last_action = "play_audio_story"
        payload = self._audio_story.play()
        payload.update({"last_action": self._last_action, "shell_mode": True, "source": "ui_shell"})
        return payload

    def pause_audio_story(self):
        self._last_action = "pause_audio_story"
        payload = self._audio_story.pause()
        payload.update({"last_action": self._last_action, "shell_mode": True, "source": "ui_shell"})
        return payload

    def stop_audio_story(self):
        self._last_action = "stop_audio_story"
        payload = self._audio_story.stop()
        payload.update({"last_action": self._last_action, "shell_mode": True, "source": "ui_shell"})
        return payload

    def seek_audio_story(self, position_percent: int):
        self._last_action = "seek_audio_story"
        payload = self._audio_story.seek(position_percent)
        payload.update({"last_action": self._last_action, "shell_mode": True, "source": "ui_shell"})
        return payload


class _UiShellTutorialService:
    """Shell-safe tutorial browser facade backed only by tutorial JSON files."""

    def __init__(self, window):
        self._window = window
        self._started_tutorial_id = ""

    def _tutorials_dir(self):
        return Path(__file__).resolve().parent / "tutorials"

    def list_tutorials(self):
        items = []
        try:
            for path in sorted(self._tutorials_dir().glob("*.json"), key=lambda item: item.stem.lower()):
                payload = self.load_tutorial(path.stem)
                if not payload:
                    continue
                items.append({
                    "id": str(payload.get("id") or path.stem),
                    "title": str(payload.get("title") or path.stem),
                    "description": str(payload.get("description") or ""),
                    "step_count": len(list(payload.get("steps") or [])),
                })
        except Exception:
            pass
        return items

    def load_tutorial(self, tutorial_id: str):
        key = str(tutorial_id or "").strip()
        if not key:
            return {}
        path = self._tutorials_dir() / f"{key}.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def start_tutorial(self, tutorial_id: str):
        self._started_tutorial_id = str(tutorial_id or "").strip()
        return {
            "started": bool(self._started_tutorial_id),
            "tutorial_id": self._started_tutorial_id,
            "shell_mode": True,
            "message": "Tutorial start is shell-local; no overlay was created.",
            "source": "ui_shell",
        }

    def snapshot(self):
        return {
            "tutorials": self.list_tutorials(),
            "started_tutorial_id": self._started_tutorial_id,
            "shell_mode": True,
            "source": "ui_shell",
        }


class _UiShellDialogService:
    """Shell-only dialog service: report intent without opening native dialogs."""

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def _log(self, message):
        _ui_shell_append_console(self._window, f"[UI Shell] {message}")

    def open_file(self, title: str, start_dir: str = "", file_filter: str = ""):
        self._last_action = "open_file"
        self._log(f"File dialog deferred: {title or 'Open File'}")
        return "", str(file_filter or "")

    def save_file(self, title: str, start_path: str = "", file_filter: str = ""):
        self._last_action = "save_file"
        self._log(f"Save dialog deferred: {title or 'Save File'}")
        return "", str(file_filter or "")

    def open_directory(self, title: str, start_dir: str = ""):
        self._last_action = "open_directory"
        self._log(f"Directory dialog deferred: {title or 'Open Directory'}")
        return ""

    def warning(self, title: str, message: str) -> None:
        self._last_action = "warning"
        self._log(f"Warning deferred: {title or 'Warning'} - {message or ''}")

    def information(self, title: str, message: str) -> None:
        self._last_action = "information"
        self._log(f"Info deferred: {title or 'Information'} - {message or ''}")

    def snapshot(self):
        return {
            "last_action": self._last_action,
            "shell_mode": True,
            "native_dialogs_available": False,
            "source": "ui_shell",
        }
