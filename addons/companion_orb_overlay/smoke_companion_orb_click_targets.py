from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class FakeControl:
    def __init__(
        self,
        name,
        control_type,
        bounds,
        *,
        enabled=True,
        offscreen=False,
        password=False,
        runtime_id=(),
    ):
        self.Name = name
        self.ControlTypeName = control_type
        self.BoundingRectangle = FakeRect(*bounds)
        self.IsEnabled = enabled
        self.IsOffscreen = offscreen
        self.IsPassword = password
        self._runtime_id = runtime_id

    def GetRuntimeId(self):
        return list(self._runtime_id)


class FakeAutomationInitializer:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeAutomationModule:
    def __init__(self, roots, *, point_control=None):
        self._roots = dict(roots)
        self._point_control = point_control
        self.handles = []

    def UIAutomationInitializerInThread(self):
        return FakeAutomationInitializer()

    def ControlFromHandle(self, handle):
        self.handles.append(handle)
        return self._roots.get(handle)

    def WalkControl(self, root, *, includeTop, maxDepth):
        assert includeTop is True
        assert maxDepth == 18
        return iter(root)

    def ControlFromPoint(self, x, y):
        return self._point_control


def _qapplication() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _preview_png() -> bytes:
    image = QtGui.QImage(96, 64, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtGui.QColor("#185a87"))
    painter = QtGui.QPainter(image)
    painter.fillRect(24, 16, 48, 32, QtGui.QColor("#facc15"))
    painter.end()
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def _non_background_pixels(image: QtGui.QImage, rect: QtCore.QRect) -> int:
    rect = rect.intersected(image.rect())
    if rect.isEmpty():
        return 0
    background = image.pixelColor(0, 0)
    return sum(
        image.pixelColor(x, y) != background
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
    )


def _changed_pixels(before: QtGui.QImage, after: QtGui.QImage, rect: QtCore.QRect) -> int:
    rect = rect.intersected(before.rect()).intersected(after.rect())
    if rect.isEmpty():
        return 0
    return sum(
        before.pixelColor(x, y) != after.pixelColor(x, y)
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
    )


def _assert_non_overlapping(rectangles: list[QtCore.QRect]) -> None:
    for index, first in enumerate(rectangles):
        assert not first.isEmpty()
        assert all(not first.intersects(second) for second in rectangles[index + 1 :])


def _assert_circle_separated(first: QtCore.QRect, second: QtCore.QRect, *, gap: float = 8.0) -> None:
    distance = QtCore.QLineF(QtCore.QPointF(first.center()), QtCore.QPointF(second.center())).length()
    required = min(first.width(), first.height()) * 0.5 + min(second.width(), second.height()) * 0.5 + gap
    assert distance >= required - 1.0, (first, second, distance, required)


