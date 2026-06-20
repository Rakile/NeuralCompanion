"""Static smoke checks for the Background Awareness UI copy.

This stays intentionally lightweight: the sensory controls are mostly Qt
widgets, but the contract being protected here is the user-facing wording and
short source labels used by both generated and Designer-backed UI paths.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PYTHON_SURFACES = [
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
    "Optional add-ons",
    "How background review uses this source",
    "Source Data Contract",
    "Reactions",
    "_sensory_source_icon",
    "_source_section_card",
    "nc-vision-source-tabs-fit",
    "setElideMode(QtCore.Qt.ElideNone)",
    "setExpanding(False)",
    "min-width: 132px;",
    "max-width: 320px;",
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
