"""Controller for the native QML Visual Reply toolbar."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PySide6 import QtCore
from ui.qml_bridge.native_commands import NativeCommandRunner


class VisualReplyToolbarController(QtCore.QObject):
    """Route actions through their owners; file-action returns mean queued.

    Storage work uses the existing bounded worker runner. Audio Story commands
    stay on the UI thread because their owner accesses Qt playback objects and
    schedules generation through its own workers.
    """

    storageReady = QtCore.Signal(QtCore.QUrl)
    stateReady = QtCore.Signal(object)
    busyChanged = QtCore.Signal()

    def __init__(
        self,
        addons: Any,
        notify: Callable[[str, str, str], None],
        refresh: Callable[[], None],
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._addons = addons
        self._notify = notify
        self._refresh = refresh
        self._commands = NativeCommandRunner(self, max_workers=1)
        self._commands.completed.connect(self._completed)
        self._commands.pendingChanged.connect(self.busyChanged.emit)
        self._failure_title = "Visual Reply action failed"
        self._closed = False

    @QtCore.Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return any(key != "runtime.current_state" for key in self._commands.pendingKeys)

    @staticmethod
    def _local_path(url_or_path: str) -> str:
        value = str(url_or_path or "").strip()
        url = QtCore.QUrl(value)
        if url.isLocalFile():
            return url.toLocalFile()
        return str(Path(value).expanduser()) if value else ""

    def _visual_action(
        self,
        capability: str,
        payload: Mapping[str, Any] | None = None,
        *,
        failure_title: str,
    ) -> bool:
        if self._closed or self.busy:
            return False
        self._failure_title = failure_title
        request = dict(payload or {})
        return self._commands.submit(
            capability,
            lambda: self._addons.invoke_addon_capability("nc.visual_reply", capability, request),
        )

    def request_state(self) -> bool:
        """Coalesce polling; enumeration and path checks run on the worker."""
        if self._closed or self.busy:
            return False
        return self._commands.submit("runtime.current_state", self._read_state)

    def _read_state(self) -> dict[str, Any]:
        result = self._addons.invoke_addon_capability("nc.visual_reply", "runtime.current_state", {})
        state = dict(result.value or {}) if result.accepted else {}
        path = str(state.get("image_path") or "").strip()
        state["imageUrl"] = (
            QtCore.QUrl.fromLocalFile(str(Path(path).resolve())).toString()
            if path and Path(path).is_file() else ""
        )
        return state

    @QtCore.Slot(str, bool, object, str)
    def _completed(self, capability: str, accepted: bool, result: Any, error: str) -> None:
        if self._closed:
            return
        if capability == "runtime.current_state":
            if accepted and not self.busy:
                self.stateReady.emit(result)
            return
        if not accepted or not getattr(result, "accepted", False):
            message = error or str(
                getattr(getattr(result, "failure", None), "message", "")
                or "Visual Reply is unavailable."
            )
            self._notify("error", self._failure_title, message)
            return
        value = result.value
        if capability == "runtime.ensure_storage":
            if value:
                self.storageReady.emit(QtCore.QUrl.fromLocalFile(str(value)))
            else:
                self._notify("warning", self._failure_title, "Visual Reply storage is unavailable.")
        elif value or capability == "runtime.delete_all_images":
            self._refresh()
        else:
            self._notify("warning", self._failure_title, "The image may be missing, unreadable, or no longer available.")

    def close(self) -> None:
        self._closed = True
        self._commands.close()

    def load_image(self, url_or_path: str) -> bool:
        path = self._local_path(url_or_path)
        return self._visual_action(
            "runtime.load_image",
            {"image_path": path},
            failure_title="Image was not loaded",
        )

    def prepare_storage(self) -> bool:
        return self._visual_action(
            "runtime.ensure_storage",
            failure_title="Visual Reply folder is unavailable",
        )

    def navigate(self, offset: int) -> bool:
        return self._visual_action(
            "runtime.navigate_storage",
            {"offset": int(offset)},
            failure_title="Visual Reply history is unavailable",
        )

    def set_caption(self, caption: str) -> bool:
        return self._visual_action(
            "runtime.set_caption",
            {"caption": str(caption or "")},
            failure_title="Caption was not changed",
        )

    def delete_current(self, expected_path: str | None = None) -> bool:
        return self._visual_action(
            "runtime.delete_current_image",
            {"expected_path": expected_path},
            failure_title="Image was not deleted",
        )

    def delete_all(self) -> bool:
        return self._visual_action(
            "runtime.delete_all_images",
            failure_title="Images were not deleted",
        )

    def clear(self) -> bool:
        return self._visual_action("runtime.clear_state", failure_title="Visual Reply was not cleared")

    def _story_action(self, capability: str, success_title: str) -> bool:
        if self._closed or self.busy:
            return False
        result = self._addons.invoke_addon_capability(
            "nc.audio_story_mode", capability, {"source": "visual_reply"}
        )
        payload = dict(result.value or {}) if result.accepted and isinstance(result.value, Mapping) else {}
        if not result.accepted or not bool(payload.get("ok")):
            message = str(
                payload.get("message")
                or getattr(getattr(result, "failure", None), "message", "")
                or "No audio story is loaded."
            )
            self._notify("warning", "Audio Story action unavailable", message)
            return False
        self._notify("success", success_title, str(payload.get("message") or "The request was accepted."))
        self._refresh()
        return True

    def load_current_story_image(self) -> bool:
        return self._story_action(
            "audio_story_mode.load_current_image", "Story image requested"
        )

    def use_current_image_style(self) -> bool:
        return self._story_action(
            "audio_story_mode.refresh_master_style_anchor",
            "Image style refresh requested",
        )
