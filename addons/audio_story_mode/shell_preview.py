from addons.audio_story_mode.session_schema import audio_story_mode_session_value
from ui.designer_loader import ui_shell_find_object
from ui.runtime.shell_addon_reports import _read_ui_shell_session_snapshot
from ui.runtime.shell_session_config import (
    _ui_shell_combo_text_value,
    _ui_shell_format_clock_seconds,
    _ui_shell_line_edit_value,
)


class AudioStoryShellPreview:
    """Shell-safe Audio Story controls without STT, TTS, or media playback side effects."""

    PLAYBACK_MODES = ("Play Imported Audio", "Use TTS Narration")
    DEFAULT_TRANSCRIBE_SECONDS = 8
    PREVIEW_TOTAL_SECONDS = 60

    def __init__(self, window):
        self._window = window
        self._playback_state = "stopped"
        self._seek_percent = 0
        self._last_action = ""

    def _audio_path(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        stored = audio_story_mode_session_value(session, "audio_story_mode_audio_path", "")
        return _ui_shell_line_edit_value(self._window, "audio_file_path_edit", str(stored or ""))

    def _playback_mode(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        stored = str(audio_story_mode_session_value(session, "audio_story_mode_playback_mode", "Play Imported Audio") or "Play Imported Audio")
        return _ui_shell_combo_text_value(self._window, "audio_story_playback_combo", stored) or "Play Imported Audio"

    def _transcribe_seconds(self) -> int:
        session = dict(_read_ui_shell_session_snapshot() or {})
        slider = ui_shell_find_object(self._window, "transcribe_seconds_slider")
        if slider is not None and hasattr(slider, "value"):
            try:
                return max(1, int(slider.value()))
            except Exception:
                pass
        fallback = audio_story_mode_session_value(session, "audio_story_mode_transcribe_seconds", self.DEFAULT_TRANSCRIBE_SECONDS)
        return max(1, int(fallback or self.DEFAULT_TRANSCRIBE_SECONDS))

    def _position_text(self, seek_percent: int) -> str:
        total_seconds = int(self.PREVIEW_TOTAL_SECONDS)
        current_seconds = int(round(total_seconds * max(0, min(100, int(seek_percent or 0))) / 100.0))
        return f"{_ui_shell_format_clock_seconds(current_seconds)} / {_ui_shell_format_clock_seconds(total_seconds)}"

    def snapshot(self):
        audio_path = self._audio_path()
        has_audio = bool(audio_path)
        playback_state = str(self._playback_state or "stopped").strip().lower()
        if playback_state not in {"playing", "paused", "stopped"}:
            playback_state = "stopped"
        if not has_audio:
            playback_state = "stopped"
            self._seek_percent = 0
        seek_widget = ui_shell_find_object(self._window, "audio_story_seek_slider")
        if seek_widget is not None and hasattr(seek_widget, "value"):
            try:
                self._seek_percent = max(0, min(100, int(seek_widget.value())))
            except Exception:
                self._seek_percent = 0
        seek_percent = 0 if not has_audio else max(0, min(100, int(self._seek_percent or 0)))
        return {
            "audio_story_last_action": self._last_action,
            "audio_story_audio_path": audio_path,
            "audio_story_has_audio": has_audio,
            "audio_story_playback_mode": self._playback_mode(),
            "audio_story_transcribe_seconds": self._transcribe_seconds(),
            "audio_story_playback_state": playback_state,
            "audio_story_seek_percent": seek_percent,
            "audio_story_position_text": self._position_text(seek_percent),
        }

    def set_audio_file_path(self, path: str):
        value = str(path or "").strip()
        self._last_action = "set_audio_file_path"
        if not value:
            self._playback_state = "stopped"
            self._seek_percent = 0
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

    def play(self):
        self._last_action = "play_audio_story"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story playback preview needs an audio path first.",
            })
            return payload
        self._playback_state = "playing"
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview started locally only. No media player or TTS narration was started.",
        })
        return payload

    def pause(self):
        self._last_action = "pause_audio_story"
        payload = self.snapshot()
        if payload.get("audio_story_playback_state") != "playing":
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story pause preview is only available while the shell preview is marked as playing.",
            })
            return payload
        self._playback_state = "paused"
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview paused locally only.",
        })
        return payload

    def stop(self):
        self._last_action = "stop_audio_story"
        self._playback_state = "stopped"
        self._seek_percent = 0
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview stopped locally only. No audio runtime was active.",
        })
        return payload

    def seek(self, position_percent: int):
        self._last_action = "seek_audio_story"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story seek preview needs an audio path first.",
            })
            return payload
        self._seek_percent = max(0, min(100, int(position_percent or 0)))
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": f"Audio Story seek preview moved to {payload.get('audio_story_seek_percent', 0)}%.",
        })
        return payload