def _source_for_function(path: Path, function_name: str, *, class_name: str = "") -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = tree.body
    if class_name:
        class_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if class_node is None:
            raise AssertionError(f"Missing {class_name} in {path.name}.")
        nodes = class_node.body
    function_node = next(
        (
            node
            for node in nodes
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if function_node is None:
        scope = f"{class_name}." if class_name else ""
        raise AssertionError(f"Missing {scope}{function_name} in {path.name}.")
    return ast.get_source_segment(source, function_node) or ""


def _assert_click_target_privacy_and_dependency_contract() -> None:
    controller_path = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py"
    )
    automation_path = controller_path.with_name("windows_ui_automation.py")
    methods = (
        (controller_path, "CompanionOrbController", "_scan_gaze_click_targets"),
        (controller_path, "CompanionOrbController", "_validate_gaze_semantic_target_click"),
        (automation_path, "", "discover_semantic_targets"),
        (automation_path, "", "validate_semantic_target"),
    )
    forbidden = ("_debug_event", "_save_runtime_setting", "write_sidecar", "automation.error")
    for path, class_name, method_name in methods:
        source = _source_for_function(path, method_name, class_name=class_name)
        for fragment in forbidden:
            assert fragment not in source, (
                f"{class_name + '.' if class_name else ''}{method_name} must not persist, log, "
                f"or serialize click-target data ({fragment!r})."
            )

    for requirements_name in ("requirements.txt", "requirements.companion.txt"):
        requirements_path = ROOT_DIR / requirements_name
        entries = [
            line.strip()
            for line in requirements_path.read_text(encoding="utf-8").splitlines()
            if line.strip() == "uiautomation==2.0.29"
        ]
        assert len(entries) == 1, (
            f"{requirements_name} must pin uiautomation==2.0.29 exactly once, "
            f"found {len(entries)} entries."
        )


def _assert_click_target_ui_contract() -> None:
    _qapplication()
    from addons.companion_orb_overlay.companion_orb import gaze_radial_menu as radial_menu_module
    from addons.companion_orb_overlay.companion_orb.click_target_overlay import (
        ClickTargetHighlightOverlay,
    )
    from addons.companion_orb_overlay.companion_orb.gaze_radial_menu import (
        GazeRadialMenu,
        RadialAction,
        ellipse_safe_preview_rect,
        preview_crosshair_geometry,
        preview_raster_target_size,
    )

    floating_preview_lens_rect = getattr(radial_menu_module, "floating_preview_lens_rect", None)
    lens_size = int(getattr(radial_menu_module, "FLOATING_PREVIEW_LENS_SIZE", 0))
    assert callable(floating_preview_lens_rect), "The floating gaze-preview placement helper is missing."
    assert lens_size == 220, f"The enlarged gaze preview must be 220 px, got {lens_size}."

    theme = {"primary": "#38bdf8", "text": "#eef7ff", "surface": "#101b2b"}
    overlay = ClickTargetHighlightOverlay()
    overlay.show_target((250, 180, 140, 36), "Button - Save", theme)
    assert overlay.isVisible()
    assert overlay.target_bounds == QtCore.QRect(250, 180, 140, 36)
    overlay.clear_target()
    assert not overlay.isVisible()
    overlay.show_candidates(
        (
            ("click_target_visual:0", (200, 120, 160, 90), "1"),
            ("click_target_visual:1", (420, 120, 160, 90), "2"),
        ),
        active_id="click_target_visual:1",
        theme=theme,
    )
    assert len(overlay.candidate_bounds) == 2
    assert overlay.active_id == "click_target_visual:1"
    overlay.setGeometry(-400, -120, 800, 600)
    overlay._theme = overlay._normalize_theme(theme)
    negative_image = QtGui.QImage(800, 600, QtGui.QImage.Format_ARGB32_Premultiplied)
    negative_image.fill(QtCore.Qt.transparent)
    negative_painter = QtGui.QPainter(negative_image)
    overlay._paint_target(
        negative_painter,
        QtCore.QRect(-320, -80, 140, 36),
        "Button - Save",
        active=True,
    )
    negative_painter.end()
    assert _non_background_pixels(negative_image, QtCore.QRect(76, 36, 152, 68)) > 100
    overlay.clear_target()

    screen_rect = QtCore.QRect(0, 0, 1600, 1000)
    menu_rect = QtCore.QRect(320, 170, 660, 660)
    source_rect = QtCore.QRect(790, 430, 104, 104)
    outward_rect = floating_preview_lens_rect(
        menu_rect,
        source_rect,
        (source_rect,),
        screen_rect,
        diameter=lens_size,
    )
    assert screen_rect.contains(outward_rect)
    _assert_circle_separated(outward_rect, source_rect)
    assert outward_rect.center().x() > source_rect.center().x()

    edge_menu_rect = QtCore.QRect(0, 0, 660, 660)
    edge_source_rect = QtCore.QRect(278, 0, 104, 104)
    edge_avoid_rects = (
        edge_source_rect,
        QtCore.QRect(80, 40, 104, 104),
        QtCore.QRect(476, 40, 104, 104),
    )
    edge_rect = floating_preview_lens_rect(
        edge_menu_rect,
        edge_source_rect,
        edge_avoid_rects,
        QtCore.QRect(0, 0, 800, 700),
        diameter=lens_size,
    )
    assert QtCore.QRect(0, 0, 800, 700).contains(edge_rect)
    for item in edge_avoid_rects:
        _assert_circle_separated(edge_rect, item)

    crowded_source_rect = QtCore.QRect(450, 560, 104, 104)
    crowded_avoid_rects = tuple(
        QtCore.QRect(*values)
        for values in (
            (348, 113, 104, 104),
            (532, 201, 104, 104),
            (577, 400, 104, 104),
            (450, 560, 104, 104),
            (246, 560, 104, 104),
            (119, 400, 104, 104),
            (164, 201, 104, 104),
        )
    )
    crowded_rect = floating_preview_lens_rect(
        QtCore.QRect(70, 70, 660, 660),
        crowded_source_rect,
        crowded_avoid_rects,
        QtCore.QRect(0, 0, 800, 800),
        diameter=lens_size,
    )
    _assert_circle_separated(crowded_rect, crowded_source_rect)

    constrained_avoid_rects = tuple(
        QtCore.QRect(*values)
        for values in (
            (348, 130, 104, 104),
            (536, 239, 104, 104),
            (536, 457, 104, 104),
            (348, 566, 104, 104),
            (160, 457, 104, 104),
            (160, 239, 104, 104),
            (358, 358, 84, 84),
        )
    )
    constrained_rect = floating_preview_lens_rect(
        QtCore.QRect(70, 70, 660, 660),
        constrained_avoid_rects[2],
        constrained_avoid_rects,
        QtCore.QRect(0, 0, 800, 800),
        diameter=lens_size,
    )
    assert QtCore.QRect(0, 0, 800, 800).contains(constrained_rect)
    for item in constrained_avoid_rects:
        _assert_circle_separated(constrained_rect, item)

    menu = GazeRadialMenu()
    long_label = "Save the current companion profile before continuing with the next scene"
    menu.show_actions(
        (RadialAction("click_target:0", long_label, role="Button", preview_png=_preview_png()),),
        anchor=QtCore.QPoint(500, 400),
        dwell_ms=650,
        theme=theme,
        opacity=0.55,
        confirmation_lens=True,
        center_label="Back",
        center_action_id="back",
    )
    QtWidgets.QApplication.processEvents()
    back_geometry = QtCore.QRect(menu._cancel_button.geometry())
    back_hit = next(target for target in menu._radial_hit_targets() if target.action_id == "back")
    candidate_events: list[str] = []
    menu.candidate_changed.connect(candidate_events.append)
    target_center = menu.mapToGlobal(menu._buttons["click_target:0"].geometry().center())
    menu.feed_gaze(target_center, now=1.0)
    assert candidate_events[-1] == "click_target:0"
    assert menu.confirmation_action_id == "click_target:0"
    assert menu._cancel_button.geometry() == back_geometry
    assert next(target for target in menu._radial_hit_targets() if target.action_id == "back") == back_hit
    preview_lens = getattr(menu, "_preview_lens", None)
    assert preview_lens is not None and preview_lens.isVisible()
    assert preview_lens.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
    assert preview_lens._button is not None
    assert preview_lens._button.width() == lens_size
    assert preview_lens._button.height() == lens_size
    assert preview_lens._button.action.action_id == "click_target:0"
    assert preview_lens._button._visual_inspection is True
    assert preview_lens._button.action.crosshair_x == 0.5
    assert preview_lens._button.action.crosshair_y == 0.5
    assert preview_lens.windowOpacity() == 1.0
    assert preview_lens._button._preview_lens_mode is True
    source_global_rect = menu._global_widget_rect(menu._buttons["click_target:0"])
    lens_global_rect = menu._global_widget_rect(preview_lens._button)
    _assert_circle_separated(lens_global_rect, source_global_rect)
    active_screen = QtWidgets.QApplication.screenAt(source_global_rect.center())
    assert active_screen is not None and active_screen.availableGeometry().contains(lens_global_rect)
    assert _non_background_pixels(preview_lens.grab().toImage(), preview_lens.rect()) > 1000
    lens_bounds = QtCore.QRectF(preview_lens._button.rect()).adjusted(7.0, 7.0, -7.0, -7.0)
    lens_label_bounds = preview_lens._button.label_content_bounds(lens_bounds)
    lens_preview_bounds = preview_lens._button.preview_content_bounds(lens_bounds)
    assert lens_label_bounds.center().y() < lens_bounds.center().y()
    assert lens_label_bounds.bottom() <= lens_preview_bounds.top()
    baseline_lens_image = preview_lens._button.grab().toImage()

    lens_center = lens_global_rect.center()
    transfer_midpoint = QtCore.QPointF(
        (target_center.x() + lens_center.x()) * 0.5,
        (target_center.y() + lens_center.y()) * 0.5,
    )
    menu.feed_gaze(transfer_midpoint, now=1.12)
    QtWidgets.QApplication.processEvents()
    assert menu.selection_candidate_id == "click_target:0"
    assert preview_lens.isVisible()

    menu.feed_gaze(lens_center, now=1.25)
    QtWidgets.QApplication.processEvents()
    source_progress = menu._buttons["click_target:0"]._gaze_progress
    assert 0.35 < source_progress < 0.45
    assert abs(preview_lens._button._gaze_progress - source_progress) < 0.0001
    progressed_lens_image = preview_lens._button.grab().toImage()
    interior_probe = preview_lens._button.rect().adjusted(48, 60, -48, -48)
    assert _changed_pixels(baseline_lens_image, progressed_lens_image, interior_probe) == 0

    menu.feed_gaze(QtCore.QPointF(menu.geometry().right() + 500, menu.geometry().bottom() + 500), now=1.30)
    QtWidgets.QApplication.processEvents()
    assert not preview_lens.isVisible()

    menu.feed_gaze(target_center, now=2.0)
    assert preview_lens.isVisible()
    menu.reset_gaze_selection()
    assert menu.confirmation_action_id == ""
    assert not preview_lens.isVisible()

    menu.feed_gaze(target_center, now=3.0)
    assert preview_lens.isVisible()
    menu.show_actions(
        (RadialAction("previous", "Previous"),),
        anchor=QtCore.QPoint(500, 400),
        dwell_ms=650,
        theme=theme,
        center_label="Back",
        center_action_id="back",
    )
    assert not preview_lens.isVisible()

    menu.show_actions(
        (
            RadialAction(
                "generic_preview",
                "Generic preview",
                role="Region",
                preview_png=_preview_png(),
            ),
        ),
        anchor=QtCore.QPoint(500, 400),
        dwell_ms=650,
        theme=theme,
        opacity=0.45,
        center_label="Back",
        center_action_id="back",
    )
    generic_source_center = menu.mapToGlobal(menu._buttons["generic_preview"].geometry().center())
    menu.feed_gaze(generic_source_center, now=3.2)
    QtWidgets.QApplication.processEvents()
    assert preview_lens.isVisible()
    assert preview_lens.windowOpacity() == 1.0
    assert preview_lens._button is not None
    assert preview_lens._button._preview_lens_mode is True
    generic_lens_center = menu._global_widget_rect(preview_lens._button).center()
    menu.feed_gaze(
        QtCore.QPointF(
            (generic_source_center.x() + generic_lens_center.x()) * 0.5,
            (generic_source_center.y() + generic_lens_center.y()) * 0.5,
        ),
        now=3.3,
    )
    menu.feed_gaze(generic_lens_center, now=3.4)
    assert menu.selection_candidate_id == "generic_preview"
    assert preview_lens.isVisible()
    menu.reset_gaze_selection()

    visual_actions = tuple(
        RadialAction(f"click_target_visual:{index}", f"Inspect {index + 1}", preview_png=_preview_png())
        for index in range(4)
    ) + (
        RadialAction("previous", "Previous"),
        RadialAction("next", "Next"),
    )
    menu.show_actions(
        visual_actions,
        anchor=QtCore.QPoint(500, 400),
        dwell_ms=650,
        theme=theme,
        enlarged_visual=True,
        center_label="Back",
        center_action_id="back",
    )
    QtWidgets.QApplication.processEvents()
    assert len(menu._buttons) == 6
    enlarged_buttons = [button for button in menu._buttons.values() if button._visual_inspection]
    utility_buttons = [button for button in menu._buttons.values() if not button._visual_inspection]
    assert len(enlarged_buttons) == 4
    assert all(button.width() > 104 for button in enlarged_buttons)
    assert [button.action.action_id for button in utility_buttons] == ["previous", "next"]
    assert all(button.width() < 104 for button in utility_buttons)
    _assert_non_overlapping([button.geometry() for button in (*enlarged_buttons, *utility_buttons, menu._cancel_button)])
    assert menu._cancel_button.geometry() == back_geometry
    assert next(target for target in menu._radial_hit_targets() if target.action_id == "back") == back_hit
    visual_source = menu._buttons["click_target_visual:0"]
    visual_source_bounds = QtCore.QRectF(visual_source.rect()).adjusted(7.0, 7.0, -7.0, -7.0)
    assert visual_source.label_content_bounds(visual_source_bounds).center().y() < visual_source_bounds.center().y()
    visual_source_center = menu.mapToGlobal(visual_source.geometry().center())
    menu.feed_gaze(visual_source_center, now=4.0)
    QtWidgets.QApplication.processEvents()
    assert preview_lens.isVisible()
    visual_lens_center = menu._global_widget_rect(preview_lens._button).center()
    menu.feed_gaze(
        QtCore.QPointF(
            (visual_source_center.x() + visual_lens_center.x()) * 0.5,
            (visual_source_center.y() + visual_lens_center.y()) * 0.5,
        ),
        now=4.1,
    )
    menu.feed_gaze(visual_lens_center, now=4.2)
    assert menu.selection_candidate_id == "click_target_visual:0"
    assert preview_lens.isVisible()
    menu.reset_gaze_selection()

    edge_button_action = RadialAction(
        "click_target_visual:0",
        long_label,
        preview_png=_preview_png(),
        crosshair_x=0.88,
        crosshair_y=0.20,
    )
    menu.show_actions(
        (edge_button_action,),
        anchor=QtCore.QPoint(500, 400),
        dwell_ms=650,
        theme=theme,
        enlarged_visual=True,
        center_label="Back",
        center_action_id="back",
    )
    QtWidgets.QApplication.processEvents()
    edge_button = menu._buttons["click_target_visual:0"]
    edge_button_image = edge_button.grab().toImage()
    button_bounds = QtCore.QRectF(edge_button.rect()).adjusted(7.0, 7.0, -7.0, -7.0)
    button_preview_bounds = button_bounds.adjusted(7.0, 7.0, -7.0, -7.0)
    button_fit_bounds = ellipse_safe_preview_rect(button_preview_bounds)
    raster_size = preview_raster_target_size(button_fit_bounds)
    assert raster_size.width() <= button_fit_bounds.width()
    assert raster_size.height() <= button_fit_bounds.height()
    preview_pixmap = QtGui.QPixmap()
    assert preview_pixmap.loadFromData(QtCore.QByteArray(_preview_png()), "PNG")
    scaled_preview = preview_pixmap.scaled(
        raster_size,
        QtCore.Qt.KeepAspectRatio,
        QtCore.Qt.SmoothTransformation,
    )
    raster_draw_rect = QtCore.QRectF(
        QtCore.QPointF(),
        QtCore.QSizeF(scaled_preview.size()),
    )
    raster_draw_rect.moveCenter(button_fit_bounds.center())
    button_draw_rect, button_crosshair = preview_crosshair_geometry(
        QtCore.QSizeF(scaled_preview.size()),
        raster_draw_rect,
        0.88,
        0.20,
    )
    assert button_draw_rect.height() < button_preview_bounds.height()
    ellipse_center = button_preview_bounds.center()
    ellipse_rx = button_preview_bounds.width() * 0.5
    ellipse_ry = button_preview_bounds.height() * 0.5
    for corner in (
        button_draw_rect.topLeft(),
        button_draw_rect.topRight(),
        button_draw_rect.bottomLeft(),
        button_draw_rect.bottomRight(),
    ):
        normalized_radius = (
            ((corner.x() - ellipse_center.x()) / ellipse_rx) ** 2
            + ((corner.y() - ellipse_center.y()) / ellipse_ry) ** 2
        )
        assert normalized_radius <= 1.000001
    menu.show_actions(
        (RadialAction("click_target_visual:0", long_label, preview_png=_preview_png()),),
        anchor=QtCore.QPoint(500, 400),
        dwell_ms=650,
        theme=theme,
        enlarged_visual=True,
        center_label="Back",
        center_action_id="back",
    )
    QtWidgets.QApplication.processEvents()
    center_button_image = menu._buttons["click_target_visual:0"].grab().toImage()
    button_probe = QtCore.QRect(
        int(round(button_crosshair.x())) - 13,
        int(round(button_crosshair.y())) - 13,
        27,
        27,
    )
    assert _changed_pixels(edge_button_image, center_button_image, button_probe) > 12
    menu.hide()
    QtWidgets.QApplication.processEvents()
    assert not preview_lens.isVisible()
    overlay.deleteLater()
    menu.deleteLater()


def _assert_windows_ui_automation_contract() -> None:
    from dataclasses import replace
    from unittest import mock

    from addons.companion_orb_overlay.companion_orb import windows_ui_automation

    controls = [
        (FakeControl("Save", "ButtonControl", (150, 130, 250, 170), runtime_id=(1, 2)), 0),
        (FakeControl("Download", "HyperlinkControl", (260, 130, 370, 170), runtime_id=(1, 3)), 1),
        (FakeControl("Settings", "TabItemControl", (380, 130, 490, 170), runtime_id=(1, 4)), 1),
        (FakeControl("Search", "EditControl", (500, 130, 620, 170), runtime_id=(1, 5)), 1),
        (FakeControl("No identity", "ButtonControl", (630, 130, 750, 170), runtime_id=()), 1),
        (FakeControl("Partial", "ButtonControl", (90, 300, 150, 340), runtime_id=(1, 12)), 1),
        (FakeControl("Outside center", "ButtonControl", (50, 350, 130, 390), runtime_id=(1, 13)), 1),
        (FakeControl("", "ButtonControl", (150, 180, 250, 220), runtime_id=(1, 6)), 1),
        (FakeControl("Secret", "EditControl", (260, 180, 370, 220), password=True, runtime_id=(1, 7)), 1),
        (FakeControl("Hidden", "ButtonControl", (380, 180, 490, 220), offscreen=True, runtime_id=(1, 8)), 1),
        (FakeControl("Disabled", "ButtonControl", (500, 180, 620, 220), enabled=False, runtime_id=(1, 9)), 1),
        (FakeControl("Outside", "ButtonControl", (1100, 180, 1200, 220), runtime_id=(1, 10)), 1),
        (FakeControl("Text", "TextControl", (150, 230, 250, 270), runtime_id=(1, 11)), 1),
    ]
    matching = controls[0][0]
    automation = FakeAutomationModule({101: controls}, point_control=matching)
    result = windows_ui_automation.discover_semantic_targets(
        (100, 100, 900, 650),
        automation_module=automation,
        window_handle_provider=lambda _bounds: [101],
        max_nodes=320,
        timeout_seconds=0.45,
    )
    assert result.available is True
    assert result.timed_out is False
    assert result.error == ""
    assert [(item.role, item.label) for item in result.targets] == [
        ("Button", "Save"),
        ("Link", "Download"),
        ("Tab", "Settings"),
        ("Input", "Search"),
        ("Button", "Partial"),
    ]
    assert all(item.label != "No identity" for item in result.targets)
    assert all(item.label != "Outside center" for item in result.targets)
    assert next(item for item in result.targets if item.label == "Partial").bounds == (90, 300, 60, 40)
    assert all(isinstance(item.runtime_id, tuple) for item in result.targets)
    assert windows_ui_automation.validate_semantic_target(
        result.targets[0],
        result.targets[0].center,
        automation_module=automation,
    )
    assert not windows_ui_automation.validate_semantic_target(
        replace(result.targets[0], runtime_id=()),
        result.targets[0].center,
        automation_module=automation,
    )
    assert windows_ui_automation._point_in_bounds((150, 130), (150, 130, 100, 40))
    assert windows_ui_automation._point_in_bounds((249.9, 169.9), (150, 130, 100, 40))
    assert not windows_ui_automation._point_in_bounds((250, 150), (150, 130, 100, 40))
    assert not windows_ui_automation._point_in_bounds((200, 170), (150, 130, 100, 40))

    with mock.patch.object(windows_ui_automation, "_load_uiautomation", return_value=None):
        unavailable = windows_ui_automation.discover_semantic_targets(
            (100, 100, 900, 650),
            automation_module=None,
            window_handle_provider=lambda _bounds: (),
        )
    assert unavailable.available is False
    assert unavailable.error == "uiautomation is not installed"

    class FakeWin32Gui:
        _bounds = {
            10: (120, 120, 220, 180),
            11: (230, 120, 330, 180),
            12: (340, 120, 440, 180),
            13: (450, 120, 450, 180),
            14: (1100, 120, 1200, 180),
            15: (560, 120, 660, 180),
        }

        @classmethod
        def EnumWindows(cls, callback, param):
            for handle in cls._bounds:
                if callback(handle, param) is False:
                    break

        @staticmethod
        def IsWindowVisible(handle):
            return handle != 11

        @staticmethod
        def IsIconic(handle):
            return handle == 12

        @classmethod
        def GetWindowRect(cls, handle):
            return cls._bounds[handle]

    with mock.patch.dict(sys.modules, {"win32gui": FakeWin32Gui}):
        assert windows_ui_automation._visible_window_handles((100, 100, 900, 650)) == (10, 15)

    with mock.patch.dict(sys.modules, {"win32gui": None}):
        with mock.patch.object(windows_ui_automation, "_visible_window_handles_ctypes", return_value=()):
            assert windows_ui_automation._visible_window_handles((100, 100, 900, 650)) == ()

    limited = FakeAutomationModule({101: controls})
    limited_result = windows_ui_automation.discover_semantic_targets(
        (100, 100, 900, 650),
        automation_module=limited,
        window_handle_provider=lambda _bounds: [101],
        max_nodes=2,
    )
    assert limited_result.timed_out is True
    assert [item.label for item in limited_result.targets] == ["Save", "Download"]

    ticks = iter((0.0, 0.06))
    deadline_result = windows_ui_automation.discover_semantic_targets(
        (100, 100, 900, 650),
        automation_module=FakeAutomationModule({101: controls}),
        window_handle_provider=lambda _bounds: [101],
        timeout_seconds=0.05,
        now_fn=lambda: next(ticks),
    )
    assert deadline_result.timed_out is True
    assert deadline_result.targets == ()

    control_release = threading.Event()
    control_entered = threading.Event()
    control_finished = threading.Event()
    control_thread_daemon = []

    class BlockingControlAutomation(FakeAutomationModule):
        def ControlFromHandle(self, handle):
            control_thread_daemon.append(threading.current_thread().daemon)
            control_entered.set()
            control_release.wait(0.4)
            try:
                return super().ControlFromHandle(handle)
            finally:
                control_finished.set()

    started_at = time.monotonic()
    blocked_control_result = windows_ui_automation.discover_semantic_targets(
        (100, 100, 900, 650),
        automation_module=BlockingControlAutomation({101: []}),
        window_handle_provider=lambda _bounds: [101],
        timeout_seconds=0.05,
    )
    blocked_control_elapsed = time.monotonic() - started_at
    control_release.set()
    assert control_entered.is_set()
    assert control_finished.wait(0.5)
    assert control_thread_daemon == [True]
    assert blocked_control_elapsed < 0.25, blocked_control_elapsed
    assert blocked_control_result.available is True
    assert blocked_control_result.timed_out is True
    assert blocked_control_result.error == ""

    iterator_release = threading.Event()
    iterator_entered = threading.Event()
    iterator_finished = threading.Event()
    iterator_thread_daemon = []

    class BlockingIterator:
        def __iter__(self):
            return self

        def __next__(self):
            iterator_thread_daemon.append(threading.current_thread().daemon)
            iterator_entered.set()
            iterator_release.wait(0.4)
            iterator_finished.set()
            raise StopIteration

    class BlockingIteratorAutomation(FakeAutomationModule):
        def WalkControl(self, root, *, includeTop, maxDepth):
            assert includeTop is True
            assert maxDepth == 18
            return BlockingIterator()

    started_at = time.monotonic()
    blocked_iterator_result = windows_ui_automation.discover_semantic_targets(
        (100, 100, 900, 650),
        automation_module=BlockingIteratorAutomation({101: object()}),
        window_handle_provider=lambda _bounds: [101],
        timeout_seconds=0.05,
    )
    blocked_iterator_elapsed = time.monotonic() - started_at
    iterator_release.set()
    assert iterator_entered.is_set()
    assert iterator_finished.wait(0.5)
    assert iterator_thread_daemon == [True]
    assert blocked_iterator_elapsed < 0.25, blocked_iterator_elapsed
    assert blocked_iterator_result.available is True
    assert blocked_iterator_result.timed_out is True
    assert blocked_iterator_result.error == ""

    for invalid_timeout in (float("nan"), float("inf"), "invalid"):
        timeout_ticks = iter((0.0, 0.46))
        invalid_timeout_result = windows_ui_automation.discover_semantic_targets(
            (100, 100, 900, 650),
            automation_module=FakeAutomationModule({101: controls}),
            window_handle_provider=lambda _bounds: [101],
            timeout_seconds=invalid_timeout,
            now_fn=lambda: next(timeout_ticks),
        )
        assert invalid_timeout_result.available is True
        assert invalid_timeout_result.timed_out is True
        assert invalid_timeout_result.targets == ()

    for invalid_max_nodes in (float("nan"), float("inf"), "invalid"):
        invalid_node_result = windows_ui_automation.discover_semantic_targets(
            (100, 100, 900, 650),
            automation_module=FakeAutomationModule({101: controls}),
            window_handle_provider=lambda _bounds: [101],
            max_nodes=invalid_max_nodes,
        )
        assert invalid_node_result.available is True
        assert invalid_node_result.timed_out is False
        assert [target.label for target in invalid_node_result.targets] == [
            "Save",
            "Download",
            "Settings",
            "Search",
            "Partial",
        ]

    six_roots = {
        handle: [(
            FakeControl(
                f"Button {handle}",
                "ButtonControl",
                (150, 130, 250, 170),
                runtime_id=(2, handle),
            ),
            0,
        )]
        for handle in range(1, 8)
    }
    capped = FakeAutomationModule(six_roots)
    capped_result = windows_ui_automation.discover_semantic_targets(
        (100, 100, 900, 650),
        automation_module=capped,
        window_handle_provider=lambda _bounds: list(range(1, 8)),
    )
    assert len(capped.handles) == 6
    assert len(capped_result.targets) == 6

    changed_name = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Changed", "ButtonControl", (150, 130, 250, 170), runtime_id=(1, 2)
    ))
    changed_runtime_id = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Save", "ButtonControl", (150, 130, 250, 170), runtime_id=(9, 9)
    ))
    missing_runtime_id = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Save", "ButtonControl", (150, 130, 250, 170), runtime_id=()
    ))
    changed_role = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Save", "HyperlinkControl", (150, 130, 250, 170), runtime_id=(1, 2)
    ))
    shifted_bounds = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Save", "ButtonControl", (160, 130, 260, 170), runtime_id=(1, 2)
    ))
    normalized_identity = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "  Save\t", "ButtonControl", (150, 130, 250, 170), runtime_id=(1, 2)
    ))
    tolerance_edge = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Save", "ButtonControl", (162, 142, 262, 182), runtime_id=(1, 2)
    ))
    outside_tolerance = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Save", "ButtonControl", (163, 143, 263, 183), runtime_id=(1, 2)
    ))
    dimension_tolerance_cases = (
        ((150, 130, 262, 170), True),
        ((150, 130, 238, 170), True),
        ((150, 130, 263, 170), False),
        ((150, 130, 237, 170), False),
        ((150, 130, 250, 182), True),
        ((150, 130, 250, 158), True),
        ((150, 130, 250, 183), False),
        ((150, 130, 250, 157), False),
    )
    outside_bounds = FakeAutomationModule({101: controls}, point_control=FakeControl(
        "Save", "ButtonControl", (900, 700, 1000, 740), runtime_id=(1, 2)
    ))
    assert not windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=changed_name
    )
    assert not windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=changed_runtime_id
    )
    assert not windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=missing_runtime_id
    )
    assert not windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=changed_role
    )
    assert windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=shifted_bounds
    )
    assert windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=normalized_identity
    )
    assert windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=tolerance_edge
    )
    assert not windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=outside_tolerance
    )
    for current_bounds, expected in dimension_tolerance_cases:
        current_automation = FakeAutomationModule(
            {101: controls},
            point_control=FakeControl(
                "Save",
                "ButtonControl",
                current_bounds,
                runtime_id=(1, 2),
            ),
        )
        assert windows_ui_automation.validate_semantic_target(
            result.targets[0],
            result.targets[0].center,
            automation_module=current_automation,
        ) is expected
    assert not windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=outside_bounds
    )
    assert not windows_ui_automation.validate_semantic_target(
        result.targets[0], result.targets[0].center, automation_module=FakeAutomationModule({}, point_control=None)
    )


