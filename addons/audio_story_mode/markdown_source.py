from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable, Iterator

from addons.audio_story_mode import chatlog_source, novel_models


CancelCheck = Callable[[], bool]
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


class MarkdownSourceAdapter:
    def inspect(
        self,
        path: str | Path,
        cancel_check: CancelCheck | None = None,
    ) -> novel_models.SourcePreview:
        source_path = Path(path)
        if not source_path.is_file():
            raise chatlog_source.SourceImportError(
                f"Markdown file does not exist: {source_path}"
            )
        fingerprint = chatlog_source.fingerprint_path(source_path, cancel_check)
        headings: list[str] = []
        has_text = False
        try:
            with source_path.open(
                "r", encoding="utf-8-sig", errors="strict", newline=""
            ) as handle:
                for line in handle:
                    chatlog_source._require_not_cancelled(cancel_check)
                    if line.strip():
                        has_text = True
                    match = _HEADING_RE.match(line.rstrip("\r\n"))
                    if match:
                        headings.append(match.group(1).strip())
        except UnicodeError as exc:
            raise chatlog_source.SourceImportError(
                "Markdown must be UTF-8 encoded."
            ) from exc
        chapter_count = len(headings) if headings else int(has_text)
        samples = tuple({"title": title} for title in headings[:5])
        return novel_models.SourcePreview(
            source_kind=novel_models.SOURCE_KIND_MARKDOWN,
            source_path=str(source_path.resolve()),
            fingerprint=fingerprint,
            parser_id="markdown",
            record_count=chapter_count,
            source_size_bytes=source_path.stat().st_size,
            estimated_chunks=chapter_count,
            samples=samples,
        )

    def iter_narration_chapters(
        self,
        path: str | Path,
        *,
        max_chars: int = 12_000,
        cancel_check: CancelCheck | None = None,
    ) -> Iterator[tuple[str, tuple[novel_models.NarrationChunk, ...]]]:
        source_path = Path(path)
        character_limit = max(500, int(max_chars))
        title = source_path.stem or "Document"
        chunks: list[novel_models.NarrationChunk] = []
        paragraph_lines: list[str] = []
        cursor = 0.0
        index = 0
        chapter_started = False

        def flush_paragraph() -> None:
            nonlocal cursor, index
            paragraph = " ".join(
                item.strip() for item in paragraph_lines if item.strip()
            ).strip()
            paragraph_lines.clear()
            if not paragraph:
                return
            for part in _split_text(paragraph, character_limit):
                duration = max(0.25, len(part.split()) / 2.6)
                chunks.append(
                    novel_models.NarrationChunk(
                        index=index,
                        text=part,
                        start_seconds=cursor,
                        end_seconds=cursor + duration,
                    )
                )
                index += 1
                cursor += duration

        with source_path.open(
            "r", encoding="utf-8-sig", errors="strict", newline=""
        ) as handle:
            for line in handle:
                chatlog_source._require_not_cancelled(cancel_check)
                stripped_line = line.rstrip("\r\n")
                heading = _HEADING_RE.match(stripped_line)
                if heading:
                    flush_paragraph()
                    if chapter_started and chunks:
                        yield title, tuple(chunks)
                        chunks = []
                        cursor = 0.0
                        index = 0
                    title = heading.group(1).strip() or "Untitled Chapter"
                    chapter_started = True
                    continue
                if stripped_line.strip():
                    paragraph_lines.append(stripped_line)
                    chapter_started = True
                else:
                    flush_paragraph()
        flush_paragraph()
        if chapter_started and chunks:
                yield title, tuple(chunks)


def split_narration_text(text: str, max_chars: int = 4_000) -> tuple[str, ...]:
    """Split prose into bounded narration chunks without retaining other chapters."""
    return _split_text(str(text or ""), max(500, int(max_chars or 500)))


def _split_text(text: str, max_chars: int) -> tuple[str, ...]:
    if len(text) <= max_chars:
        return (text,)
    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return tuple(part for part in parts if part)
