import sqlite3
import sys
import tempfile
from pathlib import Path

from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import long_term_memory


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _assert_table_exists(db_path: Path, table_name: str) -> None:
    with sqlite3.connect(str(db_path)) as connection:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    assert row is not None, f"missing table {table_name}"


def test_schema_migration_creates_asset_tables() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "old.sqlite3"
        with sqlite3.connect(str(db_path)) as connection:
            connection.execute("CREATE TABLE memory_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO memory_meta(key, value) VALUES ('schema_version', '2')")
            connection.commit()

        long_term_memory.init_store(db_path)

        _assert_table_exists(db_path, "long_term_memory_assets")
        _assert_table_exists(db_path, "long_term_memory_asset_links")


def test_archive_user_and_assistant_images_as_durable_assets() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        user_image = _write_bytes(root / "runtime" / "screen.png", b"\x89PNG\r\nuser-image")
        assistant_image = _write_bytes(root / "runtime" / "generated.jpg", b"\xff\xd8assistant-image\xff\xd9")

        turns = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "user",
                    "content": "What do you see?",
                    "attachment_image_path": str(user_image),
                    "attachment_source": "screen",
                },
                {
                    "role": "assistant",
                    "content": "I drew this.",
                    "attachment_image_path": str(assistant_image),
                    "attachment_source": "generated_image",
                },
            ]
        )

        chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="image-test", path=db_path)
        assert chunk is not None
        assert "[Image attached: screen]" in chunk["text"]
        assert "[Image attached: generated_image]" in chunk["text"]

        linked = long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path)
        assert len(linked) == 2, linked
        by_index = {item["source_message_index"]: item for item in linked}
        assert by_index[1]["role"] == "user"
        assert by_index[1]["source"] == "screen"
        assert by_index[1]["relation"] == "attached_to_turn"
        assert by_index[1]["blob"] == user_image.read_bytes()
        assert by_index[2]["role"] == "assistant"
        assert by_index[2]["source"] == "generated_image"
        assert by_index[2]["relation"] == "generated_by_reply"
        assert by_index[2]["blob"] == assistant_image.read_bytes()


def test_archive_deduplicates_image_blob_but_keeps_links() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        shared = _write_bytes(root / "runtime" / "shared.png", b"\x89PNG\r\nsame-image")

        turns = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "user",
                    "content": "First view",
                    "attachment_image_path": str(shared),
                    "attachment_source": "clipboard",
                },
                {
                    "role": "user",
                    "content": "Second view",
                    "attachment_image_path": str(shared),
                    "attachment_source": "clipboard",
                },
            ]
        )

        chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="dedupe-test", path=db_path)
        assert chunk is not None
        linked = long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path)
        assert len(linked) == 2, linked
        assert linked[0]["asset_id"] == linked[1]["asset_id"], linked

        with sqlite3.connect(str(db_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM long_term_memory_assets").fetchone()[0]
        assert count == 1


def test_missing_image_path_preserves_text_and_does_not_crash() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "memory.sqlite3"
        missing = Path(temp_dir) / "runtime" / "missing.png"

        turns = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "user",
                    "content": "This had an image.",
                    "attachment_image_path": str(missing),
                    "attachment_source": "screen",
                }
            ]
        )

        chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="missing-test", path=db_path)
        assert chunk is not None
        assert "[Image attached: screen]" in chunk["text"]
        assert long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path) == []


def test_assistant_visual_reply_image_field_is_archived() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        visual_reply = _write_bytes(root / "runtime" / "visual_reply.png", b"\x89PNG\r\nvisual-reply")

        turns = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "assistant",
                    "content": "I made a reference image.",
                    "visual_reply_image_path": str(visual_reply),
                }
            ]
        )

        chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="visual-reply-test", path=db_path)
        assert chunk is not None
        linked = long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path)
        assert len(linked) == 1, linked
        assert linked[0]["role"] == "assistant"
        assert linked[0]["source"] == "generated_image"
        assert linked[0]["origin"] == "assistant_visual_reply"
        assert linked[0]["relation"] == "generated_by_reply"
        assert linked[0]["blob"] == visual_reply.read_bytes()