def _assert_controller_task_4_contract(companion_orb_controller, eye_tracking) -> None:
    controller_type = companion_orb_controller.CompanionOrbController

    class FakeHighlightOverlay:
        def __init__(self):
            self.clear_count = 0
            self.target_calls = []
            self.candidate_calls = []

        def clear_target(self):
            self.clear_count += 1

        def show_target(self, bounds, label, theme=None):
            self.target_calls.append((tuple(bounds), label, dict(theme or {})))

        def show_candidates(self, candidates, *, active_id, theme=None):
            self.candidate_calls.append((tuple(candidates), active_id, dict(theme or {})))

    semantic_payload = [
        {
            "label": "Save",
            "bounds": [220, 140, 120, 36],
            "kind": "ButtonControl",
            "confidence": 1.0,
            "role": "Button",
            "source": "uia",
            "semantic": True,
            "runtime_id": [10, 1],
            "preview_png": _preview_png(),
            "preview_crosshair": [0.20, 0.80],
        },
        {
            "label": "Search",
            "bounds": [380, 140, 180, 36],
            "kind": "EditControl",
            "confidence": 1.0,
            "role": "Edit",
            "source": "uia",
            "semantic": True,
            "runtime_id": [10, 2],
            "preview_png": _preview_png(),
        },
        {
            "label": "Apply",
            "bounds": [590, 140, 120, 36],
            "kind": "win32_control",
            "confidence": 0.9,
            "role": "Button",
            "source": "win32",
            "semantic": False,
            "runtime_id": [],
            "preview_png": _preview_png(),
        },
        {
            "label": "No identity",
            "bounds": [720, 140, 120, 36],
            "kind": "ButtonControl",
            "confidence": 1.0,
            "role": "Button",
            "source": "uia",
            "semantic": True,
            "runtime_id": [],
            "preview_png": _preview_png(),
        },
    ]
    visual_payload = [
        {
            "label": "Apply" if index == 0 else ("" if index % 2 == 0 else f"Visual {index + 1}"),
            "bounds": [180 + index * 70, 260, 96, 64],
            "kind": "win32_control" if index == 0 else "zoom_tile",
            "confidence": 0.25,
            "role": "Button" if index == 0 else "",
            "source": "win32" if index == 0 else "fallback",
            "semantic": False,
            "runtime_id": [],
            "preview_png": _preview_png(),
            "preview_crosshair": [0.80, 0.25] if index == 0 else [0.5, 0.5],
        }
        for index in range(6)
    ]
    payload = {
        "generation": 7,
        "automation_available": True,
        "automation_timed_out": True,
        "direct": semantic_payload,
        "visual": visual_payload,
    }

    overlay = FakeHighlightOverlay()
    captured_pages = []
    controller = type("Task4ControllerDouble", (), {})()
    controller._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    controller._gaze_click_scan_generation = 7
    controller._gaze_radial_menu_open = True
    controller._gaze_click_target_page_open = True
    controller._gaze_click_targets = {}
    controller._gaze_click_target_payloads = {}
    controller._gaze_click_visual_targets = []
    controller._gaze_click_visual_page = 0
    controller._gaze_click_visual_page_open = False
    controller._gaze_click_visual_action_menu_open = False
    controller._gaze_click_visual_selected_index = None
    controller._gaze_click_target_highlight = overlay
    controller._gaze_radial_anchor = QtCore.QPoint(500, 400)
    controller._eye_tracking_latest_point = (500.0, 400.0)
    controller._gaze_radial_theme = lambda: {"primary": "#38bdf8"}
    controller._ensure_gaze_click_target_highlight_overlay = lambda: overlay
    controller._clear_gaze_click_target_highlight = lambda: overlay.clear_target()
    controller._show_gaze_radial_actions = lambda actions, **kwargs: captured_pages.append(
        (tuple(actions), dict(kwargs))
    )
    controller._show_gaze_click_target_direct_page = lambda: controller_type._show_gaze_click_target_direct_page(
        controller
    )
    controller._show_gaze_click_target_visual_page = lambda page=0: controller_type._show_gaze_click_target_visual_page(
        controller,
        page,
    )
    controller._show_gaze_click_visual_action_menu = (
        lambda index: controller_type._show_gaze_click_visual_action_menu(controller, index)
    )
    controller._gaze_click_target_enabled = lambda: True
    controller._click_target_from_payload = controller_type._click_target_from_payload
    controller._click_target_payload_preview = controller_type._click_target_payload_preview
    controller._gaze_click_automation_status_action = lambda: controller_type._gaze_click_automation_status_action(
        controller
    )
    controller._gaze_click_visual_page_entries = lambda: controller_type._gaze_click_visual_page_entries(
        controller
    )

    controller_type._handle_gaze_click_targets_result(controller, payload)
    assert tuple(controller._gaze_click_targets) == (
        "click_target:0",
        "click_target:1",
    )
    assert controller._gaze_click_visual_targets == visual_payload
    assert controller._gaze_click_visual_targets[0]["label"] == "Apply"
    assert controller._gaze_click_visual_targets[0]["source"] == "win32"
    direct_actions, direct_options = captured_pages[-1]
    assert [action.action_id for action in direct_actions] == [
        "click_target:0",
        "click_target:1",
        "click_target_inspect",
        "click_target_automation_status",
    ]
    assert direct_actions[-2].label == "Inspect nearby"
    assert direct_actions[-1].label == "App controls partial"
    assert direct_actions[-1].enabled is False
    assert direct_options["confirmation_lens"] is True
    assert (direct_actions[0].crosshair_x, direct_actions[0].crosshair_y) == (0.20, 0.80)
    assert (direct_actions[1].crosshair_x, direct_actions[1].crosshair_y) == (0.5, 0.5)
    assert all(not action.action_id.startswith("click_target_visual:") for action in direct_actions)

    controller_type._handle_gaze_click_candidate_changed(controller, "click_target:0")
    assert overlay.target_calls[-1][0] == (220, 140, 120, 36)
    controller_type._handle_gaze_click_candidate_changed(controller, "")
    assert overlay.clear_count == 1

    controller_type._handle_gaze_radial_action(controller, "click_target_inspect")
    assert controller._gaze_click_visual_page == 0
    visual_actions, visual_options = captured_pages[-1]
    assert len([action for action in visual_actions if action.preview_png]) == 4
    assert [action.action_id for action in visual_actions] == [
        "click_target_visual:0",
        "click_target_visual:1",
        "click_target_visual:2",
        "click_target_visual:3",
        "click_target_automation_status",
        "click_target_visual_next",
    ]
    assert all(
        not action.preview_png
        for action in visual_actions
        if action.action_id in {"click_target_automation_status", "click_target_visual_next"}
    )
    assert visual_options["enlarged_visual"] is True
    assert (visual_actions[0].crosshair_x, visual_actions[0].crosshair_y) == (0.80, 0.25)
    assert overlay.candidate_calls[-1][1] == ""
    assert [item[0] for item in overlay.candidate_calls[-1][0]] == [
        "click_target_visual:0",
        "click_target_visual:1",
        "click_target_visual:2",
        "click_target_visual:3",
    ]

    controller_type._handle_gaze_click_candidate_changed(controller, "click_target_visual:2")
    candidates, active_id, _theme = overlay.candidate_calls[-1]
    assert active_id == "click_target_visual:2"
    assert len(candidates) == 4

    controller_type._handle_gaze_radial_action(controller, "click_target_visual_next")
    assert controller._gaze_click_visual_page == 1
    next_actions, _next_options = captured_pages[-1]
    assert [action.action_id for action in next_actions] == [
        "click_target_visual:4",
        "click_target_visual:5",
        "click_target_automation_status",
        "click_target_visual_previous",
    ]

    controller._show_gaze_radial_main_menu = lambda _point: True
    controller_type._handle_gaze_radial_action(controller, "back")
    assert [action.action_id for action in captured_pages[-1][0]] == [
        "click_target:0",
        "click_target:1",
        "click_target_inspect",
        "click_target_automation_status",
    ]
    assert tuple(controller._gaze_click_targets) == (
        "click_target:0",
        "click_target:1",
    )
    controller_type._handle_gaze_radial_action(controller, "click_target_inspect")
    controller_type._handle_gaze_radial_action(controller, "click_target_visual_next")

    clicked_points = []
    inspect_requests = []
    controller._dismiss_gaze_radial_menu = lambda: overlay.clear_target()
    controller._queue_gaze_left_click = clicked_points.append
    controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1920.0, 1080.0)
    controller._gaze_click_visual_context_bounds = (
        lambda target: controller_type._gaze_click_visual_context_bounds(controller, target)
    )
    controller._queue_gaze_radial_context_action = (
        lambda action_id, point, **kwargs: inspect_requests.append(
            (action_id, tuple(point), list(kwargs.get("bounds_override") or []))
        )
        or {"ok": True, "queued": True}
    )
    controller._dispatch_gaze_click_visual_action = (
        lambda action_id: controller_type._dispatch_gaze_click_visual_action(controller, action_id)
    )
    controller_type._handle_gaze_radial_action(controller, "click_target_visual:4")
    assert clicked_points == []
    assert controller._gaze_click_visual_selected_index == 4
    assert controller._gaze_click_visual_action_menu_open is True
    assert controller._gaze_click_visual_page_open is False
    context_actions, context_options = captured_pages[-1]
    assert [action.action_id for action in context_actions] == [
        "click_target_visual_action:inspect",
        "click_target_visual_action:read",
        "click_target_visual_action:read_comment",
        "click_target_visual_action:comment",
    ]
    assert [action.label for action in context_actions] == [
        "Inspect",
        "Read text",
        "Read + comment",
        "Comment",
    ]
    assert context_options["title"] == "Context action"
    controller_type._handle_gaze_click_candidate_changed(
        controller,
        "click_target_visual_action:read",
    )
    assert overlay.target_calls[-1][0] == tuple(visual_payload[4]["bounds"])

    controller_type._handle_gaze_radial_action(controller, "back")
    assert controller._gaze_click_visual_action_menu_open is False
    assert [action.action_id for action in captured_pages[-1][0]] == [
        "click_target_visual:4",
        "click_target_visual:5",
        "click_target_automation_status",
        "click_target_visual_previous",
    ]

    controller_type._handle_gaze_radial_action(controller, "click_target_visual:0")
    assert clicked_points == []
    controller_type._handle_gaze_radial_action(
        controller,
        "click_target_visual_action:inspect",
    )
    assert clicked_points == []
    assert inspect_requests == [
        ("react", (228.0, 292.0), [138, 228, 180, 128]),
    ]
    controller_type._handle_gaze_radial_action(controller, "click_target_visual:4")
    controller_type._handle_gaze_radial_action(
        controller,
        "click_target_visual_action:inspect",
    )
    assert clicked_points == []
    assert inspect_requests == [
        ("react", (228.0, 292.0), [138, 228, 180, 128]),
        ("react", (508.0, 292.0), [418, 228, 180, 128]),
    ]
    controller_type._handle_gaze_radial_action(controller, "click_target_visual:-1")
    assert clicked_points == []
    assert len(inspect_requests) == 2

    reading_controller = type("Task4ReadingDispatchDouble", (), {})()
    reading_controller._gaze_click_visual_targets = [visual_payload[0]]
    reading_controller._gaze_click_visual_selected_index = 0
    reading_controller._click_target_from_payload = controller_type._click_target_from_payload
    reading_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1920.0, 1080.0)
    reading_controller._gaze_click_visual_context_bounds = (
        lambda target: controller_type._gaze_click_visual_context_bounds(reading_controller, target)
    )
    reading_controller._dismiss_gaze_radial_menu = lambda: None
    reading_controller._eye_tracking_status_message = ""
    begin_calls: list[str] = []
    reading_calls: list[tuple[object, dict[str, object]]] = []

    def begin_reading(action_id):
        begin_calls.append(str(action_id))
        return True

    reading_controller._begin_reading_job = begin_reading
    reading_controller._start_reading_worker = (
        lambda action, **kwargs: reading_calls.append((action, dict(kwargs)))
    )
    expected_reading_actions = {
        "read": "select_area_read",
        "read_comment": "select_area_read_comment",
        "comment": "select_area_comment",
    }
    for suffix, expected_action_id in expected_reading_actions.items():
        reading_controller._gaze_click_visual_selected_index = 0
        result = controller_type._dispatch_gaze_click_visual_action(
            reading_controller,
            suffix,
        )
        assert result == {"ok": True, "queued": True}
        action, kwargs = reading_calls[-1]
        assert action.action_id == expected_action_id
        assert begin_calls[-1] == expected_action_id
        assert kwargs["selected_text"] == ""
        assert kwargs["bounds"] == [138, 228, 180, 128]
        assert kwargs["private_bounds"] is True

    bounded_dispatch = type("Task4BoundedContextDispatchDouble", (), {})()
    bounded_dispatch._eye_tracking_reaction_shutting_down = False
    bounded_dispatch._gaze_context_dispatch_generation = 0
    bounded_calls = []
    bounded_dispatch._try_gaze_radial_context_action = (
        lambda action_id, point, generation, attempt, **kwargs: bounded_calls.append(
            (
                action_id,
                tuple(point),
                generation,
                attempt,
                list(kwargs.get("bounds_override") or []),
            )
        )
        or {"ok": True, "queued": True}
    )
    bounded_result = controller_type._queue_gaze_radial_context_action(
        bounded_dispatch,
        "react",
        (228.0, 292.0),
        bounds_override=[138, 228, 180, 128],
    )
    assert bounded_result == {"ok": True, "queued": True}
    assert bounded_calls == [
        ("react", (228.0, 292.0), 1, 0, [138, 228, 180, 128]),
    ]

    stale_pages = len(captured_pages)
    stale_targets = dict(controller._gaze_click_targets)
    controller_type._handle_gaze_click_targets_result(
        controller,
        {**payload, "generation": 6, "direct": [], "visual": []},
    )
    assert len(captured_pages) == stale_pages
    assert controller._gaze_click_targets == stale_targets

    controller_type._handle_gaze_radial_action(controller, "back")
    assert overlay.clear_count >= 3

    controller._gaze_click_scan_generation = 20
    controller._gaze_radial_menu_open = True
    controller_type._handle_gaze_click_targets_result(
        controller,
        {
            **payload,
            "generation": 20,
            "automation_available": False,
            "automation_timed_out": False,
            "direct": [],
        },
    )
    visual_only_actions = captured_pages[-1][0]
    assert controller._gaze_click_visual_page_open is True
    assert len([action for action in visual_only_actions if action.preview_png]) == 4
    assert next(
        action for action in visual_only_actions if action.action_id == "click_target_automation_status"
    ).label == "App controls unavailable"

    controller._gaze_click_scan_generation = 21
    controller_type._handle_gaze_click_targets_result(
        controller,
        {
            **payload,
            "generation": 21,
            "automation_available": False,
            "automation_timed_out": False,
            "direct": [],
            "visual": [],
            "error": "Click targets could not be scanned.",
        },
    )
    assert [action.action_id for action in captured_pages[-1][0]] == [
        "click_target_unavailable",
        "click_target_automation_status",
    ]

    class TrapLock:
        def __init__(self):
            self.acquire_count = 0

        def acquire(self, *, blocking):
            assert blocking is False
            self.acquire_count += 1
            return True

        def release(self):
            raise AssertionError("A disabled scan must not acquire or release the capture lock.")

    disabled_scan = type("DisabledScanControllerDouble", (), {})()
    disabled_scan._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": False,
    }
    disabled_scan._gaze_click_target_enabled = lambda: controller_type._gaze_click_target_enabled(
        disabled_scan
    )
    disabled_scan._snapshot_capture_lock = TrapLock()
    disabled_scan._proxy = type(
        "ProxyDouble",
        (),
        {"eye_click_targets_requested": type("SignalDouble", (), {"emit": lambda *_args: None})()},
    )()
    controller_type._scan_gaze_click_targets(disabled_scan, [0, 0, 800, 600], (400.0, 300.0), 9)
    assert disabled_scan._snapshot_capture_lock.acquire_count == 0

    class OrderedLock:
        def __init__(self, calls):
            self.calls = calls
            self.locked = False

        def acquire(self, *, blocking):
            assert blocking is False
            self.calls.append("lock")
            self.locked = True
            return True

        def release(self):
            self.calls.append("unlock")
            self.locked = False

    from addons.companion_orb_overlay.companion_orb import (
        reading_overlay,
        snapshot_ocr,
        windows_ui_automation,
    )

    calls = []
    emitted_payloads = []
    original_discover = windows_ui_automation.discover_semantic_targets
    original_native = snapshot_ocr.extract_window_text_regions
    original_capture = reading_overlay.capture_region_image
    original_ocr = snapshot_ocr.extract_snapshot_regions
    original_aggregate = eye_tracking.aggregate_click_targets
    scan_semantic = eye_tracking.ClickTarget(
        "Open",
        (240, 180, 100, 32),
        "ButtonControl",
        1.0,
        "Button",
        "uia",
        True,
        (99, 4),
    )

    def assert_cloaked(name):
        assert "cloak:on" in calls and "cloak:off" not in calls
        calls.append(name)

    entry_calls = []
    stale_scan = type("StaleScanControllerDouble", (), {})()
    stale_scan._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    stale_scan._gaze_click_target_enabled = lambda: True
    stale_scan._gaze_click_scan_generation = 11
    stale_scan._snapshot_capture_lock = type(
        "EntryLock",
        (),
        {"acquire": lambda _self, **_kwargs: entry_calls.append("lock") or False},
    )()
    stale_scan._apply_snapshot_cloak_blocking = lambda enabled: entry_calls.append(
        f"cloak:{enabled}"
    ) or True
    stale_scan._proxy = type(
        "ProxyDouble",
        (),
        {
            "eye_click_targets_requested": type(
                "SignalDouble",
                (),
                {"emit": lambda _self, _value: entry_calls.append("emit")},
            )()
        },
    )()
    controller_type._scan_gaze_click_targets(
        stale_scan,
        [100, 100, 900, 650],
        (400.0, 240.0),
        10,
    )
    assert entry_calls == []

    mid_calls = []
    mid_payloads = []
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_path = Path(temp_dir) / "mid-scan.png"
            capture_path.write_bytes(b"temporary")
            mid_scan = type("MidScanControllerDouble", (), {})()
            mid_scan.context = type("ContextDouble", (), {"app_root": Path(temp_dir)})()
            mid_scan._last_runtime_config = {
                "companion_orb_eye_tracking_click_target_enabled": True,
            }
            mid_scan._gaze_click_target_enabled = lambda: True
            mid_scan._gaze_click_scan_generation = 12
            mid_scan._snapshot_capture_lock = OrderedLock(mid_calls)
            mid_scan._apply_snapshot_cloak_blocking = lambda enabled: (
                mid_calls.append(f"cloak:{'on' if enabled else 'off'}") or True
            )
            mid_scan._click_target_preview_png = lambda *_args, **_kwargs: b"preview"
            mid_scan._serialize_click_target = lambda target, output_path, capture_bounds, **kwargs: (
                controller_type._serialize_click_target(
                    mid_scan,
                    target,
                    output_path,
                    capture_bounds,
                    **kwargs,
                )
            )
            mid_scan._proxy = type(
                "ProxyDouble",
                (),
                {
                    "eye_click_targets_requested": type(
                        "SignalDouble",
                        (),
                        {"emit": lambda _self, value: mid_payloads.append(value)},
                    )()
                },
            )()

            def invalidate_during_uia(*_args, **_kwargs):
                mid_calls.append("uia")
                mid_scan._gaze_click_scan_generation += 1
                return windows_ui_automation.AutomationScanResult((scan_semantic,), True, False, "")

            windows_ui_automation.discover_semantic_targets = invalidate_during_uia
            snapshot_ocr.extract_window_text_regions = lambda *_args, **_kwargs: (
                mid_calls.append("native") or []
            )
            reading_overlay.capture_region_image = lambda *_args, **_kwargs: (
                mid_calls.append("capture") or capture_path
            )
            snapshot_ocr.extract_snapshot_regions = lambda *_args, **_kwargs: (
                mid_calls.append("ocr") or {"regions": []}
            )
            eye_tracking.aggregate_click_targets = lambda **_kwargs: (
                mid_calls.append("aggregate") or eye_tracking.ClickTargetSet((scan_semantic,), ())
            )
            controller_type._scan_gaze_click_targets(
                mid_scan,
                [100, 100, 900, 650],
                (400.0, 240.0),
                12,
            )
    finally:
        windows_ui_automation.discover_semantic_targets = original_discover
        snapshot_ocr.extract_window_text_regions = original_native
        reading_overlay.capture_region_image = original_capture
        snapshot_ocr.extract_snapshot_regions = original_ocr
        eye_tracking.aggregate_click_targets = original_aggregate

    assert mid_calls == ["lock", "cloak:on", "uia", "cloak:off", "unlock"], mid_calls
    assert mid_payloads == []

    try:
        windows_ui_automation.discover_semantic_targets = lambda *_args, **_kwargs: (
            assert_cloaked("uia")
            or windows_ui_automation.AutomationScanResult(
                (scan_semantic,),
                True,
                False,
                "private UIA details",
            )
        )
        snapshot_ocr.extract_window_text_regions = lambda *_args, **_kwargs: (
            assert_cloaked("native") or []
        )
        def extract_after_release(*_args, **_kwargs):
            assert "cloak:off" in calls and "unlock" in calls
            calls.append("ocr")
            return {"regions": []}

        def aggregate_in_current_phase(**_kwargs):
            if "cloak:off" in calls:
                assert "unlock" in calls
            else:
                assert "cloak:on" in calls
            calls.append("aggregate")
            return eye_tracking.ClickTargetSet((scan_semantic,), ())

        snapshot_ocr.extract_snapshot_regions = extract_after_release
        eye_tracking.aggregate_click_targets = aggregate_in_current_phase
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_path = (
                Path(temp_dir)
                / "runtime"
                / "companion_orb"
                / "click_targets"
                / "scan.png"
            )
            capture_path.parent.mkdir(parents=True)
            capture_path.write_bytes(b"temporary")
            reading_overlay.capture_region_image = lambda *_args, **_kwargs: (
                assert_cloaked("capture") or capture_path
            )
            scan_controller = type("ScanControllerDouble", (), {})()
            scan_controller.context = type("ContextDouble", (), {"app_root": Path(temp_dir)})()
            scan_controller._last_runtime_config = {
                "companion_orb_eye_tracking_click_target_enabled": True,
            }
            scan_controller._gaze_click_target_enabled = lambda: True
            scan_controller._gaze_click_scan_generation = 12
            scan_controller._snapshot_capture_lock = OrderedLock(calls)
            scan_controller._apply_snapshot_cloak_blocking = lambda enabled: (
                calls.append(f"cloak:{'on' if enabled else 'off'}") or True
            )
            scan_controller._click_target_preview_png = lambda *_args, **_kwargs: b"preview"
            scan_controller._click_target_preview = lambda *_args, **_kwargs: (
                b"preview",
                (0.5, 0.5),
            )
            scan_controller._serialize_click_target = lambda target, output_path, capture_bounds, **kwargs: (
                controller_type._serialize_click_target(
                    scan_controller,
                    target,
                    output_path,
                    capture_bounds,
                    **kwargs,
                )
            )
            scan_controller._proxy = type(
                "ProxyDouble",
                (),
                {
                    "eye_click_targets_requested": type(
                        "SignalDouble",
                        (),
                        {"emit": lambda _self, value: emitted_payloads.append(value)},
                    )()
                },
            )()
            controller_type._scan_gaze_click_targets(
                scan_controller,
                [100, 100, 900, 650],
                (400.0, 240.0),
                12,
            )
    finally:
        windows_ui_automation.discover_semantic_targets = original_discover
        snapshot_ocr.extract_window_text_regions = original_native
        reading_overlay.capture_region_image = original_capture
        snapshot_ocr.extract_snapshot_regions = original_ocr
        eye_tracking.aggregate_click_targets = original_aggregate

    assert calls == [
        "lock",
        "cloak:on",
        "uia",
        "aggregate",
        "native",
        "capture",
        "cloak:off",
        "unlock",
        "ocr",
        "aggregate",
    ], calls
    assert len(emitted_payloads) == 1
    emitted = emitted_payloads[0]
    assert emitted["automation_available"] is True
    assert emitted["automation_timed_out"] is False
    assert emitted["direct"][0]["runtime_id"] == [99, 4]
    assert "private UIA details" not in repr(emitted)
    assert all(
        isinstance(value, (type(None), bool, int, float, str, bytes, list, dict))
        for value in emitted.values()
    )

    capture_failure_calls = []
    capture_failure_payloads = []
    try:
        windows_ui_automation.discover_semantic_targets = lambda *_args, **_kwargs: (
            capture_failure_calls.append("uia")
            or windows_ui_automation.AutomationScanResult((scan_semantic,), True, False, "")
        )
        snapshot_ocr.extract_window_text_regions = lambda *_args, **_kwargs: (
            capture_failure_calls.append("native") or []
        )
        eye_tracking.aggregate_click_targets = lambda **_kwargs: (
            capture_failure_calls.append("aggregate")
            or eye_tracking.ClickTargetSet((scan_semantic,), ())
        )

        def fail_capture(*_args, **_kwargs):
            capture_failure_calls.append("capture")
            raise RuntimeError("sensitive capture details")

        reading_overlay.capture_region_image = fail_capture
        with tempfile.TemporaryDirectory() as temp_dir:
            failure_controller = type("CaptureFailureControllerDouble", (), {})()
            failure_controller.context = type("ContextDouble", (), {"app_root": Path(temp_dir)})()
            failure_controller._last_runtime_config = {
                "companion_orb_eye_tracking_click_target_enabled": True,
            }
            failure_controller._gaze_click_target_enabled = lambda: True
            failure_controller._gaze_click_scan_generation = 13
            failure_controller._snapshot_capture_lock = OrderedLock(capture_failure_calls)
            failure_controller._apply_snapshot_cloak_blocking = lambda enabled: (
                capture_failure_calls.append(f"cloak:{'on' if enabled else 'off'}") or True
            )
            failure_controller._click_target_preview_png = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("A target without a captured image must not request a preview.")
            )
            failure_controller._serialize_click_target = (
                lambda target, output_path, capture_bounds, **kwargs: controller_type._serialize_click_target(
                    failure_controller,
                    target,
                    output_path,
                    capture_bounds,
                    **kwargs,
                )
            )
            failure_controller._proxy = type(
                "ProxyDouble",
                (),
                {
                    "eye_click_targets_requested": type(
                        "SignalDouble",
                        (),
                        {"emit": lambda _self, value: capture_failure_payloads.append(value)},
                    )()
                },
            )()
            controller_type._scan_gaze_click_targets(
                failure_controller,
                [100, 100, 900, 650],
                (400.0, 240.0),
                13,
            )
    finally:
        windows_ui_automation.discover_semantic_targets = original_discover
        snapshot_ocr.extract_window_text_regions = original_native
        reading_overlay.capture_region_image = original_capture
        snapshot_ocr.extract_snapshot_regions = original_ocr
        eye_tracking.aggregate_click_targets = original_aggregate

    assert capture_failure_calls == [
        "lock",
        "cloak:on",
        "uia",
        "aggregate",
        "native",
        "capture",
        "cloak:off",
        "unlock",
        "aggregate",
    ], capture_failure_calls
    assert len(capture_failure_payloads) == 1
    capture_failure_payload = capture_failure_payloads[0]
    assert capture_failure_payload["direct"][0]["runtime_id"] == [99, 4]
    assert capture_failure_payload["direct"][0]["preview_png"] == b""
    assert capture_failure_payload["visual"] == []
    assert capture_failure_payload["error"] == "Click targets could not be scanned."
    assert "sensitive capture details" not in repr(capture_failure_payload)

    class FakeSignal:
        def __init__(self):
            self.connections = []

        def connect(self, *args):
            self.connections.append(args)

    class FakeMenu:
        def __init__(self):
            self.action_selected = FakeSignal()
            self.cancelled = FakeSignal()
            self.candidate_changed = FakeSignal()

    menu_controller = type("MenuControllerDouble", (), {})()
    menu_controller._gaze_radial_menu = None
    menu_controller._handle_gaze_radial_action = lambda _action_id: None
    menu_controller._finish_gaze_radial_menu = lambda: None
    menu_controller._handle_gaze_click_candidate_changed = lambda _action_id: None
    original_menu_type = companion_orb_controller.gaze_radial_menu.GazeRadialMenu
    try:
        companion_orb_controller.gaze_radial_menu.GazeRadialMenu = FakeMenu
        menu = controller_type._ensure_gaze_radial_menu(menu_controller)
    finally:
        companion_orb_controller.gaze_radial_menu.GazeRadialMenu = original_menu_type
    assert len(menu.candidate_changed.connections) == 1
    assert menu.candidate_changed.connections[0][1] == QtCore.Qt.QueuedConnection

    overlay_instances = []
    original_overlay_type = companion_orb_controller.click_target_overlay.ClickTargetHighlightOverlay
    try:
        companion_orb_controller.click_target_overlay.ClickTargetHighlightOverlay = lambda: (
            overlay_instances.append(FakeHighlightOverlay()) or overlay_instances[-1]
        )
        lazy_controller = type("LazyOverlayControllerDouble", (), {})()
        lazy_controller._gaze_click_target_highlight = None
        first_overlay = controller_type._ensure_gaze_click_target_highlight_overlay(lazy_controller)
        second_overlay = controller_type._ensure_gaze_click_target_highlight_overlay(lazy_controller)
    finally:
        companion_orb_controller.click_target_overlay.ClickTargetHighlightOverlay = original_overlay_type
    assert first_overlay is second_overlay
    assert len(overlay_instances) == 1


