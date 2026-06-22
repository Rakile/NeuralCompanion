from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.musetalk_avatar import preview_panel

_preview_image_file_ready = preview_panel._preview_image_file_ready


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        frame_path = Path(temp_dir) / "00000001.png"
        frame_path.write_bytes(b"partial png bytes")

        ready, payload = _preview_image_file_ready(str(frame_path), min_age_ms=50.0)
        assert ready is False
        assert payload["exists"] is True
        assert payload["age_ms"] is not None

        old_timestamp = time.time() - 1.0
        os.utime(frame_path, (old_timestamp, old_timestamp))
        ready, payload = _preview_image_file_ready(str(frame_path), min_age_ms=50.0)
        assert ready is True
        assert payload["exists"] is True

        missing_path = Path(temp_dir) / "missing.png"
        ready, payload = _preview_image_file_ready(str(missing_path), min_age_ms=50.0)
        assert ready is False
        assert payload["exists"] is False

    assert preview_panel.QT_PREVIEW_CACHE_LIMIT >= 768
    assert preview_panel.QT_PREVIEW_INITIAL_PRELOAD >= 96
    assert preview_panel.QT_PREVIEW_AHEAD_PRELOAD >= 96
    assert preview_panel.QT_PREVIEW_PRELOAD_RETRY_DELAY_MS <= 50


if __name__ == "__main__":
    main()
    print("smoke_preview_frame_readiness: ok")