def test_existing_history_chunk_can_backfill_later_visual_reply_asset() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        visual_reply = _write_bytes(root / "runtime" / "late_visual_reply.png", b"\x89PNG\r\nlate-visual-reply")

        original_turns = long_term_memory.sanitize_history_turns(
            [{"role": "assistant", "content": "I can picture this scene."}]
        )
        chunk = long_term_memory.archive_history_chunk(original_turns, source_chat_id="late-visual-test", path=db_path)
        assert chunk is not None
        assert long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path) == []

        updated_turns = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "assistant",
                    "content": "I can picture this scene.",
                    "visual_reply_image_path": str(visual_reply),
                }
            ]
        )

        assert long_term_memory.ensure_history_chunk_assets(
            chunk,
            updated_turns,
            source_chat_id="late-visual-test",
            path=db_path,
        ) == 1
        linked = long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path)
        assert len(linked) == 1, linked
        assert linked[0]["origin"] == "assistant_visual_reply"
        assert linked[0]["blob"] == visual_reply.read_bytes()


def test_retrieved_chunk_can_be_hydrated_with_linked_visual_assets() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        visual_reply = _write_bytes(root / "runtime" / "retrieved_visual_reply.png", b"\x89PNG\r\nretrieved-visual-reply")

        turns = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "assistant",
                    "content": "I generated the remembered image.",
                    "visual_reply_image_path": str(visual_reply),
                }
            ]
        )
        chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="retrieval-asset-test", path=db_path)
        assert chunk is not None

        hydrated = long_term_memory.attach_assets_to_retrieval_results(
            [
                {
                    "kind": "chunk",
                    "id": chunk["id"],
                    "snippet": chunk["text"],
                }
            ],
            path=db_path,
        )
        assert len(hydrated) == 1
        assert len(hydrated[0]["assets"]) == 1
        assert hydrated[0]["assets"][0]["origin"] == "assistant_visual_reply"
        assert hydrated[0]["assets"][0]["relation"] == "generated_by_reply"
        assert hydrated[0]["assets"][0]["blob"] == visual_reply.read_bytes()


def test_visual_reply_prompt_participates_in_chunk_embedding_text() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        visual_reply = _write_bytes(root / "runtime" / "cornfield.png", b"\x89PNG\r\ncornfield")

        turns_without_prompt = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "assistant",
                    "content": "Here is the generated scene.",
                    "visual_reply_image_path": str(visual_reply),
                }
            ]
        )
        chunk = long_term_memory.archive_history_chunk(
            turns_without_prompt,
            source_chat_id="embedding-prompt-test",
            path=db_path,
        )
        assert chunk is not None
        before = long_term_memory.embedding_text_for_chunk(chunk, path=db_path)
        before_hash = long_term_memory.text_hash(before)
        assert "woman in a green jacket" not in before
        long_term_memory.upsert_embedding(
            target_kind="chunk",
            target_id=chunk["id"],
            model="test-embedding-model@ctx8192",
            text=before,
            vector=[0.1, 0.2, 0.3],
            path=db_path,
        )

        turns_with_prompt = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "assistant",
                    "content": "Here is the generated scene.",
                    "visual_reply_image_path": str(visual_reply),
                    "visual_reply_prompt": (
                        "A man in a red jacket and a woman in a green jacket standing in a cornfield."
                    ),
                }
            ]
        )
        assert long_term_memory.ensure_history_chunk_assets(
            chunk,
            turns_with_prompt,
            source_chat_id="embedding-prompt-test",
            path=db_path,
        ) == 1

        after = long_term_memory.embedding_text_for_chunk(chunk, path=db_path)
        assert "Linked image descriptions:" in after
        assert "A man in a red jacket and a woman in a green jacket standing in a cornfield." in after
        assert long_term_memory.text_hash(after) != before_hash
        outdated = long_term_memory.list_embedding_targets(
            model="test-embedding-model@ctx8192",
            context_length=8192,
            include_records=False,
            only_missing=True,
            path=db_path,
        )
        assert [target["id"] for target in outdated] == [chunk["id"]]


