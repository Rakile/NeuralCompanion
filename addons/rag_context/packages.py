"""UUID-addressed, revision-checked local knowledge package library."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import ntpath
import os
from pathlib import Path
import tempfile
import threading
from typing import Callable, Mapping
from uuid import UUID, uuid4

from .models import EmbeddingSpec, KnowledgePackage, RetrievalSettings, SourceRecord, UsageSettings


class PackageConflict(RuntimeError):
    """A newer edit won; a stale worker must not overwrite it."""


def canonical_id(value: str) -> str:
    try:
        parsed = UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Invalid knowledge UUID.") from exc
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("Knowledge IDs must be canonical UUIDv4 values.")
    return str(parsed)


def path_key(value: str) -> str:
    # Source selection follows Windows path semantics even in portable tests.
    return ntpath.normpath(str(value).strip()).casefold()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".staging-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def package_from_dict(value: Mapping) -> KnowledgePackage:
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported knowledge package schema.")
    sources = tuple(SourceRecord(**item) for item in value.get("sources", ()))
    for source in sources:
        canonical_id(source.id)
        for ref in (source.snapshot_id, source.generation_id):
            if ref:
                canonical_id(ref)
    generation_id = value.get("generation_id")
    if generation_id:
        canonical_id(generation_id)
    return KnowledgePackage(canonical_id(value["id"]), str(value["name"]),
                            int(value["revision"]), EmbeddingSpec(**value["embedding"]),
                            RetrievalSettings(**value["retrieval"]).normalized(),
                            sources, generation_id, UsageSettings(**value.get("usage", {})).normalized())


class PackageLibrary:
    def __init__(self, root: Path, *, uuid_factory: Callable[[], UUID] = uuid4, recover=False):
        self.root = Path(root).resolve()
        self._uuid = uuid_factory
        self.lock = threading.RLock()
        self._packages: dict[str, KnowledgePackage] = {}
        self._migrations: dict[str, str] = {}
        self._recovery_errors: list[dict[str, str]] = []
        registry = self.root / "library.json"
        self._registry_present = registry.exists()
        if self._registry_present:
            try:
                value = json.loads(registry.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value["packages"], list):
                    raise ValueError("Unsupported knowledge library schema.")
            except (KeyError, TypeError, ValueError, OSError) as exc:
                self._read_error(registry, exc, recover)
                return
            for package_id in value["packages"]:
                path = registry
                try:
                    path = self.package_dir(package_id) / "package.json"
                    package = package_from_dict(json.loads(path.read_text(encoding="utf-8")))
                    if package.id != package_id or package.id in self._packages:
                        raise ValueError("Invalid knowledge registry reference.")
                    self._validate(package)
                    self._packages[package.id] = package
                except (KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError) as exc:
                    self._read_error(path, exc, recover)
            try:
                migrations = value.get("migrations", {})
                if not isinstance(migrations, dict) or any(ref not in self._packages for ref in migrations.values()):
                    raise ValueError("Invalid legacy migration reference.")
                self._migrations = dict(migrations)
            except (TypeError, ValueError) as exc:
                self._read_error(registry, exc, recover)

    def _read_error(self, path, error, recover):
        if not recover:
            raise ValueError(f"Cannot read knowledge library at {path}: {error}") from error
        self._recovery_errors.append({"path": str(path), "reason": str(error)})

    @property
    def read_only(self):
        return bool(self._recovery_errors)

    def recovery_snapshot(self):
        return {"state": "required" if self.read_only else "healthy", "read_only": self.read_only,
                "errors": [dict(error) for error in self._recovery_errors]}

    @property
    def recovery_error(self):
        if not self.read_only:
            return ""
        details = "; ".join(f"{error['path']}: {error['reason']}" for error in self._recovery_errors)
        return (f"Document Memory recovery required; library is read-only. {details}. "
                "Files were left untouched. Restore the damaged metadata explicitly, then reload Document Memory to resume updates.")

    def ensure_writable(self):
        with self.lock:
            if not self.read_only:
                # Metadata may have been damaged after this instance was loaded.
                persisted = PackageLibrary(self.root, recover=True)
                if self._registry_present and not persisted._registry_present:
                    persisted._read_error(self.root / "library.json", "Knowledge library registry is missing.", True)
                if persisted.read_only:
                    self._recovery_errors = persisted._recovery_errors
                    self._packages = persisted._packages
                    self._migrations = persisted._migrations
            if self.read_only:
                raise RuntimeError(self.recovery_error)

    def package_dir(self, package_id: str) -> Path:
        candidate = (self.root / "packages" / canonical_id(package_id)).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Knowledge package path escapes storage.")
        return candidate

    def list_packages(self) -> tuple[KnowledgePackage, ...]:
        with self.lock:
            return tuple(self._packages.values())

    def get(self, package_id: str) -> KnowledgePackage:
        with self.lock:
            return self._packages[canonical_id(package_id)]

    def _validate(self, package: KnowledgePackage):
        canonical_id(package.id)
        name = package.name.strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Package name must contain 1–80 visible characters.")
        if any(p.id != package.id and p.name.casefold() == name.casefold() for p in self._packages.values()):
            raise ValueError("A knowledge package already has this name.")
        seen_ids, seen_paths = set(), set()
        for source in package.sources:
            canonical_id(source.id)
            key = path_key(source.path)
            if not key or source.id in seen_ids or key in seen_paths:
                raise ValueError("Duplicate or empty knowledge source.")
            for ref in (source.snapshot_id, source.generation_id):
                if ref:
                    canonical_id(ref)
            seen_ids.add(source.id)
            seen_paths.add(key)
        if package.generation_id:
            canonical_id(package.generation_id)
        if package.embedding.context_tokens < 256:
            raise ValueError("Embedding context must be at least 256 tokens.")
        package.embedding.fingerprint()  # Validate formatting without changing legacy fingerprints.
        usage = package.usage.normalized()
        if len(usage.prompt_guide) + 512 > package.retrieval.max_context_chars:
            raise ValueError("Shorten the memory prompt guide or increase the context character budget to leave room for recalled knowledge.")

    def _write_package(self, package: KnowledgePackage):
        self.ensure_writable()
        atomic_json(self.package_dir(package.id) / "package.json", {"schema_version": 1, **asdict(package)})

    def _write_registry(self, packages=None, migrations=None):
        self.ensure_writable()
        atomic_json(self.root / "library.json", {"schema_version": 1,
                    "packages": list(self._packages if packages is None else packages),
                    "migrations": self._migrations if migrations is None else migrations})
        self._registry_present = True

    def create(self, name: str, *, template: KnowledgePackage | None = None, _legacy=False) -> KnowledgePackage:
        with self.lock:
            self.ensure_writable()
            embedding = template.embedding if template else EmbeddingSpec()
            if not _legacy and embedding.token_chunking() is None:
                embedding = replace(embedding, chunk_size_tokens=min(512,int(embedding.context_tokens)-64), chunk_overlap_tokens=50)
            package = KnowledgePackage(str(self._uuid()), str(name).strip(),
                                       embedding=embedding,
                                       retrieval=template.retrieval if template else RetrievalSettings(),
                                       usage=template.usage if template else UsageSettings())
            self._validate(package)
            self._write_package(package)
            self._write_registry(packages=(*self._packages, package.id))
            self._packages[package.id] = package
            return package

    def update(self, package: KnowledgePackage, *, expected_revision: int) -> KnowledgePackage:
        with self.lock:
            self.ensure_writable()
            current = self.get(package.id)
            if current.revision != expected_revision:
                raise PackageConflict("Knowledge package changed; reload before applying this edit.")
            changed = replace(package, name=package.name.strip(), revision=current.revision + 1,
                              retrieval=package.retrieval.normalized(), usage=package.usage.normalized())
            self._validate(changed)
            self._write_package(changed)
            self._packages[changed.id] = changed
            return changed

    def migrate_legacy(self, settings: Mapping, index: Mapping) -> str:
        # A lexical index cannot be semantic-ready. Keep it intact for inspection.
        with self.lock:
            self.ensure_writable()
            paths = {}
            for path in settings.get("files", ()):
                value = str(path or "").strip()
                if value:
                    paths.setdefault(path_key(value), value)
            retrieval = RetrievalSettings(**{key: settings[key] for key in RetrievalSettings.__dataclass_fields__ if key in settings}).normalized()
            fingerprint = hashlib.sha256(json.dumps([sorted(paths), asdict(retrieval)], sort_keys=True).encode()).hexdigest()
            if fingerprint in self._migrations:
                return self._migrations[fingerprint]
            name = "Default" if not self._migrations else f"Imported selection {len(self._migrations) + 1}"
            names = {p.name.casefold() for p in self._packages.values()}
            while name.casefold() in names:
                name += " (imported)"
            package = self.create(name, _legacy=True)
            package = self.update(replace(package, retrieval=retrieval,
                                  sources=tuple(SourceRecord(str(self._uuid()), p) for p in paths.values())),
                                  expected_revision=package.revision)
            migrations = {**self._migrations, fingerprint: package.id}
            self._write_registry(migrations=migrations)
            self._migrations = migrations
            return package.id
