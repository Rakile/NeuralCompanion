from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .memory_database import DEFAULT_STORY_ID, MemorySearchResult


ALLOWED_DOCUMENT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".log", ".pdf"}


class StoryDataBank:
    def __init__(self, database, *, story_id: str = DEFAULT_STORY_ID, logger=None):
        self.database = database
        self.story_id = str(story_id or DEFAULT_STORY_ID)
        self.logger = logger

    def index_document(
        self,
        *,
        source: str,
        title: str = "",
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        clean_source = str(source or "databank/document").strip()
        clean_title = str(title or Path(clean_source).name or "Data bank document").strip()
        chunks = chunk_text(text)
        self.database.delete_chunks_by_source(clean_source, story_id=self.story_id)
        indexed = []
        for index, chunk in enumerate(chunks):
            chunk_id = _chunk_id(self.story_id, clean_source, index, chunk)
            self.database.upsert_chunk(
                chunk_id=chunk_id,
                story_id=self.story_id,
                source=clean_source,
                title=clean_title,
                chunk_index=index,
                text=chunk,
                metadata=dict(metadata or {}),
            )
            indexed.append({"id": chunk_id, "source": clean_source, "title": clean_title, "chunk_index": index, "text": chunk})
        return indexed

    def index_path(self, path: str | Path, *, source: str = "", title: str = "") -> list[dict[str, Any]]:
        document_path = Path(path)
        text = read_document_text(document_path)
        return self.index_document(
            source=source or str(document_path),
            title=title or document_path.name,
            text=text,
            metadata={"path": str(document_path)},
        )

    def index_paths(self, paths: list[str | Path]) -> list[dict[str, Any]]:
        indexed = []
        for path in list(paths or []):
            try:
                indexed.extend(self.index_path(path))
            except Exception as exc:
                self._log("Failed to index data bank source %s: %s", path, exc)
        return indexed

    def index_long_memory_payload(self, payload: dict[str, Any]) -> None:
        delete_prefix = getattr(self.database, "delete_chunks_by_source_prefix", None)
        if callable(delete_prefix):
            delete_prefix("long_memory/", story_id=self.story_id)
        pinned = [str(item).strip() for item in list(payload.get("pinned_facts") or []) if str(item).strip()]
        if pinned:
            self.index_document(
                source="long_memory/pinned_facts",
                title="Pinned Story Facts",
                text="\n".join(f"- {item}" for item in pinned),
                metadata={"kind": "pinned_facts"},
            )
        else:
            self.database.delete_chunks_by_source("long_memory/pinned_facts", story_id=self.story_id)

        for chapter in list(payload.get("chapters") or []):
            if not isinstance(chapter, dict):
                continue
            chapter_id = str(chapter.get("id") or chapter.get("title") or "").strip()
            summary = str(chapter.get("summary") or "").strip()
            if not chapter_id or not summary:
                continue
            self.index_document(
                source=f"long_memory/chapters/{chapter_id}",
                title=str(chapter.get("title") or chapter_id),
                text=summary,
                metadata={"kind": "chapter", "start_turn": chapter.get("start_turn"), "end_turn": chapter.get("end_turn")},
            )

        for event in list(payload.get("events") or [])[-120:]:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or "").strip()
            summary = str(event.get("summary") or "").strip()
            if not event_id or not summary:
                continue
            self.index_document(
                source=f"long_memory/events/{event_id}",
                title=f"Story Memory Turn {event.get('turn_index', '')}",
                text=summary,
                metadata={"kind": "event", "turn_index": event.get("turn_index")},
            )

    def index_story_archive(self, *, story_id: str, story: dict[str, Any], memory: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        title = str(story.get("title") or story_id or "Story archive").strip()
        parts = [
            f"Story: {title}",
            str(story.get("summary") or "").strip(),
            _json_section("Session", story.get("session")),
            _json_section("Personas", story.get("personas")),
        ]
        long_memory = dict((memory or {}).get("long_memory") or {})
        for event in list(long_memory.get("events") or [])[-80:]:
            if isinstance(event, dict) and str(event.get("summary") or "").strip():
                parts.append(str(event.get("summary") or "").strip())
        return self.index_document(
            source=f"story_archives/{story_id}",
            title=f"Story Archive: {title}",
            text="\n\n".join(part for part in parts if part),
            metadata={"kind": "story_archive", "story_id": story_id},
        )

    def prompt_context(self, query: str, *, max_chunks: int = 4, max_chars: int = 3000) -> str:
        results = self.search(query, limit=max_chunks)
        if not results:
            return ""
        parts = [
            "Story data bank:",
            "Use these retrieved notes for continuity when they match the current scene. Do not invent facts beyond these notes.",
        ]
        used = len("\n".join(parts))
        for result in results:
            label = f"- {result.title} [{result.source}, score {result.score:.2f}]"
            block = f"{label}\n  {result.text}"
            if used + len(block) + 1 > max_chars:
                break
            parts.append(block)
            used += len(block) + 1
        return "\n".join(parts).strip()

    def search(self, query: str, *, limit: int = 4) -> list[MemorySearchResult]:
        return self.database.search_chunks(query, story_id=self.story_id, limit=limit)

    def _log(self, message: str, *args) -> None:
        if self.logger is None:
            return
        try:
            self.logger.warning(message, *args)
        except Exception:
            pass


def chunk_text(text: Any, *, target_chars: int = 1200, overlap_chars: int = 140) -> list[str]:
    clean = re.sub(r"\r\n?", "\n", str(text or "")).strip()
    if not clean:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", clean) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_chars:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_long_text(paragraph, target_chars=target_chars, overlap_chars=overlap_chars))
            continue
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= target_chars:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())
            current = paragraph
    if current.strip():
        chunks.append(current.strip())
    return chunks or [clean[:target_chars]]


def read_document_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"Unsupported data bank document type: {suffix}")
    if suffix == ".json":
        return json.dumps(json.loads(path.read_text(encoding="utf-8-sig")), indent=2, ensure_ascii=True)
    if suffix == ".pdf":
        return _read_pdf_text(path)
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252", errors="replace")


def _split_long_text(text: str, *, target_chars: int, overlap_chars: int) -> list[str]:
    chunks = []
    start = 0
    clean = str(text or "").strip()
    while start < len(clean):
        end = min(len(clean), start + target_chars)
        if end < len(clean):
            boundary = max(clean.rfind(". ", start, end), clean.rfind("\n", start, end), clean.rfind(" ", start, end))
            if boundary > start + int(target_chars * 0.55):
                end = boundary + 1
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(clean):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _read_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("PDF data bank indexing requires the pypdf package.") from exc
    reader = PdfReader(str(path))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError("PDF is encrypted and could not be opened.") from exc
    pages = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if str(text or "").strip():
            pages.append(f"[Page {index + 1}]\n{text.strip()}")
    if not pages:
        raise RuntimeError("PDF contains no extractable text.")
    return "\n\n".join(pages)


def _chunk_id(story_id: str, source: str, index: int, text: str) -> str:
    digest = hashlib.sha1(f"{story_id}\n{source}\n{index}\n{text}".encode("utf-8", errors="replace")).hexdigest()
    return digest[:24]


def _json_section(label: str, payload: Any) -> str:
    if payload in (None, "", [], {}):
        return ""
    try:
        return f"{label}:\n{json.dumps(payload, indent=2, ensure_ascii=True)}"
    except Exception:
        return f"{label}:\n{payload}"
