"""Small GUI-thread projection of the sensory service's image fallback status."""
from PySide6 import QtCore


class SensoryImageStatusController(QtCore.QObject):
    changed = QtCore.Signal()
    notificationRaised = QtCore.Signal(str, str, str)

    def __init__(self, application, parent=None):
        super().__init__(parent)
        self._sensory = application.sensory
        self._state = {}
        self._last_notice = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    @QtCore.Property("QVariantMap", notify=changed)
    def state(self):
        return dict(self._state)

    @QtCore.Slot()
    def refresh(self):
        status = self._sensory.image_fallback_status()
        source = str(status.get("source", "Sensory"))
        remaining = int(status.get("remaining_seconds", 0))
        pending = status.get("phase") == "retry_pending"
        timing = ("The wait has been cleared. Images will be tried at the next eligible check-in "
                  "with an image-capable model; ongoing replies are not interrupted."
                  if pending else f"Images will be retried in {remaining // 60}:{remaining % 60:02d}. "
                                  "Sensory requests use text only during this pause.")
        state = {
            "active": bool(status.get("active")),
            "title": "Sensory images awaiting retry" if pending else "Sensory images temporarily paused",
            "message": f"Source: {source}. {status.get('reason', '')} {timing}",
            "canRetry": bool(status.get("active")) and not pending,
        }
        if state != self._state:
            self._state = state
            self.changed.emit()
        notice = status.get("notice", {})
        notice_id = int(notice.get("id", 0))
        if notice_id > self._last_notice:
            self._last_notice = notice_id
            if notice.get("kind") == "paused":
                self.notificationRaised.emit("warning", state["title"], state["message"])
            elif notice.get("kind") == "recovered":
                self.notificationRaised.emit("success", "Sensory images restored",
                                             f"Source: {source}. An image-bearing request succeeded.")

    @QtCore.Slot()
    def retryImages(self):
        result = self._sensory.retry_images()
        if not result.accepted:
            self.notificationRaised.emit("error", "Could not clear the sensory image wait",
                                         "Try again after the current operation finishes.")
        self.refresh()

    def close(self):
        self._timer.stop()
