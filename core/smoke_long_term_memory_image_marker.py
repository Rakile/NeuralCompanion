import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import long_term_memory


def main() -> int:
    turns = long_term_memory.sanitize_history_turns(
        [
            {
                "role": "user",
                "content": "What do you see?",
                "attachment_image_path": "runtime/clipboard.png",
                "attachment_source": "clipboard",
            },
            {
                "role": "user",
                "content": "",
                "attachment_image_path": "runtime/screen.png",
                "attachment_source": "screen",
            },
        ]
    )
    assert len(turns) == 2, turns
    assert turns[0]["content"] == "What do you see? [Image attached: clipboard]", turns[0]
    assert turns[1]["content"] == "[Image attached: screen]", turns[1]
    segment = long_term_memory.format_history_segment(turns)
    assert "[Image attached: clipboard]" in segment, segment
    assert "[Image attached: screen]" in segment, segment
    print("long term memory image marker smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