def _assert_controller_task_5_contract(companion_orb_controller, eye_tracking) -> None:
    controller_type = companion_orb_controller.CompanionOrbController
    semantic = eye_tracking.ClickTarget(
        label="  Save\t",
        bounds=(220, 140, 120, 36),
        kind=" ButtonControl ",
        confidence=1.0,
        role=" Button ",
        source=" UIA ",
        semantic=True,
        runtime_id=(10, 1),
    )
    native = eye_tracking.ClickTarget(
        label="Apply",
        bounds=(590, 140, 120, 36),
        kind="win32_control",
        confidence=0.9,
        role="Button",
        source="win32",
        semantic=False,
    )

    emitted = []
    started_threads = []
    validation_results = []

    class PrimitiveSignal:
        def emit(self, *args):
            emitted.append(args)

    class ImmediateDaemonThread:
        def __init__(self, *, target, args, daemon, name):
            assert daemon is True
            assert name == "companion-orb-click-target-validation"
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started_threads.append(self)
            self.target(*self.args)

    controller = type("Task5ControllerDouble", (), {})()
    controller._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    controller._gaze_click_scan_generation = 41
    controller._gaze_click_validation_generation = 0
    controller._gaze_radial_menu_open = True
    controller._eye_tracking_reaction_shutting_down = False
    controller._gaze_click_targets = {
        "click_target:0": semantic,
        "click_target:1": native,
    }
    controller._gaze_click_validation_pending = None
    controller._gaze_click_validation_cloak_active = False
    controller._gaze_click_validation_cloak_token = None
    controller._proxy = type(
        "ProxyDouble",
        (),
        {"eye_click_validation_requested": PrimitiveSignal()},
    )()
    controller.hidden = 0
    controller.dismissed = 0
    controller.scan_calls = 0
    controller.clicks = []
    controller.cloak_calls = []
    controller._gaze_click_target_enabled = lambda: bool(
        controller._last_runtime_config["companion_orb_eye_tracking_click_target_enabled"]
    )
    controller._hide_gaze_click_target_source_visuals = lambda: setattr(
        controller,
        "hidden",
        controller.hidden + 1,
    )
    controller._dismiss_gaze_radial_menu = lambda: setattr(
        controller,
        "dismissed",
        controller.dismissed + 1,
    )
    controller._show_gaze_click_target_menu = lambda: setattr(
        controller,
        "scan_calls",
        controller.scan_calls + 1,
    )
    controller._set_snapshot_cloak = lambda enabled: controller.cloak_calls.append(bool(enabled))
    controller._cancel_gaze_click_validation = lambda: (
        controller_type._cancel_gaze_click_validation(controller)
    )
    controller._consume_gaze_click_validation = lambda token, **kwargs: (
        controller_type._consume_gaze_click_validation(controller, token, **kwargs)
    )
    controller._handle_gaze_click_validation_watchdog = lambda token: (
        controller_type._handle_gaze_click_validation_watchdog(controller, token)
    )
    controller._queue_gaze_left_click = lambda point, **kwargs: (
        controller.clicks.append(point)
        or (
            controller._set_snapshot_cloak(False)
            if kwargs.get("cloak_already_active")
            else None
        )
    )
    controller._validate_gaze_semantic_target_click = (
        lambda target, point, generation, action_id, runtime_id, validation_token: (
            controller_type._validate_gaze_semantic_target_click(
                controller,
                target,
                point,
                generation,
                action_id,
                runtime_id,
                validation_token,
            )
        )
    )
    controller._queue_confirmed_target_click = lambda target, *, action_id: (
        controller_type._queue_confirmed_target_click(
            controller,
            target,
            action_id=action_id,
        )
    )

    def request_result(valid: bool) -> tuple:
        controller._gaze_click_targets["click_target:0"] = semantic
        validation_results.append(bool(valid))
        original_thread = companion_orb_controller.threading.Thread
        original_validate = companion_orb_controller.windows_ui_automation.validate_semantic_target
        try:
            companion_orb_controller.threading.Thread = ImmediateDaemonThread
            companion_orb_controller.windows_ui_automation.validate_semantic_target = (
                lambda target, point: (
                    target is semantic
                    and point == semantic.center
                    and validation_results.pop(0)
                )
            )
            controller_type._handle_gaze_radial_action(
                controller,
                "click_target:0",
            )
        finally:
            companion_orb_controller.threading.Thread = original_thread
            companion_orb_controller.windows_ui_automation.validate_semantic_target = original_validate
        return emitted[-1]

    valid_result = request_result(True)

    assert len(started_threads) == 1
    assert started_threads[0].daemon is True
    assert controller.hidden == 1
    assert emitted == [(41, "click_target:0", [10, 1], True, 1)]
    assert all(
        isinstance(value, (bool, int, str, list))
        for value in emitted[0]
    )

    controller_type._handle_gaze_click_validation_result(controller, *valid_result)
    assert controller.dismissed == 1
    assert controller.clicks == [semantic.center]
    assert controller.scan_calls == 0
    controller_type._handle_gaze_click_validation_result(controller, *valid_result)
    assert controller.clicks == [semantic.center]

    invalid_result = request_result(False)
    controller_type._handle_gaze_click_validation_result(controller, *invalid_result)
    assert controller.clicks == [semantic.center]
    assert controller.scan_calls == 1
    controller_type._handle_gaze_click_validation_result(controller, *invalid_result)
    assert controller.scan_calls == 1

    stale_result = request_result(True)
    controller._gaze_click_scan_generation += 1
    controller_type._handle_gaze_click_validation_result(controller, *stale_result)
    assert controller.clicks == [semantic.center]
    assert controller.scan_calls == 1

    controller._gaze_click_scan_generation += 1
    disabled_result = request_result(True)
    controller._last_runtime_config[
        "companion_orb_eye_tracking_click_target_enabled"
    ] = False
    controller_type._handle_gaze_click_validation_result(controller, *disabled_result)
    assert controller.clicks == [semantic.center]
    assert controller.scan_calls == 1

    controller._last_runtime_config[
        "companion_orb_eye_tracking_click_target_enabled"
    ] = True
    shutdown_result = request_result(True)
    controller._eye_tracking_reaction_shutting_down = True
    controller_type._handle_gaze_click_validation_result(controller, *shutdown_result)
    assert controller.clicks == [semantic.center]
    assert controller.scan_calls == 1
    controller._eye_tracking_reaction_shutting_down = False

    remapped_result = request_result(True)
    remapped = eye_tracking.ClickTarget(
        label="Open",
        bounds=(520, 360, 180, 48),
        kind="HyperlinkControl",
        confidence=1.0,
        role="Link",
        source="uia",
        semantic=True,
        runtime_id=semantic.runtime_id,
    )
    controller._gaze_click_targets["click_target:0"] = remapped
    controller_type._handle_gaze_click_validation_result(controller, *remapped_result)
    assert controller.clicks == [semantic.center]
    assert controller.scan_calls == 2
    assert controller._gaze_click_validation_pending is None
    controller_type._handle_gaze_click_validation_result(controller, *remapped_result)
    assert controller.scan_calls == 2

    missing_mapping_result = request_result(True)
    controller._gaze_click_targets.pop("click_target:0")
    controller_type._handle_gaze_click_validation_result(controller, *missing_mapping_result)
    assert controller.clicks == [semantic.center]
    assert controller.scan_calls == 3
    assert controller._gaze_click_validation_pending is None
    controller_type._handle_gaze_click_validation_result(controller, *missing_mapping_result)
    assert controller.scan_calls == 3

    fingerprint_result = request_result(True)
    expected_fingerprint = (
        "Save",
        "Button",
        "uia",
        True,
        (10, 1),
        (220, 140, 120, 36),
        "ButtonControl",
    )
    assert controller._gaze_click_validation_pending == (
        controller._gaze_click_scan_generation,
        "click_target:0",
        semantic.runtime_id,
        expected_fingerprint,
        semantic.center,
        controller._gaze_click_validation_generation,
    )

    def primitive_only(value) -> bool:
        if isinstance(value, tuple):
            return all(primitive_only(item) for item in value)
        return isinstance(value, (bool, int, float, str))

    assert primitive_only(controller._gaze_click_validation_pending)
    controller_type._handle_gaze_click_validation_result(controller, *fingerprint_result)
    assert controller.clicks == [semantic.center, semantic.center]
    assert controller._gaze_click_validation_pending is None

    changed_mapping_result = request_result(True)
    controller._gaze_click_targets["click_target:0"] = eye_tracking.ClickTarget(
        label="Save",
        bounds=semantic.bounds,
        kind=semantic.kind,
        confidence=semantic.confidence,
        role=semantic.role,
        source=semantic.source,
        semantic=True,
        runtime_id=(99, 4),
    )
    controller_type._handle_gaze_click_validation_result(controller, *changed_mapping_result)
    assert controller.clicks == [semantic.center, semantic.center]
    assert controller.scan_calls == 4
    assert controller._gaze_click_validation_pending is None

    class TrapThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Nonsemantic targets must bypass UIA validation.")

    controller._gaze_click_targets["click_target:1"] = native
    clicks_before_native_direct = list(controller.clicks)
    original_thread = companion_orb_controller.threading.Thread
    try:
        companion_orb_controller.threading.Thread = TrapThread
        controller_type._handle_gaze_radial_action(
            controller,
            "click_target:1",
        )
    finally:
        companion_orb_controller.threading.Thread = original_thread
    assert controller.clicks == clicks_before_native_direct

    visual_controller = type("Task5VisualControllerDouble", (), {})()
    visual_controller._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    visual_controller._gaze_click_visual_targets = [{
        "label": "",
        "bounds": [100, 100, 80, 40],
        "kind": "zoom_tile",
        "confidence": 0.25,
        "role": "",
        "source": "fallback",
        "semantic": False,
        "runtime_id": [],
    }]
    visual_controller._gaze_click_target_enabled = lambda: True
    visual_controller._click_target_from_payload = controller_type._click_target_from_payload
    visual_controller._gaze_click_visual_selected_index = 0
    visual_controller._dismiss_gaze_radial_menu = lambda: None
    visual_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1920.0, 1080.0)
    visual_controller._gaze_click_visual_context_bounds = (
        lambda target: controller_type._gaze_click_visual_context_bounds(
            visual_controller,
            target,
        )
    )
    visual_controller.inspect_requests = []
    visual_controller._queue_gaze_radial_context_action = (
        lambda action_id, point, **kwargs: visual_controller.inspect_requests.append(
            (action_id, tuple(point), list(kwargs.get("bounds_override") or []))
        )
        or {"ok": True, "queued": True}
    )
    visual_controller.clicks = []
    visual_controller._queue_gaze_left_click = visual_controller.clicks.append
    result = controller_type._dispatch_gaze_click_visual_action(
        visual_controller,
        "inspect",
    )
    assert result == {"ok": True, "queued": True}
    assert visual_controller.clicks == []
    assert visual_controller.inspect_requests == [
        ("react", (140.0, 120.0), [50, 66, 180, 108]),
    ]


