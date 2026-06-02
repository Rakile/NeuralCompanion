"""SQLite-backed Long-Term Memory record store.

This module is intentionally isolated from chat runtime, UI, embeddings, and
retrieval providers. SQLite is the canonical store; search/index backends can be
added later without changing the memory record contract.
"""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from core import runtime_paths


SCHEMA_VERSION = 1
MEMORY_DIR = runtime_paths.RUNTIME_DIR / "long_term_memory"
DEFAULT_DB_PATH = MEMORY_DIR / "memory.sqlite3"
DEFAULT_LIMIT = 100
DEFAULT_EXTRACTION_TURNS = 120
DEFAULT_EXTRACTION_MAX_RECORDS = 12
VALID_STATUSES = {"active", "archived", "superseded", "deleted"}
VALID_MEMORY_TYPES = {
    "preference",
    "decision",
    "project_state",
    "fact",
    "relationship",
    "unresolved_thread",
    "correction",
    "note",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_memory_id() -> str:
    return f"mem_{uuid.uuid4().hex[:16]}"


def normalize_memory_id(value: Any, *, fallback: str = "") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return fallback
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("._-")
    return normalized[:96] or fallback


def normalize_status(value: Any, *, fallback: str = "active") -> str:
    status = str(value or "").strip().lower()
    if status in VALID_STATUSES:
        return status
    return fallback


def normalize_memory_type(value: Any, *, fallback: str = "note") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return fallback
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("._-")
    return normalized[:64] or fallback


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = re.split(r"[,;\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = [value]
    tags: list[str] = []
    for item in candidates:
        tag = re.sub(r"\s+", " ", str(item or "").strip().lower())
        if tag and tag not in tags:
            tags.append(tag[:80])
    return tags


def _tags_json(value: Any) -> str:
    return json.dumps(normalize_tags(value), ensure_ascii=True)


def _loads_tags(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        parsed = []
    return normalize_tags(parsed)


def _json_text(value: Any) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "[]"
        try:
            json.loads(text)
            return text
        except Exception:
            return json.dumps([text], ensure_ascii=True)
    try:
        return json.dumps(value, ensure_ascii=True)
    except Exception:
        return json.dumps([str(value)], ensure_ascii=True)


def _db_path(path: Any = None) -> Path:
    return Path(path) if path else DEFAULT_DB_PATH


def _connect(path: Any = None) -> sqlite3.Connection:
    target = _db_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target))
    connection.row_factory = sqlite3.Row
    return connection


def init_store(path: Any = None) -> Path:
    """Create or upgrade the local Long-Term Memory store."""
    target = _db_path(path)
    with _connect(target) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                source_chat_id TEXT NOT NULL DEFAULT '',
                source_message_start INTEGER,
                source_message_end INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                confidence REAL NOT NULL DEFAULT 0.8,
                status TEXT NOT NULL DEFAULT 'active',
                supersedes_json TEXT NOT NULL DEFAULT '[]',
                superseded_by TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS long_term_memory_chunks (
                id TEXT PRIMARY KEY,
                source_chat_id TEXT NOT NULL DEFAULT '',
                source_message_start INTEGER,
                source_message_end INTEGER,
                text TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ltm_status ON long_term_memory(status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ltm_type ON long_term_memory(type)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ltm_source_chat ON long_term_memory(source_chat_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ltm_updated_at ON long_term_memory(updated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ltm_chunks_status ON long_term_memory_chunks(status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ltm_chunks_source_chat ON long_term_memory_chunks(source_chat_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ltm_chunks_updated_at ON long_term_memory_chunks(updated_at)")
        connection.execute(
            "INSERT OR REPLACE INTO memory_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        connection.commit()
    return target


def _row_to_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row["id"] or ""),
        "type": str(row["type"] or ""),
        "title": str(row["title"] or ""),
        "summary": str(row["summary"] or ""),
        "content": str(row["content"] or ""),
        "tags": _loads_tags(row["tags_json"]),
        "source_chat_id": str(row["source_chat_id"] or ""),
        "source_message_start": row["source_message_start"],
        "source_message_end": row["source_message_end"],
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "importance": float(row["importance"] or 0.0),
        "confidence": float(row["confidence"] or 0.0),
        "status": str(row["status"] or ""),
        "supersedes": _loads_tags(row["supersedes_json"]),
        "superseded_by": str(row["superseded_by"] or ""),
    }


def _row_to_chunk(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row["id"] or ""),
        "source_chat_id": str(row["source_chat_id"] or ""),
        "source_message_start": row["source_message_start"],
        "source_message_end": row["source_message_end"],
        "text": str(row["text"] or ""),
        "tags": _loads_tags(row["tags_json"]),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "status": str(row["status"] or ""),
    }


def memory_record(
    *,
    memory_id: Any = "",
    memory_type: Any = "note",
    title: Any = "",
    summary: Any = "",
    content: Any = "",
    tags: Any = None,
    source_chat_id: Any = "",
    source_message_start: Any = None,
    source_message_end: Any = None,
    importance: Any = 0.5,
    confidence: Any = 0.8,
    status: Any = "active",
    supersedes: Any = None,
    superseded_by: Any = "",
    created_at: Any = "",
    updated_at: Any = "",
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": normalize_memory_id(memory_id, fallback=new_memory_id()),
        "type": normalize_memory_type(memory_type),
        "title": str(title or "").strip(),
        "summary": str(summary or "").strip(),
        "content": str(content or "").strip(),
        "tags": normalize_tags(tags),
        "source_chat_id": normalize_memory_id(source_chat_id),
        "source_message_start": _optional_int(source_message_start),
        "source_message_end": _optional_int(source_message_end),
        "created_at": str(created_at or now),
        "updated_at": str(updated_at or now),
        "importance": _clamped_float(importance, 0.0, 1.0, 0.5),
        "confidence": _clamped_float(confidence, 0.0, 1.0, 0.8),
        "status": normalize_status(status),
        "supersedes": [normalize_memory_id(item) for item in normalize_tags(supersedes) if normalize_memory_id(item)],
        "superseded_by": normalize_memory_id(superseded_by),
    }


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _clamped_float(value: Any, low: float, high: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = fallback
    return max(low, min(high, parsed))


def compact_text(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


_SEARCH_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "can",
    "did",
    "does",
    "for",
    "from",
    "have",
    "how",
    "know",
    "our",
    "the",
    "this",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
}


def _search_terms(query: Any, *, limit: int = 8) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9_'-]+", str(query or "").lower()):
        cleaned = token.strip("_'-")
        if len(cleaned) < 3 or cleaned in _SEARCH_STOPWORDS:
            continue
        if cleaned not in terms:
            terms.append(cleaned)
        if len(terms) >= limit:
            break
    return terms


def _append_text_search_clause(clauses: list[str], values: list[Any], fields: list[str], query: Any) -> None:
    text = str(query or "").strip().lower()
    if not text:
        return
    parts: list[str] = []
    phrase_like = f"%{text}%"
    for field in fields:
        parts.append(f"{field} LIKE ?")
        values.append(phrase_like)
    for term in _search_terms(text):
        term_like = f"%{term}%"
        for field in fields:
            parts.append(f"{field} LIKE ?")
            values.append(term_like)
    if parts:
        clauses.append("(" + " OR ".join(parts) + ")")


def sanitize_history_turns(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for index, turn in enumerate(list(history or []), start=1):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "") or "").strip().lower()
        if role not in {"user", "assistant", "system"}:
            continue
        content = compact_text(turn.get("content", ""))
        if not content:
            continue
        label = "User" if role == "user" else ("Assistant" if role == "assistant" else "System")
        sanitized.append({"index": index, "role": role, "label": label, "content": content})
    return sanitized


def select_history_turns(
    history: list[dict[str, Any]],
    *,
    start_index: Any = None,
    end_index: Any = None,
    turn_count: Any = DEFAULT_EXTRACTION_TURNS,
) -> list[dict[str, Any]]:
    turns = sanitize_history_turns(history)
    if not turns:
        return []
    start = _optional_int(start_index)
    end = _optional_int(end_index)
    if start is not None or end is not None:
        start = max(1, start or 1)
        end = max(start, end or turns[-1]["index"])
        return [turn for turn in turns if start <= int(turn["index"]) <= end]
    try:
        limit = max(1, int(turn_count))
    except Exception:
        limit = DEFAULT_EXTRACTION_TURNS
    return turns[-limit:]


def format_history_segment(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in list(turns or []):
        lines.append(f"{int(turn['index'])}. {turn['label']}: {turn['content']}")
    return "\n".join(lines).strip()


def chunk_id_for_segment(source_chat_id: Any, source_message_start: Any, source_message_end: Any, text: Any) -> str:
    source = normalize_memory_id(source_chat_id, fallback="unsaved_chat")
    start = _optional_int(source_message_start) or 0
    end = _optional_int(source_message_end) or 0
    digest = hashlib.sha1(str(text or "").encode("utf-8", errors="replace")).hexdigest()[:16]
    return normalize_memory_id(f"chunk_{source}_{start}_{end}_{digest}", fallback=f"chunk_{digest}")


def archive_history_chunk(
    turns: list[dict[str, Any]],
    *,
    source_chat_id: Any = "",
    tags: Any = None,
    status: Any = "active",
    path: Any = None,
) -> dict[str, Any] | None:
    selected = list(turns or [])
    if not selected:
        return None
    text = format_history_segment(selected)
    if not text:
        return None
    start = int(selected[0]["index"])
    end = int(selected[-1]["index"])
    source = normalize_memory_id(source_chat_id, fallback="unsaved_chat")
    now = _now_iso()
    chunk_id = chunk_id_for_segment(source, start, end, text)
    init_store(path)
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO long_term_memory_chunks(
                id, source_chat_id, source_message_start, source_message_end,
                text, tags_json, created_at, updated_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_chat_id=excluded.source_chat_id,
                source_message_start=excluded.source_message_start,
                source_message_end=excluded.source_message_end,
                text=excluded.text,
                tags_json=excluded.tags_json,
                updated_at=excluded.updated_at,
                status=excluded.status
            """,
            (
                chunk_id,
                source,
                start,
                end,
                text,
                _tags_json(tags),
                now,
                now,
                normalize_status(status),
            ),
        )
        connection.commit()
    return get_archived_chunk(chunk_id, path=path)


def build_extraction_messages(
    turns: list[dict[str, Any]],
    *,
    source_chat_id: Any = "",
    max_records: Any = DEFAULT_EXTRACTION_MAX_RECORDS,
) -> list[dict[str, str]]:
    try:
        limit = max(1, min(50, int(max_records)))
    except Exception:
        limit = DEFAULT_EXTRACTION_MAX_RECORDS
    segment = format_history_segment(turns)
    return [
        {
            "role": "system",
            "content": (
                "You extract durable Long-Term Memory records for a local AI companion. "
                "Extract only information that could be useful in a later session. "
                "Prefer user preferences, decisions, project state, important facts, relationships, "
                "corrections, and unresolved follow-ups. Skip greetings, filler, temporary wording, "
                "and generic assistant chatter. Do not invent facts. "
                "Return only valid JSON with this shape: "
                '{"memories":[{"type":"preference|decision|project_state|fact|relationship|'
                'unresolved_thread|correction|note","title":"short title","summary":"one sentence",'
                '"content":"supporting detail","tags":["lowercase tag"],"importance":0.0,'
                '"confidence":0.0,"source_message_start":1,"source_message_end":2}]}. '
                f"Return at most {limit} memory records. Use an empty memories array if nothing durable is present."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source chat id: {normalize_memory_id(source_chat_id) or 'unsaved_chat'}\n\n"
                "Chat segment:\n"
                "<<<BEGIN CHAT SEGMENT>>>\n"
                f"{segment or '(empty)'}\n"
                "<<<END CHAT SEGMENT>>>\n\n"
                "Extract Long-Term Memory records now."
            ),
        },
    ]


def normalize_extracted_memories(payload: Any, *, max_records: Any = DEFAULT_EXTRACTION_MAX_RECORDS) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("memories", [])
    if not isinstance(raw_items, list):
        return []
    try:
        limit = max(1, min(50, int(max_records)))
    except Exception:
        limit = DEFAULT_EXTRACTION_MAX_RECORDS
    records: list[dict[str, Any]] = []
    for item in raw_items[:limit]:
        if not isinstance(item, dict):
            continue
        memory_type = normalize_memory_type(item.get("type") or item.get("memory_type"))
        if memory_type not in VALID_MEMORY_TYPES:
            memory_type = "note"
        summary = str(item.get("summary", "") or "").strip()
        content = str(item.get("content", "") or "").strip()
        title = str(item.get("title", "") or "").strip()
        if not summary and not content:
            continue
        records.append({
            "type": memory_type,
            "title": title or summary[:80] or memory_type,
            "summary": summary or compact_text(content, 320),
            "content": content or summary,
            "tags": normalize_tags(item.get("tags")),
            "importance": _clamped_float(item.get("importance", 0.5), 0.0, 1.0, 0.5),
            "confidence": _clamped_float(item.get("confidence", 0.8), 0.0, 1.0, 0.8),
            "source_message_start": _optional_int(item.get("source_message_start")),
            "source_message_end": _optional_int(item.get("source_message_end")),
        })
    return records


def upsert_memory(record: dict[str, Any], path: Any = None) -> dict[str, Any]:
    """Insert or replace one memory record and return the stored record."""
    init_store(path)
    normalized = memory_record(
        memory_id=record.get("id") or record.get("memory_id"),
        memory_type=record.get("type") or record.get("memory_type"),
        title=record.get("title"),
        summary=record.get("summary"),
        content=record.get("content"),
        tags=record.get("tags") or record.get("tags_json"),
        source_chat_id=record.get("source_chat_id"),
        source_message_start=record.get("source_message_start"),
        source_message_end=record.get("source_message_end"),
        importance=record.get("importance", 0.5),
        confidence=record.get("confidence", 0.8),
        status=record.get("status", "active"),
        supersedes=record.get("supersedes") or record.get("supersedes_json"),
        superseded_by=record.get("superseded_by"),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at") or _now_iso(),
    )
    if not normalized["summary"] and normalized["content"]:
        normalized["summary"] = normalized["content"][:320].strip()
    if not normalized["title"]:
        normalized["title"] = normalized["summary"][:80].strip() or normalized["type"]
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO long_term_memory(
                id, type, title, summary, content, tags_json, source_chat_id,
                source_message_start, source_message_end, created_at, updated_at,
                importance, confidence, status, supersedes_json, superseded_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                title=excluded.title,
                summary=excluded.summary,
                content=excluded.content,
                tags_json=excluded.tags_json,
                source_chat_id=excluded.source_chat_id,
                source_message_start=excluded.source_message_start,
                source_message_end=excluded.source_message_end,
                updated_at=excluded.updated_at,
                importance=excluded.importance,
                confidence=excluded.confidence,
                status=excluded.status,
                supersedes_json=excluded.supersedes_json,
                superseded_by=excluded.superseded_by
            """,
            (
                normalized["id"],
                normalized["type"],
                normalized["title"],
                normalized["summary"],
                normalized["content"],
                _tags_json(normalized["tags"]),
                normalized["source_chat_id"],
                normalized["source_message_start"],
                normalized["source_message_end"],
                normalized["created_at"],
                normalized["updated_at"],
                normalized["importance"],
                normalized["confidence"],
                normalized["status"],
                _json_text(normalized["supersedes"]),
                normalized["superseded_by"],
            ),
        )
        connection.commit()
    stored = get_memory(normalized["id"], path=path)
    return stored or normalized


def create_memory(
    *,
    memory_type: Any = "note",
    title: Any = "",
    summary: Any = "",
    content: Any = "",
    tags: Any = None,
    source_chat_id: Any = "",
    source_message_start: Any = None,
    source_message_end: Any = None,
    importance: Any = 0.5,
    confidence: Any = 0.8,
    path: Any = None,
) -> dict[str, Any]:
    return upsert_memory(
        memory_record(
            memory_type=memory_type,
            title=title,
            summary=summary,
            content=content,
            tags=tags,
            source_chat_id=source_chat_id,
            source_message_start=source_message_start,
            source_message_end=source_message_end,
            importance=importance,
            confidence=confidence,
        ),
        path=path,
    )


def get_memory(memory_id: Any, path: Any = None) -> dict[str, Any] | None:
    init_store(path)
    normalized_id = normalize_memory_id(memory_id)
    if not normalized_id:
        return None
    with _connect(path) as connection:
        row = connection.execute("SELECT * FROM long_term_memory WHERE id = ?", (normalized_id,)).fetchone()
    return _row_to_record(row)


def update_memory(memory_id: Any, path: Any = None, **fields: Any) -> dict[str, Any] | None:
    existing = get_memory(memory_id, path=path)
    if existing is None:
        return None
    updated = dict(existing)
    updated.update(fields)
    updated["id"] = existing["id"]
    updated["created_at"] = existing["created_at"]
    updated["updated_at"] = _now_iso()
    return upsert_memory(updated, path=path)


def set_memory_status(memory_id: Any, status: Any, path: Any = None) -> dict[str, Any] | None:
    return update_memory(memory_id, path=path, status=normalize_status(status))


def delete_memory(memory_id: Any, *, hard: bool = False, path: Any = None) -> bool:
    init_store(path)
    normalized_id = normalize_memory_id(memory_id)
    if not normalized_id:
        return False
    if hard:
        with _connect(path) as connection:
            cursor = connection.execute("DELETE FROM long_term_memory WHERE id = ?", (normalized_id,))
            connection.commit()
            return cursor.rowcount > 0
    return set_memory_status(normalized_id, "deleted", path=path) is not None


def list_memories(
    *,
    status: Any = "active",
    memory_type: Any = "",
    source_chat_id: Any = "",
    include_deleted: bool = False,
    limit: Any = DEFAULT_LIMIT,
    offset: Any = 0,
    path: Any = None,
) -> list[dict[str, Any]]:
    init_store(path)
    clauses, values = _filter_clauses(
        status=status,
        memory_type=memory_type,
        source_chat_id=source_chat_id,
        include_deleted=include_deleted,
    )
    sql = "SELECT * FROM long_term_memory"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY importance DESC, updated_at DESC LIMIT ? OFFSET ?"
    values.extend([_limit(limit), _offset(offset)])
    with _connect(path) as connection:
        rows = connection.execute(sql, values).fetchall()
    return [record for record in (_row_to_record(row) for row in rows) if record]


def search_memories(
    query: Any,
    *,
    status: Any = "active",
    memory_type: Any = "",
    source_chat_id: Any = "",
    include_deleted: bool = False,
    limit: Any = DEFAULT_LIMIT,
    offset: Any = 0,
    path: Any = None,
) -> list[dict[str, Any]]:
    """Simple dependency-free text search over canonical records."""
    init_store(path)
    text = str(query or "").strip()
    clauses, values = _filter_clauses(
        status=status,
        memory_type=memory_type,
        source_chat_id=source_chat_id,
        include_deleted=include_deleted,
    )
    if text:
        _append_text_search_clause(
            clauses,
            values,
            ["lower(title)", "lower(summary)", "lower(content)", "lower(tags_json)"],
            text,
        )
    sql = "SELECT * FROM long_term_memory"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY importance DESC, updated_at DESC LIMIT ? OFFSET ?"
    values.extend([_limit(limit), _offset(offset)])
    with _connect(path) as connection:
        rows = connection.execute(sql, values).fetchall()
    return [record for record in (_row_to_record(row) for row in rows) if record]


def get_archived_chunk(chunk_id: Any, path: Any = None) -> dict[str, Any] | None:
    init_store(path)
    normalized_id = normalize_memory_id(chunk_id)
    if not normalized_id:
        return None
    with _connect(path) as connection:
        row = connection.execute("SELECT * FROM long_term_memory_chunks WHERE id = ?", (normalized_id,)).fetchone()
    return _row_to_chunk(row)


def list_archived_chunks(
    *,
    status: Any = "active",
    source_chat_id: Any = "",
    include_deleted: bool = False,
    limit: Any = DEFAULT_LIMIT,
    offset: Any = 0,
    path: Any = None,
) -> list[dict[str, Any]]:
    init_store(path)
    clauses, values = _chunk_filter_clauses(
        status=status,
        source_chat_id=source_chat_id,
        include_deleted=include_deleted,
    )
    sql = "SELECT * FROM long_term_memory_chunks"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    values.extend([_limit(limit), _offset(offset)])
    with _connect(path) as connection:
        rows = connection.execute(sql, values).fetchall()
    return [chunk for chunk in (_row_to_chunk(row) for row in rows) if chunk]


def search_archived_chunks(
    query: Any,
    *,
    status: Any = "active",
    source_chat_id: Any = "",
    include_deleted: bool = False,
    limit: Any = DEFAULT_LIMIT,
    offset: Any = 0,
    path: Any = None,
) -> list[dict[str, Any]]:
    init_store(path)
    text = str(query or "").strip()
    clauses, values = _chunk_filter_clauses(
        status=status,
        source_chat_id=source_chat_id,
        include_deleted=include_deleted,
    )
    if text:
        _append_text_search_clause(
            clauses,
            values,
            ["lower(text)", "lower(tags_json)"],
            text,
        )
    sql = "SELECT * FROM long_term_memory_chunks"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    values.extend([_limit(limit), _offset(offset)])
    with _connect(path) as connection:
        rows = connection.execute(sql, values).fetchall()
    return [chunk for chunk in (_row_to_chunk(row) for row in rows) if chunk]


def delete_archived_chunk(chunk_id: Any, *, hard: bool = False, path: Any = None) -> bool:
    init_store(path)
    normalized_id = normalize_memory_id(chunk_id)
    if not normalized_id:
        return False
    if hard:
        with _connect(path) as connection:
            cursor = connection.execute("DELETE FROM long_term_memory_chunks WHERE id = ?", (normalized_id,))
            connection.commit()
            return cursor.rowcount > 0
    now = _now_iso()
    with _connect(path) as connection:
        cursor = connection.execute(
            "UPDATE long_term_memory_chunks SET status = ?, updated_at = ? WHERE id = ?",
            ("deleted", now, normalized_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def retrieve_memories(
    query: Any,
    *,
    record_limit: Any = 6,
    chunk_limit: Any = 4,
    source_chat_id: Any = "",
    path: Any = None,
) -> list[dict[str, Any]]:
    records = search_memories(
        query,
        source_chat_id=source_chat_id,
        limit=record_limit,
        path=path,
    )
    chunks = search_archived_chunks(
        query,
        source_chat_id=source_chat_id,
        limit=chunk_limit,
        path=path,
    )
    results: list[dict[str, Any]] = []
    for record in records:
        results.append({
            "kind": "record",
            "id": record.get("id", ""),
            "title": record.get("title", ""),
            "type": record.get("type", ""),
            "summary": record.get("summary", ""),
            "content": record.get("content", ""),
            "tags": list(record.get("tags") or []),
            "source_chat_id": record.get("source_chat_id", ""),
            "source_message_start": record.get("source_message_start"),
            "source_message_end": record.get("source_message_end"),
            "importance": float(record.get("importance", 0.0) or 0.0),
            "confidence": float(record.get("confidence", 0.0) or 0.0),
            "snippet": compact_text(record.get("summary") or record.get("content"), 520),
        })
    for chunk in chunks:
        results.append({
            "kind": "chunk",
            "id": chunk.get("id", ""),
            "title": "Raw chat chunk",
            "type": "raw_chat",
            "summary": "",
            "content": chunk.get("text", ""),
            "tags": list(chunk.get("tags") or []),
            "source_chat_id": chunk.get("source_chat_id", ""),
            "source_message_start": chunk.get("source_message_start"),
            "source_message_end": chunk.get("source_message_end"),
            "importance": 0.25,
            "confidence": 1.0,
            "snippet": compact_text(chunk.get("text", ""), 720),
        })
    return results


def _filter_clauses(
    *,
    status: Any = "active",
    memory_type: Any = "",
    source_chat_id: Any = "",
    include_deleted: bool = False,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if not include_deleted:
        normalized_status = normalize_status(status)
        clauses.append("status = ?")
        values.append(normalized_status)
    elif status:
        normalized_status = normalize_status(status)
        clauses.append("status = ?")
        values.append(normalized_status)
    normalized_type = normalize_memory_type(memory_type, fallback="")
    if normalized_type:
        clauses.append("type = ?")
        values.append(normalized_type)
    normalized_source = normalize_memory_id(source_chat_id)
    if normalized_source:
        clauses.append("source_chat_id = ?")
        values.append(normalized_source)
    return clauses, values


def _chunk_filter_clauses(
    *,
    status: Any = "active",
    source_chat_id: Any = "",
    include_deleted: bool = False,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if not include_deleted:
        normalized_status = normalize_status(status)
        clauses.append("status = ?")
        values.append(normalized_status)
    elif status:
        normalized_status = normalize_status(status)
        clauses.append("status = ?")
        values.append(normalized_status)
    normalized_source = normalize_memory_id(source_chat_id)
    if normalized_source:
        clauses.append("source_chat_id = ?")
        values.append(normalized_source)
    return clauses, values


def _limit(value: Any) -> int:
    try:
        return max(1, min(1000, int(value)))
    except Exception:
        return DEFAULT_LIMIT


def _offset(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


__all__ = [
    "DEFAULT_EXTRACTION_MAX_RECORDS",
    "DEFAULT_EXTRACTION_TURNS",
    "DEFAULT_DB_PATH",
    "MEMORY_DIR",
    "SCHEMA_VERSION",
    "archive_history_chunk",
    "build_extraction_messages",
    "chunk_id_for_segment",
    "compact_text",
    "create_memory",
    "delete_archived_chunk",
    "delete_memory",
    "format_history_segment",
    "get_archived_chunk",
    "get_memory",
    "init_store",
    "list_archived_chunks",
    "list_memories",
    "memory_record",
    "new_memory_id",
    "normalize_memory_id",
    "normalize_memory_type",
    "normalize_extracted_memories",
    "normalize_status",
    "normalize_tags",
    "retrieve_memories",
    "sanitize_history_turns",
    "search_archived_chunks",
    "search_memories",
    "select_history_turns",
    "set_memory_status",
    "update_memory",
    "upsert_memory",
]
