from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from core import long_term_memory
from core.long_term_memory_archive_rebuild import rebuild_archive_candidate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_context(path: Path, image_path: Path) -> None:
    history = []
    for index in range(18):
        role = "user" if index % 2 == 0 else "assistant"
        turn = {
            "role": role,
            "content": f"message {index + 1}",
            "origin": "input" if role == "user" else "assistant_reply",
        }
        if index == 8:
            turn.update(
                {
                    "attachment_image_path": image_path.name,
                    "attachment_source": "clipboard",
                }
            )
        history.append(turn)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "continuity_memory_id": "rebuild-test",
                "conversation_history": history,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_rebuild_creates_isolated_candidate_with_relinked_images() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        context_path = root / "rebuild-test.json"
        image_path = root / "remembered.png"
        image_path.write_bytes(b"\x89PNG\r\narchive-rebuild-image")
        _write_context(context_path, image_path)

        source_db = root / "rebuild-test.sqlite3"
        old_turns = long_term_memory.sanitize_history_turns(
            json.loads(context_path.read_text(encoding="utf-8"))["conversation_history"]
        )
        old_chunk = long_term_memory.archive_history_chunk(
            old_turns,
            source_chat_id="rebuild-test",
            path=source_db,
        )
        assert old_chunk is not None
        long_term_memory.create_memory(
            memory_type="fact",
            title="Preserved record",
            summary="Keep this record",
            content="This durable record must survive candidate rebuilding.",
            source_chat_id="rebuild-test",
            path=source_db,
        )
        before_hash = _sha256(source_db)

        output_dir = root / "candidates"
        result = rebuild_archive_candidate(
            context_path,
            source_db_path=source_db,
            output_dir=output_dir,
            chunk_size=8,
        )

        candidate_db = Path(result["candidate_db"])
        assert candidate_db.is_file()
        assert candidate_db != source_db
        assert _sha256(source_db) == before_hash
        assert result["source_unchanged"] is True
        assert result["messages_archived"] == 18
        assert result["chunks_created"] == 3
        assert result["records_preserved"] == 1
        assert result["assets_preserved"] == 1
        assert result["asset_links_relinked"] == 1
        assert result["unresolved_asset_links"] == 0
        assert result["activated"] is False
        assert Path(result["report_path"]).is_file()

        chunks = long_term_memory.list_archived_chunks(
            source_chat_id="rebuild-test",
            limit=20,
            path=candidate_db,
        )
        ranges = sorted(
            (int(chunk["source_message_start"]), int(chunk["source_message_end"]))
            for chunk in chunks
        )
        assert ranges == [(1, 8), (9, 16), (17, 18)]
        image_chunk = next(
            chunk for chunk in chunks
            if int(chunk["source_message_start"]) <= 9 <= int(chunk["source_message_end"])
        )
        assets = long_term_memory.list_assets_for_target(
            "chunk",
            image_chunk["id"],
            path=candidate_db,
        )
        assert len(assets) == 1
        assert assets[0]["source_message_index"] == 9
        assert assets[0]["sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()

        connection = sqlite3.connect(str(candidate_db))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        assert integrity == "ok"

        moved_db = candidate_db.with_name(f"{candidate_db.stem}-moved.sqlite3")
        candidate_db.replace(moved_db)
        moved_db.replace(candidate_db)


def test_default_archive_chunk_size_is_eight() -> None:
    assert long_term_memory.DEFAULT_EXTRACTION_TURNS == 8


def test_rebuild_recovers_missing_context_image_from_legacy_asset_blob() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        context_path = root / "legacy-image.json"
        image_path = root / "legacy.png"
        image_bytes = b"\x89PNG\r\nlegacy-image-only-in-sqlite"
        image_path.write_bytes(image_bytes)
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"legacy {index + 1}"}
            for index in range(10)
        ]
        history[3].update(
            {
                "attachment_image_path": "missing-after-save.png",
                "attachment_source": "clipboard",
            }
        )
        context_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "continuity_memory_id": "legacy-image",
                    "conversation_history": history,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        source_history = json.loads(context_path.read_text(encoding="utf-8"))["conversation_history"]
        source_history[3]["attachment_image_path"] = str(image_path)
        source_db = root / "legacy-image.sqlite3"
        old_chunk = long_term_memory.archive_history_chunk(
            long_term_memory.sanitize_history_turns(source_history),
            source_chat_id="legacy-image",
            path=source_db,
        )
        assert old_chunk is not None
        image_path.unlink()

        result = rebuild_archive_candidate(
            context_path,
            source_db_path=source_db,
            output_dir=root / "candidates",
            chunk_size=8,
        )
        candidate_db = Path(result["candidate_db"])
        chunks = long_term_memory.list_archived_chunks(
            source_chat_id="legacy-image",
            limit=10,
            path=candidate_db,
        )
        image_chunk = next(chunk for chunk in chunks if int(chunk["source_message_start"]) == 1)
        assets = long_term_memory.list_assets_for_target("chunk", image_chunk["id"], path=candidate_db)
        assert len(assets) == 1
        assert assets[0]["source_message_index"] == 4
        assert assets[0]["blob"] == image_bytes
        assert result["unresolved_asset_links"] == 0