def _assert_safety_b_validation_cloak_contract(companion_orb_controller, eye_tracking) -> None:
    controller_type = companion_orb_controller.CompanionOrbController
    semantic = eye_tracking.ClickTarget(
        label="Save",
        bounds=(220, 140, 120, 36),
        kind="ButtonControl",
        confidence=1.0,
        role="Button",
        source="uia",
        semantic=True,
        runtime_id=(10, 1),
    )
    timers = []
    threads = []
    events = []
    enabled = [True]

    class DeferredDaemonThread:
        def __init__(self, *, target, args, daemon, name):
            assert daemon is True
            assert name == "companion-orb-click-target-validation"
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            threads.append(self)
            events.append(
                (
                    "validator:start",
                    controller.cloak_count,
                    controller._gaze_click_validation_cloak_active,
                )
            )

    class CapturingTimer:
        @staticmethod
        def singleShot(delay_ms, callback):
            timers.append((int(delay_ms), callback))

    controller = type("SafetyBValidationControllerDouble", (), {})()
    controller._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    controller._gaze_click_scan_generation = 9
    controller._gaze_click_validation_generation = 0
    controller._gaze_click_validation_pending = None
    controller._gaze_click_validation_cloak_active = False
    controller._gaze_click_validation_cloak_token = None
    controller._gaze_radial_menu_open = True
    controller._gaze_click_target_page_open = True
    controller._eye_tracking_reaction_shutting_down = False
    controller._gaze_click_targets = {"click_target:0": semantic}
    controller._gaze_click_target_payloads = {}
    controller._gaze_click_visual_targets = []
    controller._gaze_click_visual_page_open = False
    controller._eye_tracking_interaction_source_point = None
    controller._eye_tracking_interaction_target = None
    controller._eye_tracking_interaction_until = 0.0
    controller._eye_tracking_last_external_target = None
    controller._eye_tracking_last_external_sent_at = 0.0
    controller._eye_tracking_latest_point = (300.0, 200.0)
    controller._gaze_radial_anchor = QtCore.QPoint(300, 200)
    controller.cloak_count = 0
    controller.cloak_calls = []
    controller.dismissed = 0
    controller.rescans = 0
    controller.clicks = []

    def set_cloak(active):
        controller.cloak_calls.append(bool(active))
        controller.cloak_count += 1 if active else -1
        assert controller.cloak_count >= 0
        events.append((f"cloak:{'on' if active else 'off'}", controller.cloak_count))

    controller._set_snapshot_cloak = set_cloak
    controller._gaze_click_target_enabled = lambda: enabled[0]
    controller._hide_gaze_click_target_source_visuals = lambda: events.append(("hide",))
    controller._dismiss_gaze_radial_menu = lambda: setattr(
        controller,
        "dismissed",
        controller.dismissed + 1,
    )
    controller._show_gaze_click_target_menu = lambda: setattr(
        controller,
        "rescans",
        controller.rescans + 1,
    )
    controller._show_gaze_radial_main_menu = lambda _point: True
    controller._clear_gaze_click_target_highlight = lambda: None
    controller._send_external_runtime = lambda _payload: None
    controller._perform_gaze_left_click = lambda point: controller.clicks.append(point) or True
    controller._validate_gaze_semantic_target_click = lambda *_args: None
    controller._cancel_gaze_click_validation = lambda: (
        controller_type._cancel_gaze_click_validation(controller)
    )
    controller._consume_gaze_click_validation = lambda token, **kwargs: (
        controller_type._consume_gaze_click_validation(controller, token, **kwargs)
    )
    controller._handle_gaze_click_validation_watchdog = lambda token: (
        controller_type._handle_gaze_click_validation_watchdog(controller, token)
    )
    controller._queue_gaze_left_click = lambda point, **kwargs: controller_type._queue_gaze_left_click(
        controller,
        point,
        **kwargs,
    )

    original_thread = companion_orb_controller.threading.Thread
    original_qtimer = companion_orb_controller.QtCore.QTimer
    companion_orb_controller.threading.Thread = DeferredDaemonThread
    companion_orb_controller.QtCore.QTimer = CapturingTimer
    try:
        def begin_validation():
            enabled[0] = True
            controller._last_runtime_config[
                "companion_orb_eye_tracking_click_target_enabled"
            ] = True
            controller._gaze_click_targets["click_target:0"] = semantic
            controller_type._queue_confirmed_target_click(
                controller,
                semantic,
                action_id="click_target:0",
            )
            pending = controller._gaze_click_validation_pending
            assert isinstance(pending, tuple) and len(pending) == 6
            return pending[-1]

        valid_token = begin_validation()
        assert threads[-1].daemon is True
        assert events.index(("cloak:on", 1)) < len(events) - 1
        assert events[-1] == ("validator:start", 1, True)
        assert controller.cloak_calls == [True]
        assert any(delay == 1000 for delay, _callback in timers)

        controller_type._handle_gaze_click_validation_result(
            controller,
            9,
            "click_target:0",
            [10, 1],
            True,
            valid_token,
        )
        assert controller.dismissed == 1
        assert controller.cloak_calls == [True]
        click_callback = next(callback for delay, callback in timers if delay == 55)
        click_callback()
        uncloak_callback = next(callback for delay, callback in timers if delay == 70)
        uncloak_callback()
        assert controller.clicks == [semantic.center]
        assert controller.cloak_calls == [True, False]
        assert controller.cloak_count == 0

        stale_watchdog = next(callback for delay, callback in timers if delay == 1000)
        stale_watchdog()
        controller_type._handle_gaze_click_validation_result(
            controller,
            9,
            "click_target:0",
            [10, 1],
            True,
            valid_token,
        )
        assert controller.cloak_calls == [True, False]
        assert controller.rescans == 0

        invalid_token = begin_validation()
        controller_type._handle_gaze_click_validation_result(
            controller,
            9,
            "click_target:0",
            [10, 1],
            False,
            invalid_token,
        )
        assert controller.cloak_calls[-2:] == [True, False]
        assert controller.cloak_count == 0
        assert controller.rescans == 1

        watchdog_token = begin_validation()
        watchdog_callback = [callback for delay, callback in timers if delay == 1000][-1]
        watchdog_callback()
        calls_after_watchdog = list(controller.cloak_calls)
        rescans_after_watchdog = controller.rescans
        assert calls_after_watchdog[-2:] == [True, False]
        assert controller.cloak_count == 0
        assert controller.rescans == 2
        controller_type._handle_gaze_click_validation_result(
            controller,
            9,
            "click_target:0",
            [10, 1],
            True,
            watchdog_token,
        )
        assert controller.cloak_calls == calls_after_watchdog
        assert controller.rescans == rescans_after_watchdog

        begin_validation()
        enabled[0] = False
        controller._last_runtime_config[
            "companion_orb_eye_tracking_click_target_enabled"
        ] = False
        controller_type._refresh_gaze_radial_menu_after_click_target_disable(
            controller,
            True,
        )
        assert controller.cloak_calls[-2:] == [True, False]
        assert controller.cloak_count == 0
        assert controller._gaze_click_validation_pending is None

        enabled[0] = True
        controller._last_runtime_config[
            "companion_orb_eye_tracking_click_target_enabled"
        ] = True
        controller._gaze_click_targets["click_target:0"] = semantic
        threads_before_reentrant_cancel = len(threads)
        timers_before_reentrant_cancel = len(timers)

        def reentrant_cancel_cloak(active):
            controller.cloak_calls.append(bool(active))
            controller.cloak_count += 1 if active else -1
            assert controller.cloak_count >= 0
            if active:
                controller_type._cancel_gaze_click_validation(controller)

        controller._set_snapshot_cloak = reentrant_cancel_cloak
        controller_type._queue_confirmed_target_click(
            controller,
            semantic,
            action_id="click_target:0",
        )
        assert controller._gaze_click_validation_pending is None
        assert controller._gaze_click_validation_cloak_active is False
        assert controller._gaze_click_validation_cloak_token is None
        assert controller.cloak_count == 0
        assert controller.cloak_calls[-2:] == [True, False]
        assert len(threads) == threads_before_reentrant_cancel
        assert len(timers) == timers_before_reentrant_cancel
    finally:
        companion_orb_controller.threading.Thread = original_thread
        companion_orb_controller.QtCore.QTimer = original_qtimer


def _assert_task_5_pending_cleanup(companion_orb_controller) -> None:
    controller_type = companion_orb_controller.CompanionOrbController

    class Resettable:
        def __init__(self):
            self.calls = 0

        def reset(self):
            self.calls += 1

    clear_controller = type("Task5ClearControllerDouble", (), {})()
    clear_controller._eye_tracking_policy = Resettable()
    clear_controller._blink_gesture_detector = Resettable()
    clear_controller._blink_click_policy = Resettable()
    clear_controller._eye_tracking_latest_point = (1.0, 2.0)
    clear_controller._eye_tracking_latest_at = 3.0
    clear_controller._eye_tracking_stable_point = (1.0, 2.0)
    clear_controller._eye_tracking_interaction_source_point = (1.0, 2.0)
    clear_controller._eye_tracking_interaction_target = object()
    clear_controller._eye_tracking_interaction_until = 4.0
    clear_controller._eye_tracking_last_external_target = object()
    clear_controller._eye_tracking_last_external_sent_at = 5.0
    clear_controller._gaze_context_dispatch_generation = 6
    clear_controller._gaze_click_scan_generation = 7
    clear_controller._gaze_click_validation_pending = ("pending",)
    clear_controller._gaze_click_validation_cloak_active = True
    clear_controller._gaze_click_validation_cloak_token = 1
    clear_controller.cloak_calls = []
    clear_controller._set_snapshot_cloak = lambda enabled: clear_controller.cloak_calls.append(
        bool(enabled)
    )
    clear_controller._cancel_gaze_click_validation = lambda: (
        controller_type._cancel_gaze_click_validation(clear_controller)
    )
    clear_controller._gaze_click_targets = {"target": object()}
    clear_controller._gaze_click_target_payloads = {"target": {}}
    clear_controller._gaze_click_visual_targets = [{}]
    clear_controller._gaze_click_visual_page_open = True
    clear_controller._gaze_click_target_page_open = True
    clear_controller._clear_gaze_click_target_highlight = lambda: None
    clear_controller._gaze_radial_menu = None
    clear_controller._gaze_radial_menu_open = True
    clear_controller._gaze_radial_context_point = (1.0, 2.0)
    clear_controller._gaze_radial_payloads = {"payload": object()}
    clear_controller._set_gaze_timer_state = lambda *_args, **_kwargs: None
    clear_controller._send_external_runtime = lambda _payload: None
    controller_type._clear_eye_tracking_state(clear_controller, send_external=False)
    assert clear_controller._gaze_click_validation_pending is None
    assert clear_controller._gaze_click_scan_generation == 8
    assert clear_controller.cloak_calls == [False]
    assert clear_controller._gaze_click_validation_cloak_active is False
    assert clear_controller._gaze_click_target_page_open is False
    _assert_task_5_finish_cleanup(companion_orb_controller)


def _assert_safety_c_coordinate_preview_cleanup_contract(
    companion_orb_controller,
    eye_tracking,
) -> None:
    controller_type = companion_orb_controller.CompanionOrbController

    legacy = eye_tracking.ClickTarget("Legacy", (10, 20, 40, 30), "control_text", 0.5)
    assert legacy.click_point is None
    assert legacy.center == (30.0, 35.0)
    exact = eye_tracking.ClickTarget(
        "Visual",
        (100, 100, 80, 40),
        source="fallback",
        click_point=[102.0, 104.0],
    )
    assert exact.click_point == (102.0, 104.0)
    assert exact.center == (102.0, 104.0)
    semantic_with_point = eye_tracking.ClickTarget(
        "Save",
        (100, 100, 80, 40),
        source="uia",
        semantic=True,
        runtime_id=(55, 1),
        click_point=[102.0, 104.0],
    )
    assert semantic_with_point.click_point is None
    assert semantic_with_point.center == (140.0, 120.0)
    assert eye_tracking.is_semantic_direct_target(semantic_with_point)
    for invalid in ((1.0,), (1.0, 2.0, 3.0), (math.nan, 2.0), "12"):
        target = eye_tracking.ClickTarget("Invalid", (10, 20, 40, 30), click_point=invalid)
        assert target.click_point is None
        assert target.center == (30.0, 35.0)

    focus = (400.25, 200.75)
    fallback_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[],
        regions=[],
        focus_point=focus,
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    focus_candidates = [target for target in fallback_result.visual if target.click_point == focus]
    assert len(focus_candidates) == 1
    assert focus_candidates[0].center == focus
    repeated = eye_tracking.aggregate_click_targets(
        semantic_targets=[],
        regions=[],
        focus_point=focus,
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert repeated.visual == fallback_result.visual

    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "scaled-edge.png"
        image = QtGui.QImage(400, 200, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("#185a87"))
        assert image.save(str(image_path), "PNG")
        png, crosshair = controller_type._click_target_preview(
            image_path,
            exact,
            [100, 100, 200, 100],
        )
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert abs(crosshair[0] - (4.0 / 360.0)) < 1e-6
        assert abs(crosshair[1] - (8.0 / 200.0)) < 1e-6
        assert crosshair != (0.5, 0.5)
        assert controller_type._click_target_preview_png(
            image_path,
            exact,
            [100, 100, 200, 100],
        ).startswith(b"\x89PNG\r\n\x1a\n")

        serializer = type("SafetyCSerializerDouble", (), {})()
        serializer._click_target_preview = controller_type._click_target_preview
        payload = controller_type._serialize_click_target(
            serializer,
            exact,
            image_path,
            [100, 100, 200, 100],
        )
    assert payload["click_point"] == [102.0, 104.0]
    assert payload["preview_crosshair"] == [crosshair[0], crosshair[1]]
    parsed = controller_type._click_target_from_payload(payload)
    assert parsed is not None
    assert parsed.click_point == exact.click_point
    assert parsed.center == exact.center

    def primitive_tree(value) -> bool:
        if isinstance(value, dict):
            return all(isinstance(key, str) and primitive_tree(item) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return all(primitive_tree(item) for item in value)
        return isinstance(value, (type(None), bool, int, float, str, bytes))

    assert primitive_tree(payload)
    assert controller_type._click_target_payload_crosshair({}) == (0.5, 0.5)
    assert controller_type._click_target_payload_crosshair(
        {"preview_crosshair": ["invalid", 0.25]}
    ) == (0.5, 0.5)
    assert controller_type._click_target_payload_crosshair(
        {"preview_crosshair": [2.0, -1.0]}
    ) == (1.0, 0.0)

    visual_controller = type("SafetyCVisualDispatchDouble", (), {})()
    visual_controller._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    visual_controller._gaze_click_visual_targets = [payload]
    visual_controller._gaze_click_target_enabled = lambda: True
    visual_controller._click_target_from_payload = controller_type._click_target_from_payload
    visual_controller._gaze_click_visual_selected_index = 0
    visual_controller._dismiss_gaze_radial_menu = lambda: None
    visual_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1920.0, 1080.0)
    visual_controller._gaze_click_visual_context_bounds = (
        lambda target: controller_type._gaze_click_visual_context_bounds(
            visual_controller,
            target,
        )
    )
    visual_controller.inspect_requests = []
    visual_controller._queue_gaze_radial_context_action = (
        lambda action_id, point, **kwargs: visual_controller.inspect_requests.append(
            (action_id, tuple(point), list(kwargs.get("bounds_override") or []))
        )
        or {"ok": True, "queued": True}
    )
    visual_controller.clicks = []
    visual_controller._queue_gaze_left_click = visual_controller.clicks.append
    result = controller_type._dispatch_gaze_click_visual_action(
        visual_controller,
        "inspect",
    )
    assert result == {"ok": True, "queued": True}
    assert visual_controller.clicks == []
    assert visual_controller.inspect_requests == [
        ("react", exact.click_point, [50, 66, 180, 108]),
    ]

    cleanup_source = _source_for_function(
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py",
        "_remove_click_target_capture",
        class_name="CompanionOrbController",
    )
    assert all(fragment not in cleanup_source for fragment in ("_log", "_debug_event", "print("))
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir) / "runtime" / "companion_orb" / "click_targets"
        output_dir.mkdir(parents=True)
        capture_path = output_dir / "sensitive-capture-name.png"
        capture_path.write_bytes(b"temporary")
        outsider = Path(temp_dir) / "outside.png"
        outsider.write_bytes(b"keep")
        calls: list[Path] = []
        delays: list[float] = []
        original_unlink = Path.unlink
        original_sleep = companion_orb_controller.time.sleep

        def flaky_unlink(path, *args, **kwargs):
            calls.append(Path(path))
            if Path(path) == capture_path and calls.count(capture_path) < 3:
                raise PermissionError("sensitive cleanup details")
            return original_unlink(path, *args, **kwargs)

        captured_output = io.StringIO()
        try:
            Path.unlink = flaky_unlink
            companion_orb_controller.time.sleep = delays.append
            with contextlib.redirect_stdout(captured_output), contextlib.redirect_stderr(captured_output):
                controller_type._remove_click_target_capture(capture_path, output_dir)
                controller_type._remove_click_target_capture(outsider, output_dir)
        finally:
            Path.unlink = original_unlink
            companion_orb_controller.time.sleep = original_sleep
        assert not capture_path.exists()
        assert outsider.exists()
        assert calls == [capture_path, capture_path, capture_path]
        assert delays == [0.01, 0.01]
        assert captured_output.getvalue() == ""

        failed_path = output_dir / "still-locked.png"
        failed_path.write_bytes(b"temporary")
        failed_calls = []

        def always_fail(path, *args, **kwargs):
            failed_calls.append(Path(path))
            raise PermissionError("sensitive cleanup details")

        try:
            Path.unlink = always_fail
            companion_orb_controller.time.sleep = lambda _delay: None
            controller_type._remove_click_target_capture(failed_path, output_dir)
        finally:
            Path.unlink = original_unlink
            companion_orb_controller.time.sleep = original_sleep
        assert failed_path.exists()
        assert failed_calls == [failed_path, failed_path, failed_path]


