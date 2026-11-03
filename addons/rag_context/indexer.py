from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".log", ".pdf"}
SETTINGS_FILE = "settings.json"
INDEX_FILE = "index.json"

DEFAULT_SETTINGS = {
    "enabled": False,
    "files": [],
    "top_k": 4,
    "min_score": 2,
    "max_context_chars": 4000,
}

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class SearchResult:
    source: str
    chunk_index: int
    score: int
    text: str


def normalize_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(payload, dict):
        settings.update(payload)
    files = []
    seen = set()
    for item in settings.get("files") or []:
        path = str(item or "").strip()
        if not path:
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        files.append(path)
    settings["files"] = files
    settings["enabled"] = bool(settings.get("enabled", False))
    settings["top_k"] = max(1, min(12, _int(settings.get("top_k"), DEFAULT_SETTINGS["top_k"])))
    settings["min_score"] = max(0, min(20, _int(settings.get("min_score"), DEFAULT_SETTINGS["min_score"])))
    settings["max_context_chars"] = max(1000, min(16000, _int(settings.get("max_context_chars"), DEFAULT_SETTINGS["max_context_chars"])))
    return settings


def load_settings(storage) -> dict[str, Any]:
    try:
        return normalize_settings(storage.read_json(SETTINGS_FILE))
    except Exception:
        return normalize_settings(None)


def save_settings(storage, settings: dict[str, Any]) -> None:
    storage.write_json(SETTINGS_FILE, normalize_settings(settings))


def load_index(storage) -> dict[str, Any]:
    try:
        payload = storage.read_json(INDEX_FILE)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        chunks = []
    return {
        "version": 1,
        "built_at": str(payload.get("built_at") or ""),
        "files": list(payload.get("files") or []),
        "chunks": [item for item in chunks if isinstance(item, dict)],
    }


def save_index(storage, index: dict[str, Any]) -> None:
    storage.write_json(INDEX_FILE, index)


def build_index(file_paths: list[str]) -> dict[str, Any]:
    from datetime import datetime, timezone

    files = []
    chunks = []
    for raw_path in file_paths:
        path = Path(str(raw_path or "").strip())
        if not path.exists() or not path.is_file():
            files.append({"path": str(path), "status": "missing", "chunks": 0})
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            files.append({"path": str(path), "status": "skipped_extension", "chunks": 0})
            continue
        try:
            text = _read_text_file(path)
        except Exception as exc:
            files.append({"path": str(path), "status": f"read_error: {exc}", "chunks": 0})
            continue
        file_chunks = _chunk_text(text)
        for index, chunk in enumerate(file_chunks):
            chunks.append(
                {
                    "source": str(path),
                    "title": path.name,
                    "chunk_index": index,
                    "text": chunk,
                    "tokens": sorted(_tokens(chunk)),
                }
            )
        files.append(
            {
                "path": str(path),
                "status": "ok",
                "chunks": len(file_chunks),
                "mtime": path.stat().st_mtime,
            }
        )
    return {
        "version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
        "chunks": chunks,
    }


def search_index(index: dict[str, Any], query: str, *, top_k: int, min_score: int) -> list[SearchResult]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    results = []
    for item in list(index.get("chunks") or []):
        if not isinstance(item, dict):
            continue
        chunk_tokens = set(item.get("tokens") or _tokens(str(item.get("text") or "")))
        score = len(query_tokens & chunk_tokens)
        if score < min_score:
            continue
        results.append(
            SearchResult(
                source=str(item.get("source") or ""),
                chunk_index=_int(item.get("chunk_index"), 0),
                score=score,
                text=str(item.get("text") or "").strip(),
            )
        )
    results.sort(key=lambda item: (-item.score, item.source.lower(), item.chunk_index))
    return results[: max(1, int(top_k))]


def build_context(results: list[SearchResult], *, max_chars: int) -> str:
    if not results:
        return ""
    parts = [
        "Relevant retrieval context from the user's selected local RAG source index.",
        "Use this context when it helps answer the user's latest message. Do not invent details that are not present here.",
    ]
    used = len("\n\n".join(parts))
    for result in results:
        label = f"[Source: {Path(result.source).name}, chunk {result.chunk_index + 1}, score {result.score}]"
        text = str(result.text or "").strip()
        block = f"{label}\n{text}"
        if used + len(block) + 2 > max_chars:
            remaining = max_chars - used - len(label) - 8
            if remaining > 80:
                parts.append(f"{label}\n{text[:remaining].rstrip()}...")
            break
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts).strip()


def _read_text_file(path: Path) -> str:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return json.dumps(payload, indent=2, ensure_ascii=True)
    if path.suffix.lower() == ".pdf":
        return _read_pdf_file(path)
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252", errors="replace")


def _read_pdf_file(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("PDF support requires the pypdf package. Re-run the installer or install pypdf.") from exc

    reader = PdfReader(str(path))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError("PDF is encrypted and could not be opened.") from exc

    page_blocks = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = str(text or "").strip()
        if text:
            page_blocks.append(f"[Page {index + 1}]\n{text}")
    if not page_blocks:
        raise RuntimeError("PDF contains no extractable text. Scanned/OCR-only PDFs are not supported yet.")
    return "\n\n".join(page_blocks)


def _chunk_text(text: str, *, target_chars: int = 1400, overlap_chars: int = 160) -> list[str]:
    clean = re.sub(r"\r\n?", "\n", str(text or ""))
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", clean) if part.strip()]
    chunks = []
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
            continue
        if current.strip():
            chunks.append(current.strip())
        tail = current[-overlap_chars:].strip() if current else ""
        current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _split_long_text(text: str, *, target_chars: int, overlap_chars: int) -> list[str]:
    chunks = []
    start = 0
    value = str(text or "").strip()
    while start < len(value):
        end = min(len(value), start + target_chars)
        if end < len(value):
            pivot = value.rfind(". ", start, end)
            if pivot > start + int(target_chars * 0.5):
                end = pivot + 1
        chunk = value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(value):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_]{3,}", str(text or "").lower())
        if token not in _STOP_WORDS
    }


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)
