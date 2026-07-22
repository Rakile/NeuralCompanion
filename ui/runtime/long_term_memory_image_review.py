"""Qt coordinator for optional Long-Term Memory recalled-image review."""

from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


def _candidate_suffix(candidate) -> str:
    mime_type = str((candidate or {}).get("mime_type", "") or "").strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/gif": ".gif",
    }.get(mime_type, ".img")


class _CandidateCard(QtWidgets.QFrame):
    previewRequested = QtCore.Signal(str)

    def __init__(self, candidate, image_path, *, selected=False, parent=None):
        super().__init__(parent)
        self.candidate = dict(candidate or {})
        self.asset_id = str(self.candidate.get("asset_id", "") or "").strip()
        self.setObjectName("memory_image_candidate_card")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame#memory_image_candidate_card { border: 1px solid #30465f; border-radius: 6px; }"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumbnail = QtWidgets.QToolButton(self)
        self.thumbnail.setObjectName(f"memory_image_thumbnail_{self.asset_id}")
        self.thumbnail.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.thumbnail.setIconSize(QtCore.QSize(176, 132))
        self.thumbnail.setFixedSize(190, 146)
        self.thumbnail.setToolTip("Preview this candidate in Visual Reply")
        pixmap = QtGui.QPixmap(str(image_path or ""))
        if not pixmap.isNull():
            self.thumbnail.setIcon(
                QtGui.QIcon(
                    pixmap.scaled(
                        176,
                        132,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                )
            )
        else:
            self.thumbnail.setText("Image unavailable")
            self.thumbnail.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.thumbnail.clicked.connect(lambda: self.previewRequested.emit(self.asset_id))
        layout.addWidget(self.thumbnail, 0, QtCore.Qt.AlignHCenter)

        self.checkbox = QtWidgets.QCheckBox("Attach to this request", self)
        self.checkbox.setChecked(bool(selected))
        layout.addWidget(self.checkbox)

        role = str(self.candidate.get("role", "") or "unknown").strip()
        source = str(self.candidate.get("source", "") or "").strip()
        source_index = self.candidate.get("source_message_index")
        origin = str(self.candidate.get("origin", "") or "").strip()
        details = QtWidgets.QLabel(
            f"{role.title()} image | {origin or 'unknown origin'}\n"
            f"{source or 'unknown source'} | message {source_index if source_index is not None else '?'}",
            self,
        )
        details.setWordWrap(True)
        details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(details)

        prompt = str(self.candidate.get("visualization_prompt", "") or "").strip()
        if prompt:
            prompt_label = QtWidgets.QLabel(f"Prompt: {prompt}", self)
            prompt_label.setWordWrap(True)
            prompt_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            layout.addWidget(prompt_label)


class LongTermMemoryImageReviewDialog(QtWidgets.QDialog):
    completed = QtCore.Signal(bool, object)
    previewRequested = QtCore.Signal(str)

    def __init__(self, payload, *, image_paths=None, parent=None):
        super().__init__(parent)
        self.payload = dict(payload or {})
        self.image_paths = dict(image_paths or {})
        self.candidate_cards = []
        self.focused_asset_id = ""
        self._force_closing = False
        self.setObjectName("long_term_memory_image_review_dialog")
        self.setWindowTitle("Review Recalled Images")
        self.setWindowFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.CustomizeWindowHint
            | QtCore.Qt.WindowTitleHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setMinimumSize(720, 520)
        self.resize(940, 680)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        title = QtWidgets.QLabel("Long-Term Memory image candidates", self)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(title)

        decision = str(self.payload.get("decision_action", "no_images") or "no_images")
        request_kind = str(self.payload.get("request_kind", "none") or "none")
        reason = str(self.payload.get("decision_reason", "") or "").strip()
        decision_label = QtWidgets.QLabel(
            f"LLM decision: {decision} | request: {request_kind}\n{reason}",
            self,
        )
        decision_label.setWordWrap(True)
        decision_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(decision_label)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget(scroll)
        self.grid = QtWidgets.QGridLayout(scroll_content)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        selected_ids = {
            str(item or "").strip()
            for item in list(self.payload.get("selected_asset_ids") or [])
            if str(item or "").strip()
        }
        for index, candidate in enumerate(list(self.payload.get("candidates") or [])):
            asset_id = str((candidate or {}).get("asset_id", "") or "").strip()
            card = _CandidateCard(
                candidate,
                self.image_paths.get(asset_id, ""),
                selected=asset_id in selected_ids,
                parent=scroll_content,
            )
            card.previewRequested.connect(self._on_preview_requested)
            card.checkbox.toggled.connect(self._refresh_continue_label)
            self.candidate_cards.append(card)
            self.grid.addWidget(card, index // 3, index % 3, QtCore.Qt.AlignTop)
        self.grid.setRowStretch(max(1, (len(self.candidate_cards) + 2) // 3), 1)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, 1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QtWidgets.QPushButton("Cancel reply", self)
        self.continue_button = QtWidgets.QPushButton(self)
        self.continue_button.setDefault(True)
        self.cancel_button.clicked.connect(lambda: self.completed.emit(True, []))
        self.continue_button.clicked.connect(
            lambda: self.completed.emit(False, self.selected_asset_ids())
        )
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.continue_button)
        root.addLayout(button_row)
        self._refresh_continue_label()

    def selected_asset_ids(self):
        return [card.asset_id for card in self.candidate_cards if card.checkbox.isChecked()]

    def _refresh_continue_label(self, *_args):
        count = len(self.selected_asset_ids())
        if count == 0:
            text = "Continue without images"
        elif count == 1:
            text = "Continue with 1 image"
        else:
            text = f"Continue with {count} images"
        self.continue_button.setText(text)

    def _on_preview_requested(self, asset_id):
        self.focused_asset_id = str(asset_id or "")
        self.previewRequested.emit(self.focused_asset_id)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def reject(self):
        if self._force_closing:
            super().reject()

    def closeEvent(self, event):
        if self._force_closing:
            event.accept()
        else:
            event.ignore()

    def force_close(self):
        self._force_closing = True
        self.close()


@dataclass
class _PendingReview:
    payload: dict
    event: threading.Event = field(default_factory=threading.Event)
    result: dict = field(default_factory=lambda: {"cancelled": True, "asset_ids": []})


class ManualImageReviewCoordinator(QtCore.QObject):
    reviewRequested = QtCore.Signal(object)

    def __init__(self, host_window):
        super().__init__(host_window)
        self.host_window = host_window
        self.dialog = None
        self._pending = None
        self._pending_lock = threading.Lock()
        self._shutdown = False
        self._temp_dir = None
        self._candidate_paths = {}
        self._visual_snapshot = None
        self.reviewRequested.connect(self._show_review, QtCore.Qt.QueuedConnection)

    def review(self, payload):
        if self._shutdown:
            return {"cancelled": True, "asset_ids": []}
        if QtCore.QThread.currentThread() == self.thread():
            return {
                "cancelled": False,
                "asset_ids": list((payload or {}).get("selected_asset_ids") or []),
            }
        pending = _PendingReview(dict(payload or {}))
        with self._pending_lock:
            if self._pending is not None:
                return {"cancelled": True, "asset_ids": []}
            self._pending = pending
        self.reviewRequested.emit(pending)
        pending.event.wait()
        return dict(pending.result)

    @QtCore.Slot(object)
    def _show_review(self, pending):
        if self._shutdown or pending is not self._pending:
            pending.event.set()
            return
        try:
            self._visual_snapshot = self._snapshot_visual_reply()
            self._candidate_paths = self._materialize_candidates(pending.payload)
            self.dialog = LongTermMemoryImageReviewDialog(
                pending.payload,
                image_paths=self._candidate_paths,
                parent=self.host_window,
            )
            self.dialog.previewRequested.connect(self._preview_candidate)
            self.dialog.completed.connect(self._complete_review)
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
        except Exception as exc:
            print(f"⚠️ [Memory] Could not open manual image review: {exc}")
            self._complete_review(True, [])

    def _materialize_candidates(self, payload):
        self._temp_dir = tempfile.TemporaryDirectory(prefix="nc-memory-image-review-")
        paths = {}
        for candidate in list((payload or {}).get("candidates") or []):
            asset_id = str((candidate or {}).get("asset_id", "") or "").strip()
            metadata = dict((candidate or {}).get("metadata") or {})
            link_metadata = dict((candidate or {}).get("link_metadata") or {})
            original_path = str(
                link_metadata.get("original_path") or metadata.get("original_path") or ""
            ).strip()
            if original_path and Path(original_path).is_file():
                paths[asset_id] = original_path
                continue
            blob = bytes((candidate or {}).get("blob") or b"")
            if not asset_id or not blob:
                continue
            target = Path(self._temp_dir.name) / f"{asset_id}{_candidate_suffix(candidate)}"
            target.write_bytes(blob)
            paths[asset_id] = str(target)
        return paths

    def _snapshot_visual_reply(self):
        panel = getattr(self.host_window, "visual_reply_panel", None)
        dock = getattr(self.host_window, "visual_reply_dock", None)
        if panel is None:
            return {"available": False}
        pixmap = getattr(panel, "current_pixmap", None)
        return {
            "available": True,
            "image_path": str(getattr(panel, "current_image_path", "") or ""),
            "caption": str(getattr(panel, "current_caption", "") or ""),
            "zoom": float(getattr(panel, "preview_zoom_factor", 1.0) or 1.0),
            "pixmap": pixmap.copy() if pixmap is not None and hasattr(pixmap, "copy") else None,
            "status_text": panel.status_label.text() if hasattr(panel, "status_label") else "",
            "detail_text": panel.placeholder.text() if hasattr(panel, "placeholder") else "",
            "content_index": panel.content_stack.currentIndex() if hasattr(panel, "content_stack") else None,
            "caption_visible": panel.caption_label.isVisible() if hasattr(panel, "caption_label") else False,
            "dock_visible": bool(dock is not None and dock.isVisible()),
            "dock_floating": bool(dock is not None and dock.isFloating()),
            "dock_geometry": bytes(dock.saveGeometry()) if dock is not None else b"",
        }

    @QtCore.Slot(str)
    def _preview_candidate(self, asset_id):
        panel = getattr(self.host_window, "visual_reply_panel", None)
        path = str(self._candidate_paths.get(str(asset_id or ""), "") or "")
        if panel is None or not path:
            return
        candidate = next(
            (
                item
                for item in list((self._pending.payload if self._pending else {}).get("candidates") or [])
                if str((item or {}).get("asset_id", "") or "") == str(asset_id or "")
            ),
            {},
        )
        caption = str(candidate.get("visualization_prompt", "") or "").strip()
        if panel.show_image(path, status_text="Long-Term Memory candidate preview", caption=caption):
            dock = getattr(self.host_window, "visual_reply_dock", None)
            if dock is not None:
                dock.show()
                dock.raise_()

    def _restore_visual_reply(self):
        snapshot = dict(self._visual_snapshot or {})
        panel = getattr(self.host_window, "visual_reply_panel", None)
        dock = getattr(self.host_window, "visual_reply_dock", None)
        if snapshot.get("available") and panel is not None:
            image_path = str(snapshot.get("image_path", "") or "")
            pixmap = snapshot.get("pixmap")
            if pixmap is not None and not pixmap.isNull() and hasattr(panel, "current_pixmap"):
                panel.current_pixmap = pixmap.copy()
                panel.current_image_path = image_path
                panel.current_caption = str(snapshot.get("caption", "") or "")
                if hasattr(panel, "set_caption"):
                    panel.set_caption(panel.current_caption)
                if hasattr(panel, "_refresh_displayed_pixmap"):
                    panel._refresh_displayed_pixmap()
            elif image_path and Path(image_path).is_file() and hasattr(panel, "show_image"):
                panel.show_image(
                    image_path,
                    status_text=str(snapshot.get("status_text", "") or "Visual Reply"),
                    caption=str(snapshot.get("caption", "") or ""),
                )
            elif hasattr(panel, "clear_visual_reply"):
                panel.clear_visual_reply(
                    status_text=str(snapshot.get("status_text", "") or "Visual Reply idle"),
                    detail_text=str(snapshot.get("detail_text", "") or ""),
                )
            panel.preview_zoom_factor = float(snapshot.get("zoom", 1.0) or 1.0)
            if hasattr(panel, "status_label"):
                panel.status_label.setText(str(snapshot.get("status_text", "") or ""))
            if hasattr(panel, "placeholder"):
                panel.placeholder.setText(str(snapshot.get("detail_text", "") or ""))
            content_index = snapshot.get("content_index")
            if content_index is not None and hasattr(panel, "content_stack"):
                panel.content_stack.setCurrentIndex(int(content_index))
            if hasattr(panel, "caption_label"):
                panel.caption_label.setVisible(bool(snapshot.get("caption_visible", False)))
            if hasattr(panel, "_refresh_displayed_pixmap"):
                panel._refresh_displayed_pixmap()
        if dock is not None:
            dock.setFloating(bool(snapshot.get("dock_floating", False)))
            geometry = snapshot.get("dock_geometry")
            if geometry:
                dock.restoreGeometry(QtCore.QByteArray(geometry))
            dock.setVisible(bool(snapshot.get("dock_visible", False)))

    @QtCore.Slot(bool, object)
    def _complete_review(self, cancelled, asset_ids):
        pending = self._pending
        if pending is None:
            return
        self._restore_visual_reply()
        if self.dialog is not None:
            self.dialog.force_close()
            self.dialog.deleteLater()
            self.dialog = None
        pending.result = {
            "cancelled": bool(cancelled),
            "asset_ids": [] if cancelled else [str(item or "") for item in list(asset_ids or [])],
        }
        with self._pending_lock:
            self._pending = None
        pending.event.set()
        self._cleanup_preview_files()

    def cancel_pending(self):
        if self._pending is not None:
            self._complete_review(True, [])

    def _cleanup_preview_files(self):
        self._candidate_paths = {}
        self._visual_snapshot = None
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def shutdown(self):
        self._shutdown = True
        self.cancel_pending()
        self._cleanup_preview_files()
