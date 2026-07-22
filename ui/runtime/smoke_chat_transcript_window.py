from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))

from ui.runtime import chat_transcript_window as window


def test_latest_batch_and_previous_batch_use_full_history_indexes() -> None:
    history = [
        {"role": "system", "content": ""},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "", "attachment_image_path": "runtime/a.png"},
        {"role": "assistant", "content": "four"},
    ]

    assert window.normalize_visual_batch_size(None) == 200
    assert window.normalize_visual_batch_size(0) == 200
    assert window.normalize_visual_batch_size(-2) == 200
    assert window.normalize_visual_batch_size(-1) == -1
    assert window.displayable_history_indexes(history) == (1, 2, 3, 4)
    assert window.initial_window(history, 2) == ((3, 4), 4)
    assert window.previous_batch(history, (3, 4), 2) == (1, 2)
    assert window.previous_batch(history, (1, 2, 3, 4), 2) == ()
    assert window.initial_window(history, -1) == ((1, 2, 3, 4), 4)


def test_partial_edit_preserves_unseen_and_hidden_entries() -> None:
    history = [
        {"role": "user", "content": "unseen prefix", "created_at": 1.0},
        {"role": "user", "content": "visible one", "origin": "input", "created_at": 2.0},
        {"role": "system", "content": "", "internal": "preserve"},
        {
            "role": "assistant",
            "content": "visible two",
            "origin": "assistant_reply",
            "created_at": 3.0,
            "visual_reply_prompt": "keep",
        },
        {"role": "assistant", "content": "unseen suffix", "created_at": 4.0},
    ]

    merged = window.merge_edited_window(
        history,
        visible_indexes=(1, 3),
        original_display_entries=[
            {"role": "user", "origin": "input", "content": "visible one"},
            {"role": "assistant", "origin": "assistant_reply", "content": "visible two"},
        ],
        edited_entries=[
            {"role": "user", "origin": "input", "content": "edited one"},
            {"role": "assistant", "origin": "assistant_reply", "content": "edited two"},
        ],
        created_at=9.0,
    )

    assert merged[0] == history[0]
    assert merged[1]["content"] == "edited one"
    assert merged[1]["created_at"] == 2.0
    assert merged[2] == history[2]
    assert merged[3]["content"] == "edited two"
    assert merged[3]["visual_reply_prompt"] == "keep"
    assert merged[4] == history[4]


def test_partial_edit_insertions_and_deletions_keep_hidden_gaps() -> None:
    history = [
        {"role": "user", "content": "prefix"},
        {"role": "user", "origin": "input", "content": "delete"},
        {"role": "system", "content": "", "internal": "between"},
        {"role": "assistant", "origin": "assistant_reply", "content": "keep", "created_at": 4.0},
        {"role": "assistant", "content": "suffix"},
    ]

    merged = window.merge_edited_window(
        history,
        visible_indexes=(1, 3),
        original_display_entries=[
            {"role": "user", "origin": "input", "content": "delete"},
            {"role": "assistant", "origin": "assistant_reply", "content": "keep"},
        ],
        edited_entries=[
            {"role": "assistant", "origin": "assistant_reply", "content": "keep"},
            {"role": "user", "origin": "input", "content": "new"},
        ],
        created_at=9.0,
    )

    assert merged[0]["content"] == "prefix"
    assert merged[1]["internal"] == "between"
    assert merged[2]["content"] == "keep"
    assert merged[2]["created_at"] == 4.0
    assert merged[3]["content"] == "new"
    assert merged[3]["created_at"] == 9.0
    assert merged[4]["content"] == "suffix"


if __name__ == "__main__":
    test_latest_batch_and_previous_batch_use_full_history_indexes()
    test_partial_edit_preserves_unseen_and_hidden_entries()
    test_partial_edit_insertions_and_deletions_keep_hidden_gaps()
    print("smoke_chat_transcript_window: ok")