def _assert_task_5_finish_cleanup(companion_orb_controller) -> None:
    controller_type = companion_orb_controller.CompanionOrbController
    finish_controller = type("Task5FinishControllerDouble", (), {})()
    finish_controller._gaze_click_scan_generation = 10
    finish_controller._gaze_click_validation_pending = ("pending",)
    finish_controller._gaze_click_validation_cloak_active = True
    finish_controller._gaze_click_validation_cloak_token = 2
    finish_controller.cloak_calls = []
    finish_controller._set_snapshot_cloak = lambda enabled: finish_controller.cloak_calls.append(
        bool(enabled)
    )
    finish_controller._cancel_gaze_click_validation = lambda: (
        controller_type._cancel_gaze_click_validation(finish_controller)
    )
    finish_controller._gaze_click_targets = {"target": object()}
    finish_controller._gaze_click_target_payloads = {"target": {}}
    finish_controller._gaze_click_visual_targets = [{}]
    finish_controller._gaze_click_visual_page_open = True
    finish_controller._clear_gaze_click_target_highlight = lambda: None
    finish_controller._gaze_click_target_page_open = True
    finish_controller._gaze_radial_menu_open = True
    finish_controller._gaze_radial_context_point = (1.0, 2.0)
    finish_controller._gaze_radial_payloads = {"payload": object()}
    finish_controller._set_gaze_timer_state = lambda *_args, **_kwargs: None
    finish_controller._eye_tracking_interaction_target = object()
    finish_controller._eye_tracking_interaction_until = 4.0
    finish_controller._eye_tracking_last_external_target = object()
    finish_controller._eye_tracking_last_external_sent_at = 5.0
    finish_controller._send_external_runtime = lambda _payload: None
    finish_controller._mark_user_interaction = lambda: None
    finish_controller._sync_drift_timer = lambda: None
    controller_type._finish_gaze_radial_menu(finish_controller)
    assert finish_controller._gaze_click_validation_pending is None
    assert finish_controller._gaze_click_scan_generation == 11
    assert finish_controller.cloak_calls == [False]
    assert finish_controller._gaze_click_validation_cloak_active is False

    class Stopper:
        def __init__(self):
            self.calls = []

        def stop(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    shutdown_controller = type("Task5ShutdownControllerDouble", (), {})()
    shutdown_controller._eye_tracking_reaction_lock = companion_orb_controller.threading.Lock()
    shutdown_controller._eye_tracking_reaction_shutting_down = False
    shutdown_controller._eye_tracking_reaction_generation = 0
    shutdown_controller._gaze_context_dispatch_generation = 0
    shutdown_controller._eye_tracking_connection_key = None
    shutdown_controller._gaze_click_validation_pending = ("pending",)
    shutdown_controller._gaze_click_validation_cloak_active = True
    shutdown_controller._gaze_click_validation_cloak_token = 3
    shutdown_controller.cloak_calls = []
    shutdown_controller._set_snapshot_cloak = lambda enabled: shutdown_controller.cloak_calls.append(
        bool(enabled)
    )
    shutdown_controller.clear_calls = []

    def clear_shutdown_state(*, send_external):
        shutdown_controller.clear_calls.append(send_external)
        controller_type._cancel_gaze_click_validation(shutdown_controller)

    shutdown_controller._clear_eye_tracking_state = clear_shutdown_state
    shutdown_controller._eye_tracking_provider = Stopper()
    shutdown_controller._drift_timer = Stopper()
    shutdown_controller._motion_timer = Stopper()
    shutdown_controller._return_home_timer = Stopper()
    shutdown_controller._menu_poll_timer = Stopper()
    shutdown_controller._save_timer = Stopper()
    shutdown_controller._gaze_radial_menu = None
    shutdown_controller._gaze_click_target_highlight = None
    shutdown_controller._stop_external_runtime = lambda: None
    shutdown_controller._unregister_sensory_provider = lambda: None
    shutdown_controller._window = None
    shutdown_controller._quick = object()
    controller_type.shutdown(shutdown_controller)
    assert shutdown_controller.clear_calls == [True]
    assert shutdown_controller._gaze_click_validation_pending is None
    assert shutdown_controller.cloak_calls == [False]
    assert shutdown_controller._gaze_click_validation_cloak_active is False
    assert shutdown_controller._eye_tracking_reaction_shutting_down is True
    assert shutdown_controller._quick is None


def _wait_for(predicate, *, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        if predicate():
            return True
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents(QtCore.QEventLoop.AllEvents, 10)
        time.sleep(0.005)
    return bool(predicate())


def _assert_safety_d_focus_fallback_contract(
    companion_orb_controller,
    eye_tracking,
) -> None:
    focus = (400.25, 300.75)
    nearby_native = eye_tracking.ClickTarget(
        "Nearby native",
        (425, 286, 90, 28),
        kind="control_text",
        source="win32",
    )
    result = eye_tracking.aggregate_click_targets(
        semantic_targets=[nearby_native],
        regions=[
            {
                "text": "Nearby OCR",
                "screen_bounds": [330, 330, 62, 24],
                "kind": "control_text",
                "source": "ocr",
            }
        ],
        focus_point=focus,
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    focus_candidates = [target for target in result.visual if target.click_point == focus]
    assert len(focus_candidates) == 1
    assert focus_candidates[0].center == focus
    left, top, width, height = focus_candidates[0].bounds
    assert left <= focus[0] <= left + width
    assert top <= focus[1] <= top + height

    controller_type = companion_orb_controller.CompanionOrbController
    serializer = type("SafetyDFocusSerializerDouble", (), {})()
    payload = controller_type._serialize_click_target(
        serializer,
        focus_candidates[0],
        None,
        [100, 100, 900, 650],
    )
    dispatch = type("SafetyDFocusDispatchDouble", (), {})()
    dispatch._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    dispatch._gaze_click_visual_targets = [payload]
    dispatch._gaze_click_target_enabled = lambda: True
    dispatch._click_target_from_payload = controller_type._click_target_from_payload
    dispatch._gaze_click_visual_selected_index = 0
    dispatch._dismiss_gaze_radial_menu = lambda: None
    dispatch._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1920.0, 1080.0)
    dispatch._gaze_click_visual_context_bounds = (
        lambda target: controller_type._gaze_click_visual_context_bounds(
            dispatch,
            target,
        )
    )
    dispatch.inspect_requests = []
    dispatch._queue_gaze_radial_context_action = (
        lambda action_id, point, **kwargs: dispatch.inspect_requests.append(
            (action_id, tuple(point), list(kwargs.get("bounds_override") or []))
        )
        or {"ok": True, "queued": True}
    )
    dispatch.clicks = []
    dispatch._queue_gaze_left_click = dispatch.clicks.append
    result = controller_type._dispatch_gaze_click_visual_action(
        dispatch,
        "inspect",
    )
    assert result == {"ok": True, "queued": True}
    assert dispatch.clicks == []
    assert len(dispatch.inspect_requests) == 1
    inspect_action_id, inspect_point, inspect_bounds = dispatch.inspect_requests[0]
    assert inspect_action_id == "react"
    assert inspect_point == focus
    assert inspect_bounds
    assert inspect_bounds[0] <= focus[0] <= inspect_bounds[0] + inspect_bounds[2]
    assert inspect_bounds[1] <= focus[1] <= inspect_bounds[1] + inspect_bounds[3]

    containing_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[],
        regions=[
            {
                "text": "Containing OCR",
                "screen_bounds": [360, 280, 100, 60],
                "kind": "control_text",
                "source": "ocr",
            }
        ],
        focus_point=focus,
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    containing_focus = [
        target for target in containing_result.visual if target.click_point == focus
    ]
    assert len(containing_focus) == 1
    assert containing_focus[0].label == "Containing OCR"
    assert containing_focus[0].center == focus


def _assert_safety_d_pytesseract_timeout(snapshot_ocr) -> None:
    from PIL import Image

    observed: list[float | None] = []
    fake = types.ModuleType("pytesseract")
    fake.Output = types.SimpleNamespace(DICT="dict")

    def image_to_data(_image, *, output_type, timeout=None):
        assert output_type == "dict"
        observed.append(timeout)
        return {
            "text": ["Safe"],
            "conf": ["95"],
            "left": [2],
            "top": [3],
            "width": [20],
            "height": [10],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        }

    fake.image_to_data = image_to_data
    previous = sys.modules.get("pytesseract")
    try:
        sys.modules["pytesseract"] = fake
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "ocr.png"
            Image.new("RGB", (40, 24), "white").save(image_path)
            regions = snapshot_ocr._extract_with_pytesseract(
                image_path,
                [40, 24],
                [0, 0, 40, 24],
            )
    finally:
        if previous is None:
            sys.modules.pop("pytesseract", None)
        else:
            sys.modules["pytesseract"] = previous
    assert regions
    assert len(observed) == 1
    assert observed[0] is not None
    assert 3.5 <= float(observed[0]) <= 4.5


def _assert_safety_d_cleanup_contract(companion_orb_controller) -> None:
    controller_type = companion_orb_controller.CompanionOrbController
    assert hasattr(controller_type, "_schedule_click_target_capture_cleanup")
    assert hasattr(controller_type, "_sweep_stale_click_target_captures")
    cleanup_names = (
        "_remove_click_target_capture",
        "_schedule_click_target_capture_cleanup",
        "_sweep_stale_click_target_captures",
    )
    controller_path = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py"
    )
    for name in cleanup_names:
        source = _source_for_function(
            controller_path,
            name,
            class_name="CompanionOrbController",
        )
        assert all(fragment not in source for fragment in ("_log", "_debug_event", "print("))

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir) / "runtime" / "companion_orb" / "click_targets"
        output_dir.mkdir(parents=True)
        delayed = output_dir / "companion_orb_read_delayed.png"
        delayed.write_bytes(b"private capture")
        outsider = Path(temp_dir) / "companion_orb_read_outside.png"
        outsider.write_bytes(b"keep")
        original_unlink = Path.unlink
        original_delay = getattr(
            companion_orb_controller,
            "GAZE_CLICK_CAPTURE_DEFERRED_RETRY_DELAY_SECONDS",
            None,
        )
        attempts: list[Path] = []

        def unlock_later(path, *args, **kwargs):
            candidate = Path(path)
            attempts.append(candidate)
            if candidate == delayed and attempts.count(delayed) <= 3:
                raise PermissionError("private path and content")
            return original_unlink(path, *args, **kwargs)

        captured_output = io.StringIO()
        try:
            Path.unlink = unlock_later
            companion_orb_controller.GAZE_CLICK_CAPTURE_DEFERRED_RETRY_DELAY_SECONDS = 0.01
            with contextlib.redirect_stdout(captured_output), contextlib.redirect_stderr(captured_output):
                immediate = controller_type._schedule_click_target_capture_cleanup(
                    delayed,
                    output_dir,
                )
                assert immediate is False
                assert _wait_for(lambda: not delayed.exists(), timeout_seconds=1.0)
                assert controller_type._remove_click_target_capture(outsider, output_dir) is False
        finally:
            Path.unlink = original_unlink
            if original_delay is None:
                delattr(
                    companion_orb_controller,
                    "GAZE_CLICK_CAPTURE_DEFERRED_RETRY_DELAY_SECONDS",
                )
            else:
                companion_orb_controller.GAZE_CLICK_CAPTURE_DEFERRED_RETRY_DELAY_SECONDS = (
                    original_delay
                )
        assert outsider.exists()
        assert captured_output.getvalue() == ""
        assert attempts[:3] == [delayed, delayed, delayed]

        stale_files = [
            output_dir / "companion_orb_read_old.jpg",
            output_dir / "companion_orb_read_old.jpeg",
            output_dir / "companion_orb_read_old.png",
        ]
        for stale_path in stale_files:
            stale_path.write_bytes(b"stale")
        unrelated = [
            output_dir / "notes.txt",
            output_dir / "other.png",
            output_dir / "companion_orb_preview.jpg",
        ]
        for unrelated_path in unrelated:
            unrelated_path.write_bytes(b"keep")
        with contextlib.redirect_stdout(captured_output), contextlib.redirect_stderr(captured_output):
            controller_type._sweep_stale_click_target_captures(output_dir)
        assert _wait_for(
            lambda: all(not stale_path.exists() for stale_path in stale_files),
            timeout_seconds=1.0,
        )
        assert all(path.exists() for path in unrelated)
        assert outsider.exists()
        assert "private" not in captured_output.getvalue()
        assert str(output_dir) not in captured_output.getvalue()


def _safety_d_scan_controller(controller_type, root: Path, generation: int):
    events: list[str] = []
    payloads: list[dict] = []

    class ScanLock:
        def __init__(self):
            self.locked = False

        def acquire(self, *, blocking):
            assert blocking is False
            assert not self.locked
            self.locked = True
            events.append("lock")
            return True

        def release(self):
            assert self.locked
            self.locked = False
            events.append("unlock")

    controller = type("SafetyDScanControllerDouble", (), {})()
    controller.context = type("ContextDouble", (), {"app_root": root})()
    controller._last_runtime_config = {
        "companion_orb_eye_tracking_click_target_enabled": True,
        "companion_orb_enabled": False,
        "companion_orb_display_mode": "off",
    }
    controller._gaze_click_target_enabled = lambda: bool(
        controller._last_runtime_config[
            "companion_orb_eye_tracking_click_target_enabled"
        ]
    )
    controller._gaze_click_scan_generation = int(generation)
    controller._eye_tracking_reaction_shutting_down = False
    controller._snapshot_capture_lock = ScanLock()
    controller._apply_snapshot_cloak_blocking = lambda enabled: (
        events.append(f"cloak:{'on' if enabled else 'off'}") or True
    )
    controller._click_target_preview = controller_type._click_target_preview
    controller._serialize_click_target = lambda target, output_path, bounds, **kwargs: (
        controller_type._serialize_click_target(
            controller,
            target,
            output_path,
            bounds,
            **kwargs,
        )
    )
    controller._proxy = type(
        "ProxyDouble",
        (),
        {
            "eye_click_targets_requested": type(
                "SignalDouble",
                (),
                {"emit": lambda _self, payload: payloads.append(dict(payload))},
            )()
        },
    )()
    return controller, events, payloads


