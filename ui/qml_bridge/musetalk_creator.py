"""UI-thread MuseTalk creator model and paint-only QML image surface."""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
import math
from pathlib import Path
import threading
from typing import Any, Mapping

import numpy as np
from PySide6 import QtCore, QtGui, QtQml, QtQuick

from addons.musetalk_preprocess.mask_document import MaskDocument
from ui.qml_bridge.native_commands import NativeCommandRunner


_TYPE_LOCK = threading.Lock()
_TYPES_REGISTERED = False

def register_musetalk_creator_types() -> None:
    """Register the paint surface once before any application QML is loaded."""

    global _TYPES_REGISTERED
    with _TYPE_LOCK:
        if _TYPES_REGISTERED:
            return
        QtQml.qmlRegisterType(
            MuseTalkMaskSurface,
            "NeuralCompanion.Creator",
            1,
            0,
            "MuseTalkMaskSurface",
        )
        _TYPES_REGISTERED = True


class MuseTalkMaskSurface(QtQuick.QQuickPaintedItem):
    """Paint a detached image; editing and worker lifetime remain model-owned."""

    imageChanged = QtCore.Signal()

    def __init__(self, parent: QtQuick.QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._image = QtGui.QImage()
        self.setAntialiasing(False)
        self.setMipmap(False)

    @QtCore.Property(QtGui.QImage, notify=imageChanged)
    def image(self) -> QtGui.QImage:
        return self._image.copy()

    @image.setter
    def image(self, value: QtGui.QImage) -> None:
        detached = (
            QtGui.QImage(value).copy()
            if isinstance(value, QtGui.QImage)
            else QtGui.QImage()
        )
        if detached.cacheKey() == self._image.cacheKey():
            return
        self._image = detached
        self.imageChanged.emit()
        self.update()

    def paint(self, painter: QtGui.QPainter) -> None:
        if self._image.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.drawImage(self.boundingRect(), self._image)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _freeze(item))
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _identity_tuple(identity: Mapping[str, Any]) -> tuple[Any, ...]:
    profile = dict(identity.get("profile") or {})
    return (
        str(identity.get("source_path") or ""),
        _freeze(identity.get("source_signature") or {}),
        int(identity.get("actual_frame_index", -1)),
        _freeze(profile),
        tuple(int(item) for item in identity.get("bbox") or ()),
        tuple(int(item) for item in identity.get("crop_box") or ()),
        int(identity.get("crop_width", 0)),
        int(identity.get("crop_height", 0)),
        int(identity.get("preview_revision", -1)),
    )


def _rgb_array(image: QtGui.QImage) -> np.ndarray:
    converted = image.convertToFormat(QtGui.QImage.Format_RGB888)
    width = converted.width()
    height = converted.height()
    rows = np.frombuffer(
        converted.bits(), dtype=np.uint8, count=converted.sizeInBytes()
    ).reshape(height, converted.bytesPerLine())
    return rows[:, : width * 3].reshape(height, width, 3).copy()


def _gray_array(image: QtGui.QImage) -> np.ndarray:
    converted = image.convertToFormat(QtGui.QImage.Format_Grayscale8)
    width = converted.width()
    height = converted.height()
    rows = np.frombuffer(
        converted.bits(), dtype=np.uint8, count=converted.sizeInBytes()
    ).reshape(height, converted.bytesPerLine())
    return rows[:, :width].copy()


def _image_from_rgb(rgb: np.ndarray) -> QtGui.QImage:
    data = np.ascontiguousarray(rgb, dtype=np.uint8)
    return QtGui.QImage(
        data.data,
        data.shape[1],
        data.shape[0],
        int(data.strides[0]),
        QtGui.QImage.Format_RGB888,
    ).copy()


def _load_image(path: str) -> QtGui.QImage:
    if not str(path or "").strip():
        return QtGui.QImage()
    image = QtGui.QImage(str(Path(path)))
    return image.copy() if not image.isNull() else QtGui.QImage()


@dataclass(frozen=True)
class _PreparedSnapshot:
    raw: dict[str, Any]
    identity: tuple[Any, ...] | None
    base_bgr: np.ndarray | None
    crop_mask: np.ndarray | None
    bbox: tuple[int, int, int, int] | None
    crop_box: tuple[int, int, int, int] | None
    display_image: QtGui.QImage
    error: str = ""


