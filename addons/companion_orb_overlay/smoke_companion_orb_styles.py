from __future__ import annotations

import sys
from pathlib import Path

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
}
EXPECTED_RENDER_FUNCTIONS = {
    "aurora_glass": "drawAuroraGlass",
    "prismatic_pulse": "drawPrismaticPulse",
    "aether_wisp": "drawAetherWisp",
    "celestial_firetrail": "drawCelestialFiretrail",
}


def main() -> None:
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

    qml_path = ROOT_DIR / "addons" / "companion_orb_overlay" / "companion_orb" / "qml" / "CompanionOrbOverlay.qml"
    qml_source = qml_path.read_text(encoding="utf-8")
    for style, function_name in EXPECTED_RENDER_FUNCTIONS.items():
        if f'visualStyle === "{style}"' not in qml_source:
            raise AssertionError(f"QML renderer does not dispatch visual style {style!r}")
        if f"function {function_name}(" not in qml_source:
            raise AssertionError(f"QML renderer is missing {function_name}()")

    print("Companion Orb visual style smoke passed.")


if __name__ == "__main__":
    main()
