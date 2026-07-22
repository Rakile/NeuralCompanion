from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.ai_presence_mode.controller import ORB_VISUAL_STYLES
from addons.companion_orb_overlay.companion_orb.companion_orb_bridge import CompanionOrbBridge


EXPECTED_ORB_STYLES = {
    "neural_spark",
    "aurora_glass",
    "prismatic_pulse",
    "aether_wisp",
    "celestial_firetrail",
    "quantum_halo",
    "event_horizon",
    "holographic_iris",
    "synaptic_bloom",
    "liquid_core",
    "void_prism",
}
EXPECTED_RENDER_FUNCTIONS = {
    "aurora_glass": "drawAuroraGlass",
    "prismatic_pulse": "drawPrismaticPulse",
    "aether_wisp": "drawAetherWisp",
    "celestial_firetrail": "drawCelestialFiretrail",
    "quantum_halo": "drawQuantumHalo",
    "event_horizon": "drawEventHorizon",
    "holographic_iris": "drawHolographicIris",
    "synaptic_bloom": "drawSynapticBloom",
    "liquid_core": "drawLiquidCore",
    "void_prism": "drawVoidPrism",
}


def _assert_radial_orbital_glass_style() -> None:
    from addons.companion_orb_overlay.companion_orb.gaze_radial_menu import (
        GazeRadialMenu,
        RadialAction,
    )

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    preview = QtGui.QImage(72, 48, QtGui.QImage.Format_ARGB32_Premultiplied)
    preview.fill(QtGui.QColor("#2f6f91"))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    assert preview.save(buffer, "PNG")
    menu = GazeRadialMenu()
    menu.show_actions(
        tuple(
            RadialAction(f"visual:{index}", f"Visual {index + 1}", role="Region", preview_png=bytes(buffer.data()))
            for index in range(4)
        ),
        anchor=QtCore.QPoint(500, 400),
        dwell_ms=650,
        theme={"primary": "#38bdf8", "text": "#eef7ff", "surface": "#101b2b"},
        opacity=0.72,
        focus_beam_enabled=False,
        enlarged_visual=True,
        center_label="Back",
        center_action_id="back",
    )
    app.processEvents()
    assert menu.menu_opacity == 0.72
    assert not menu.focus_beam_enabled
    back_geometry = menu._cancel_button.geometry()
    assert back_geometry.x() + back_geometry.width() * 0.5 == menu.width() * 0.5
    assert back_geometry.y() + back_geometry.height() * 0.5 == menu.height() * 0.5
    assert menu._cancel_button.width() == 92
    assert all(button.width() > 104 for button in menu._buttons.values())
    rendered = menu.grab().toImage()
    assert rendered.size() == menu.size()
    assert sum(
        1
        for y in range(rendered.height() // 2 - 120, rendered.height() // 2 + 120)
        for x in range(rendered.width() // 2 - 120, rendered.width() // 2 + 120)
        if rendered.pixelColor(x, y).alpha() > 0
    ) > 2000
    menu.hide()
    menu.deleteLater()


def main() -> None:
    _assert_radial_orbital_glass_style()
    available_styles = {value for _label, value in ORB_VISUAL_STYLES}
    missing_styles = sorted(EXPECTED_ORB_STYLES - available_styles)
    if missing_styles:
        raise AssertionError(f"Missing Companion Orb visual styles: {missing_styles}")

    bridge = CompanionOrbBridge()
    for style in sorted(EXPECTED_ORB_STYLES):
        bridge.apply_settings({"companion_orb_visual_style": style})
        if bridge.visualStyle != style:
            raise AssertionError(f"Bridge did not preserve visual style {style!r}: got {bridge.visualStyle!r}")

    bridge.apply_settings({"companion_orb_visual_style": "not-a-style"})
    if bridge.visualStyle != "neural_spark":
        raise AssertionError(f"Unknown visual style should fall back to 'neural_spark', got {bridge.visualStyle!r}")

    bridge.apply_settings({"companion_orb_eye_tracking_gaze_timer_color": "#facc15"})
    if bridge.gazeTimerActive or bridge.gazeTimerProgress != 0.0:
        raise AssertionError("Gaze timer visual state should be inactive by default.")
    if bridge.gazeTimerColor != "#facc15":
        raise AssertionError(f"The configured gaze timer color was not applied: {bridge.gazeTimerColor!r}")
    bridge.setGazeTimerState(True, 1.5, "#12ab34")
    if not bridge.gazeTimerActive or bridge.gazeTimerProgress != 1.0:
        raise AssertionError("Gaze timer state should clamp progress and activate immediately.")
    if bridge.gazeTimerColor != "#12ab34":
        raise AssertionError(f"A live gaze timer color was not normalized: {bridge.gazeTimerColor!r}")
    bridge.setGazeTimerState(False, 0.8, "")
    if bridge.gazeTimerActive or bridge.gazeTimerProgress != 0.0:
        raise AssertionError("Clearing the gaze timer must also clear visual progress.")

    qml_path = ROOT_DIR / "addons" / "companion_orb_overlay" / "companion_orb" / "qml" / "CompanionOrbOverlay.qml"
    qml_source = qml_path.read_text(encoding="utf-8")
    for style, function_name in EXPECTED_RENDER_FUNCTIONS.items():
        if f'visualStyle === "{style}"' not in qml_source:
            raise AssertionError(f"QML renderer does not dispatch visual style {style!r}")
        if f"function {function_name}(" not in qml_source:
            raise AssertionError(f"QML renderer is missing {function_name}()")
    for fragment in (
        "property bool gazeTimerActive:",
        "property real gazeTimerProgress:",
        "property color gazeTimerColor:",
        "var gazeMix =",
        "root.blendColor(primary, root.gazeTimerColor, gazeMix)",
    ):
        if fragment not in qml_source:
            raise AssertionError(f"QML gaze timer rendering is missing {fragment!r}.")

    external_runtime_path = qml_path.parents[1] / "external_orb_runtime.py"
    external_runtime_source = external_runtime_path.read_text(encoding="utf-8")
    for fragment in (
        'if msg_type == "gaze_timer":',
        "self.bridge.setGazeTimerState(",
    ):
        if fragment not in external_runtime_source:
            raise AssertionError(f"External Orb timer synchronization is missing {fragment!r}.")

    print("Companion Orb visual style smoke passed.")


if __name__ == "__main__":
    main()