@dataclass(frozen=True)
class _CreatorCommandResult:
    prepared: _PreparedSnapshot
    action_error: str = ""
    settings_revision: int = -1
    preview_epoch: int = -1


@dataclass(frozen=True)
class _CreatorReleaseResult:
    action_error: str = ""


class MuseTalkCreatorModel(QtCore.QObject):
    """Dedicated creator state/action facade and sole UI-thread mask owner."""

    stateChanged = QtCore.Signal()
    shutdownFinished = QtCore.Signal(bool, str)
    renderPreviewChanged = QtCore.Signal()
    renderPreviewRequested = QtCore.Signal()

    def __init__(self, adapter: Any, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._adapter = adapter
        self._document = MaskDocument()
        self._identity: tuple[Any, ...] | None = None
        self._active_stroke_revision: int | None = None
        self._last_point: tuple[float, float] | None = None
        self._closed = False
        self._notifying_state = False
        self._state_notify_timer = QtCore.QTimer(self)
        self._state_notify_timer.setSingleShot(True)
        self._state_notify_timer.timeout.connect(self._notify_state_changed)
        self._refresh_after_pending = False
        self._settings_revision = 0
        self._settings_refresh_pending = False
        self._departure_id = 0
        self._departure_visible = False
        self._startup_release_pending = False
        self._preview_epoch = 0
        self._preview_serial = 0
        self._render_preview_state: dict[str, Any] = {}
        self._release_error = ""
        self._shutdown_requested = False
        self._shutdown_release_done = False
        self._state: dict[str, Any] = {
            "maskEditable": False,
            "maskSourceWidth": 0,
            "maskSourceHeight": 0,
            "maskPreviewRevision": -1,
            "maskImage": QtGui.QImage(),
            "commandBusy": False,
            "pendingKeys": [],
            "error": "",
        }
        self._commands = NativeCommandRunner(self, max_workers=1)
        self._commands.pendingChanged.connect(self._pending_changed)
        self._commands.completed.connect(self._command_completed)
        self._releases = NativeCommandRunner(self, max_workers=1)
        self._releases.pendingChanged.connect(self._pending_changed)
        self._releases.completed.connect(self._command_completed)
        self._overlay_timer = QtCore.QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._publish_document_image)
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self._activity_timer = QtCore.QTimer(self)
        self._activity_timer.setInterval(40)
        self._activity_timer.timeout.connect(self._poll_creator_activity)
        changed = getattr(adapter, "changed", None)
        if changed is not None:
            changed.connect(self._settings_changed)
        QtCore.QTimer.singleShot(0, self.refresh)

    def _notify_state_changed(self) -> None:
        if self._closed:
            return
        # QML focus/enablement handlers can submit an edit while consuming this
        # signal. Publish any resulting state only after that binding has settled.
        if self._notifying_state:
            if not self._state_notify_timer.isActive():
                self._state_notify_timer.start(0)
            return
        self._state_notify_timer.stop()
        self._notifying_state = True
        try:
            self.stateChanged.emit()
        finally:
            self._notifying_state = False

    @QtCore.Property("QVariantMap", notify=stateChanged)
    def state(self) -> dict[str, Any]:
        result = dict(self._state)
        result["startupPending"] = self._startup_release_pending or self._shutdown_requested
        result["previewSubmissionReady"] = (
            not self._closed and not result["startupPending"]
            and not self._settings_refresh_pending and not self._refresh_timer.isActive()
            and not self._commands.pendingKeys and not self._releases.pendingKeys
        )
        result["releaseBusy"] = bool(self._releases.pendingKeys)
        result["quietCommand"] = (not self._shutdown_requested
                                  and not self._releases.pendingKeys
                                  and all(key == "refresh" for key in self._commands.pendingKeys))
        image = result.get("maskImage")
        if isinstance(image, QtGui.QImage):
            result["maskImage"] = image.copy()
        return result

    @QtCore.Property("QVariantMap", notify=stateChanged)
    def departurePrompt(self) -> dict:
        return {"id": self._departure_id, "visible": self._departure_visible}

    @QtCore.Property("QVariantMap", notify=renderPreviewChanged)
    def renderPreviewState(self) -> dict:
        return dict(self._render_preview_state)

    def _clear_render_preview(self) -> None:
        # Fence already-running renders, even if startup finishes before they do.
        self._preview_epoch += 1
        if self._render_preview_state:
            self._render_preview_state = {}
            self.renderPreviewChanged.emit()

    def _present_render_preview(self, result: _CreatorCommandResult) -> None:
        if (result.preview_epoch != self._preview_epoch
                or self._startup_release_pending or self._shutdown_requested
                or dict(self._state.get("creator_access") or {}).get("owner") == "chat"
                or result.prepared.display_image.isNull()):
            return
        path = str(result.prepared.raw.get("musetalk_native_preview_path") or "")
        if not path:
            return
        self._preview_serial += 1
        url = QtCore.QUrl.fromLocalFile(str(Path(path).resolve()))
        # Worker debug renders can overwrite the same path on consecutive clicks.
        url.setQuery(f"creator_render={self._preview_serial}")
        self._render_preview_state = {
            "imageUrl": url.toString(), "creatorPreview": True, "status": "ready",
            "status_text": "Creator render · clean result",
        }
        self.renderPreviewChanged.emit()
        self.renderPreviewRequested.emit()

    @QtCore.Slot()
    def requestDeparture(self) -> None:
        if self._closed or self._departure_visible or self._startup_release_pending:
            return
        try:
            activity = self._adapter.creator_activity_snapshot()
        except Exception:
            return
        residency = dict(activity.get("creator_residency") or {})
        if (residency.get("loaded") or residency.get("loading")) and not residency.get("release_requested"):
            self._departure_id += 1
            self._departure_visible = True
            self._notify_state_changed()

    @QtCore.Slot()
    def invalidateDeparture(self) -> None:
        self._startup_release_pending = True
        self._clear_render_preview()
        self._departure_id += 1
        self._departure_visible = False
        self._notify_state_changed()

    @QtCore.Slot(bool)
    def setStartupPending(self, pending: bool) -> None:
        if pending and not self._startup_release_pending:
            self._clear_render_preview()
        self._startup_release_pending = bool(pending)
        self._notify_state_changed()

    @QtCore.Slot(int)
    def dismissDeparture(self, prompt_id: int) -> None:
        if prompt_id == self._departure_id and self._departure_visible:
            self._departure_visible = False
            self._notify_state_changed()

    @QtCore.Slot(int, bool)
    def answerDeparture(self, prompt_id: int, unload: bool) -> None:
        if prompt_id != self._departure_id or not self._departure_visible:
            return
        self._departure_visible = False
        self._notify_state_changed()
        if unload:
            self._releases.submit("release-worker", lambda: self._run_release(self._adapter.release_worker))

    @staticmethod
    def _run_release(callback: Any) -> _CreatorReleaseResult:
        try:
            callback()
            return _CreatorReleaseResult()
        except Exception as error:
            return _CreatorReleaseResult(str(error) or type(error).__name__)

    def requiresShutdownDrain(self) -> bool:
        activity = self._adapter.creator_activity_snapshot()
        residency = dict(activity.get("creator_residency") or {})
        return (any(bool(residency.get(key)) for key in (
                    "loaded", "loading", "busy", "worker_failed", "cleanup_failed", "release_requested"))
                or any(key != "refresh" for key in self._commands.pendingKeys)
                or bool(self._releases.pendingKeys))

    def beginShutdown(self, wait_for_startup) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        self._shutdown_release_done = False
        self.invalidateDeparture()
        self._refresh_timer.stop()
        self._refresh_after_pending = False

        def prepare() -> None:
            wait_for_startup()
            self._adapter.prepare_shutdown()

        if not self._releases.submit("shutdown-worker", lambda: self._run_release(prepare)):
            self._shutdown_requested = False
            self.shutdownFinished.emit(False, "Could not schedule MuseTalk shutdown.")

    def _finish_shutdown_if_idle(self) -> None:
        if (self._shutdown_requested and self._shutdown_release_done
                and not self._commands.pendingKeys and not self._releases.pendingKeys):
            self._shutdown_release_done = False
            self.shutdownFinished.emit(True, "")

    def _set_error(self, message: str) -> None:
        self._state["error"] = str(message or "")
        self._notify_state_changed()

    @QtCore.Slot()
    def _settings_changed(self) -> None:
        if self._closed or self._shutdown_requested:
            return
        self._settings_revision += 1
        self._settings_refresh_pending = True
        self._document.end_stroke()
        self._active_stroke_revision = None
        self._last_point = None
        self._request_refresh()
        # Invalidate cached QML readiness before an already-due render tick runs.
        self._notify_state_changed()

    @QtCore.Slot()
    def _request_refresh(self) -> None:
        if self._closed or self._shutdown_requested:
            return
        if self._commands.pendingKeys or self._releases.pendingKeys:
            self._refresh_after_pending = True
            return
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(0)

    @staticmethod
    def _prepare_snapshot(raw_value: Any) -> _PreparedSnapshot:
        raw = copy.deepcopy(dict(raw_value or {}))
        identity_map = dict(raw.get("creator_preview_identity") or {})
        preview_image = _load_image(str(raw.get("musetalk_native_preview_path") or ""))
        if not identity_map:
            return _PreparedSnapshot(raw, None, None, None, None, None, preview_image)
        try:
            identity = _identity_tuple(identity_map)
            if identity[-1] < 0 or identity[-1] != int(
                raw.get("creator_preview_revision", -1)
            ):
                raise ValueError(
                    "The editable preview revision is inconsistent; render a fresh preview."
                )
            bbox = tuple(int(item) for item in identity_map.get("bbox") or ())
            crop_box = tuple(int(item) for item in identity_map.get("crop_box") or ())
            if len(bbox) != 4 or len(crop_box) != 4:
                raise ValueError("The editable preview has invalid mask bounds.")
            details = dict(raw.get("musetalk_native_preview_details") or {})
            base_path = str(details.get("input_frame_path") or "")
            mask_path = str(
                raw.get("creator_edited_mask_path")
                or details.get("mask_frame_path")
                or ""
            )
            base = _load_image(base_path)
            mask = _load_image(mask_path)
            if base.isNull() or mask.isNull():
                raise ValueError(
                    "The editable preview images are unavailable; render a fresh preview."
                )
            crop_mask = _gray_array(mask)
            expected_size = (
                int(identity_map.get("crop_width", 0)),
                int(identity_map.get("crop_height", 0)),
            )
            if (crop_mask.shape[1], crop_mask.shape[0]) != expected_size:
                raise ValueError(
                    "The editable mask dimensions no longer match the preview."
                )
            rgb = _rgb_array(base)
            return _PreparedSnapshot(
                raw,
                identity,
                rgb[:, :, ::-1].copy(),
                crop_mask,
                bbox,
                crop_box,
                preview_image if not preview_image.isNull() else _image_from_rgb(rgb),
            )
        except (OSError, TypeError, ValueError) as error:
            return _PreparedSnapshot(
                raw, None, None, None, None, None, preview_image, str(error)
            )

    def _read_prepared_snapshot(self) -> _PreparedSnapshot:
        return self._prepare_snapshot(self._adapter.creator_snapshot())

    @staticmethod
    def _unavailable_snapshot(error: BaseException) -> _PreparedSnapshot:
        reason = str(error) or type(error).__name__
        return _PreparedSnapshot(
            {
                "musetalk_native_status": "MuseTalk Avatar Creator is unavailable.",
                "musetalk_native_active_job": {},
                "musetalk_native_cleanup_pending": False,
                "creator_access": {
                    "owner": "",
                    "phase": "unavailable",
                    "reason": reason,
                },
                "creator_busy": False,
                "creator_job_id": "",
                "creator_preview_revision": -1,
                "creator_preview_identity": {},
                "creator_edited_mask_path": "",
            },
            None,
            None,
            None,
            None,
            None,
            QtGui.QImage(),
            reason,
        )

    def _read_authoritative_snapshot(self) -> _PreparedSnapshot:
        try:
            return self._read_prepared_snapshot()
        except Exception as error:  # noqa: BLE001 - adapter failures become unavailable UI state.
            return self._unavailable_snapshot(error)

    def _run_then_snapshot(
        self, callback: Any, *, settings_revision: int, preview_epoch: int = -1
    ) -> _CreatorCommandResult:
        action_error = ""
        try:
            callback()
        except Exception as error:  # noqa: BLE001 - preserve the original adapter action error.
            action_error = str(error) or type(error).__name__
        prepared = self._read_authoritative_snapshot()
        return _CreatorCommandResult(
            prepared,
            action_error=action_error,
            settings_revision=settings_revision,
            preview_epoch=preview_epoch,
        )

    def _submit(self, key: str, callback: Any) -> bool:
        if self._closed or self._shutdown_requested:
            return False
        pending = self._commands.pendingKeys
        if self._releases.pendingKeys or (
            pending and (key == "refresh" or any(item != "refresh" for item in pending))
        ):
            self._set_error(
                "Wait for the current MuseTalk creator operation to finish."
            )
            return False
        accepted = self._commands.submit(key, callback)
        if not accepted:
            self._set_error(
                "Wait for the current MuseTalk creator operation to finish."
            )
        return accepted

    @QtCore.Slot()
    def refresh(self) -> None:
        if self._commands.pendingKeys or self._releases.pendingKeys:
            self._refresh_after_pending = True
            return
        settings_revision = self._settings_revision
        self._submit(
            "refresh",
            lambda: self._run_then_snapshot(
                lambda: None, settings_revision=settings_revision
            ),
        )

    @QtCore.Slot(str, "QVariant")
    def trigger(self, control_id: str, payload: Any) -> None:
        key = str(control_id or "").strip()
        if not key:
            self._set_error("A MuseTalk creator action id is required.")
            return
        if isinstance(payload, QtQml.QJSValue):
            payload = payload.toVariant()
        if key == "btn_musetalk_debug_first_frame_modified":
            revision = self._editing_revision()
            if not self._can_edit(revision):
                self._set_error("Render a fresh editable preview before previewing its mask.")
                return
            try:
                # Snapshot current brush pixels on their owning UI thread.
                # Previewing does not invoke Save as override or persist settings.
                payload = {"preview_revision": revision, "mask_png_base64": self._png_base64()}
            except RuntimeError as error:
                self._set_error(str(error))
                return
        settings_revision = self._settings_revision
        preview_epoch = self._preview_epoch

        def work() -> _CreatorCommandResult:
            return self._run_then_snapshot(
                lambda: self._adapter.trigger_with_payload(key, payload),
                settings_revision=settings_revision,
                preview_epoch=preview_epoch,
            )

        self._submit(f"trigger:{key}", work)

    def _editing_revision(self) -> int:
        return int(self._state.get("maskPreviewRevision", -1))

    def _can_edit(self, preview_revision: int) -> bool:
        return (
            not self._closed
            and not self._settings_refresh_pending
            and not self._releases.pendingKeys
            and not self._startup_release_pending
            and bool(self._state.get("maskEditable"))
            and self._identity is not None
            and int(preview_revision) == self._editing_revision()
        )

    @QtCore.Slot(int, bool)
    def beginStroke(self, preview_revision: int, add: bool) -> None:
        if not self._can_edit(preview_revision):
            return
        self._document.begin_stroke(add=bool(add))
        self._active_stroke_revision = int(preview_revision)
        self._last_point = None

    @QtCore.Slot(int, float, float)
    def paintPoint(
        self, preview_revision: int, source_x: float, source_y: float
    ) -> None:
        if not self._can_edit(preview_revision) or self._active_stroke_revision != int(
            preview_revision
        ):
            return
        point = (float(source_x), float(source_y))
        radius = max(1, int(self._state.get("musetalk_debug_brush_size", 12)))
        feather = max(0, int(self._state.get("musetalk_debug_brush_feather", 6)))
        transparency = max(
            0, min(99, int(self._state.get("musetalk_debug_brush_transparency", 0)))
        )
        points = [point]
        if self._last_point is not None:
            delta_x = point[0] - self._last_point[0]
            delta_y = point[1] - self._last_point[1]
            distance = math.hypot(delta_x, delta_y)
            steps = max(1, int(math.ceil(distance / max(1.0, radius * 0.45))))
            points = [
                (
                    self._last_point[0] + delta_x * step / steps,
                    self._last_point[1] + delta_y * step / steps,
                )
                for step in range(1, steps + 1)
            ]
        changed = False
        for x_value, y_value in points:
            changed = (
                self._document.paint(
                    x_value,
                    y_value,
                    radius=radius,
                    feather=feather,
                    transparency=transparency,
                )
                or changed
            )
        self._last_point = point
        if changed and not self._overlay_timer.isActive():
            self._overlay_timer.start(0)

    @QtCore.Slot(int)
    def endStroke(self, preview_revision: int) -> None:
        if self._active_stroke_revision != int(preview_revision):
            return
        self._document.end_stroke()
        self._active_stroke_revision = None
        self._last_point = None
        if not self._overlay_timer.isActive():
            self._overlay_timer.start(0)

    def _png_base64(self) -> str:
        crop = np.ascontiguousarray(self._document.crop_mask(), dtype=np.uint8)
        image = QtGui.QImage(
            crop.data,
            crop.shape[1],
            crop.shape[0],
            int(crop.strides[0]),
            QtGui.QImage.Format_Grayscale8,
        ).copy()
        buffer = QtCore.QBuffer()
        if not buffer.open(QtCore.QIODevice.WriteOnly) or not image.save(buffer, "PNG"):
            raise RuntimeError(
                "Could not encode the edited mask as an 8-bit grayscale PNG."
            )
        return base64.b64encode(bytes(buffer.data())).decode("ascii")

    @QtCore.Slot()
    @QtCore.Slot(int)
    def saveEditedMask(self, preview_revision: int = -1) -> None:
        revision = (
            self._editing_revision()
            if int(preview_revision) < 0
            else int(preview_revision)
        )
        if not self._can_edit(revision):
            self._set_error("Render a fresh editable preview before saving the mask.")
            return
        try:
            encoded = self._png_base64()
        except RuntimeError as error:
            self._set_error(str(error))
            return
        payload = {"preview_revision": revision, "mask_png_base64": encoded}
        settings_revision = self._settings_revision

        def work() -> _CreatorCommandResult:
            def save_override() -> None:
                self._adapter.invoke_creator_action("save_edited_mask", payload)
                self._adapter.invoke_creator_action("add_mask_override", {})

            return self._run_then_snapshot(
                save_override, settings_revision=settings_revision
            )

        self._submit("save-edited-mask", work)

    @QtCore.Slot()
    def _pending_changed(self) -> None:
        pending = self._commands.pendingKeys
        self._state["pendingKeys"] = list(pending)
        self._state["commandBusy"] = bool(pending)
        if self._releases.pendingKeys or (pending and any(key != "refresh" for key in pending)):
            if not self._activity_timer.isActive():
                self._activity_timer.start()
        else:
            self._activity_timer.stop()
        self._notify_state_changed()
        self._finish_shutdown_if_idle()

    @QtCore.Slot()
    def _poll_creator_activity(self) -> None:
        if self._closed:
            self._activity_timer.stop()
            return
        if not (self._commands.pendingKeys or self._releases.pendingKeys):
            self._activity_timer.stop()
        reader = getattr(self._adapter, "creator_activity_snapshot", None)
        if not callable(reader):
            return
        try:
            activity = dict(reader() or {})
        except Exception:  # noqa: BLE001 - live activity is optional during teardown.
            return
        changed = False
        for key in (
            "musetalk_native_status",
            "musetalk_native_active_job",
            "musetalk_native_cleanup_pending",
            "creator_access",
            "creator_busy",
            "creator_job_id",
            "creator_residency",
        ):
            if key in activity and self._state.get(key) != activity[key]:
                self._state[key] = copy.deepcopy(activity[key])
                changed = True
        if changed:
            if dict(self._state.get("creator_access") or {}).get("owner") == "chat":
                self._clear_render_preview()
            self._notify_state_changed()

    @QtCore.Slot(str, bool, object, str)
    def _command_completed(
        self, _key: str, accepted: bool, result: object, error: str
    ) -> None:
        if self._closed:
            return
        if _key == "shutdown-worker":
            failure = (str(getattr(result, "action_error", "")) if accepted
                       else str(error or "MuseTalk creator shutdown failed."))
            self._release_error = failure
            self._poll_creator_activity()
            self._set_error(failure)
            if failure:
                self._shutdown_requested = False
                self._startup_release_pending = False
                self.shutdownFinished.emit(False, failure)
                self._request_refresh()
            else:
                self._shutdown_release_done = True
                self._finish_shutdown_if_idle()
            return
        if _key == "release-worker":
            self._release_error = (
                str(getattr(result, "action_error", "")) if accepted
                else str(error or "MuseTalk creator release failed.")
            )
            self._poll_creator_activity()
            self._set_error(self._release_error)
            # Only the normal serialized lane publishes image snapshots. A
            # release can finish before the service commits the active preview.
            self._request_refresh()
            return
        if accepted and isinstance(result, _CreatorCommandResult):
            if _key == "trigger:btn_musetalk_retry_cleanup" and not result.action_error:
                self._release_error = ""
            self._apply_snapshot(result.prepared, result.settings_revision)
            if result.action_error:
                self._set_error(result.action_error)
            elif _key in {
                "trigger:btn_musetalk_debug_first_frame",
                "trigger:btn_musetalk_debug_first_frame_modified",
                "trigger:btn_musetalk_first_frame_test",
            }:
                self._present_render_preview(result)
        elif accepted and isinstance(result, _PreparedSnapshot):
            self._apply_snapshot(result)
        elif not accepted:
            self._set_error(str(error or "MuseTalk creator operation failed."))
        if self._refresh_after_pending:
            self._refresh_after_pending = False
            self._request_refresh()
        self._finish_shutdown_if_idle()

    def _apply_snapshot(
        self, prepared: _PreparedSnapshot, settings_revision: int = -1
    ) -> None:
        if settings_revision == self._settings_revision:
            self._settings_refresh_pending = False
        if prepared.identity != self._identity:
            self._document.clear()
            self._identity = None
            self._active_stroke_revision = None
            self._last_point = None
            if (
                prepared.identity is not None
                and prepared.base_bgr is not None
                and prepared.crop_mask is not None
                and prepared.bbox is not None
                and prepared.crop_box is not None
            ):
                self._document.load(
                    base_bgr=prepared.base_bgr,
                    crop_mask=prepared.crop_mask,
                    bbox=prepared.bbox,
                    crop_box=prepared.crop_box,
                    identity=prepared.identity,
                )
                self._identity = prepared.identity
        editable = self._identity is not None
        image = QtGui.QImage()
        if self._identity is not None:
            image = _image_from_rgb(self._document.overlay_rgb())
        state = dict(prepared.raw)
        state.update(
            {
                "maskEditable": editable,
                "maskSourceWidth": image.width() if not image.isNull() else 0,
                "maskSourceHeight": image.height() if not image.isNull() else 0,
                "maskPreviewRevision": int(
                    prepared.raw.get("creator_preview_revision", -1)
                )
                if self._identity is not None
                else -1,
                "maskImage": image.copy(),
                "commandBusy": bool(self._commands.pendingKeys),
                "pendingKeys": list(self._commands.pendingKeys),
                "error": str(prepared.error or self._release_error),
            }
        )
        self._state = state
        if dict(state.get("creator_access") or {}).get("owner") == "chat":
            self._clear_render_preview()
        # Release and a finishing job use separate lanes. Their image snapshots
        # may arrive out of order; resource status must always remain live.
        self._poll_creator_activity()
        self._notify_state_changed()

    @QtCore.Slot()
    def _publish_document_image(self) -> None:
        if self._identity is None:
            return
        self._state["maskImage"] = _image_from_rgb(self._document.overlay_rgb())
        self._notify_state_changed()

    @QtCore.Slot()
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._state_notify_timer.stop()
        self._overlay_timer.stop()
        self._refresh_timer.stop()
        self._activity_timer.stop()
        self._document.end_stroke()
        self._active_stroke_revision = None
        self._last_point = None
        self._commands.close()
        self._releases.close()


__all__ = [
    "MuseTalkCreatorModel",
    "MuseTalkMaskSurface",
    "register_musetalk_creator_types",
]
