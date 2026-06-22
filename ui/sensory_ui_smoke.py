"""Static smoke checks for the Background Awareness UI copy.

This stays intentionally lightweight: the sensory controls are mostly Qt
widgets, but the contract being protected here is the user-facing wording and
short source labels used by both generated and Designer-backed UI paths.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PYTHON_SURFACES = [
    ROOT / "addons" / "screen_source" / "main.py",
    ROOT / "ui" / "theme_support.py",
    ROOT / "ui" / "runtime" / "backend_sensory_config.py",
    ROOT / "ui" / "runtime" / "backend_sensory_tabs.py",
    ROOT / "ui" / "runtime" / "backend_system_shaping_builders.py",
    ROOT / "ui" / "runtime" / "real_ui_layout.py",
    ROOT / "ui" / "runtime" / "real_ui_surfaces.py",
    ROOT / "ui" / "runtime" / "real_ui_theme.py",
]

REQUIRED_COPY = [
    "Background Awareness",
    "Enable background review",
    "Allow NC to speak about observations",
    "Use observations for Visual Reply images",
    "Sources to observe",
    "Review every",
    "Keep recent observations",
    "Restore recommended prompt",
    '"tab_label": "Screen"',
    '"tab_label": "Clipboard"',
    '"tab_label": "Spotify"',
    "Source Overview",
    "Optional Reactions",
    "How NC reads this source",
    "Advanced Source Details",
    "What gets reviewed",
    "What review can do",
    "Matching tags",
    "Reactions",
    "_sensory_source_icon",
    "_source_section_card",
    '"vision_background_awareness_group"',
    '"vision_overview_review_group"',
    '"vision_overview_sources_group"',
    '"vision_overview_actions_group"',
    '"vision_source_overview_group"',
    '"vision_source_guidance_group"',
    '"vision_source_advanced_details_group"',
    '"vision_source_reactions_group"',
    "_normalize_vision_source_contribution_widget",
    '"vision_contribution_panel"',
    '"vision_source_capture_area_group"',
    '"vision_source_image_detail_group"',
    '"vision_source_capture_actions_group"',
    '"vision_source_current_selection_group"',
    "Capture Area",
    "Image Detail",
    "Capture Actions",
    "Current Selection",
    "rgba(96, 165, 250, 0.32)",
    "nc-vision-source-tabs-fit",
    "setElideMode(QtCore.Qt.ElideNone)",
    "setExpanding(False)",
    "_apply_vision_tab_button_style",
    "_apply_vision_tab_button_style(self.sensory_feedback_tabs",
    "_apply_vision_tab_button_style(nested_tabs",
    "min-width: 112px;",
    "max-width: 190px;",
    "nc-vision-tab-buttons-compact",
    "min-height: 30px;",
    "max-height: 30px;",
    "height: 30px;",
    "padding: 4px 12px;",
    "margin-right: 3px;",
    "setFixedHeight(34)",
]

OUTDATED_COPY = [
    "Background Sensory Awareness",
    "Run background sensory review",
    "Let NC speak from background observations",
    "Let Visual Reply use background observations",
    "Capture sources",
    "Keep recent notes",
    "Use Recommended",
    "hidden PING/PONG",
    "Optional add-ons",
    "How background review uses this source",
    "Source Data Contract",
    "Data sent to review",
    "Allowed review outputs",
    "Tags this source can use",
    "min-width: 132px;",
    "max-width: 320px;",
    "padding-left: 18px;",
    "padding-right: 18px;",
]


def _combined_python_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in PYTHON_SURFACES)


def main() -> int:
    text = _combined_python_text()
    missing = [copy for copy in REQUIRED_COPY if copy not in text]
    stale = [copy for copy in OUTDATED_COPY if copy in text]
    if missing:
        print("[Sensory UI Smoke] Missing updated copy:")
        for copy in missing:
            print(f"  - {copy}")
    if stale:
        print("[Sensory UI Smoke] Outdated copy still present:")
        for copy in stale:
            print(f"  - {copy}")
    if missing or stale:
        return 1
    print("[Sensory UI Smoke] Background Awareness UI copy is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
