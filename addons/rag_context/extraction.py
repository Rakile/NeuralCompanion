"""Extract explicit source snapshots; never invoked by retrieval."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from . import indexer
from .models import DocumentChunk


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_snapshot(path: Path, *, cancelled) -> dict:
    path = Path(path)
    if cancelled():
        raise InterruptedError("Document extraction cancelled.")
    if path.suffix.casefold() not in indexer.ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported document type.")
    blocks = []
    if path.suffix.casefold() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF is encrypted and cannot be opened.")
        for page_number, page in enumerate(reader.pages, 1):
            if cancelled():
                raise InterruptedError("Document extraction cancelled.")
            text = str(page.extract_text() or "").strip()
            if text:
                blocks.append({"text": text, "page": page_number, "section": ""})
    else:
        text = indexer._read_text_file(path).replace("\r\n", "\n").strip()
        section, current = "", []
        for line in text.splitlines():
            heading = re.match(r"^#{1,6}\s+(.+)$", line)
            if heading and current:
                blocks.append({"text": "\n".join(current).strip(), "page": None, "section": section})
                current = []
            if heading:
                section = heading.group(1).strip()
            current.append(line)
        if current:
            blocks.append({"text": "\n".join(current).strip(), "page": None, "section": section})
    blocks = [block for block in blocks if block["text"]]
    if not blocks:
        raise ValueError("Document contains no extractable text. Scanned PDFs require OCR, which is not supported.")
    if cancelled():
        raise InterruptedError("Document extraction cancelled.")
    text = "\n\n".join(block["text"] for block in blocks)
    return {"schema_version": 1, "path": str(path), "title": path.name,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "content_hash": text_hash(text), "blocks": blocks}


def snapshot_chunks(snapshot, source, context_tokens: int) -> tuple[DocumentChunk, ...]:
    chunks = []
    limit = max(64, int(context_tokens) - 64)
    for block in snapshot["blocks"]:
        for value in indexer._chunk_text(block["text"], target_chars=min(1400, limit), overlap_chars=min(160, limit//8)):
            # UTF-8 bytes are a conservative upper bound on ordinary tokenizer input.
            parts, remaining = [], value
            while len(remaining.encode("utf-8")) > limit:
                end = min(len(remaining), limit)
                while len(remaining[:end].encode("utf-8")) > limit:
                    end -= 1
                parts.append(remaining[:end])
                remaining = remaining[max(1, end-min(40, end//8)):]
            if remaining:
                parts.append(remaining)
            for part in parts:
                chunks.append(DocumentChunk(source.id, len(chunks), part, snapshot["title"],
                                            block.get("page"), str(block.get("section") or ""), text_hash(part)))
    return tuple(chunks)


def next_token_chunk(snapshot, source, spec, state, *, count_tokens):
    """One resumable chunk, counted with the selected model's tokenizer."""
    from core.runtime.document_memory import embedding_prefixes, embedding_context_tokens
    size, overlap = spec.token_chunking()
    prefix = embedding_prefixes(spec)[0]
    capacity = embedding_context_tokens(spec)-64
    block_index, start, ordinal = state['block'], state['start'], state['ordinal']
    blocks = snapshot['blocks']
    while block_index < len(blocks) and not blocks[block_index]['text'][start:].strip():
        block_index, start = block_index+1, 0
    if block_index >= len(blocks):
        return None
    block = blocks[block_index]
    text = block['text']

    # Counts are stable within this chunk's exact model/configuration. Keep the
    # cache local so document edits and subsequent jobs cannot reuse stale data.
    counts = {}
    def token_count(value):
        if value not in counts:
            counts[value] = count_tokens(value)
        return counts[value]

    def fits(value):
        return token_count(value) <= size and token_count(prefix+value) <= capacity

    # Search character boundaries, but measure every candidate in model tokens.
    low, high = start, min(len(text), start+size*4)
    while high < len(text) and fits(text[start:high].strip()):
        low, high = high, min(len(text),start+(high-start)*2)
    if fits(text[start:high].strip()):
        end = high
    else:
        while low+1 < high:
            middle = (low+high)//2
            if fits(text[start:middle].strip()):low = middle
            else:high = middle
        end = low
    if end <= start or not text[start:end].strip():
        raise ValueError('Chunk prefix leaves too little model context for document text.')
    if end < len(text):
        # Prefer a nearby paragraph/sentence boundary, retaining Unicode verbatim.
        boundary = max(text.rfind('\n\n',start,end),text.rfind('. ',start,end))
        if boundary > start+(end-start)//2:
            candidate = boundary+(2 if text[boundary:boundary+2]=='\n\n' else 1)
            if fits(text[start:candidate].strip()):end = candidate
    value = text[start:end].strip()
    next_start = end
    if overlap and end < len(text):
        left, right = start+1, end
        while left < right:
            middle = (left+right)//2
            if token_count(text[middle:end].strip()) <= overlap:right = middle
            else:left = middle+1
        next_start = max(start+1,left)
    next_state = {'block':block_index,'start':next_start,'ordinal':ordinal+1}
    if end == len(text):next_state.update(block=block_index+1,start=0)
    chunk = DocumentChunk(source.id,ordinal,value,snapshot['title'],block.get('page'),str(block.get('section') or ''),text_hash(value))
    return chunk,next_state
