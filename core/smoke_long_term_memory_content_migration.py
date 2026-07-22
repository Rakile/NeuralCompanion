from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))

from core import long_term_memory


LEGACY_TEXT = """1. User: [2026-07-13 02:15:43] Keep this user timestamp
2. Assistant: [2026-07-13 02:16:01] [2026-07-13 02:16:22] [neutral] Clean these prefixes
3. Assistant: The event happened at [2026-07-13 02:16:01]."""


def _insert_legacy_fixture(db_path: Path) -> None:
    long_term_memory.init_store(db_path)
    with sqlite3.connect(str(db_path)) as connection:
        connection.execute("DELETE FROM memory_meta WHERE key = 'content_format_version'")
        connection.execute(
            """
            INSERT INTO long_term_memory(
                id, type, title, summary, content, tags_json, source_chat_id,
                created_at, updated_at, status
            ) VALUES ('mem_keep', 'note', 'Keep', 'Keep', 'Keep', '[]', 'legacy', 'now', 'now', 'active')
            """
        )
        for chunk_id, text in (("chunk_legacy", LEGACY_TEXT), ("chunk_clean", "1. Assistant: Already clean")):
            connection.execute(
                """
                INSERT INTO long_term_memory_chunks(
                    id, source_chat_id, source_message_start, source_message_end,
                    text, tags_json, created_at, updated_at, status
                ) VALUES (?, 'legacy', 1, 3, ?, '[]', 'now', 'now', 'active')
                """,
                (chunk_id, text),
            )
        for embedding_id, kind, target_id in (
            ("emb_chunk", "chunk", "chunk_legacy"),
            ("emb_slice", "chunk_slice", "chunk_legacy_s0001"),
            ("emb_clean", "chunk", "chunk_clean"),
            ("emb_record", "record", "mem_keep"),
        ):
            connection.execute(
                """
                INSERT INTO long_term_memory_embeddings(
                    id, target_kind, target_id, model, text_hash, dimension,
                    vector_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'embed-model', 'old-hash', 1, '[1.0]', 'now', 'now')
                """,
                (embedding_id, kind, target_id),
            )
        connection.execute(
            """
            INSERT INTO long_term_memory_assets(
                id, kind, origin, source, mime_type, sha256, blob,
                metadata_json, created_at, updated_at
            ) VALUES ('asset_keep', 'image', 'user_attachment', 'clipboard',
                      'image/png', 'sha_keep', X'89504E47', '{}', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO long_term_memory_asset_links(
                id, asset_id, target_kind, target_id, source_chat_id,
                source_message_index, role, relation, metadata_json, created_at
            ) VALUES ('link_keep', 'asset_keep', 'chunk', 'chunk_legacy', 'legacy',
                      2, 'assistant', 'generated_by_reply', '{}', 'now')
            """
        )
        connection.commit()


def test_new_store_records_current_content_format_version() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "new.sqlite3"
        long_term_memory.init_store(db_path)
        with sqlite3.connect(str(db_path)) as connection:
            version = connection.execute(
                "SELECT value FROM memory_meta WHERE key = 'content_format_version'"
            ).fetchone()
        assert version == ("1",)
        assert long_term_memory.pending_content_migration_report(db_path) is None


def test_legacy_store_cleans_assistant_prefixes_once_and_preserves_memory() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "legacy.sqlite3"
        _insert_legacy_fixture(db_path)

        long_term_memory.init_store(db_path)

        with sqlite3.connect(str(db_path)) as connection:
            version = connection.execute(
                "SELECT value FROM memory_meta WHERE key = 'content_format_version'"
            ).fetchone()
            legacy_text = connection.execute(
                "SELECT text FROM long_term_memory_chunks WHERE id = 'chunk_legacy'"
            ).fetchone()[0]
            remaining_embeddings = {
                row[0]
                for row in connection.execute("SELECT id FROM long_term_memory_embeddings")
            }
            counts = {
                "records": connection.execute("SELECT COUNT(*) FROM long_term_memory").fetchone()[0],
                "assets": connection.execute("SELECT COUNT(*) FROM long_term_memory_assets").fetchone()[0],
                "links": connection.execute("SELECT COUNT(*) FROM long_term_memory_asset_links").fetchone()[0],
            }

        assert version == ("1",)
        assert "1. User: [2026-07-13 02:15:43]" in legacy_text
        assert "2. Assistant: [neutral] Clean these prefixes" in legacy_text
        assert "3. Assistant: The event happened at [2026-07-13 02:16:01]." in legacy_text
        assert remaining_embeddings == {"emb_clean", "emb_record"}
        assert counts == {"records": 1, "assets": 1, "links": 1}

        report = long_term_memory.pending_content_migration_report(db_path)
        assert report == {
            "source_version": 0,
            "target_version": 1,
            "cleaned_chunks": 1,
            "invalidated_embeddings": 2,
        }

        long_term_memory.init_store(db_path)
        assert long_term_memory.pending_content_migration_report(db_path) == report
        with sqlite3.connect(str(db_path)) as connection:
            second_text = connection.execute(
                "SELECT text FROM long_term_memory_chunks WHERE id = 'chunk_legacy'"
            ).fetchone()[0]
            second_embeddings = connection.execute(
                "SELECT COUNT(*) FROM long_term_memory_embeddings"
            ).fetchone()[0]
        assert second_text == legacy_text
        assert second_embeddings == 2

        long_term_memory.acknowledge_content_migration_report(db_path)
        assert long_term_memory.pending_content_migration_report(db_path) is None
        long_term_memory.init_store(db_path)
        assert long_term_memory.pending_content_migration_report(db_path) is None


