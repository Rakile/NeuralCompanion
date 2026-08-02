"""Non-destructive Long-Term Memory archive rebuild candidates."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core import chat_context_assets, long_term_memory, runtime_paths


DEFAULT_OUTPUT_DIR = runtime_paths.RUNTIME_DIR / "long_term_memory" / "rebuild_candidates"


@contextmanager
def _sqlite_connection(database: str | Path, **kwargs):
    connection = sqlite3.connect(str(database), **kwargs)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _file_signature(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return int(stat.st_size), int(stat.st_mtime_ns)


def _copy_sqlite_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with _sqlite_connection(source_uri, uri=True) as source_connection:
        with _sqlite_connection(destination) as destination_connection:
            source_connection.backup(destination_connection)


def _resolve_history_image_paths(history: list[dict[str, Any]], context_path: Path) -> None:
    fields = (
        "generated_image_path",
        "visual_reply_image_path",
        "assistant_visual_reply_image_path",
    )
    list_fields = (
        "generated_image_paths",
        "visual_reply_image_paths",
        "assistant_visual_reply_image_paths",
    )
    for turn in history:
        if not isinstance(turn, dict):
            continue
        for field in fields:
            raw_path = str(turn.get(field, "") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                candidate = (context_path.parent / path).resolve()
                if candidate.exists():
                    turn[field] = str(candidate)
        for field in list_fields:
            raw_paths = turn.get(field)
            if not isinstance(raw_paths, list):
                continue
            resolved_paths = []
            for raw_path in raw_paths:
                path = Path(str(raw_path or "")).expanduser()
                if not path.is_absolute():
                    candidate = (context_path.parent / path).resolve()
                    if candidate.exists():
                        path = candidate
                resolved_paths.append(str(path))
            turn[field] = resolved_paths


def _candidate_path(output_dir: Path, memory_id: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    nonce = uuid.uuid4().hex[:8]
    return output_dir / f"{memory_id}_{stamp}_{nonce}.sqlite3"


def _snapshot_legacy_chunk_links(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT asset_id, source_chat_id, source_message_index, role,
               relation, metadata_json
        FROM long_term_memory_asset_links
        WHERE target_kind = 'chunk'
        ORDER BY source_message_index, created_at, id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _context_asset_reference_state(turns: list[dict[str, Any]]) -> tuple[set[int], set[int], int, int]:
    declared_indexes: set[int] = set()
    missing_indexes: set[int] = set()
    reference_count = 0
    missing_reference_count = 0
    for turn in turns:
        index = int(turn["index"])
        for asset in list(turn.get("assets") or []):
            if not isinstance(asset, dict):
                continue
            reference_count += 1
            declared_indexes.add(index)
            asset_path = Path(str(asset.get("path", "") or "")).expanduser()
            if not asset_path.is_file():
                missing_indexes.add(index)
                missing_reference_count += 1
    return declared_indexes, missing_indexes, reference_count, missing_reference_count


def rebuild_archive_candidate(
    context_path: Any,
    *,
    source_db_path: Any = None,
    output_dir: Any = None,
    chunk_size: Any = long_term_memory.DEFAULT_EXTRACTION_TURNS,
) -> dict[str, Any]:
    """Build an inactive archive candidate from a complete saved chat context.

    The source context and source SQLite database are read-only inputs. The
    returned candidate path is never selected as the active NC memory store.
    """

    context = Path(str(context_path or "")).expanduser().resolve()
    if not context.is_file():
        raise FileNotFoundError(f"Chat context not found: {context}")
    try:
        size = max(1, min(10000, int(chunk_size)))
    except Exception as exc:
        raise ValueError("Archive chunk size must be an integer from 1 to 10000.") from exc

    payload = json.loads(context.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Chat context root must be a JSON object.")
    history = payload.get("conversation_history")
    if not isinstance(history, list) or not history:
        raise ValueError("Chat context does not contain a non-empty conversation_history list.")

    resolved_payload = chat_context_assets.resolve_chat_context_image_assets(payload, context)
    resolved_history = list(resolved_payload.get("conversation_history") or [])
    _resolve_history_image_paths(resolved_history, context)
    turns = long_term_memory.sanitize_history_turns(resolved_history)
    if not turns:
        raise ValueError("Chat context does not contain archiveable user, assistant, or system messages.")
    (
        declared_asset_indexes,
        missing_asset_indexes,
        context_asset_references,
        missing_context_asset_references,
    ) = _context_asset_reference_state(turns)

    memory_id = long_term_memory.normalize_memory_id(
        payload.get("continuity_memory_id") or context.stem,
        fallback="rebuild_candidate",
    )
    source_chat_id = long_term_memory.normalize_memory_id(context.stem, fallback=memory_id)
    source_db = Path(source_db_path).expanduser().resolve() if source_db_path else long_term_memory.db_path_for_memory_id(memory_id).resolve()
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else DEFAULT_OUTPUT_DIR.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    candidate_db = _candidate_path(target_dir, memory_id)

    source_signature_before = _file_signature(source_db)
    if source_db.is_file():
        _copy_sqlite_snapshot(source_db, candidate_db)
    else:
        long_term_memory.init_store(candidate_db)
    long_term_memory.init_store(candidate_db)

    with _sqlite_connection(candidate_db) as connection:
        connection.row_factory = sqlite3.Row
        old_chunks = _table_count(connection, "long_term_memory_chunks")
        records_preserved = _table_count(connection, "long_term_memory")
        assets_preserved = _table_count(connection, "long_term_memory_assets")
        legacy_links = _snapshot_legacy_chunk_links(connection)
        old_chunk_embeddings = int(
            connection.execute(
                "SELECT COUNT(*) FROM long_term_memory_embeddings WHERE target_kind IN ('chunk', 'chunk_slice')"
            ).fetchone()[0]
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM long_term_memory_asset_links WHERE target_kind = 'chunk'")
        connection.execute("DELETE FROM long_term_memory_embeddings WHERE target_kind IN ('chunk', 'chunk_slice')")
        connection.execute("DELETE FROM long_term_memory_chunks")
        connection.commit()

    created_chunks: list[dict[str, Any]] = []
    chunk_by_message_index: dict[int, dict[str, Any]] = {}
    for offset in range(0, len(turns), size):
        batch = turns[offset : offset + size]
        chunk = long_term_memory.archive_history_chunk(
            batch,
            source_chat_id=source_chat_id,
            tags=["raw_chat", "rebuild_candidate"],
            path=candidate_db,
        )
        if not chunk:
            raise RuntimeError(f"Could not create archive candidate chunk at message offset {offset}.")
        created_chunks.append(chunk)
        for turn in batch:
            chunk_by_message_index[int(turn["index"])] = chunk

    unresolved_links = 0
    legacy_links_recovered = 0
    legacy_links_skipped = 0
    with _sqlite_connection(candidate_db) as connection:
        existing_link_keys = {
            (str(row[0]), int(row[1]), str(row[2]))
            for row in connection.execute(
                """
                SELECT asset_id, source_message_index, relation
                FROM long_term_memory_asset_links
                WHERE target_kind = 'chunk' AND source_message_index IS NOT NULL
                """
            ).fetchall()
        }
    for legacy_link in legacy_links:
        source_index = legacy_link.get("source_message_index")
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            unresolved_links += 1
            continue
        legacy_key = (
            str(legacy_link.get("asset_id") or ""),
            source_index,
            str(legacy_link.get("relation") or "attached_to_turn"),
        )
        if legacy_key in existing_link_keys:
            legacy_links_skipped += 1
            continue
        if source_index in declared_asset_indexes and source_index not in missing_asset_indexes:
            legacy_links_skipped += 1
            continue
        chunk = chunk_by_message_index.get(source_index)
        if not chunk:
            unresolved_links += 1
            continue
        try:
            metadata = json.loads(str(legacy_link.get("metadata_json") or "{}"))
        except Exception:
            metadata = {}
        link = long_term_memory.link_asset_to_target(
            legacy_link.get("asset_id"),
            target_kind="chunk",
            target_id=chunk["id"],
            source_chat_id=source_chat_id,
            source_message_index=source_index,
            role=legacy_link.get("role", ""),
            relation=legacy_link.get("relation", "attached_to_turn"),
            metadata=metadata if isinstance(metadata, dict) else {},
            path=candidate_db,
        )
        if link:
            existing_link_keys.add(legacy_key)
            legacy_links_recovered += 1
        else:
            unresolved_links += 1

    with _sqlite_connection(candidate_db) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0] or "")
        candidate_links = int(
            connection.execute(
                "SELECT COUNT(*) FROM long_term_memory_asset_links WHERE target_kind = 'chunk'"
            ).fetchone()[0]
        )
        candidate_records = _table_count(connection, "long_term_memory")
        candidate_assets = _table_count(connection, "long_term_memory_assets")
        candidate_chunk_embeddings = int(
            connection.execute(
                "SELECT COUNT(*) FROM long_term_memory_embeddings WHERE target_kind IN ('chunk', 'chunk_slice')"
            ).fetchone()[0]
        )
    if integrity.lower() != "ok":
        raise RuntimeError(f"Candidate SQLite integrity check failed: {integrity}")

    source_signature_after = _file_signature(source_db)
    report = {
        "status": "candidate_ready",
        "activated": False,
        "context_path": str(context),
        "source_db": str(source_db),
        "candidate_db": str(candidate_db),
        "memory_id": memory_id,
        "source_chat_id": source_chat_id,
        "chunk_size": size,
        "context_messages": len(history),
        "messages_archived": len(turns),
        "old_chunks": old_chunks,
        "chunks_created": len(created_chunks),
        "records_preserved": candidate_records,
        "assets_preserved": candidate_assets,
        "context_asset_references": context_asset_references,
        "missing_context_asset_references": missing_context_asset_references,
        "legacy_asset_links": len(legacy_links),
        "legacy_asset_links_recovered": legacy_links_recovered,
        "legacy_asset_links_skipped": legacy_links_skipped,
        "asset_links_relinked": candidate_links,
        "unresolved_asset_links": unresolved_links,
        "old_chunk_embeddings_removed": old_chunk_embeddings,
        "candidate_chunk_embeddings": candidate_chunk_embeddings,
        "source_unchanged": source_signature_before == source_signature_after,
        "sqlite_integrity": integrity,
        "note": "This candidate is inactive. Neural Companion continues using the original Long-Term Memory database.",
    }
    if records_preserved != candidate_records or candidate_assets < assets_preserved:
        raise RuntimeError("Candidate validation failed while preserving durable records or image assets.")
    report_path = candidate_db.with_suffix(".report.json")
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


__all__ = ["DEFAULT_OUTPUT_DIR", "rebuild_archive_candidate"]