def test_rebuild_from_context_only_preserves_generated_image_metadata() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        context_path = root / "context-only.json"
        image_path = root / "generated.jpg"
        image_path.write_bytes(b"context-only-generated-image")
        visual_prompt = "A precise remembered workshop scene with blueprints."
        context_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "continuity_memory_id": "context-only",
                    "conversation_history": [
                        {"role": "user", "content": "Please create the workshop image."},
                        {
                            "role": "assistant",
                            "content": "Here is the workshop image.",
                            "origin": "assistant_reply",
                            "visual_reply_image_path": image_path.name,
                            "visual_reply_image_path_source": "generated_image",
                            "visual_reply_prompt": visual_prompt,
                        },
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        result = rebuild_archive_candidate(
            context_path,
            source_db_path=root / "does-not-exist.sqlite3",
            output_dir=root / "candidates",
            chunk_size=8,
        )
        candidate_db = Path(result["candidate_db"])
        chunks = long_term_memory.list_archived_chunks(
            source_chat_id="context-only",
            limit=10,
            path=candidate_db,
        )
        assert len(chunks) == 1
        assets = long_term_memory.list_assets_for_target("chunk", chunks[0]["id"], path=candidate_db)
        assert len(assets) == 1
        assert assets[0]["source_message_index"] == 2
        assert assets[0]["metadata"]["visual_reply_prompt"] == visual_prompt
        assert result["old_chunks"] == 0
        assert result["assets_preserved"] == 1
        assert result["asset_links_relinked"] == 1


def test_valid_context_image_does_not_relink_stale_legacy_image() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        context_path = root / "authoritative-context.json"
        current_image = root / "current.png"
        stale_image = root / "stale.png"
        current_image.write_bytes(b"current-context-image")
        stale_image.write_bytes(b"stale-legacy-image")
        context_history = [
            {"role": "user", "content": "Look at this.", "attachment_image_path": current_image.name},
            {"role": "assistant", "content": "I see it."},
        ]
        context_path.write_text(
            json.dumps(
                {
                    "continuity_memory_id": "authoritative-context",
                    "conversation_history": context_history,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        legacy_history = json.loads(json.dumps(context_history))
        legacy_history[0]["attachment_image_path"] = str(stale_image)
        source_db = root / "authoritative-context.sqlite3"
        old_chunk = long_term_memory.archive_history_chunk(
            long_term_memory.sanitize_history_turns(legacy_history),
            source_chat_id="authoritative-context",
            path=source_db,
        )
        assert old_chunk is not None

        result = rebuild_archive_candidate(
            context_path,
            source_db_path=source_db,
            output_dir=root / "candidates",
            chunk_size=8,
        )
        candidate_db = Path(result["candidate_db"])
        chunks = long_term_memory.list_archived_chunks(
            source_chat_id="authoritative-context",
            limit=10,
            path=candidate_db,
        )
        assets = long_term_memory.list_assets_for_target("chunk", chunks[0]["id"], path=candidate_db)
        assert len(assets) == 1
        assert assets[0]["sha256"] == hashlib.sha256(current_image.read_bytes()).hexdigest()
        assert result["legacy_asset_links_recovered"] == 0
        assert result["legacy_asset_links_skipped"] == 1


if __name__ == "__main__":
    test_rebuild_creates_isolated_candidate_with_relinked_images()
    test_default_archive_chunk_size_is_eight()
    test_rebuild_recovers_missing_context_image_from_legacy_asset_blob()
    test_rebuild_from_context_only_preserves_generated_image_metadata()
    test_valid_context_image_does_not_relink_stale_legacy_image()
    print("long term memory archive rebuild candidate smoke passed")
