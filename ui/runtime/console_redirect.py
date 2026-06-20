"""Console and chat stream redirection helpers for the Qt UI."""

import re

from PySide6 import QtCore

from core import crash_diagnostics


class QtConsoleBridge(QtCore.QObject):
    text_ready = QtCore.Signal(str)
    chat_ready = QtCore.Signal(str)
    status_ready = QtCore.Signal(int, int)
    chat_status_ready = QtCore.Signal(int, int)
    rebuild_chat_ready = QtCore.Signal()


class QtTextRedirector:
    _ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    _CHAT_REBUILD_SENTINEL = "[[CHAT_REBUILD]]"

    def __init__(self, bridge, mirror_stream=None):
        self.bridge = bridge
        self.mirror_stream = mirror_stream
        self.line_count = 0
        self.chat_line_count = 0
        self._chat_buffer = ""
        self._line_buffer = ""
        self._discard_line = False
        self._progress_patterns = [
            re.compile(r"^\s*Fetching \d+ files:"),
            re.compile(r"^\s*\d+%[\|#]"),
            re.compile(r"^\s*\d+%\|"),
            re.compile(r"^\s*\|\s*\d+/\d+"),
            re.compile(r"^\s*\d+/\d+\s*\["),
        ]

    def _should_skip_line(self, line):
        stripped = self._ANSI_ESCAPE_RE.sub("", str(line or "")).replace("\r", "").strip()
        if not stripped:
            return False
        if "Reference mel length is not equal to 2 * reference token length." in stripped:
            return True
        if any(pattern.search(stripped) for pattern in self._progress_patterns):
            return True
        if "it/s" in stripped and (re.search(r"\b\d+/\d+\b", stripped) or "%|" in stripped or "#|" in stripped):
            return True
        return False

    def _emit_text(self, value):
        if not value:
            return
        crash_diagnostics.record_console_text(value)
        self.bridge.text_ready.emit(value)
        self.line_count += value.count("\n") or 1
        self.bridge.status_ready.emit(self.line_count, 1)
        if self.mirror_stream:
            try:
                self.mirror_stream.write(value)
            except Exception:
                pass

    def write(self, value):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        elif not isinstance(value, str):
            value = str(value)
        if not value:
            return
        if self._CHAT_REBUILD_SENTINEL in value:
            self.bridge.rebuild_chat_ready.emit()
            value = value.replace(self._CHAT_REBUILD_SENTINEL, "")
        if not value:
            return
        if re.search(r"💬 You(?: \([^)]*\))?:|🤖 Assistant:", value):
            self._append_chat_stream(value)
        parts = re.split(r"(\r|\n)", value)
        for part in parts:
            if part in {"\r", "\n"}:
                line = self._line_buffer
                self._line_buffer = ""
                should_emit = (not self._discard_line) and (not self._should_skip_line(line))
                self._discard_line = False
                if should_emit:
                    self._emit_text(line + "\n")
                continue
            if self._discard_line:
                continue
            self._line_buffer += part
            if self._should_skip_line(self._line_buffer):
                self._line_buffer = ""
                self._discard_line = True

    def flush(self):
        if self._line_buffer and not self._discard_line and not self._should_skip_line(self._line_buffer):
            self._emit_text(self._line_buffer)
        self._line_buffer = ""
        self._discard_line = False
        if self.mirror_stream:
            try:
                self.mirror_stream.flush()
            except Exception:
                pass

    def close(self):
        # Some third-party logging handlers call close() on the active stream
        # during interpreter shutdown. Flush pending text, but do not close the
        # mirrored stdio stream owned by Python/Codex.
        try:
            self.flush()
        except Exception:
            pass

    def _append_chat_stream(self, value):
        self._chat_buffer += value
        normalized = re.sub(r"(?<!\n)(💬 You(?: \([^)]*\))?:|🤖 Assistant:)", r"\n\1", self._chat_buffer)
        if normalized.startswith("\n"):
            normalized = normalized[1:]
        self._chat_buffer = ""
        self.bridge.chat_ready.emit(normalized)
        emitted_lines = sum(1 for line in normalized.splitlines() if line.strip())
        self.chat_line_count += emitted_lines or 1
        self.bridge.chat_status_ready.emit(self.chat_line_count, 1)
