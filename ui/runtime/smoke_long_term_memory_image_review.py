from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtCore, QtGui, QtWidgets

from ui.runtime.long_term_memory_image_review import (
    LongTermMemoryImageReviewDialog,
    ManualImageReviewCoordinator,
)


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Panel:
    def __init__(self, original_path: str):
        self.current_image_path = original_path
        self.current_caption = "Original caption"
        self.preview_zoom_factor = 1.75
        self.status_label = QtWidgets.QLabel("Original status")
        self.placeholder = QtWidgets.QLabel("Original detail")
        self.previewed = []

    def show_image(self, path, status_text="", caption=""):
        self.previewed.append(path)
        self.current_image_path = path
        self.current_caption = caption
        self.status_label.setText(status_text)
        return True

    def clear_visual_reply(self, status_text="", detail_text=""):
        self.current_image_path = ""
        self.current_caption = ""
        self.status_label.setText(status_text)
        self.placeholder.setText(detail_text)

    def set_caption(self, caption=""):
        self.current_caption = caption

    def reset_zoom(self):
        self.preview_zoom_factor = 1.0


class _Host(QtWidgets.QMainWindow):
    def __init__(self, original_path: str):
        super().__init__()
        self.visual_reply_panel = _Panel(original_path)
        self.visual_reply_dock = QtWidgets.QDockWidget("Visual Reply", self)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.visual_reply_dock)
        self.visual_reply_dock.hide()


def _payload(blob: bytes):
    return {
        "candidates": [
            {
                "asset_id": "asset_one",
                "role": "user",
                "origin": "user_attachment",
                "source": "memory messages 1-4",
                "source_message_index": 1,
                "visualization_prompt": "First image",
                "mime_type": "image/png",
                "blob": blob,
            },
            {
                "asset_id": "asset_two",
                "role": "assistant",
                "origin": "assistant_visual_reply",
                "source": "memory messages 1-4",
                "source_message_index": 2,
                "visualization_prompt": "Second image",
                "mime_type": "image/png",
                "blob": blob,
            },
        ],
        "selected_asset_ids": ["asset_two"],
        "decision_action": "memory_only",
        "request_kind": "prior_image",
        "decision_reason": "Second image matched.",
    }


def _png_bytes() -> bytes:
    image = QtGui.QImage(16, 16, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#3aa7ff"))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_dialog_has_explicit_actions_and_separates_preview_from_selection():
    _app()
    dialog = LongTermMemoryImageReviewDialog(_payload(_png_bytes()))
    assert not bool(dialog.windowFlags() & QtCore.Qt.WindowCloseButtonHint)
    assert dialog.selected_asset_ids() == ["asset_two"]
    assert dialog.continue_button.text() == "Continue with 1 image"

    dialog.candidate_cards[0].thumbnail.click()
    assert dialog.selected_asset_ids() == ["asset_two"]
    assert dialog.focused_asset_id == "asset_one"

    dialog.candidate_cards[0].checkbox.setChecked(True)
    assert dialog.selected_asset_ids() == ["asset_one", "asset_two"]
    assert dialog.continue_button.text() == "Continue with 2 images"
    dialog.deleteLater()


def test_coordinator_unblocks_worker_and_restores_visual_reply_after_continue():
    app = _app()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        original = Path(temp_dir) / "original.png"
        original.write_bytes(_png_bytes())
        host = _Host(str(original))
        coordinator = ManualImageReviewCoordinator(host)
        result = {}

        worker = threading.Thread(
            target=lambda: result.update(coordinator.review(_payload(_png_bytes()))),
            daemon=True,
        )
        worker.start()
        for _ in range(100):
            app.processEvents()
            if coordinator.dialog is not None:
                break
            QtCore.QThread.msleep(5)
        assert coordinator.dialog is not None

        coordinator.dialog.candidate_cards[0].thumbnail.click()
        app.processEvents()
        assert host.visual_reply_panel.current_image_path != str(original)
        coordinator.dialog.continue_button.click()
        for _ in range(100):
            app.processEvents()
            if not worker.is_alive():
                break
            QtCore.QThread.msleep(5)
        worker.join(timeout=1.0)

        assert result == {"cancelled": False, "asset_ids": ["asset_two"]}
        assert host.visual_reply_panel.current_image_path == str(original)
        assert host.visual_reply_panel.current_caption == "Original caption"
        assert host.visual_reply_panel.preview_zoom_factor == 1.75
        assert not host.visual_reply_dock.isVisible()
        coordinator.shutdown()
        host.deleteLater()


def test_cancel_reply_unblocks_worker_with_cancelled_result():
    app = _app()
    host = _Host("")
    coordinator = ManualImageReviewCoordinator(host)
    result = {}
    worker = threading.Thread(
        target=lambda: result.update(coordinator.review(_payload(_png_bytes()))),
        daemon=True,
    )
    worker.start()
    for _ in range(100):
        app.processEvents()
        if coordinator.dialog is not None:
            break
        QtCore.QThread.msleep(5)
    assert coordinator.dialog is not None
    coordinator.dialog.cancel_button.click()
    for _ in range(100):
        app.processEvents()
        if not worker.is_alive():
            break
        QtCore.QThread.msleep(5)
    worker.join(timeout=1.0)
    assert result == {"cancelled": True, "asset_ids": []}
    coordinator.shutdown()
    host.deleteLater()


def test_dialog_setup_failure_cancels_and_unblocks_worker():
    app = _app()
    host = _Host("")
    coordinator = ManualImageReviewCoordinator(host)
    coordinator._materialize_candidates = lambda _payload: (_ for _ in ()).throw(
        RuntimeError("preview setup failed")
    )
    result = {}
    worker = threading.Thread(
        target=lambda: result.update(coordinator.review(_payload(_png_bytes()))),
        daemon=True,
    )
    worker.start()
    for _ in range(100):
        app.processEvents()
        if not worker.is_alive():
            break
        QtCore.QThread.msleep(5)
    worker.join(timeout=1.0)
    assert result == {"cancelled": True, "asset_ids": []}
    coordinator.shutdown()
    host.deleteLater()


def main() -> int:
    test_dialog_has_explicit_actions_and_separates_preview_from_selection()
    test_coordinator_unblocks_worker_and_restores_visual_reply_after_continue()
    test_cancel_reply_unblocks_worker_with_cancelled_result()
    test_dialog_setup_failure_cancels_and_unblocks_worker()
    print("long term memory image review Qt smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
