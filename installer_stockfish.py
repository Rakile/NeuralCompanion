"""Install the pinned official Windows Stockfish archive on explicit request.

Every upstream file is retained beside the canonical ``stockfish.exe``. The
download callback is supplied by the caller. No engine is executed during
installation. Legacy app-relative destinations remain supported.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import sys
import tempfile
import zipfile

from addons.companion_chess.engine_paths import bundled_stockfish_path


@dataclass(frozen=True)
class StockfishRelease:
    url: str
    sha256: str
    size: int
    executable: str


STOCKFISH_VERSION = "19"
STOCKFISH_RELEASES = {
    "x86_64": StockfishRelease(
        "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-windows-x86-64-universal.zip",
        "3c8bf1f9ea66a09350a40df4f632288285ac206d99f33ab5842c408fc30b48a7",
        81431614,
        "stockfish-windows-x86-64-universal.exe",
    ),
    "arm64": StockfishRelease(
        "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-windows-arm64-universal.zip",
        "8372ad3f0d7276deb2c70f801f541ec7db463219fc6d9c7592864e542aa4f401",
        80190536,
        "stockfish-windows-arm64-universal.exe",
    ),
}
_MANIFEST = "nc-stockfish.json"
_OWNER = "NeuralCompanion Stockfish bundle"


def _release(machine: str | None) -> tuple[str, StockfishRelease]:
    if sys.platform != "win32":
        raise ValueError("Stockfish installation supports Windows only; select an existing engine on this platform.")
    selected = (machine or platform.machine()).strip().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(selected)
    if arch is None:
        raise ValueError(f"Unsupported Stockfish machine architecture {selected!r}; configure a compatible local engine path.")
    return arch, STOCKFISH_RELEASES[arch]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    """Detect Windows junctions on Python 3.11 as well as ordinary symlinks."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _require_contained(app_root: Path, *paths: Path) -> None:
    root = app_root.resolve()
    for path in paths:
        resolved = path.resolve()
        if resolved == root or not resolved.is_relative_to(root):
            raise ValueError(f"Stockfish path resolves outside the intended app root: {path}")


def _safe_parts(name: str) -> tuple[str, ...]:
    parts = PurePosixPath(name).parts
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if (not parts or PurePosixPath(name).is_absolute() or "\\" in name
            or any(part in {".", ".."} or part.endswith((".", " "))
                   or any(char in part for char in ':<>"|?*\x00')
                   or part.split(".", 1)[0].upper() in reserved for part in parts)):
        raise ValueError(f"Stockfish archive contains an unsafe path: {name!r}")
    return parts


