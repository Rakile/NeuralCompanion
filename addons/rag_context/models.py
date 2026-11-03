"""Immutable document-only state; no conversation or archive bindings."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable
from core.runtime.document_memory import embedding_prefixes

CancelCheck = Callable[[], bool]
Clock = Callable[[], float]


@dataclass(frozen=True)
class EmbeddingSpec:
    base_url: str = "http://127.0.0.1:1234/v1"
    model: str = "text-embedding-bge-m3"
    context_tokens: int = 8192
    prefix_scheme: str = "bge-m3"
    artifact: str = ""
    dimensions: int = 0
    chunk_prefix: str | None = None
    query_prefix: str | None = None
    chunk_size_tokens: int | None = None
    chunk_overlap_tokens: int | None = None

    def token_chunking(self):
        import math
        if self.chunk_size_tokens is None and self.chunk_overlap_tokens is None:
            return None  # Existing indexes retain character splitting until Apply.
        size, overlap = self.chunk_size_tokens, self.chunk_overlap_tokens
        for value in (size, overlap):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or (isinstance(value, float) and not math.isfinite(value)) or int(value) != value):
                raise ValueError("Chunk size and overlap must be whole numbers of tokens.")
        size, overlap = int(size), int(overlap)
        if not 64 <= size <= min(32768, int(self.context_tokens)-64):
            raise ValueError("Chunk size must be at least 64 tokens and leave 64 tokens of model context headroom.")
        if not 0 <= overlap < size:
            raise ValueError("Chunk overlap must be zero or greater and smaller than the chunk size.")
        return size, overlap

    def fingerprint(self) -> str:
        prefixes = embedding_prefixes(self)
        legacy = "bge-m3" if prefixes == ("", "") else "nomic" if prefixes == ("search_document: ", "search_query: ") else self.prefix_scheme
        value = (self.base_url.rstrip("/"), self.model, self.context_tokens,
                 legacy, self.artifact, self.dimensions, "l2-f32-v1")
        if prefixes not in (("", ""), ("search_document: ", "search_query: ")):
            value += (prefixes, "manual-prefix-v1")
        chunking = self.token_chunking()
        if chunking is not None:
            value += (chunking, "model-token-chunks-v1")
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class RetrievalSettings:
    top_k: int = 4
    min_score: int = 2
    semantic_min_score: float = 0.25
    max_context_chars: int = 4000
    deadline_ms: int = 1500

    def normalized(self) -> RetrievalSettings:
        import math
        score = float(self.semantic_min_score)
        if not math.isfinite(score):
            raise ValueError("Similarity must be finite.")
        return RetrievalSettings(max(1, min(12, int(self.top_k))),
                                 max(0, min(20, int(self.min_score))),
                                 max(-1.0, min(1.0, score)),
                                 max(1000, min(16000, int(self.max_context_chars))),
                                 max(100, min(5000, int(self.deadline_ms))))


REFERENCE_GUIDE = "Use these excerpts as reference material. Name the source when useful, and distinguish its contents from our conversation."
INTEGRATED_GUIDE = "You retrieve this knowledge from your memory:"


@dataclass(frozen=True)
class UsageSettings:
    usage_mode: str = "reference"
    prompt_guide: str = REFERENCE_GUIDE
    show_sources: bool = True

    @classmethod
    def preset(cls, mode):
        if mode not in {"reference", "integrated"}:
            raise ValueError("Choose Reference documents or Integrated knowledge.")
        return cls(mode, REFERENCE_GUIDE if mode == "reference" else INTEGRATED_GUIDE, mode == "reference")

    def normalized(self):
        if self.usage_mode not in {"reference", "integrated"}:
            raise ValueError("Unknown Document Memory usage preset.")
        if not isinstance(self.prompt_guide, str) or len(self.prompt_guide) > 2000 or "\x00" in self.prompt_guide:
            raise ValueError("Memory prompt guide must be text of at most 2,000 characters.")
        if type(self.show_sources) is not bool:
            raise ValueError("Source visibility must be enabled or disabled.")
        return UsageSettings(self.usage_mode, self.prompt_guide.strip(), self.show_sources)


@dataclass(frozen=True)
class SourceRecord:
    id: str
    path: str
    enabled: bool = True
    snapshot_id: str | None = None
    generation_id: str | None = None
    status: str = "pending"
    error: str = ""
    revision: int = 0
    pending_operation: str = ""


@dataclass(frozen=True)
class KnowledgePackage:
    id: str
    name: str
    revision: int = 0
    embedding: EmbeddingSpec = EmbeddingSpec()
    retrieval: RetrievalSettings = RetrievalSettings()
    sources: tuple[SourceRecord, ...] = ()
    generation_id: str | None = None
    usage: UsageSettings = UsageSettings()


@dataclass(frozen=True)
class DocumentChunk:
    source_id: str
    ordinal: int
    text: str
    title: str
    page: int | None = None
    section: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class IndexGeneration:
    package_id: str
    id: str
    fingerprint: str
    chunks: tuple[DocumentChunk, ...]
    vectors: object  # NumPy array loaded only by the indexing/retrieval modules.


@dataclass(frozen=True)
class DocumentScope:
    owner_generation: int
    session_generation: int
    package_id: str
    package_revision: int
    activation_revision: int


@dataclass(frozen=True)
class RetrievalResult:
    context: str
    debug: dict[str, object]
    scope: DocumentScope
