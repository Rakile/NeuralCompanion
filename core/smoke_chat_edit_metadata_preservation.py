from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))


def _load_test_module(*parts: str):
    return importlib.import_module(".".join(parts))


addons_module = types.ModuleType("addons")
addons_module.__path__ = [str(ROOT / "addons")]
sys.modules["addons"] = addons_module
_load_test_module("addons", "vam_avatar", "config")

from core import conversation_history

engine = _load_test_module("engine")


def test_text_edits_preserve_hidden_turn_metadata() -> None:
    original_history = [
        {
            "role": "user",
            "content": "Inspect this image.",
            "origin": "input",
            "created_at": 10.0,
            "attachment_image_path": "runtime/input.png",
            "attachment_source": "clipboard",
            "identity_relay": {
                "state": "active",
                "artifact_ref": "library/" + "a" * 64 + ".json",
                "artifact_hash": "a" * 64,
                "snapshot_hash": "b" * 64,
                "failure_code": None,
            },
        },
        {
            "role": "assistant",
            "content": "Here is the generated image.",
            "origin": "assistant_reply",
            "created_at": 20.0,
            "visual_reply_image_path": "runtime/generated.png",
            "visual_reply_request_id": "visual-1",
            "visual_reply_prompt": "Generate a test image.",
        },
    ]
    original_display_entries = [
        {"role": "user", "content": "Inspect this image. [Image attached]", "origin": "input"},
        {"role": "assistant", "content": "Here is the generated image.", "origin": "assistant_reply"},
    ]
    edited_entries = [
        {"role": "user", "content": "Inspect this updated image. [Image attached]", "origin": "input"},
        {"role": "assistant", "content": "Here is the revised generated image.", "origin": "assistant_reply"},
    ]

    merged = conversation_history.merge_edited_history_metadata(
        original_history,
        original_display_entries,
        edited_entries,
        created_at=99.0,
    )

    assert merged[0]["content"] == "Inspect this updated image."
    assert merged[0]["created_at"] == 10.0
    assert merged[0]["attachment_image_path"] == "runtime/input.png"
    assert merged[0]["attachment_source"] == "clipboard"
    sanitized = engine._sanitize_chat_turn(merged[0])
    original_history[0]["identity_relay"]["state"] = "suspended"
    merged[0]["identity_relay"]["state"] = "unavailable"
    assert sanitized["identity_relay"]["state"] == "active"
    assert sanitized["identity_relay"]["snapshot_hash"] == "b" * 64
    assert merged[1]["content"] == "Here is the revised generated image."
    assert merged[1]["created_at"] == 20.0
    assert merged[1]["visual_reply_image_path"] == "runtime/generated.png"
    assert merged[1]["visual_reply_request_id"] == "visual-1"
    assert merged[1]["visual_reply_prompt"] == "Generate a test image."


def test_insertions_and_deletions_do_not_transfer_unrelated_metadata() -> None:
    original_history = [
        {"role": "user", "content": "Delete me.", "origin": "input", "created_at": 10.0, "attachment_image_path": "runtime/deleted.png"},
        {"role": "assistant", "content": "Keep me.", "origin": "assistant_reply", "created_at": 20.0, "visual_reply_image_path": "runtime/kept.png"},
    ]
    original_display_entries = [
        {"role": "user", "content": "Delete me. [Image attached]", "origin": "input"},
        {"role": "assistant", "content": "Keep me.", "origin": "assistant_reply"},
    ]
    edited_entries = [
        {"role": "assistant", "content": "Keep me.", "origin": "assistant_reply"},
        {"role": "user", "content": "A new message.", "origin": "input"},
    ]

    merged = conversation_history.merge_edited_history_metadata(
        original_history,
        original_display_entries,
        edited_entries,
        created_at=99.0,
    )

    assert merged[0]["created_at"] == 20.0
    assert merged[0]["visual_reply_image_path"] == "runtime/kept.png"
    assert "attachment_image_path" not in merged[0]
    assert merged[1] == {
        "role": "user",
        "content": "A new message.",
        "origin": "input",
        "created_at": 99.0,
    }


if __name__ == "__main__":
    test_text_edits_preserve_hidden_turn_metadata()
    test_insertions_and_deletions_do_not_transfer_unrelated_metadata()
    print("smoke_chat_edit_metadata_preservation: ok")
