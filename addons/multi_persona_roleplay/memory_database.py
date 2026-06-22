from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .memory_embeddings import (
    cosine_similarity,
    deserialize_embedding,
    embed_text,
    keyword_set,
    serialize_embedding,
)


DEFAULT_STORY_ID = "active"
DEFAULT_SQLITE_PATH = "memory/long_memory.sqlite3"


@dataclass(frozen=True)
class MemorySearchResult:
    record_id: str
    source: str
    title: str
    text: str
    score: float
    metadata: dict[str, Any]


class SQLiteMemoryDatabase:
    def __init__(self, path: str | Path, *, logger=None):
        self.path = Path(path)
        self.logger = logger
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def upsert_event(self, event: dict[str, Any], *, story_id: str = DEFAULT_STORY_ID) -> None:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            return
        summary = str(event.get("summary") or "").strip()
        text = "\n".join(
            item
            for item in (
                summary,
                str(event.get("user_text") or "").strip(),
                str(event.get("assistant_text") or "").strip(),
                str(event.get("scene") or "").strip(),
                str(event.get("location") or "").strip(),
            )
            if item
        )
        keywords = sorted(set(event.get("keywords") or []) | keyword_set(text))
        payload = (
            event_id,
            str(story_id or DEFAULT_STORY_ID),
            float(event.get("created_at", time.time()) or time.time()),
            int(event.get("turn_index", 0) or 0),
            str(event.get("mode") or ""),
            str(event.get("scene") or ""),
            str(event.get("location") or ""),
            str(event.get("mood") or ""),
            str(event.get("story_goal") or ""),
            json.dumps(list(event.get("active_characters") or []), ensure_ascii=True),
            str(event.get("user_text") or ""),
            str(event.get("assistant_text") or ""),
            summary,
            json.dumps(keywords, ensure_ascii=True),
            serialize_embedding(embed_text(text)),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_events (
                    id, story_id, created_at, turn_index, mode, scene, location,
                    mood, story_goal, active_characters, user_text, assistant_text,
                    summary, keywords, embedding
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    story_id=excluded.story_id,
                    created_at=excluded.created_at,
                    turn_index=excluded.turn_index,
                    mode=excluded.mode,
                    scene=excluded.scene,
                    location=excluded.location,
                    mood=excluded.mood,
                    story_goal=excluded.story_goal,
                    active_characters=excluded.active_characters,
                    user_text=excluded.user_text,
                    assistant_text=excluded.assistant_text,
                    summary=excluded.summary,
                    keywords=excluded.keywords,
                    embedding=excluded.embedding
                """,
                payload,
            )

    def replace_events(self, events: list[dict[str, Any]], *, story_id: str = DEFAULT_STORY_ID) -> None:
        story = str(story_id or DEFAULT_STORY_ID)
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_events WHERE story_id = ?", (story,))
        for event in list(events or []):
            if isinstance(event, dict):
                self.upsert_event(event, story_id=story)

    def search_events(self, query: str, *, story_id: str = DEFAULT_STORY_ID, limit: int = 6) -> list[MemorySearchResult]:
        rows = self._fetch_all(
            """
            SELECT id, created_at, turn_index, mode, scene, location, summary,
                   user_text, assistant_text, keywords, embedding
            FROM memory_events
            WHERE story_id = ?
            ORDER BY created_at DESC
            LIMIT 400
            """,
            (str(story_id or DEFAULT_STORY_ID),),
        )
        query_embedding = embed_text(query)
        query_keywords = keyword_set(query)
        results = []
        for row in rows:
            summary = str(row.get("summary") or "").strip()
            full_text = "\n".join(
                item
                for item in (
                    summary,
                    row.get("user_text"),
                    row.get("assistant_text"),
                    row.get("scene"),
                    row.get("location"),
                )
                if str(item or "").strip()
            )
            score = _rank_score(
                query_keywords=query_keywords,
                query_embedding=query_embedding,
                row_keywords=_json_list(row.get("keywords")),
                row_embedding=deserialize_embedding(row.get("embedding")),
                text=full_text,
            )
            if score <= 0:
                continue
            results.append(
                MemorySearchResult(
                    record_id=str(row.get("id") or ""),
                    source="long_memory",
                    title=f"Turn {int(row.get('turn_index') or 0)}",
                    text=summary or str(row.get("assistant_text") or "").strip(),
                    score=score,
                    metadata={
                        "created_at": row.get("created_at"),
                        "mode": row.get("mode"),
                        "scene": row.get("scene"),
                        "location": row.get("location"),
                    },
                )
            )
        results.sort(key=lambda item: (-item.score, -float(item.metadata.get("created_at") or 0.0)))
        return results[: max(1, int(limit or 1))]

    def upsert_chunk(
        self,
        *,
        chunk_id: str,
        story_id: str = DEFAULT_STORY_ID,
        source: str,
        title: str,
        chunk_index: int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        clean_text = str(text or "").strip()
        if not chunk_id or not clean_text:
            return
        keywords = sorted(keyword_set(f"{title}\n{clean_text}"))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO databank_chunks (
                    id, story_id, source, title, chunk_index, text,
                    keywords, embedding, metadata, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    story_id=excluded.story_id,
                    source=excluded.source,
                    title=excluded.title,
                    chunk_index=excluded.chunk_index,
                    text=excluded.text,
                    keywords=excluded.keywords,
                    embedding=excluded.embedding,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    str(chunk_id),
                    str(story_id or DEFAULT_STORY_ID),
                    str(source or ""),
                    str(title or ""),
                    int(chunk_index or 0),
                    clean_text,
                    json.dumps(keywords, ensure_ascii=True),
                    serialize_embedding(embed_text(f"{title}\n{clean_text}")),
                    json.dumps(dict(metadata or {}), ensure_ascii=True),
                    time.time(),
                ),
            )

    def delete_chunks_by_source(self, source: str, *, story_id: str = DEFAULT_STORY_ID) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM databank_chunks WHERE story_id = ? AND source = ?",
                (str(story_id or DEFAULT_STORY_ID), str(source or "")),
            )

    def delete_chunks_by_source_prefix(self, source_prefix: str, *, story_id: str = DEFAULT_STORY_ID) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM databank_chunks WHERE story_id = ? AND source LIKE ?",
                (str(story_id or DEFAULT_STORY_ID), f"{str(source_prefix or '')}%"),
            )

    def search_chunks(
        self,
        query: str,
        *,
        story_id: str = DEFAULT_STORY_ID,
        limit: int = 6,
        include_event_chunks: bool = False,
    ) -> list[MemorySearchResult]:
        rows = self._fetch_all(
            """
            SELECT id, source, title, chunk_index, text, keywords, embedding, metadata, updated_at
            FROM databank_chunks
            WHERE story_id = ?
            ORDER BY updated_at DESC
            LIMIT 600
            """,
            (str(story_id or DEFAULT_STORY_ID),),
        )
        query_embedding = embed_text(query)
        query_keywords = keyword_set(query)
        results = []
        for row in rows:
            source = str(row.get("source") or "")
            if not include_event_chunks and source.startswith("long_memory/events/"):
                continue
            text = str(row.get("text") or "").strip()
            score = _rank_score(
                query_keywords=query_keywords,
                query_embedding=query_embedding,
                row_keywords=_json_list(row.get("keywords")),
                row_embedding=deserialize_embedding(row.get("embedding")),
                text=f"{row.get('title')}\n{text}",
            )
            if score <= 0:
                continue
            results.append(
                MemorySearchResult(
                    record_id=str(row.get("id") or ""),
                    source=source,
                    title=str(row.get("title") or source),
                    text=text,
                    score=score,
                    metadata=dict(_json_dict(row.get("metadata")), chunk_index=int(row.get("chunk_index") or 0)),
                )
            )
        results.sort(key=lambda item: (-item.score, item.source.lower(), int(item.metadata.get("chunk_index") or 0)))
        return results[: max(1, int(limit or 1))]

    def clear_story(self, *, story_id: str = DEFAULT_STORY_ID) -> None:
        story = str(story_id or DEFAULT_STORY_ID)
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_events WHERE story_id = ?", (story,))
            conn.execute("DELETE FROM databank_chunks WHERE story_id = ?", (story,))

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    turn_index INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    scene TEXT NOT NULL,
                    location TEXT NOT NULL,
                    mood TEXT NOT NULL,
                    story_goal TEXT NOT NULL,
                    active_characters TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    embedding TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_story_created ON memory_events(story_id, created_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS databank_chunks (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_databank_story_source ON databank_chunks(story_id, source)")

    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        return _SQLiteConnectionScope(conn, self._lock)

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]


class PostgresMemoryDatabase:
    def __init__(self, dsn: str, *, logger=None):
        self.dsn = str(dsn or "").strip()
        if not self.dsn:
            raise ValueError("PostgreSQL DSN is required")
        self.logger = logger
        self._driver = self._load_driver()
        self._initialize()

    def upsert_event(self, event: dict[str, Any], *, story_id: str = DEFAULT_STORY_ID) -> None:
        mirror = _EphemeralEventMirror()
        mirror.upsert_event(event, story_id=story_id)
        row = mirror.event_rows[0]
        self._execute(
            """
            INSERT INTO memory_events (
                id, story_id, created_at, turn_index, mode, scene, location,
                mood, story_goal, active_characters, user_text, assistant_text,
                summary, keywords, embedding
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                story_id=EXCLUDED.story_id,
                created_at=EXCLUDED.created_at,
                turn_index=EXCLUDED.turn_index,
                mode=EXCLUDED.mode,
                scene=EXCLUDED.scene,
                location=EXCLUDED.location,
                mood=EXCLUDED.mood,
                story_goal=EXCLUDED.story_goal,
                active_characters=EXCLUDED.active_characters,
                user_text=EXCLUDED.user_text,
                assistant_text=EXCLUDED.assistant_text,
                summary=EXCLUDED.summary,
                keywords=EXCLUDED.keywords,
                embedding=EXCLUDED.embedding
            """,
            row,
        )

    def replace_events(self, events: list[dict[str, Any]], *, story_id: str = DEFAULT_STORY_ID) -> None:
        story = str(story_id or DEFAULT_STORY_ID)
        self._execute("DELETE FROM memory_events WHERE story_id = %s", (story,))
        for event in list(events or []):
            if isinstance(event, dict):
                self.upsert_event(event, story_id=story)

    def search_events(self, query: str, *, story_id: str = DEFAULT_STORY_ID, limit: int = 6) -> list[MemorySearchResult]:
        rows = self._fetch_all(
            """
            SELECT id, created_at, turn_index, mode, scene, location, summary,
                   user_text, assistant_text, keywords, embedding
            FROM memory_events
            WHERE story_id = %s
            ORDER BY created_at DESC
            LIMIT 400
            """,
            (str(story_id or DEFAULT_STORY_ID),),
        )
        return _rank_event_rows(rows, query, limit=limit)

    def upsert_chunk(
        self,
        *,
        chunk_id: str,
        story_id: str = DEFAULT_STORY_ID,
        source: str,
        title: str,
        chunk_index: int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        mirror = _EphemeralEventMirror()
        mirror.upsert_chunk(
            chunk_id=chunk_id,
            story_id=story_id,
            source=source,
            title=title,
            chunk_index=chunk_index,
            text=text,
            metadata=metadata,
        )
        self._execute(
            """
            INSERT INTO databank_chunks (
                id, story_id, source, title, chunk_index, text,
                keywords, embedding, metadata, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                story_id=EXCLUDED.story_id,
                source=EXCLUDED.source,
                title=EXCLUDED.title,
                chunk_index=EXCLUDED.chunk_index,
                text=EXCLUDED.text,
                keywords=EXCLUDED.keywords,
                embedding=EXCLUDED.embedding,
                metadata=EXCLUDED.metadata,
                updated_at=EXCLUDED.updated_at
            """,
            mirror.chunk_rows[0],
        )

    def delete_chunks_by_source(self, source: str, *, story_id: str = DEFAULT_STORY_ID) -> None:
        self._execute(
            "DELETE FROM databank_chunks WHERE story_id = %s AND source = %s",
            (str(story_id or DEFAULT_STORY_ID), str(source or "")),
        )

    def delete_chunks_by_source_prefix(self, source_prefix: str, *, story_id: str = DEFAULT_STORY_ID) -> None:
        self._execute(
            "DELETE FROM databank_chunks WHERE story_id = %s AND source LIKE %s",
            (str(story_id or DEFAULT_STORY_ID), f"{str(source_prefix or '')}%"),
        )

    def search_chunks(
        self,
        query: str,
        *,
        story_id: str = DEFAULT_STORY_ID,
        limit: int = 6,
        include_event_chunks: bool = False,
    ) -> list[MemorySearchResult]:
        rows = self._fetch_all(
            """
            SELECT id, source, title, chunk_index, text, keywords, embedding, metadata, updated_at
            FROM databank_chunks
            WHERE story_id = %s
            ORDER BY updated_at DESC
            LIMIT 600
            """,
            (str(story_id or DEFAULT_STORY_ID),),
        )
        return _rank_chunk_rows(rows, query, limit=limit, include_event_chunks=include_event_chunks)

    def clear_story(self, *, story_id: str = DEFAULT_STORY_ID) -> None:
        story = str(story_id or DEFAULT_STORY_ID)
        self._execute("DELETE FROM memory_events WHERE story_id = %s", (story,))
        self._execute("DELETE FROM databank_chunks WHERE story_id = %s", (story,))

    def _initialize(self) -> None:
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                turn_index INTEGER NOT NULL,
                mode TEXT NOT NULL,
                scene TEXT NOT NULL,
                location TEXT NOT NULL,
                mood TEXT NOT NULL,
                story_goal TEXT NOT NULL,
                active_characters TEXT NOT NULL,
                user_text TEXT NOT NULL,
                assistant_text TEXT NOT NULL,
                summary TEXT NOT NULL,
                keywords TEXT NOT NULL,
                embedding TEXT NOT NULL
            )
            """,
            (),
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS databank_chunks (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                keywords TEXT NOT NULL,
                embedding TEXT NOT NULL,
                metadata TEXT NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )
            """,
            (),
        )

    def _load_driver(self):
        try:
            import psycopg

            return ("psycopg", psycopg)
        except Exception:
            try:
                import psycopg2

                return ("psycopg2", psycopg2)
            except Exception as exc:
                raise RuntimeError("PostgreSQL memory backend requires psycopg or psycopg2.") from exc

    def _connect(self):
        _name, driver = self._driver
        return driver.connect(self.dsn)

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
            conn.commit()

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                columns = [item[0] for item in cursor.description or []]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]


def open_memory_database(storage, *, settings: dict[str, Any] | None = None, logger=None):
    normalized = dict(settings or {})
    backend = str(normalized.get("long_memory_database_backend") or normalized.get("memory_database_backend") or "sqlite").strip().lower()
    if backend in {"postgres", "postgresql"}:
        dsn = str(normalized.get("long_memory_postgres_dsn") or normalized.get("postgres_dsn") or "").strip()
        if dsn:
            try:
                return PostgresMemoryDatabase(dsn, logger=logger)
            except Exception as exc:
                _log(logger, "[LONG_MEMORY] PostgreSQL backend unavailable; falling back to SQLite: %s", exc)
    return SQLiteMemoryDatabase(_resolve_storage_path(storage, str(normalized.get("long_memory_sqlite_path") or DEFAULT_SQLITE_PATH)), logger=logger)


def _resolve_storage_path(storage, relative_path: str) -> Path:
    clean = str(relative_path or DEFAULT_SQLITE_PATH).replace("\\", "/").lstrip("/")
    context = getattr(storage, "context", None)
    context_storage = getattr(context, "storage", None)
    if context_storage is not None and hasattr(context_storage, "resolve"):
        return Path(context_storage.resolve(clean))
    if hasattr(storage, "resolve"):
        return Path(storage.resolve(clean))
    root = getattr(storage, "root", None)
    if root is not None:
        return Path(root) / clean
    return Path(clean)


def _rank_event_rows(rows: list[dict[str, Any]], query: str, *, limit: int) -> list[MemorySearchResult]:
    query_embedding = embed_text(query)
    query_keywords = keyword_set(query)
    results = []
    for row in rows:
        summary = str(row.get("summary") or "").strip()
        full_text = "\n".join(
            item
            for item in (
                summary,
                row.get("user_text"),
                row.get("assistant_text"),
                row.get("scene"),
                row.get("location"),
            )
            if str(item or "").strip()
        )
        score = _rank_score(
            query_keywords=query_keywords,
            query_embedding=query_embedding,
            row_keywords=_json_list(row.get("keywords")),
            row_embedding=deserialize_embedding(row.get("embedding")),
            text=full_text,
        )
        if score <= 0:
            continue
        results.append(
            MemorySearchResult(
                record_id=str(row.get("id") or ""),
                source="long_memory",
                title=f"Turn {int(row.get('turn_index') or 0)}",
                text=summary or str(row.get("assistant_text") or "").strip(),
                score=score,
                metadata={
                    "created_at": row.get("created_at"),
                    "mode": row.get("mode"),
                    "scene": row.get("scene"),
                    "location": row.get("location"),
                },
            )
        )
    results.sort(key=lambda item: (-item.score, -float(item.metadata.get("created_at") or 0.0)))
    return results[: max(1, int(limit or 1))]


def _rank_chunk_rows(
    rows: list[dict[str, Any]],
    query: str,
    *,
    limit: int,
    include_event_chunks: bool,
) -> list[MemorySearchResult]:
    query_embedding = embed_text(query)
    query_keywords = keyword_set(query)
    results = []
    for row in rows:
        source = str(row.get("source") or "")
        if not include_event_chunks and source.startswith("long_memory/events/"):
            continue
        text = str(row.get("text") or "").strip()
        score = _rank_score(
            query_keywords=query_keywords,
            query_embedding=query_embedding,
            row_keywords=_json_list(row.get("keywords")),
            row_embedding=deserialize_embedding(row.get("embedding")),
            text=f"{row.get('title')}\n{text}",
        )
        if score <= 0:
            continue
        results.append(
            MemorySearchResult(
                record_id=str(row.get("id") or ""),
                source=source,
                title=str(row.get("title") or source),
                text=text,
                score=score,
                metadata=dict(_json_dict(row.get("metadata")), chunk_index=int(row.get("chunk_index") or 0)),
            )
        )
    results.sort(key=lambda item: (-item.score, item.source.lower(), int(item.metadata.get("chunk_index") or 0)))
    return results[: max(1, int(limit or 1))]


def _rank_score(
    *,
    query_keywords: set[str],
    query_embedding: list[float],
    row_keywords: list[str],
    row_embedding: list[float],
    text: str,
) -> float:
    if not query_keywords and not str(text or "").strip():
        return 0.0
    keywords = set(row_keywords) | keyword_set(text)
    keyword_overlap = len(query_keywords & keywords)
    vector_score = max(0.0, cosine_similarity(query_embedding, row_embedding))
    exact_bonus = 1.0 if str(text or "").lower().find(" ".join(sorted(query_keywords))[:40]) >= 0 else 0.0
    return float(keyword_overlap) + (vector_score * 3.0) + exact_bonus


def _json_list(payload: Any) -> list[str]:
    if isinstance(payload, list):
        values = payload
    else:
        try:
            values = json.loads(str(payload or "[]"))
        except Exception:
            values = []
    return [str(item) for item in values if str(item or "").strip()]


def _json_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    try:
        value = json.loads(str(payload or "{}"))
    except Exception:
        value = {}
    return dict(value) if isinstance(value, dict) else {}


def _log(logger, message: str, *args) -> None:
    if logger is None:
        return
    try:
        logger.warning(message, *args)
    except Exception:
        pass


class _SQLiteConnectionScope:
    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock):
        self.conn = conn
        self.lock = lock

    def __enter__(self):
        self.lock.acquire()
        return self.conn.__enter__()

    def __exit__(self, exc_type, exc, tb):
        try:
            return self.conn.__exit__(exc_type, exc, tb)
        finally:
            self.conn.close()
            self.lock.release()


class _EphemeralEventMirror:
    def __init__(self):
        self.event_rows: list[tuple[Any, ...]] = []
        self.chunk_rows: list[tuple[Any, ...]] = []

    def upsert_event(self, event: dict[str, Any], *, story_id: str = DEFAULT_STORY_ID) -> None:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            return
        summary = str(event.get("summary") or "").strip()
        text = "\n".join(
            item
            for item in (
                summary,
                str(event.get("user_text") or "").strip(),
                str(event.get("assistant_text") or "").strip(),
                str(event.get("scene") or "").strip(),
                str(event.get("location") or "").strip(),
            )
            if item
        )
        keywords = sorted(set(event.get("keywords") or []) | keyword_set(text))
        self.event_rows.append(
            (
                event_id,
                str(story_id or DEFAULT_STORY_ID),
                float(event.get("created_at", time.time()) or time.time()),
                int(event.get("turn_index", 0) or 0),
                str(event.get("mode") or ""),
                str(event.get("scene") or ""),
                str(event.get("location") or ""),
                str(event.get("mood") or ""),
                str(event.get("story_goal") or ""),
                json.dumps(list(event.get("active_characters") or []), ensure_ascii=True),
                str(event.get("user_text") or ""),
                str(event.get("assistant_text") or ""),
                summary,
                json.dumps(keywords, ensure_ascii=True),
                serialize_embedding(embed_text(text)),
            )
        )

    def upsert_chunk(
        self,
        *,
        chunk_id: str,
        story_id: str,
        source: str,
        title: str,
        chunk_index: int,
        text: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        clean_text = str(text or "").strip()
        if not chunk_id or not clean_text:
            return
        keywords = sorted(keyword_set(f"{title}\n{clean_text}"))
        self.chunk_rows.append(
            (
                str(chunk_id),
                str(story_id or DEFAULT_STORY_ID),
                str(source or ""),
                str(title or ""),
                int(chunk_index or 0),
                clean_text,
                json.dumps(keywords, ensure_ascii=True),
                serialize_embedding(embed_text(f"{title}\n{clean_text}")),
                json.dumps(dict(metadata or {}), ensure_ascii=True),
                time.time(),
            )
        )
