import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import chat_context_assets


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"nc-test-image"


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        runtime_image = root / "runtime" / "clipboard_image.png"
        runtime_image.parent.mkdir(parents=True)
        runtime_image.write_bytes(PNG_BYTES)
        context_path = root / "Saved Chat.json"
        payload = {
            "conversation_history": [
                {
                    "role": "user",
                    "content": "What is in this image?",
                    "origin": "input",
                    "attachment_image_path": str(runtime_image),
                    "attachment_source": "clipboard",
                }
            ]
        }

        preserved, report = chat_context_assets.preserve_chat_context_image_assets(payload, context_path)
        saved_path = str(preserved["conversation_history"][0]["attachment_image_path"])
        copied = root / saved_path
        assert report["copied"] == 1, report
        assert copied.exists(), copied
        assert copied.read_bytes() == PNG_BYTES
        assert copied.parent == root / "Saved Chat_assets" / "images"
        assert not Path(saved_path).is_absolute(), saved_path
        assert preserved["conversation_history"][0]["attachment_source"] == "clipboard"
        assert "attachment_missing_on_save" not in preserved["conversation_history"][0]
        json.dumps(preserved)

        preserved_again, report_again = chat_context_assets.preserve_chat_context_image_assets(preserved, context_path)
        assert report_again["copied"] == 0, report_again
        assert report_again["reused"] == 1, report_again
        assert preserved_again["conversation_history"][0]["attachment_image_path"] == saved_path
        assert len(list((root / "Saved Chat_assets" / "images").iterdir())) == 1

        resolved = chat_context_assets.resolve_chat_context_image_assets(preserved_again, context_path)
        resolved_path = Path(resolved["conversation_history"][0]["attachment_image_path"])
        assert resolved_path.is_absolute(), resolved_path
        assert resolved_path.exists(), resolved_path

        missing_payload = {
            "conversation_history": [
                {
                    "role": "user",
                    "content": "This had an image.",
                    "origin": "input",
                    "attachment_image_path": str(root / "runtime" / "missing.png"),
                    "attachment_source": "clipboard",
                }
            ]
        }
        missing_saved, missing_report = chat_context_assets.preserve_chat_context_image_assets(missing_payload, context_path)
        missing_turn = missing_saved["conversation_history"][0]
        assert missing_report["missing"] == 1, missing_report
        assert missing_turn["attachment_missing_on_save"] is True, missing_turn
        assert missing_turn["attachment_preservation_error"] == "missing_file", missing_turn

        old_payload = {"conversation_history": [{"role": "user", "content": "No image here."}]}
        old_resolved = chat_context_assets.resolve_chat_context_image_assets(old_payload, context_path)
        assert old_resolved == old_payload, old_resolved

        backend_console = (Path(__file__).resolve().parents[1] / "ui" / "runtime" / "backend_console_chat.py").read_text(encoding="utf-8")
        write_start = backend_console.index("def _write_chat_context_to_path")
        write_end = backend_console.index("def save_chat_context", write_start)
        write_body = backend_console[write_start:write_end]
        assert "resolve_chat_context_image_assets(payload, target)" in write_body, (
            "Save-triggered memory flush must resolve portable relative image paths before archive sync"
        )
        assert "_start_chat_context_memory_flush(memory_payload.get(\"conversation_history\", [])" in write_body, (
            "Save-triggered memory flush must use the resolved memory payload, not the portable saved JSON payload"
        )

    print("chat context image assets smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
