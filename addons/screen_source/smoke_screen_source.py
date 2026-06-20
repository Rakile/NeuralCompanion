from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.screen_source.main import SCREEN_INDEX_ALL, _normalize_screen_index, _screen_label
from core.sensory_session_schema import LEGACY_FIELD_PATHS


def main() -> None:
    assert _normalize_screen_index(None) == SCREEN_INDEX_ALL
    assert _normalize_screen_index("-1") == SCREEN_INDEX_ALL
    assert _normalize_screen_index("2") == 2
    assert "1024 x 768 px at -1024, 0" in _screen_label(
        {
            "index": 1,
            "name": "Display-2",
            "primary": False,
            "bounds": {"x": -1024, "y": 0, "width": 1024, "height": 768},
        }
    )
    assert "screen_source_capture_screen_index" in LEGACY_FIELD_PATHS

    source = (ROOT / "addons" / "screen_source" / "main.py").read_text(encoding="utf-8")
    assert "screen_combo" in source
    assert "capture_screen_label" in source
    assert "screen_source_capture_screen_index" in source
    assert "Screen {selected + 1} unavailable" in source

    companion_source = (
        ROOT / "addons" / "companion_orb_overlay" / "companion_orb" / "companion_orb_controller.py"
    ).read_text(encoding="utf-8")
    assert "def _screen_source_capture_index" in companion_source
    assert "def _configured_screen_source_bounds" in companion_source
    assert "capture_mode = \"selected_screen\"" in companion_source
    assert "screen_source_capture_screen_index" in companion_source

    metadata = (ROOT / "addons" / "screen_source" / "sensory_metadata.json").read_text(encoding="utf-8")
    assert "selected monitor" in metadata
    assert "metadata.screen_bounds" in metadata

    print("Screen Source monitor selection smoke checks passed.")


if __name__ == "__main__":
    main()