def _owned_manifest(bundle: Path) -> dict:
    if _is_reparse_point(bundle) or not bundle.is_dir():
        raise ValueError(f"Stockfish destination is not an owned directory: {bundle}")
    try:
        manifest_path = bundle / _MANIFEST
        if _is_reparse_point(manifest_path):
            raise ValueError("linked bundle manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest["files"]
        directories = manifest["directories"]
        if manifest.get("owner") != _OWNER or manifest.get("schema_version") != 1 or not isinstance(files, dict) or not files:
            raise ValueError("unrecognized manifest")
        if not isinstance(directories, list):
            raise ValueError("invalid directory manifest")
        for name in directories:
            _safe_parts(name)
        for name, entry in files.items():
            _safe_parts(name)
            if name == _MANIFEST or not isinstance(entry, dict) or not isinstance(entry.get("size"), int) or not isinstance(entry.get("sha256"), str):
                raise ValueError("invalid file manifest")
        pending = [bundle]
        while pending:
            for path in pending.pop().iterdir():
                if _is_reparse_point(path):
                    raise ValueError("linked bundle content")
                if path.is_file() and path.relative_to(bundle).as_posix() not in {*files, _MANIFEST}:
                    raise ValueError("unknown bundle content")
                if path.is_dir():
                    if path.relative_to(bundle).as_posix() not in directories:
                        raise ValueError("unknown bundle directory")
                    pending.append(path)
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Stockfish destination has unknown or unrecognized content; preserve it and choose another location: {bundle}") from exc


def _installation_paths(app_root: Path, destination: Path | None) -> tuple[Path, Path]:
    if destination is None:
        return Path(app_root).resolve(), bundled_stockfish_path(Path(app_root))
    bundle = Path(destination)
    if not bundle.is_absolute():
        raise ValueError('Choose an absolute Stockfish installation folder.')
    # Keep the final component unresolved so links/reparse points are rejected.
    return bundle.parent.resolve(), bundle / 'stockfish.exe'


def validate_stockfish_bundle(app_root: Path, *, machine: str | None = None,
                             destination: Path | None = None) -> bool:
    """Return whether the owned bundle matches its pinned release and file hashes."""
    arch, release = _release(machine)
    root, executable = _installation_paths(app_root, destination)
    bundle = executable.parent
    try:
        _require_contained(root, bundle)
        if _is_reparse_point(bundle.parent):
            return False
        manifest = _owned_manifest(bundle)
        if manifest.get("architecture") != arch or manifest.get("archive_sha256") != release.sha256 or manifest.get("version") != STOCKFISH_VERSION:
            return False
        if not {"stockfish.exe", "Copying.txt", "README.md", "src/main.cpp"}.issubset(manifest["files"]):
            return False
        for name, entry in manifest["files"].items():
            path = bundle.joinpath(*_safe_parts(name))
            if not path.is_file() or path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
                return False
        return True
    except (OSError, ValueError):
        return False


def _check_destination(app_root: Path, bundle: Path) -> None:
    if _is_reparse_point(bundle.parent):
        raise ValueError(f"Stockfish tools destination must not be a link: {bundle.parent}")
    if _is_reparse_point(bundle):
        raise ValueError(f"Stockfish destination must not be a link or reparse point: {bundle}")
    _require_contained(app_root, bundle)
    if bundle.exists():
        _owned_manifest(bundle)


def install_stockfish_archive(app_root: Path, archive_path: Path, *, machine: str | None = None,
                              destination: Path | None = None) -> Path:
    """Verify a pinned ZIP and stage/replace only an NC-owned bundle.

    Use this entry point for an already downloaded archive; validation always
    happens again before extraction. Existing bundles survive invalid archives
    and extraction errors. Unknown destination content is never overwritten.
    """
    arch, release = _release(machine)
    archive_path = Path(archive_path)
    if archive_path.stat().st_size != release.size:
        raise ValueError("Stockfish archive size differs from the pinned official release; download it again.")
    if _sha256(archive_path) != release.sha256:
        raise ValueError("Stockfish archive SHA256 differs from the pinned official release; download it again.")
    resolved_root, executable = _installation_paths(app_root, destination)
    bundle = executable.parent
    _check_destination(resolved_root, bundle)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nc-stockfish-", dir=bundle.parent) as temp_dir:
        staging = Path(temp_dir) / "bundle"
        staging.mkdir()
        files: dict[str, dict[str, int | str]] = {}
        with zipfile.ZipFile(archive_path) as archive:
            members: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
            seen: set[str] = set()
            for info in archive.infolist():
                parts = _safe_parts(info.orig_filename)
                key = "/".join(parts).casefold()
                mode = info.external_attr >> 16
                if key in seen or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}) or parts[0] != "stockfish":
                    raise ValueError(f"Stockfish archive contains a duplicate, linked or unexpected path: {info.filename}")
                seen.add(key)
                members.append((info, parts))
            for info, parts in members:
                relative = parts[1:]
                if not relative:
                    if not info.is_dir():
                        raise ValueError("Stockfish archive root is not a directory.")
                    continue
                if relative == (release.executable,):
                    relative = ("stockfish.exe",)
                path = staging.joinpath(*relative)
                if info.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                if path.exists() or path.name == _MANIFEST:
                    raise ValueError(f"Stockfish archive path conflicts with another file: {info.filename}")
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target)
                files[path.relative_to(staging).as_posix()] = {"size": path.stat().st_size, "sha256": _sha256(path)}
        if not {"stockfish.exe", "Copying.txt", "README.md", "src/main.cpp"}.issubset(files):
            raise ValueError("Stockfish archive is missing its engine, Copying.txt license, README.md or src/main.cpp source.")
        manifest = {"schema_version": 1, "owner": _OWNER, "version": STOCKFISH_VERSION,
                    "architecture": arch, "archive_url": release.url, "archive_sha256": release.sha256,
                    "files": files, "directories": sorted(path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_dir())}
        (staging / _MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        _check_destination(resolved_root, bundle)
        previous = Path(temp_dir) / "previous"
        _require_contained(resolved_root, bundle, staging, previous)
        if bundle.exists():
            bundle.rename(previous)
        try:
            _require_contained(resolved_root, staging, bundle, previous)
            staging.rename(bundle)
        except (OSError, ValueError):
            if previous.exists():
                _require_contained(resolved_root, previous, bundle)
                previous.rename(bundle)
            raise
    return executable


def ensure_stockfish(app_root: Path, download_file: Callable[[str, Path], None], *, machine: str | None = None,
                     destination: Path | None = None) -> Path:
    """Reuse an intact portable bundle or fetch and install the pinned release."""
    _, release = _release(machine)
    root, executable = _installation_paths(app_root, destination)
    if validate_stockfish_bundle(app_root, machine=machine, destination=destination):
        return executable
    _check_destination(root, executable.parent)
    with tempfile.TemporaryDirectory(prefix="nc-stockfish-download-") as temp_dir:
        archive = Path(temp_dir) / "stockfish.zip"
        download_file(release.url, archive)
        return install_stockfish_archive(app_root, archive, machine=machine, destination=destination)