def test_visual_reply_prompt_can_be_recovered_from_original_image_comment() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        prompt = "A silver lighthouse beneath a violet aurora."
        png_path = root / "commented.png"
        png_info = PngImagePlugin.PngInfo()
        png_info.add_text("Comment", prompt)
        Image.new("RGB", (8, 8), "navy").save(png_path, pnginfo=png_info)

        turns = long_term_memory.sanitize_history_turns(
            [
                {
                    "role": "assistant",
                    "content": "Here is the older generated image.",
                    "visual_reply_image_path": str(png_path),
                }
            ]
        )
        chunk = long_term_memory.archive_history_chunk(
            turns,
            source_chat_id="comment-recovery-test",
            path=db_path,
        )
        assert chunk is not None
        linked_before = long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path, include_blob=False)
        assert "visual_reply_prompt" not in linked_before[0]["link_metadata"]

        recovered = long_term_memory.backfill_target_visualization_prompts_from_original_paths(
            "chunk",
            chunk["id"],
            path=db_path,
        )
        assert recovered == 1
        linked_after = long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path, include_blob=False)
        assert linked_after[0]["link_metadata"]["visual_reply_prompt"] == prompt
        assert linked_after[0]["metadata"]["visual_reply_prompt"] == prompt
        assert prompt in long_term_memory.embedding_text_for_chunk(chunk, path=db_path)

        jpeg_prompt = "A red tram crossing a snowy bridge."
        jpeg_path = root / "commented.jpg"
        Image.new("RGB", (8, 8), "white").save(jpeg_path, format="JPEG", comment=jpeg_prompt.encode("utf-8"))
        assert long_term_memory.visualization_prompt_from_image_comment(jpeg_path) == jpeg_prompt


def test_user_attachment_comment_is_not_reclassified_as_visual_reply_prompt() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.sqlite3"
        image_path = root / "user-image.png"
        png_info = PngImagePlugin.PngInfo()
        png_info.add_text("Comment", "Untrusted comment from an unrelated image editor.")
        Image.new("RGB", (8, 8), "black").save(image_path, pnginfo=png_info)
        turns = long_term_memory.sanitize_history_turns(
            [{
                "role": "user",
                "content": "Look at this image.",
                "attachment_image_path": str(image_path),
                "attachment_source": "clipboard",
            }]
        )
        chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="user-comment-test", path=db_path)
        assert chunk is not None

        recovered = long_term_memory.backfill_target_visualization_prompts_from_original_paths(
            "chunk", chunk["id"], path=db_path,
        )
        assert recovered == 0
        embedding_text = long_term_memory.embedding_text_for_chunk(chunk, path=db_path)
        assert "Untrusted comment" not in embedding_text


def test_image_recall_query_gate() -> None:
    assert not long_term_memory.query_requests_image_recall("Hello, how are you?")
    assert not long_term_memory.query_requests_image_recall("Tell me what we discussed yesterday.")
    assert long_term_memory.query_requests_image_recall("Let's look at the image you generated next.")
    assert long_term_memory.query_requests_image_recall("What do you see in that screenshot?")


def test_asset_debug_label_includes_runtime_validation_fields() -> None:
    label = long_term_memory.asset_debug_label(
        {
            "asset_id": "asset_image_test",
            "role": "assistant",
            "origin": "assistant_visual_reply",
            "source": "generated_image",
            "relation": "generated_by_reply",
            "mime_type": "image/png",
            "source_message_index": 12,
            "blob": b"abc",
        }
    )
    assert "asset=asset_image_test" in label
    assert "role=assistant" in label
    assert "origin=assistant_visual_reply" in label
    assert "source=generated_image" in label
    assert "relation=generated_by_reply" in label
    assert "mime=image/png" in label
    assert "message=12" in label
    assert "bytes=3" in label


def test_text_only_archive_has_no_assets() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "memory.sqlite3"
        turns = long_term_memory.sanitize_history_turns(
            [{"role": "user", "content": "Plain text only."}]
        )

        chunk = long_term_memory.archive_history_chunk(turns, source_chat_id="text-test", path=db_path)
        assert chunk is not None
        assert chunk["text"] == "1. User: Plain text only."
        assert long_term_memory.list_assets_for_target("chunk", chunk["id"], path=db_path) == []


def main() -> int:
    previous_path = long_term_memory.default_db_path()
    try:
        test_schema_migration_creates_asset_tables()
        test_archive_user_and_assistant_images_as_durable_assets()
        test_archive_deduplicates_image_blob_but_keeps_links()
        test_missing_image_path_preserves_text_and_does_not_crash()
        test_assistant_visual_reply_image_field_is_archived()
        test_existing_history_chunk_can_backfill_later_visual_reply_asset()
        test_retrieved_chunk_can_be_hydrated_with_linked_visual_assets()
        test_visual_reply_prompt_participates_in_chunk_embedding_text()
        test_visual_reply_prompt_can_be_recovered_from_original_image_comment()
        test_user_attachment_comment_is_not_reclassified_as_visual_reply_prompt()
        test_image_recall_query_gate()
        test_asset_debug_label_includes_runtime_validation_fields()
        test_text_only_archive_has_no_assets()
    finally:
        long_term_memory.set_default_db_path(previous_path)
    print("long term memory image asset smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
