from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.chat_runtime_session_schema import group_chat_runtime_session
from core.ui_session_schema import group_ui_session, with_flat_ui_settings


def test_review_preference_is_global_ui_state_not_chat_session_state():
    grouped = group_ui_session({"long_term_memory_image_review_enabled": True})
    assert grouped["ui"]["memory"]["review_recalled_images_before_sending"] is True
    assert with_flat_ui_settings(grouped)["long_term_memory_image_review_enabled"] is True

    chat_payload = group_chat_runtime_session({"long_term_memory_image_review_enabled": True})
    assert "long_term_memory_image_review_enabled" in chat_payload
    assert "review_recalled_images_before_sending" not in str(chat_payload.get("chat_runtime", {}))


if __name__ == "__main__":
    test_review_preference_is_global_ui_state_not_chat_session_state()
    print("long term memory image review session scope smoke passed")