def _assert_safety_d_bounded_scan_contract(
    companion_orb_controller,
    eye_tracking,
) -> None:
    from addons.companion_orb_overlay.companion_orb import (
        reading_overlay,
        snapshot_ocr,
        windows_ui_automation,
    )

    controller_type = companion_orb_controller.CompanionOrbController
    assert hasattr(controller_type, "_run_bounded_daemon_stage")
    assert hasattr(controller_type, "_click_target_native_capture_stage")
    assert hasattr(controller_type, "_click_target_ocr_stage")

    original_native_timeout = getattr(
        companion_orb_controller,
        "GAZE_CLICK_NATIVE_CAPTURE_TIMEOUT_SECONDS",
        None,
    )
    original_ocr_timeout = getattr(
        companion_orb_controller,
        "GAZE_CLICK_OCR_TIMEOUT_SECONDS",
        None,
    )
    original_discover = windows_ui_automation.discover_semantic_targets
    original_native = snapshot_ocr.extract_window_text_regions
    original_capture = reading_overlay.capture_region_image
    original_ocr = snapshot_ocr.extract_snapshot_regions
    semantic = eye_tracking.ClickTarget(
        "Open",
        (240, 180, 100, 32),
        "ButtonControl",
        1.0,
        "Button",
        "uia",
        True,
        (99, 4),
    )
    try:
        companion_orb_controller.GAZE_CLICK_NATIVE_CAPTURE_TIMEOUT_SECONDS = 0.08
        companion_orb_controller.GAZE_CLICK_OCR_TIMEOUT_SECONDS = 0.10
        windows_ui_automation.discover_semantic_targets = lambda *_args, **_kwargs: (
            windows_ui_automation.AutomationScanResult(
                (semantic,),
                True,
                False,
                "private provider details",
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            native_started = threading.Event()
            release_native = threading.Event()
            capture_calls: list[str] = []

            def blocked_native(*_args, **_kwargs):
                native_started.set()
                release_native.wait(2.0)
                return [
                    {
                        "text": "late private native",
                        "screen_bounds": [300, 300, 80, 24],
                    }
                ]

            snapshot_ocr.extract_window_text_regions = blocked_native
            reading_overlay.capture_region_image = lambda *_args, **_kwargs: (
                capture_calls.append("capture")
            )
            controller, events, payloads = _safety_d_scan_controller(
                controller_type,
                root,
                41,
            )
            scan_thread = threading.Thread(
                target=controller_type._scan_gaze_click_targets,
                args=(controller, [100, 100, 900, 650], (400.0, 300.0), 41),
                daemon=True,
            )
            started_at = time.monotonic()
            scan_thread.start()
            assert native_started.wait(0.5)
            controller._gaze_click_scan_generation += 1
            scan_thread.join(0.7)
            elapsed = time.monotonic() - started_at
            assert not scan_thread.is_alive()
            assert elapsed < 0.7
            assert events[-2:] == ["cloak:off", "unlock"]
            assert controller._snapshot_capture_lock.locked is False
            assert payloads == []
            release_native.set()
            assert _wait_for(lambda: not scan_thread.is_alive(), timeout_seconds=0.2)
            time.sleep(0.03)
            assert capture_calls == []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            native_started = threading.Event()
            release_native = threading.Event()
            capture_calls = []

            def blocked_native_for_disable(*_args, **_kwargs):
                native_started.set()
                release_native.wait(2.0)
                return []

            snapshot_ocr.extract_window_text_regions = blocked_native_for_disable
            reading_overlay.capture_region_image = lambda *_args, **_kwargs: (
                capture_calls.append("capture")
            )
            controller, events, payloads = _safety_d_scan_controller(
                controller_type,
                root,
                411,
            )
            scan_thread = threading.Thread(
                target=controller_type._scan_gaze_click_targets,
                args=(controller, [100, 100, 900, 650], (400.0, 300.0), 411),
                daemon=True,
            )
            scan_thread.start()
            assert native_started.wait(0.5)
            controller._last_runtime_config[
                "companion_orb_eye_tracking_click_target_enabled"
            ] = False
            scan_thread.join(0.7)
            assert not scan_thread.is_alive()
            assert events[-2:] == ["cloak:off", "unlock"]
            assert payloads == []
            release_native.set()
            time.sleep(0.03)
            assert capture_calls == []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "runtime" / "companion_orb" / "click_targets"
            capture_started = threading.Event()
            release_capture = threading.Event()
            capture_created = threading.Event()
            late_capture = output_dir / "companion_orb_read_late.png"
            snapshot_ocr.extract_window_text_regions = lambda *_args, **_kwargs: []

            def blocked_capture(_bounds, directory, **_kwargs):
                assert Path(directory) == output_dir
                capture_started.set()
                release_capture.wait(2.0)
                output_dir.mkdir(parents=True, exist_ok=True)
                late_capture.write_bytes(_preview_png())
                capture_created.set()
                return late_capture

            reading_overlay.capture_region_image = blocked_capture
            snapshot_ocr.extract_snapshot_regions = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("OCR must not run for a timed-out capture stage.")
            )
            controller, events, payloads = _safety_d_scan_controller(
                controller_type,
                root,
                42,
            )
            started_at = time.monotonic()
            controller_type._scan_gaze_click_targets(
                controller,
                [100, 100, 900, 650],
                (400.0, 300.0),
                42,
            )
            assert capture_started.is_set()
            assert time.monotonic() - started_at < 0.7
            assert events[-2:] == ["cloak:off", "unlock"]
            assert controller._snapshot_capture_lock.locked is False
            assert len(payloads) == 1
            assert payloads[0]["direct"][0]["runtime_id"] == [99, 4]
            assert payloads[0]["direct"][0]["preview_png"] == b""
            assert payloads[0]["automation_provider_error"] is True
            assert payloads[0]["error"] == "Click targets could not be scanned."
            assert "private" not in repr(payloads[0])
            assert str(root) not in repr(payloads[0])
            release_capture.set()
            assert capture_created.wait(0.5)
            assert _wait_for(lambda: not late_capture.exists(), timeout_seconds=1.0)
            assert len(payloads) == 1

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "runtime" / "companion_orb" / "click_targets"
            events: list[str]
            ocr_started = threading.Event()
            release_ocr = threading.Event()
            capture_path = output_dir / "companion_orb_read_current.png"
            native_region = {
                "text": "Native nearby",
                "screen_bounds": [430, 286, 110, 28],
                "kind": "control_text",
                "source": "win32",
            }
            snapshot_ocr.extract_window_text_regions = lambda *_args, **_kwargs: [
                dict(native_region)
            ]

            def quick_capture(_bounds, directory, **_kwargs):
                events.append("capture")
                Path(directory).mkdir(parents=True, exist_ok=True)
                capture_path.write_bytes(_preview_png())
                return capture_path

            def blocked_ocr(*_args, **_kwargs):
                events.append("ocr")
                ocr_started.set()
                release_ocr.wait(2.0)
                return {
                    "regions": [
                        {
                            "text": "late private OCR",
                            "screen_bounds": [300, 300, 90, 24],
                        }
                    ],
                    "backend": "private backend path",
                }

            reading_overlay.capture_region_image = quick_capture
            snapshot_ocr.extract_snapshot_regions = blocked_ocr
            controller, events, payloads = _safety_d_scan_controller(
                controller_type,
                root,
                43,
            )
            original_apply = controller._apply_snapshot_cloak_blocking
            controller._apply_snapshot_cloak_blocking = lambda enabled: (
                events.append(f"cloak:{'on' if enabled else 'off'}") or True
            )
            started_at = time.monotonic()
            controller_type._scan_gaze_click_targets(
                controller,
                [100, 100, 900, 650],
                (400.0, 300.0),
                43,
            )
            assert original_apply is not None
            assert ocr_started.is_set()
            assert time.monotonic() - started_at < 0.8
            assert events.index("cloak:off") < events.index("ocr")
            assert events.index("unlock") < events.index("ocr")
            assert controller._snapshot_capture_lock.locked is False
            assert len(payloads) == 1
            payload = payloads[0]
            assert payload["direct"][0]["runtime_id"] == [99, 4]
            assert payload["direct"][0]["preview_png"].startswith(b"\x89PNG")
            assert any(item["label"] == "Native nearby" for item in payload["visual"])
            assert payload["error"] == "Click targets could not be scanned."
            assert "private" not in repr(payload)
            assert str(root) not in repr(payload)
            assert not capture_path.exists()
            release_ocr.set()
            time.sleep(0.05)
            assert len(payloads) == 1
    finally:
        windows_ui_automation.discover_semantic_targets = original_discover
        snapshot_ocr.extract_window_text_regions = original_native
        reading_overlay.capture_region_image = original_capture
        snapshot_ocr.extract_snapshot_regions = original_ocr
        if original_native_timeout is None:
            delattr(
                companion_orb_controller,
                "GAZE_CLICK_NATIVE_CAPTURE_TIMEOUT_SECONDS",
            )
        else:
            companion_orb_controller.GAZE_CLICK_NATIVE_CAPTURE_TIMEOUT_SECONDS = (
                original_native_timeout
            )
        if original_ocr_timeout is None:
            delattr(companion_orb_controller, "GAZE_CLICK_OCR_TIMEOUT_SECONDS")
        else:
            companion_orb_controller.GAZE_CLICK_OCR_TIMEOUT_SECONDS = original_ocr_timeout


def _new_safety_d_ack_controller(controller_type):
    controller = type("SafetyDAckControllerDouble", (), {})()
    controller._last_runtime_config = {
        "companion_orb_external_runtime_enabled": True,
        "companion_orb_enabled": True,
        "companion_orb_display_mode": "always",
        "companion_orb_eye_tracking_click_target_enabled": True,
    }
    controller._eye_tracking_reaction_shutting_down = False
    controller._external_cloak_ack_lock = threading.Lock()
    controller._external_cloak_ack_event = threading.Event()
    controller._external_cloak_ack_expected = None
    controller._external_cloak_ack_enabled = None
    controller._snapshot_cloak_count = 0
    controller._debug_event = lambda *_args, **_kwargs: None
    controller.cloak_calls = []

    def apply_cloak(enabled):
        active = bool(enabled)
        controller.cloak_calls.append(active)
        if active:
            if controller._snapshot_cloak_count <= 0:
                controller_type._prepare_external_cloak_ack(controller, True)
            controller._snapshot_cloak_count += 1
        else:
            controller._snapshot_cloak_count = max(
                0,
                controller._snapshot_cloak_count - 1,
            )
            if controller._snapshot_cloak_count <= 0:
                controller_type._prepare_external_cloak_ack(controller, False)
        return True

    controller._apply_snapshot_cloak_blocking = apply_cloak
    controller._set_snapshot_cloak = lambda enabled: apply_cloak(enabled)
    controller._external_runtime_enabled = lambda: controller_type._external_runtime_enabled(
        controller
    )
    return controller


def _assert_safety_d_capture_uses_primitive_geometry() -> None:
    from PIL import Image
    from addons.companion_orb_overlay.companion_orb import reading_overlay

    original_virtual_desktop_rect = reading_overlay.virtual_desktop_rect
    reading_overlay.virtual_desktop_rect = lambda: (_ for _ in ()).throw(
        AssertionError("A bounded capture stage must not query Qt screen geometry.")
    )
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = reading_overlay.capture_region_image(
                [10, 10, 40, 30],
                Path(temp_dir),
                grabber=lambda **_kwargs: Image.new("RGB", (100, 100), "white"),
                virtual_bounds=[0, 0, 100, 100],
            )
            assert output_path.is_file()
    finally:
        reading_overlay.virtual_desktop_rect = original_virtual_desktop_rect


def _assert_safety_d_external_cloak_ack_contract(companion_orb_controller) -> None:
    controller_type = companion_orb_controller.CompanionOrbController
    assert hasattr(controller_type, "_prepare_external_cloak_ack")
    assert hasattr(controller_type, "_external_cloak_ack_ready")
    assert hasattr(controller_type, "_apply_click_target_scan_cloak_blocking")

    waiting = _new_safety_d_ack_controller(controller_type)
    result: list[bool] = []
    worker = threading.Thread(
        target=lambda: result.append(
            controller_type._apply_click_target_scan_cloak_blocking(
                waiting,
                timeout_seconds=0.25,
            )
        ),
        daemon=True,
    )
    worker.start()
    assert _wait_for(lambda: waiting.cloak_calls == [True], timeout_seconds=0.2)
    controller_type._handle_external_runtime_event(
        waiting,
        {"type": "orb.cloak_changed", "enabled": False},
    )
    time.sleep(0.03)
    assert worker.is_alive()
    controller_type._handle_external_runtime_event(
        waiting,
        {"type": "orb.cloak_changed", "enabled": True},
    )
    worker.join(0.4)
    assert result == [True]
    assert waiting.cloak_calls == [True]
    assert waiting._snapshot_cloak_count == 1

    missing = _new_safety_d_ack_controller(controller_type)
    started_at = time.monotonic()
    assert controller_type._apply_click_target_scan_cloak_blocking(
        missing,
        timeout_seconds=0.05,
    ) is False
    assert time.monotonic() - started_at < 0.3
    assert missing.cloak_calls == [True, False]
    assert missing._snapshot_cloak_count == 0

    nested = type("SafetyDNestedCloakControllerDouble", (), {})()
    nested._window = None
    nested._snapshot_cloak_count = 0
    nested._snapshot_restore_visible = False
    nested._external_cloak_ack_lock = threading.Lock()
    nested._external_cloak_ack_event = threading.Event()
    nested._external_cloak_ack_expected = None
    nested._external_cloak_ack_enabled = None
    nested._clear_gaze_click_target_highlight = lambda: None
    nested._debug_event = lambda *_args, **_kwargs: None
    nested._refresh_visibility = lambda: None
    nested.sent = []

    def record_cloak_send(payload):
        nested.sent.append(
            (
                bool(payload.get("enabled")),
                nested._external_cloak_ack_expected,
                nested._external_cloak_ack_event.is_set(),
            )
        )
        return True

    nested._send_external_runtime = record_cloak_send
    controller_type._set_snapshot_cloak(nested, True)
    controller_type._set_snapshot_cloak(nested, True)
    assert nested._snapshot_cloak_count == 2
    controller_type._set_snapshot_cloak(nested, False)
    assert nested._snapshot_cloak_count == 1
    controller_type._set_snapshot_cloak(nested, False)
    assert nested._snapshot_cloak_count == 0
    assert nested.sent == [(True, True, False), (False, False, False)]
    controller_type._handle_external_runtime_event(
        nested,
        {"type": "orb.cloak_changed", "enabled": True},
    )
    assert controller_type._external_cloak_ack_ready(nested, False) is False
    controller_type._handle_external_runtime_event(
        nested,
        {"type": "orb.cloak_changed", "enabled": False},
    )
    assert controller_type._external_cloak_ack_ready(nested, False) is True

    original_ack_timeout = getattr(
        companion_orb_controller,
        "GAZE_CLICK_CLOAK_ACK_TIMEOUT_SECONDS",
        None,
    )
    original_ack_poll = getattr(
        companion_orb_controller,
        "GAZE_CLICK_CLOAK_ACK_POLL_MS",
        None,
    )
    try:
        companion_orb_controller.GAZE_CLICK_CLOAK_ACK_TIMEOUT_SECONDS = 0.12
        companion_orb_controller.GAZE_CLICK_CLOAK_ACK_POLL_MS = 5
        _qapplication()
        click = _new_safety_d_ack_controller(controller_type)
        click.clicks = []
        click._perform_gaze_left_click = lambda point: click.clicks.append(point) or True
        queued_at = time.monotonic()
        controller_type._queue_gaze_left_click(click, (321.0, 222.0))
        assert time.monotonic() - queued_at < 0.03
        assert click.clicks == []
        assert click.cloak_calls == [True]
        time.sleep(0.03)
        _qapplication().processEvents(QtCore.QEventLoop.AllEvents, 20)
        assert click.clicks == []
        controller_type._handle_external_runtime_event(
            click,
            {"type": "orb.cloak_changed", "enabled": True},
        )
        assert _wait_for(lambda: click.clicks == [(321.0, 222.0)], timeout_seconds=0.3)
        assert _wait_for(lambda: click.cloak_calls == [True, False], timeout_seconds=0.3)
        controller_type._handle_external_runtime_event(
            click,
            {"type": "orb.cloak_changed", "enabled": True},
        )
        time.sleep(0.03)
        _qapplication().processEvents(QtCore.QEventLoop.AllEvents, 20)
        assert click.clicks == [(321.0, 222.0)]
        assert click.cloak_calls == [True, False]

        timed_out = _new_safety_d_ack_controller(controller_type)
        timed_out.clicks = []
        timed_out._perform_gaze_left_click = lambda point: timed_out.clicks.append(point) or True
        queued_at = time.monotonic()
        controller_type._queue_gaze_left_click(timed_out, (444.0, 333.0))
        assert time.monotonic() - queued_at < 0.03
        assert _wait_for(
            lambda: timed_out.cloak_calls == [True, False],
            timeout_seconds=0.4,
        )
        assert timed_out.clicks == []
        controller_type._handle_external_runtime_event(
            timed_out,
            {"type": "orb.cloak_changed", "enabled": True},
        )
        time.sleep(0.03)
        _qapplication().processEvents(QtCore.QEventLoop.AllEvents, 20)
        assert timed_out.clicks == []
        assert timed_out.cloak_calls == [True, False]

        disabled_while_waiting = _new_safety_d_ack_controller(controller_type)
        disabled_while_waiting.clicks = []
        disabled_while_waiting._perform_gaze_left_click = (
            lambda point: disabled_while_waiting.clicks.append(point) or True
        )
        controller_type._queue_gaze_left_click(
            disabled_while_waiting,
            (555.0, 444.0),
        )
        disabled_while_waiting._last_runtime_config[
            "companion_orb_external_runtime_enabled"
        ] = False
        assert _wait_for(
            lambda: disabled_while_waiting.cloak_calls == [True, False],
            timeout_seconds=0.3,
        )
        assert disabled_while_waiting.clicks == []

        click_target_disabled = _new_safety_d_ack_controller(controller_type)
        click_target_disabled.clicks = []
        click_target_disabled._gaze_click_scan_generation = 17
        click_target_disabled._gaze_click_target_enabled = lambda: bool(
            click_target_disabled._last_runtime_config.get(
                "companion_orb_eye_tracking_click_target_enabled",
                False,
            )
        )
        click_target_disabled._perform_gaze_left_click = (
            lambda point: click_target_disabled.clicks.append(point) or True
        )
        controller_type._queue_gaze_left_click(
            click_target_disabled,
            (666.0, 555.0),
            require_click_target_enabled=True,
        )
        click_target_disabled._last_runtime_config[
            "companion_orb_eye_tracking_click_target_enabled"
        ] = False
        controller_type._handle_external_runtime_event(
            click_target_disabled,
            {"type": "orb.cloak_changed", "enabled": True},
        )
        assert _wait_for(
            lambda: click_target_disabled.cloak_calls == [True, False],
            timeout_seconds=0.3,
        )
        assert click_target_disabled.clicks == []
    finally:
        if original_ack_timeout is None:
            delattr(
                companion_orb_controller,
                "GAZE_CLICK_CLOAK_ACK_TIMEOUT_SECONDS",
            )
        else:
            companion_orb_controller.GAZE_CLICK_CLOAK_ACK_TIMEOUT_SECONDS = (
                original_ack_timeout
            )
        if original_ack_poll is None:
            delattr(companion_orb_controller, "GAZE_CLICK_CLOAK_ACK_POLL_MS")
        else:
            companion_orb_controller.GAZE_CLICK_CLOAK_ACK_POLL_MS = original_ack_poll


def _assert_safety_d_shutdown_and_status_contract(companion_orb_controller) -> None:
    controller_type = companion_orb_controller.CompanionOrbController
    shutdown = type("SafetyDShutdownControllerDouble", (), {})()
    shutdown._last_runtime_config = {
        "companion_orb_external_runtime_enabled": True,
        "companion_orb_enabled": True,
        "companion_orb_display_mode": "always",
    }
    shutdown._eye_tracking_reaction_shutting_down = True
    assert controller_type._external_runtime_enabled(shutdown) is False
    shutdown._external_runtime_enabled = lambda: controller_type._external_runtime_enabled(
        shutdown
    )
    shutdown._ensure_external_runtime = lambda: (_ for _ in ()).throw(
        AssertionError("Late uncloak must not start the external runtime.")
    )
    shutdown._external_runtime = type(
        "RuntimeDouble",
        (),
        {
            "send": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("Late uncloak must not send to the external runtime.")
            )
        },
    )()
    shutdown._send_external_runtime = lambda payload: controller_type._send_external_runtime(
        shutdown,
        payload,
    )
    shutdown._snapshot_cloak_count = 1
    shutdown._snapshot_restore_visible = False
    shutdown._window = None
    shutdown._debug_event = lambda *_args, **_kwargs: None
    shutdown._refresh_visibility = lambda: None
    shutdown._external_cloak_ack_lock = threading.Lock()
    shutdown._external_cloak_ack_event = threading.Event()
    shutdown._external_cloak_ack_expected = True
    shutdown._external_cloak_ack_enabled = True
    controller_type._set_snapshot_cloak(shutdown, False)
    assert shutdown._snapshot_cloak_count == 0

    status = type("SafetyDStatusControllerDouble", (), {})()
    status._gaze_click_automation_available = True
    status._gaze_click_automation_timed_out = False
    status._gaze_click_automation_provider_error = True
    action = controller_type._gaze_click_automation_status_action(status)
    assert action is not None
    assert action.label == "App controls limited"
    assert action.enabled is False


