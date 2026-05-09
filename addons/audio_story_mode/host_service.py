from __future__ import annotations

from PySide6 import QtCore


class QtAudioStoryActionService:
    PREVIEW_TOTAL_SECONDS = 60

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def _widget(self, name: str):
        widget = getattr(self._window, str(name), None)
        if widget is not None:
            return widget
        if hasattr(self._window, "findChild"):
            try:
                return self._window.findChild(QtCore.QObject, str(name))
            except Exception:
                return None
        return None

    def _combo_text(self, name: str, default: str = "") -> str:
        widget = self._widget(name)
        if widget is not None and hasattr(widget, "currentText"):
            try:
                text = str(widget.currentText() or "").strip()
                if text:
                    return text
            except Exception:
                pass
        return str(default or "").strip()

    def _line_value(self, name: str, default: str = "") -> str:
        widget = self._widget(name)
        if widget is not None and hasattr(widget, "text"):
            try:
                return str(widget.text() or "").strip()
            except Exception:
                pass
        return str(default or "").strip()

    def _slider_value(self, name: str, default: int = 0) -> int:
        widget = self._widget(name)
        if widget is not None and hasattr(widget, "value"):
            try:
                return int(widget.value())
            except Exception:
                pass
        return int(default)

    def _format_clock_seconds(self, seconds: int) -> str:
        total = max(0, int(seconds or 0))
        minutes, secs = divmod(total, 60)
        return f"{minutes:02d}:{secs:02d}"

    def snapshot(self):
        audio_path = self._line_value("audio_file_path_edit", "")
        seek_percent = max(0, min(100, self._slider_value("audio_story_seek_slider", 0)))
        total_seconds = int(self.PREVIEW_TOTAL_SECONDS)
        current_seconds = int(round(total_seconds * seek_percent / 100.0))
        return {
            "last_action": self._last_action,
            "audio_story_audio_path": audio_path,
            "audio_story_has_audio": bool(audio_path),
            "audio_story_playback_mode": self._combo_text("audio_story_playback_combo", "Play Imported Audio"),
            "audio_story_transcribe_seconds": max(1, self._slider_value("transcribe_seconds_slider", 8)),
            "audio_story_playback_state": "unavailable",
            "audio_story_seek_percent": seek_percent,
            "audio_story_position_text": f"{self._format_clock_seconds(current_seconds)} / {self._format_clock_seconds(total_seconds)}",
            "shell_mode": False,
            "audio_story_runtime_available": self._widget("transcribe_audio_button") is not None,
            "message": "Audio Story actions are available when the owning UI/runtime exists.",
            "source": "qt_app",
        }

    def set_audio_file_path(self, path: str):
        self._last_action = "set_audio_file_path"
        widget = self._widget("audio_file_path_edit")
        accepted = False
        if widget is not None and hasattr(widget, "setText"):
            try:
                widget.setText(str(path or "").strip())
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio Story path updated." if accepted else "Audio Story path field is unavailable in this UI mode.",
        })
        return payload

    def request_audio_import(self):
        self._last_action = "request_audio_import"
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Audio import remains owned by the runtime Audio Story surface.",
        })
        return payload

    def request_audio_transcription(self):
        self._last_action = "request_audio_transcription"
        button = self._widget("transcribe_audio_button")
        accepted = False
        if button is not None and hasattr(button, "click"):
            try:
                button.click()
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio transcription requested." if accepted else "Audio transcription is unavailable in this UI mode.",
        })
        return payload

    def play_audio_story(self):
        return self._click_audio_story_button("play_audio_story", "audio_story_play_button", "play")

    def pause_audio_story(self):
        return self._click_audio_story_button("pause_audio_story", "audio_story_pause_button", "pause")

    def stop_audio_story(self):
        return self._click_audio_story_button("stop_audio_story", "audio_story_stop_button", "stop")

    def _click_audio_story_button(self, action: str, button_name: str, verb: str):
        self._last_action = action
        button = self._widget(button_name)
        accepted = False
        if button is not None and hasattr(button, "click"):
            try:
                button.click()
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": f"Audio Story {verb} requested." if accepted else f"Audio Story {verb} is unavailable in this UI mode.",
        })
        return payload

    def seek_audio_story(self, position_percent: int):
        self._last_action = "seek_audio_story"
        slider = self._widget("audio_story_seek_slider")
        accepted = False
        if slider is not None and hasattr(slider, "setValue"):
            try:
                slider.setValue(max(0, min(100, int(position_percent or 0))))
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio Story seek updated." if accepted else "Audio Story seek is unavailable in this UI mode.",
        })
        return payload