def test_current_store_bypasses_content_cleanup() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "current.sqlite3"
        long_term_memory.init_store(db_path)
        with sqlite3.connect(str(db_path)) as connection:
            connection.execute(
                """
                INSERT INTO long_term_memory_chunks(
                    id, source_chat_id, source_message_start, source_message_end,
                    text, tags_json, created_at, updated_at, status
                ) VALUES ('chunk_current', 'current', 1, 1, ?, '[]', 'now', 'now', 'active')
                """,
                ("1. Assistant: [2026-07-13 02:16:01] Keep because the store is current",),
            )
            connection.commit()

        long_term_memory.init_store(db_path)

        with sqlite3.connect(str(db_path)) as connection:
            text = connection.execute(
                "SELECT text FROM long_term_memory_chunks WHERE id = 'chunk_current'"
            ).fetchone()[0]
        assert text == "1. Assistant: [2026-07-13 02:16:01] Keep because the store is current"


def test_failed_migration_rolls_back_content_and_version_marker() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "rollback.sqlite3"
        _insert_legacy_fixture(db_path)
        original_migrator = long_term_memory._migrate_archive_content_to_v1

        def fail_after_changes(connection):
            original_migrator(connection)
            raise RuntimeError("forced migration failure")

        long_term_memory._migrate_archive_content_to_v1 = fail_after_changes
        try:
            try:
                long_term_memory.init_store(db_path)
            except RuntimeError as exc:
                assert str(exc) == "forced migration failure"
            else:
                raise AssertionError("forced migration failure was not propagated")
        finally:
            long_term_memory._migrate_archive_content_to_v1 = original_migrator

        with sqlite3.connect(str(db_path)) as connection:
            version = connection.execute(
                "SELECT value FROM memory_meta WHERE key = 'content_format_version'"
            ).fetchone()
            text = connection.execute(
                "SELECT text FROM long_term_memory_chunks WHERE id = 'chunk_legacy'"
            ).fetchone()[0]
            embedding_count = connection.execute(
                "SELECT COUNT(*) FROM long_term_memory_embeddings"
            ).fetchone()[0]
        assert version is None
        assert text == LEGACY_TEXT
        assert embedding_count == 4
        assert long_term_memory.pending_content_migration_report(db_path) is None


def test_migration_invalidates_slice_embedding_with_truncated_suffix() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "truncated_slice.sqlite3"
        long_term_memory.init_store(db_path)
        chunk_id = "chunk_" + ("x" * 90)
        assert len(chunk_id) == 96
        slice_target_id = long_term_memory.normalize_memory_id(f"{chunk_id}_s0001")
        assert slice_target_id == chunk_id

        with sqlite3.connect(str(db_path)) as connection:
            connection.execute("DELETE FROM memory_meta WHERE key = 'content_format_version'")
            connection.execute(
                """
                INSERT INTO long_term_memory_chunks(
                    id, source_chat_id, source_message_start, source_message_end,
                    text, tags_json, created_at, updated_at, status
                ) VALUES (?, 'legacy', 1, 1, ?, '[]', 'now', 'now', 'active')
                """,
                (chunk_id, "1. Assistant: [2026-07-13 02:16:01] Clean me"),
            )
            connection.execute(
                """
                INSERT INTO long_term_memory_embeddings(
                    id, target_kind, target_id, model, text_hash, dimension,
                    vector_json, created_at, updated_at
                ) VALUES ('emb_truncated_slice', 'chunk_slice', ?, 'embed-model',
                          'old-hash', 1, '[1.0]', 'now', 'now')
                """,
                (slice_target_id,),
            )
            connection.commit()

        long_term_memory.init_store(db_path)

        with sqlite3.connect(str(db_path)) as connection:
            embedding = connection.execute(
                "SELECT id FROM long_term_memory_embeddings WHERE id = 'emb_truncated_slice'"
            ).fetchone()
        assert embedding is None


def test_migration_preserves_slice_with_different_parsed_parent() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "slice_prefix_collision.sqlite3"
        long_term_memory.init_store(db_path)
        with sqlite3.connect(str(db_path)) as connection:
            connection.execute("DELETE FROM memory_meta WHERE key = 'content_format_version'")
            connection.execute(
                """
                INSERT INTO long_term_memory_chunks(
                    id, source_chat_id, source_message_start, source_message_end,
                    text, tags_json, created_at, updated_at, status
                ) VALUES ('chunk_a', 'legacy', 1, 1, ?, '[]', 'now', 'now', 'active')
                """,
                ("1. Assistant: [2026-07-13 02:16:01] Clean me",),
            )
            connection.execute(
                """
                INSERT INTO long_term_memory_embeddings(
                    id, target_kind, target_id, model, text_hash, dimension,
                    vector_json, created_at, updated_at
                ) VALUES ('emb_other_parent', 'chunk_slice', 'chunk_a_sibling_s0001',
                          'embed-model', 'other-hash', 1, '[1.0]', 'now', 'now')
                """
            )
            connection.commit()

        long_term_memory.init_store(db_path)

        with sqlite3.connect(str(db_path)) as connection:
            embedding = connection.execute(
                "SELECT id FROM long_term_memory_embeddings WHERE id = 'emb_other_parent'"
            ).fetchone()
        assert embedding == ("emb_other_parent",)


if __name__ == "__main__":
    test_new_store_records_current_content_format_version()
    test_legacy_store_cleans_assistant_prefixes_once_and_preserves_memory()
    test_current_store_bypasses_content_cleanup()
    test_failed_migration_rolls_back_content_and_version_marker()
    test_migration_invalidates_slice_embedding_with_truncated_suffix()
    test_migration_preserves_slice_with_different_parsed_parent()
    print("smoke_long_term_memory_content_migration: ok")
