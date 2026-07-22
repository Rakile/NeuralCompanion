from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ui_session_schema import group_ui_session, with_flat_ui_settings
from ui.runtime.chat_transcript_window import DEFAULT_VISUAL_BATCH_SIZE


def test_visual_batch_setting_is_grouped_and_flattened():
    grouped = group_ui_session({"chat_visual_batch_size": 350})
    assert grouped["ui"]["chat"]["messages_per_visual_batch"] == 350
    assert "chat_visual_batch_size" not in grouped
    assert with_flat_ui_settings(grouped)["chat_visual_batch_size"] == 350


def test_visual_batch_setting_wiring_exists():
    assert DEFAULT_VISUAL_BATCH_SIZE == 200
    assert '"chat_visual_batch_size": 200' in (ROOT / "engine.py").read_text(encoding="utf-8")
    assert "chat_visual_batch_size_spin" in (ROOT / "main.ui").read_text(encoding="utf-8")
    assert "on_chat_visual_batch_size_changed" in (
        ROOT / "ui" / "runtime" / "backend_chat_session_runtime.py"
    ).read_text(encoding="utf-8")


def test_visual_batch_text_input_commits_only_after_editing_finishes():
    ui_root = ET.parse(ROOT / "main.ui").getroot()
    widget = ui_root.find(".//widget[@name='chat_visual_batch_size_spin']")
    assert widget is not None
    keyboard_tracking = widget.find("./property[@name='keyboardTracking']/bool")
    assert keyboard_tracking is not None
    assert str(keyboard_tracking.text or "").strip().lower() == "false"


def main():
    test_visual_batch_setting_is_grouped_and_flattened()
    test_visual_batch_setting_wiring_exists()
    test_visual_batch_text_input_commits_only_after_editing_finishes()
    print("smoke_chat_visual_batch_setting: ok")


if __name__ == "__main__":
    main()
