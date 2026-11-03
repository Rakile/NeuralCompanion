"""Saved extracted text and immutable vector generations, atomically published."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4
import numpy as np

from .extraction import text_hash
from .models import DocumentChunk, IndexGeneration
from .packages import atomic_json, canonical_id, PackageConflict


class IndexUnavailable(ValueError):
    pass


def _digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


class SnapshotStore:
    def __init__(self, root: Path, *, library):
        self.root, self.library = Path(root), library

    def stage(self, package_id, source, snapshot, embedding_fingerprint):
        snapshot_id = str(uuid4())
        value = {**snapshot, "source_id": source.id, "embedding_fingerprint": embedding_fingerprint}
        self._validate_snapshot(value, source.id)
        atomic_json(self.library.package_dir(package_id) / "snapshots" / (snapshot_id+".json"), value)
        return snapshot_id

    @staticmethod
    def _validate_snapshot(value, source_id):
        if value.get("schema_version") != 1 or value.get("source_id", source_id) != source_id:
            raise IndexUnavailable("Invalid saved source snapshot.")
        blocks = value.get("blocks")
        if not isinstance(blocks, list) or not blocks or any(not isinstance(b.get("text"), str) for b in blocks):
            raise IndexUnavailable("Saved snapshot has no text.")
        if text_hash("\n\n".join(b["text"] for b in blocks)) != value.get("content_hash"):
            raise IndexUnavailable("Saved snapshot checksum failed.")

    def read_snapshot(self, package_id, source):
        if not source.snapshot_id:
            return None
        path = self.library.package_dir(package_id) / "snapshots" / (canonical_id(source.snapshot_id)+".json")
        value = json.loads(path.read_text(encoding="utf-8"))
        self._validate_snapshot(value, source.id)
        return value

    @staticmethod
    def _vectors(vectors, rows):
        value = np.asarray(vectors, dtype=np.float32)
        if value.ndim != 2 or value.shape[0] != rows or value.shape[1] < 1 or not np.isfinite(value).all():
            raise IndexUnavailable("Invalid document vector dimensions or values.")
        if rows:
            norms = np.linalg.norm(value, axis=1)
            if np.any(norms == 0) or not np.allclose(norms, 1, atol=1e-4):
                raise IndexUnavailable("Document vectors must be normalized.")
        value = np.array(value, dtype=np.float32, copy=True)
        value.setflags(write=False)
        return value

    def publish(self, package_id, generation, *, expected_revision, sources=None, is_current=lambda: True):
        if self.library is not None:
            self.library.ensure_writable()
        if generation.package_id != package_id:
            raise ValueError("Generation belongs to another package.")
        canonical_id(generation.id)
        vectors = self._vectors(generation.vectors, len(generation.chunks))
        path = self.library.package_dir(package_id) / "generations" / generation.id
        path.mkdir(parents=True, exist_ok=False)
        atomic_json(path / "chunks.json", [asdict(chunk) for chunk in generation.chunks])
        with (path / "vectors.npy").open("wb") as handle:
            np.save(handle, vectors, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_json(path / "manifest.json", {"schema_version": 1, "package_id": package_id,
                    "id": generation.id, "fingerprint": generation.fingerprint, "rows": len(generation.chunks),
                    "dimensions": vectors.shape[1], "chunks_hash": _digest(path / "chunks.json"),
                    "vectors_hash": _digest(path / "vectors.npy")})
        with self.library.lock:
            package = self.library.get(package_id)
            if package.revision != expected_revision or not is_current():
                raise PackageConflict("Package changed before document publication.")
            if package.embedding.fingerprint() != generation.fingerprint:
                raise PackageConflict("Embedding configuration changed before publication.")
            self.library.update(replace(package, generation_id=generation.id,
                                       sources=package.sources if sources is None else tuple(sources)), expected_revision=expected_revision)

    def load(self, package):
        if not package.generation_id:
            return None
        try:
            path = self.library.package_dir(package.id) / "generations" / canonical_id(package.generation_id)
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("schema_version") != 1 or manifest.get("package_id") != package.id or manifest.get("id") != package.generation_id:
                raise IndexUnavailable("Invalid document generation manifest.")
            if manifest.get("fingerprint") != package.embedding.fingerprint():
                return None
            if manifest["chunks_hash"] != _digest(path / "chunks.json") or manifest["vectors_hash"] != _digest(path / "vectors.npy"):
                raise IndexUnavailable("Document generation checksum failed. Rebuild saved embeddings.")
            chunks = tuple(DocumentChunk(**item) for item in json.loads((path / "chunks.json").read_text(encoding="utf-8")))
            if any(c.content_hash != text_hash(c.text) for c in chunks):
                raise IndexUnavailable("Document chunk checksum failed.")
            vectors = self._vectors(np.load(path / "vectors.npy", allow_pickle=False), len(chunks))
            if vectors.shape != (manifest["rows"], manifest["dimensions"]):
                raise IndexUnavailable("Document manifest dimensions do not match.")
            return IndexGeneration(package.id, package.generation_id, manifest["fingerprint"], chunks, vectors)
        except IndexUnavailable:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise IndexUnavailable(f"Saved document index is unavailable: {exc}") from exc

    def _cache_path(self, content_hash, fingerprint):
        if any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in (content_hash, fingerprint)):
            raise ValueError("Invalid document cache hash.")
        return self.root / "cache" / fingerprint / (content_hash+".npy")

    def cached_embedding(self, content_hash, fingerprint):
        path = self._cache_path(content_hash, fingerprint)
        try:
            value = np.load(path, allow_pickle=False)
            return self._vectors(value.reshape(1, -1), 1)[0]
        except (OSError, ValueError):
            return None

    def cache_embedding(self, content_hash, fingerprint, vector):
        value = self._vectors(np.asarray(vector, dtype=np.float32).reshape(1, -1), 1)[0]
        path = self._cache_path(content_hash, fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".staging-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                np.save(handle, value, allow_pickle=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
