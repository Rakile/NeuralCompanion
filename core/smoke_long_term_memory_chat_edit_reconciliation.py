from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from core import long_term_memory


def _history(count: int) -> list[dict[str, str]]:
    return [
        {
            "role": "user" if index % 2 else "assistant",
            "content": f"message {index}",
        }
        for index in range(1, count + 1)
    ]


def test_prune_archived_chunks_from_first_edited_message() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "memory.sqlite3"
        turns = long_term_memory.sanitize_history_turns(_history(16))
        current_chunks = [
            long_term_memory.archive_history_chunk(
                turns[start:start + 4],
                source_chat_id="current_chat",
                path=db_path,
            )
            for start in range(0, 16, 4)
        ]
        other_chunk = long_term_memory.archive_history_chunk(
            turns[:4],
            source_chat_id="other_chat",
            path=db_path,
        )
        stale_chunk = dict(current_chunks[2] or {})
        stale_chunk_id = str(stale_chunk.get("id") or "")
        preserved_chunk_id = str((current_chunks[1] or {}).get("id") or "")
        assert stale_chunk_id and preserved_chunk_id and other_chunk

        long_term_memory.upsert_embedding(
            target_kind="chunk",
            target_id=stale_chunk_id,
            model="test-model",
            text="stale",
            vector=[1.0, 0.0],
            path=db_path,
        )
        long_term_memory.upsert_embedding(
            target_kind="chunk_slice",
            target_id=f"{stale_chunk_id}_s0001",
            model="test-model",
            text="stale slice",
            vector=[0.0, 1.0],
            path=db_path,
        )
        long_term_memory.upsert_embedding(
            target_kind="chunk",
            target_id=preserved_chunk_id,
            model="test-model",
            text="preserved",
            vector=[1.0, 1.0],
            path=db_path,
        )
        image_path = Path(temp_dir) / "linked-image.png"
        image_path.write_bytes(b"preserved image bytes")
        asset = long_term_memory.upsert_image_asset(image_path, path=db_path)
        assert asset
        long_term_memory.link_asset_to_target(
            asset["id"],
            target_kind="chunk",
            target_id=stale_chunk_id,
            source_chat_id="current_chat",
            source_message_index=9,
            role="user",
            path=db_path,
        )

        result = long_term_memory.delete_archived_chunks_from_message(
            "current_chat",
            9,
            path=db_path,
        )

        assert result["chunks_deleted"] == 2
        assert result["embeddings_deleted"] == 2
        assert result["asset_links_deleted"] == 1
        remaining_current = long_term_memory.list_archived_chunks(
            source_chat_id="current_chat",
            limit=100,
            path=db_path,
        )
        assert sorted(int(chunk["source_message_end"]) for chunk in remaining_current) == [4, 8]
        assert len(long_term_memory.list_archived_chunks(source_chat_id="other_chat", path=db_path)) == 1

        connection = sqlite3.connect(db_path)
        try:
            embedding_targets = {
                str(row[0])
                for row in connection.execute("SELECT target_id FROM long_term_memory_embeddings").fetchall()
            }
            link_targets = {
                str(row[0])
                for row in connection.execute("SELECT target_id FROM long_term_memory_asset_links").fetchall()
            }
            asset_count = int(connection.execute("SELECT COUNT(*) FROM long_term_memory_assets").fetchone()[0])
        finally:
            connection.close()
        assert embedding_targets == {preserved_chunk_id}
        assert stale_chunk_id not in link_targets
        assert asset_count == 1, "Removing an obsolete chunk must not destroy the underlying archived image asset"
        long_term_memory.release_store(db_path)


if __name__ == "__main__":
    test_prune_archived_chunks_from_first_edited_message()
    print("smoke_long_term_memory_chat_edit_reconciliation: ok")
