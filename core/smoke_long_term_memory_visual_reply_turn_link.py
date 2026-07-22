"""Smoke checks that generated visual replies become assistant turn assets."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import long_term_memory
from core import visual_reply_history


def test_visual_reply_image_links_to_matching_assistant_turn_and_archive_asset() -> None:
    previous_db_path = long_term_memory.default_db_path()

    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            db_path = root / "memory.sqlite3"
            image_path = root / "runtime" / "visual_reply.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(b"\x89PNG\r\nassistant-generated-image")

            conversation_history = [
                {
                    "role": "assistant",
                    "content": "Here is the scene I imagined.",
                    "origin": "assistant_reply",
                }
            ]

            assert visual_reply_history.attach_visual_reply_image_to_assistant_history(
                conversation_history,
                "visual-request-1",
                str(image_path),
                source_text="Here is the scene I imagined.",
                prompt_text="A small neon harbor at night.",
            )

            assistant_turn = conversation_history[-1]
            assert assistant_turn["visual_reply_image_path"] == str(image_path.resolve())
            assert assistant_turn["visual_reply_image_path_source"] == "generated_image"
            assert assistant_turn["visual_reply_request_id"] == "visual-request-1"
            assert assistant_turn["visual_reply_prompt"] == "A small neon harbor at night."

            turns = long_term_memory.sanitize_history_turns(conversation_history)
            chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="visual-link-test", path=db_path)
            assert chunk is not None
            linked = long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path)
            assert len(linked) == 1, linked
            assert linked[0]["role"] == "assistant"
            assert linked[0]["source"] == "generated_image"
            assert linked[0]["origin"] == "assistant_visual_reply"
            assert linked[0]["relation"] == "generated_by_reply"
            assert linked[0]["blob"] == image_path.read_bytes()
            assert linked[0]["metadata"]["visual_reply_prompt"] == "A small neon harbor at night."
            assert linked[0]["link_metadata"]["visual_reply_prompt"] == "A small neon harbor at night."
    finally:
        long_term_memory.set_default_db_path(previous_db_path)


def test_visual_reply_image_fields_survive_engine_chat_turn_sanitizer_boundary() -> None:
    turn = {
        "role": "assistant",
        "content": "Here is the generated image.",
        "origin": "assistant_reply",
    }
    source = {
        "visual_reply_image_path": "runtime/visual_reply/generated.png",
        "visual_reply_image_path_source": "generated_image",
        "visual_reply_request_id": "visual-request-2",
        "visual_reply_prompt": "A glass city in rain.",
    }

    visual_reply_history.preserve_visual_reply_image_fields(turn, source)

    assert turn["visual_reply_image_path"] == "runtime/visual_reply/generated.png"
    assert turn["visual_reply_image_path_source"] == "generated_image"
    assert turn["visual_reply_request_id"] == "visual-request-2"
    assert turn["visual_reply_prompt"] == "A glass city in rain."

    engine_text = (ROOT_DIR / "engine.py").read_text(encoding="utf-8")
    assert "visual_reply_history.preserve_visual_reply_image_fields(turn, entry)" in engine_text


def test_visual_reply_image_can_reconcile_after_assistant_turn_arrives() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        image_path = root / "runtime" / "visual_reply.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"\x89PNG\r\nassistant-generated-image")

        conversation_history = []
        pending_links = [
            {
                "request_id": "visual-request-delayed",
                "image_path": str(image_path),
                "source_text": "Here is the delayed scene.",
                "prompt_text": "A little moonlit observatory.",
            }
        ]

        first_result = visual_reply_history.reconcile_pending_visual_reply_image_links(
            conversation_history,
            pending_links,
        )
        assert first_result["linked"] == 0
        assert len(first_result["pending"]) == 1

        conversation_history.append(
            {
                "role": "assistant",
                "content": "Here is the delayed scene.",
                "origin": "assistant_reply",
            }
        )

        second_result = visual_reply_history.reconcile_pending_visual_reply_image_links(
            conversation_history,
            first_result["pending"],
        )
        assert second_result["linked"] == 1
        assert second_result["pending"] == []
        assert conversation_history[-1]["visual_reply_image_path"] == str(image_path.resolve())
        assert conversation_history[-1]["visual_reply_request_id"] == "visual-request-delayed"


def main() -> int:
    test_visual_reply_image_links_to_matching_assistant_turn_and_archive_asset()
    test_visual_reply_image_fields_survive_engine_chat_turn_sanitizer_boundary()
    test_visual_reply_image_can_reconcile_after_assistant_turn_arrives()
    print("long term memory visual reply turn link smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