def main() -> None:
    _assert_click_target_ui_contract()
    _assert_windows_ui_automation_contract()
    _assert_click_target_privacy_and_dependency_contract()

    from addons.companion_orb_overlay.companion_orb import eye_tracking
    from addons.companion_orb_overlay import controller as settings_controller
    from addons.companion_orb_overlay.companion_orb import companion_orb_controller

    _assert_controller_task_4_contract(companion_orb_controller, eye_tracking)
    _assert_controller_task_5_contract(companion_orb_controller, eye_tracking)
    _assert_safety_b_validation_cloak_contract(companion_orb_controller, eye_tracking)
    _assert_task_5_pending_cleanup(companion_orb_controller)
    _assert_safety_c_coordinate_preview_cleanup_contract(
        companion_orb_controller,
        eye_tracking,
    )
    from addons.companion_orb_overlay.companion_orb import snapshot_ocr

    _assert_safety_d_focus_fallback_contract(companion_orb_controller, eye_tracking)
    _assert_safety_d_pytesseract_timeout(snapshot_ocr)
    _assert_safety_d_cleanup_contract(companion_orb_controller)
    _assert_safety_d_bounded_scan_contract(companion_orb_controller, eye_tracking)
    _assert_safety_d_capture_uses_primitive_geometry()
    _assert_safety_d_external_cloak_ack_contract(companion_orb_controller)
    _assert_safety_d_shutdown_and_status_contract(companion_orb_controller)

    semantic = eye_tracking.ClickTarget(
        label="Save",
        bounds=(320, 180, 180, 38),
        kind="ButtonControl",
        confidence=1.0,
        role="Button",
        source="uia",
        semantic=True,
        runtime_id=(42, 7),
    )
    result = eye_tracking.aggregate_click_targets(
        semantic_targets=[semantic],
        regions=[
            {"text": "Save", "screen_bounds": [322, 181, 176, 36], "kind": "control_text"},
            {
                "text": "Save",
                "screen_bounds": [321, 180, 178, 38],
                "kind": "control_text",
                "source": "ocr",
            },
            {
                "text": "Static label",
                "screen_bounds": [520, 180, 120, 38],
                "kind": "control_text",
                "source": "win32",
            },
            {"text": "", "screen_bounds": [600, 300, 150, 44], "kind": "text_region"},
        ],
        focus_point=(400.0, 200.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert [target.display_label for target in result.direct] == ["Button - Save"]
    assert result.direct[0].source == "uia"
    assert sum(target.label == "Save" for target in result.direct) == 1
    assert any(
        target.label == "Static label" and target.source == "win32"
        for target in result.visual
    )
    assert any(target.bounds == (600, 300, 150, 44) and not target.label for target in result.visual)
    assert all(target.semantic is False for target in result.visual)
    assert all("area" not in target.display_label.casefold() for target in result.direct)

    legacy = eye_tracking.ClickTarget("Legacy", (120, 120, 40, 20), "control_text", 0.5)
    assert legacy.role == ""
    assert legacy.source == ""
    assert legacy.semantic is False
    assert legacy.runtime_id == ()

    overlapping_controls = eye_tracking.aggregate_click_targets(
        semantic_targets=[
            eye_tracking.ClickTarget(
                label="Play",
                bounds=(300, 180, 120, 42),
                role="Button",
                source="uia",
                semantic=True,
                runtime_id=(8, 1),
            ),
            eye_tracking.ClickTarget(
                label="Playlist",
                bounds=(320, 185, 120, 42),
                role="ListItem",
                source="uia",
                semantic=True,
                runtime_id=(8, 2),
            ),
        ],
        regions=[],
        focus_point=(360.0, 200.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert [target.label for target in overlapping_controls.direct] == ["Play", "Playlist"]

    legacy_visual_targets = eye_tracking.rank_click_targets(
        [
            {"text": "", "screen_bounds": [120, 120, 140, 42], "kind": "text_region"},
            {"text": "", "screen_bounds": [720, 570, 120, 38], "kind": "text_region"},
        ],
        focus_point=(500.0, 350.0),
        capture_bounds=(100, 100, 800, 560),
        limit=8,
    )
    assert legacy_visual_targets == ()
    assert all(target.label.strip() for target in legacy_visual_targets)

    full_visual_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[],
        regions=[
            {
                "text": "",
                "screen_bounds": [600 + index * 55, 500, 40, 20],
                "kind": "text_region",
            }
            for index in range(6)
        ],
        focus_point=(120.0, 120.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=3,
    )
    assert len(full_visual_result.visual) == 3
    assert any(
        target.bounds[0] <= 120 <= target.bounds[0] + target.bounds[2]
        and target.bounds[1] <= 120 <= target.bounds[1] + target.bounds[3]
        for target in full_visual_result.visual
    )

    tiny_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[],
        regions=[],
        focus_point=(2.0, 2.0),
        capture_bounds=(0, 0, 4, 4),
        direct_limit=8,
        visual_limit=12,
    )
    assert tiny_result.visual == ()

    unnamed = eye_tracking.ClickTarget(
        label="",
        bounds=(250, 200, 120, 40),
        kind="ButtonControl",
        confidence=1.0,
        role="Button",
        source="uia",
        semantic=True,
        runtime_id=(42, 8),
    )
    unnamed_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[unnamed],
        regions=[],
        focus_point=(300.0, 220.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert unnamed_result.direct == ()
    assert any(target.bounds == unnamed.bounds for target in unnamed_result.visual)

    empty_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[],
        regions=[],
        focus_point=(400.0, 200.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert len(empty_result.visual) >= 2
    assert all(
        100 <= target.bounds[0]
        and 100 <= target.bounds[1]
        and target.bounds[0] + target.bounds[2] <= 1000
        and target.bounds[1] + target.bounds[3] <= 750
        for target in empty_result.visual
    )
    focus_x, focus_y = (400, 200)
    assert any(
        target.bounds[0] <= focus_x <= target.bounds[0] + target.bounds[2]
        and target.bounds[1] <= focus_y <= target.bounds[1] + target.bounds[3]
        for target in empty_result.visual
    )
    assert any(
        first.bounds[0] < second.bounds[0] + second.bounds[2]
        and second.bounds[0] < first.bounds[0] + first.bounds[2]
        and first.bounds[1] < second.bounds[1] + second.bounds[3]
        and second.bounds[1] < first.bounds[1] + first.bounds[3]
        for index, first in enumerate(empty_result.visual)
        for second in empty_result.visual[index + 1 :]
    )
    repeated_empty_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[],
        regions=[],
        focus_point=(400.0, 200.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert empty_result.visual == repeated_empty_result.visual

    clipped_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[
            eye_tracking.ClickTarget(
                label="Close",
                bounds=(90, 90, 50, 30),
                role="Button",
                source="uia",
                semantic=True,
                runtime_id=(9, 1),
            )
        ],
        regions=[],
        focus_point=(110.0, 110.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert clipped_result.direct[0].bounds == (90, 90, 50, 30)

    outside_center_result = eye_tracking.aggregate_click_targets(
        semantic_targets=[
            eye_tracking.ClickTarget(
                label="Outside center",
                bounds=(50, 120, 80, 30),
                role="Button",
                source="uia",
                semantic=True,
                runtime_id=(9, 2),
            )
        ],
        regions=[],
        focus_point=(110.0, 135.0),
        capture_bounds=(100, 100, 900, 650),
        direct_limit=8,
        visual_limit=12,
    )
    assert outside_center_result.direct == ()
    assert all(target.label != "Outside center" for target in outside_center_result.visual)

    manifest = json.loads(
        (ROOT_DIR / "addons" / "companion_orb_overlay" / "addon.json").read_text(encoding="utf-8")
    )
    settings_source = (ROOT_DIR / "addons" / "companion_orb_overlay" / "controller.py").read_text(
        encoding="utf-8"
    )
    key = "companion_orb_eye_tracking_click_target_enabled"
    assert settings_controller.COMPANION_ORB_EYE_TRACKING_DEFAULTS[key] is False
    assert key in settings_controller.COMPANION_ORB_EYE_TRACKING_SESSION_KEYS
    assert manifest["runtime_defaults"][key] is False
    assert "companion_orb_eye_tracking_click_target_checkbox" in settings_source

    def fake_controller(value: bool):
        controller = type("FakeController", (), {"_last_runtime_config": {key: value}})()
        controller._gaze_click_target_enabled = lambda: (
            companion_orb_controller.CompanionOrbController._gaze_click_target_enabled(controller)
        )
        controller._gaze_click_validation_cloak_active = False
        controller._gaze_click_validation_cloak_token = None
        controller._set_snapshot_cloak = lambda _enabled: None
        controller._cancel_gaze_click_validation = lambda: (
            companion_orb_controller.CompanionOrbController._cancel_gaze_click_validation(
                controller
            )
        )
        return controller

    disabled_actions = companion_orb_controller.CompanionOrbController._gaze_main_actions(
        fake_controller(False)
    )
    enabled_actions = companion_orb_controller.CompanionOrbController._gaze_main_actions(
        fake_controller(True)
    )
    disabled_action_map = {item.action_id: item for item in disabled_actions}
    enabled_action_map = {item.action_id: item for item in enabled_actions}
    assert "click_target" not in disabled_action_map
    assert "click_target" not in enabled_action_map
    assert disabled_action_map["action"].enabled is False
    assert enabled_action_map["action"].enabled is True

    action_controller = fake_controller(True)
    action_controller.scan_calls = 0
    action_controller._show_gaze_click_target_menu = lambda: setattr(
        action_controller,
        "scan_calls",
        action_controller.scan_calls + 1,
    )
    companion_orb_controller.CompanionOrbController._handle_gaze_radial_action(
        action_controller,
        "action",
    )
    assert action_controller.scan_calls == 1

    transition_controller = fake_controller(False)
    transition_controller._gaze_click_target_page_open = False
    transition_controller._gaze_radial_menu_open = True
    transition_controller._gaze_click_scan_generation = 4
    transition_controller._gaze_click_validation_pending = ("pending",)
    transition_controller._gaze_click_targets = {"stale": object()}
    transition_controller._eye_tracking_latest_point = (120.0, 80.0)
    transition_controller._eye_tracking_interaction_source_point = (1.0, 2.0)
    transition_controller._eye_tracking_interaction_target = object()
    transition_controller._eye_tracking_interaction_until = 99.0
    transition_controller._eye_tracking_last_external_target = object()
    transition_controller._eye_tracking_last_external_sent_at = 5.0
    transition_controller.external_events = []
    transition_controller.main_menu_points = []
    transition_controller._send_external_runtime = lambda payload: transition_controller.external_events.append(payload)
    transition_controller._show_gaze_radial_main_menu = (
        lambda point: transition_controller.main_menu_points.append(point) or True
    )
    companion_orb_controller.CompanionOrbController._refresh_gaze_radial_menu_after_click_target_disable(
        transition_controller,
        True,
    )
    assert transition_controller.main_menu_points == [(120.0, 80.0)]
    assert transition_controller._gaze_click_scan_generation == 5
    assert transition_controller._gaze_click_validation_pending is None
    assert transition_controller._gaze_click_targets == {}
    assert transition_controller._eye_tracking_interaction_source_point is None
    assert transition_controller._eye_tracking_interaction_target is None
    assert transition_controller._eye_tracking_interaction_until == 0.0
    assert transition_controller._gaze_click_target_page_open is False
    assert transition_controller.external_events == [{"type": "interaction_target_clear"}]

    stale_action_controller = fake_controller(False)
    stale_action_controller.scan_calls = 0
    stale_action_controller.page_calls = []
    stale_action_controller.dismiss_calls = 0
    stale_action_controller.click_calls = []
    stale_action_controller.highlight_clears = 0
    stale_action_controller.main_menu_points = []
    stale_action_controller._gaze_click_visual_page = 1
    stale_action_controller._gaze_click_visual_page_open = False
    stale_action_controller._gaze_click_scan_generation = 4
    stale_action_controller._gaze_click_targets = {
        "click_target:0": eye_tracking.ClickTarget("Apply", (20, 20, 80, 30), source="win32")
    }
    stale_action_controller._gaze_click_target_payloads = {}
    stale_action_controller._gaze_click_visual_targets = [
        {"label": "Visual", "bounds": [100, 100, 80, 40]}
    ]
    stale_action_controller._eye_tracking_latest_point = (120.0, 80.0)
    stale_action_controller._gaze_radial_anchor = QtCore.QPoint(120, 80)
    stale_action_controller._show_gaze_click_target_menu = lambda: setattr(
        stale_action_controller,
        "scan_calls",
        stale_action_controller.scan_calls + 1,
    )
    stale_action_controller._show_gaze_click_target_visual_page = (
        lambda page=0: stale_action_controller.page_calls.append(page)
    )
    stale_action_controller._dismiss_gaze_radial_menu = lambda: setattr(
        stale_action_controller,
        "dismiss_calls",
        stale_action_controller.dismiss_calls + 1,
    )
    stale_action_controller._queue_gaze_left_click = stale_action_controller.click_calls.append
    stale_action_controller._clear_gaze_click_target_highlight = lambda: setattr(
        stale_action_controller,
        "highlight_clears",
        stale_action_controller.highlight_clears + 1,
    )
    stale_action_controller._show_gaze_radial_main_menu = (
        lambda point: stale_action_controller.main_menu_points.append(point) or True
    )
    for action_id in (
        "click_target",
        "click_target_inspect",
        "click_target_visual_previous",
        "click_target_visual_next",
        "click_target_visual:0",
        "click_target:0",
    ):
        companion_orb_controller.CompanionOrbController._handle_gaze_radial_action(
            stale_action_controller,
            action_id,
        )
    assert stale_action_controller.scan_calls == 0
    assert stale_action_controller.page_calls == []
    assert stale_action_controller.dismiss_calls == 0
    assert stale_action_controller.click_calls == []
    assert stale_action_controller.highlight_clears == 6

    stale_candidate_controller = fake_controller(False)
    stale_candidate_controller._gaze_click_targets = {
        "click_target:0": eye_tracking.ClickTarget("Apply", (20, 20, 80, 30), source="win32")
    }
    stale_candidate_controller._gaze_click_visual_page_open = False
    stale_candidate_controller.highlight_clears = 0
    stale_candidate_controller._clear_gaze_click_target_highlight = lambda: setattr(
        stale_candidate_controller,
        "highlight_clears",
        stale_candidate_controller.highlight_clears + 1,
    )
    stale_candidate_controller._ensure_gaze_click_target_highlight_overlay = lambda: (_ for _ in ()).throw(
        AssertionError("A disabled queued candidate must not create or show the highlight overlay.")
    )
    companion_orb_controller.CompanionOrbController._handle_gaze_click_candidate_changed(
        stale_candidate_controller,
        "click_target:0",
    )
    assert stale_candidate_controller.highlight_clears == 1

    stale_action_controller._gaze_click_validation_pending = ("pending",)
    companion_orb_controller.CompanionOrbController._handle_gaze_radial_action(
        stale_action_controller,
        "back",
    )
    assert stale_action_controller.main_menu_points == [(120.0, 80.0)]
    assert stale_action_controller._gaze_click_validation_pending is None

    print("Companion Orb Click Target gate smoke passed.")


if __name__ == "__main__":
    main()
