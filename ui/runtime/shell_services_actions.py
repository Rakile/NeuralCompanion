"""Grouped shell-preview services extracted from shell_services.py."""

import json
from collections import OrderedDict
from pathlib import Path


def configure_shell_services_actions_dependencies(namespace):
    globals().update(dict(namespace or {}))


class _UiShellInputActionService:
    """Shell-safe input/runtime-adjacent control facade."""

    AUDIO_STORY_PLAYBACK_MODES = ("Play Imported Audio", "Use TTS Narration")
    AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS = 8
    AUDIO_STORY_PREVIEW_TOTAL_SECONDS = 60

    def __init__(self, window):
        self._window = window
        self._last_action = ""
        self._push_to_talk_held = False
        self._audio_story_playback_state = "stopped"
        self._audio_story_seek_percent = 0

    def _audio_story_path(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        return _ui_shell_line_edit_value(self._window, "audio_file_path_edit", str(session.get("audio_story_mode_audio_path", "") or ""))

    def _audio_story_playback_mode(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        stored = str(session.get("audio_story_mode_playback_mode", "Play Imported Audio") or "Play Imported Audio")
        return _ui_shell_combo_text_value(self._window, "audio_story_playback_combo", stored) or "Play Imported Audio"

    def _audio_story_transcribe_seconds(self) -> int:
        session = dict(_read_ui_shell_session_snapshot() or {})
        slider = _ui_shell_find_object(self._window, "transcribe_seconds_slider")
        if slider is not None and hasattr(slider, "value"):
            try:
                return max(1, int(slider.value()))
            except Exception:
                pass
        return max(1, int(session.get("audio_story_mode_transcribe_seconds", self.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS) or self.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS))

    def _push_to_talk_enabled(self) -> bool:
        session = dict(_read_ui_shell_session_snapshot() or {})
        input_mode = _ui_shell_combo_text_value(self._window, "input_mode_combo", str(session.get("input_mode", "Voice Activation") or "Voice Activation"))
        dry_run_state = str(_ui_shell_dry_run_service(self._window).snapshot().get("state") or "idle").strip().lower()
        return input_mode == "Push-to-Talk" and dry_run_state != "armed"

    def _push_to_talk_hotkey(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        return str(session.get("push_to_talk_hotkey", "Right Ctrl") or "Right Ctrl").strip() or "Right Ctrl"

    def _position_text(self, seek_percent: int) -> str:
        total_seconds = int(self.AUDIO_STORY_PREVIEW_TOTAL_SECONDS)
        current_seconds = int(round(total_seconds * max(0, min(100, int(seek_percent or 0))) / 100.0))
        return f"{_ui_shell_format_clock_seconds(current_seconds)} / {_ui_shell_format_clock_seconds(total_seconds)}"

    def snapshot(self):
        push_enabled = self._push_to_talk_enabled()
        if not push_enabled:
            self._push_to_talk_held = False
        audio_path = self._audio_story_path()
        has_audio = bool(audio_path)
        playback_state = str(self._audio_story_playback_state or "stopped").strip().lower()
        if playback_state not in {"playing", "paused", "stopped"}:
            playback_state = "stopped"
        if not has_audio:
            playback_state = "stopped"
            self._audio_story_seek_percent = 0
        seek_widget = _ui_shell_find_object(self._window, "audio_story_seek_slider")
        if seek_widget is not None and hasattr(seek_widget, "value"):
            try:
                self._audio_story_seek_percent = max(0, min(100, int(seek_widget.value())))
            except Exception:
                self._audio_story_seek_percent = 0
        seek_percent = 0 if not has_audio else max(0, min(100, int(self._audio_story_seek_percent or 0)))
        return {
            "last_action": self._last_action,
            "push_to_talk_enabled": push_enabled,
            "push_to_talk_held": bool(self._push_to_talk_held and push_enabled),
            "push_to_talk_hotkey": self._push_to_talk_hotkey(),
            "audio_story_audio_path": audio_path,
            "audio_story_has_audio": has_audio,
            "audio_story_playback_mode": self._audio_story_playback_mode(),
            "audio_story_transcribe_seconds": self._audio_story_transcribe_seconds(),
            "audio_story_playback_state": playback_state,
            "audio_story_seek_percent": seek_percent,
            "audio_story_position_text": self._position_text(seek_percent),
            "shell_mode": True,
            "message": "Input/runtime-adjacent actions are shell-local previews only.",
            "source": "ui_shell",
        }

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
        value = str(path or "").strip()
        self._last_action = "set_audio_file_path"
        if not value:
            self._audio_story_playback_state = "stopped"
            self._audio_story_seek_percent = 0
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "audio_story_audio_path": value,
            "message": "Audio Story preview path updated locally only." if value else "Audio Story preview path cleared.",
        })
        return payload

    def request_audio_import(self):
        self._last_action = "request_audio_import"
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Audio import dialog is deferred in shell preview. Paste a local audio path into the field to preview this surface.",
        })
        return payload

    def request_audio_transcription(self):
        self._last_action = "request_audio_transcription"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Transcription preview needs an audio path first. No Whisper/STT runtime was started.",
            })
            return payload
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Audio transcription remains deferred in shell preview. No Whisper/STT runtime was started.",
        })
        return payload

    def play_audio_story(self):
        self._last_action = "play_audio_story"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story playback preview needs an audio path first.",
            })
            return payload
        self._audio_story_playback_state = "playing"
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview started locally only. No media player or TTS narration was started.",
        })
        return payload

    def pause_audio_story(self):
        self._last_action = "pause_audio_story"
        payload = self.snapshot()
        if payload.get("audio_story_playback_state") != "playing":
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story pause preview is only available while the shell preview is marked as playing.",
            })
            return payload
        self._audio_story_playback_state = "paused"
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview paused locally only.",
        })
        return payload

    def stop_audio_story(self):
        self._last_action = "stop_audio_story"
        self._audio_story_playback_state = "stopped"
        self._audio_story_seek_percent = 0
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview stopped locally only. No audio runtime was active.",
        })
        return payload

    def seek_audio_story(self, position_percent: int):
        self._last_action = "seek_audio_story"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story seek preview needs an audio path first.",
            })
            return payload
        self._audio_story_seek_percent = max(0, min(100, int(position_percent or 0)))
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": f"Audio Story seek preview moved to {payload.get('audio_story_seek_percent', 0)}%.",
        })
        return payload


class _UiShellChatReplayService:
    """Shell-safe replay facade for Chat Player and related addons."""

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def snapshot_chat_session(self):
        return {
            "conversation_history": [],
            "shell_mode": True,
            "message": "Chat replay is not connected in shell preview.",
        }

    def replayable_assistant_entries(self):
        return []

    def replayable_assistant_messages(self):
        return []

    def is_engine_running(self) -> bool:
        return False

    def is_offline_replay_only(self) -> bool:
        return False

    def trigger_control_action(self, action: str) -> None:
        self._last_action = str(action or "").strip()

    def replay_latest_reply(self) -> None:
        self._last_action = "replay_latest_reply"

    def replay_chat_session(self) -> None:
        self._last_action = "replay_chat_session"

    def replay_chat_session_from_index(self, start_index: int) -> None:
        self._last_action = f"replay_chat_session_from_index:{int(start_index or 0)}"

    def load_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).load_chat_context()

    def quick_load_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).quick_load_chat_context()

    def save_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).save_chat_context()

    def quick_save_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).quick_save_chat_context()


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
