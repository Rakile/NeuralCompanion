"""Pinned MuseTalk file integrity and staged, per-file atomic publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


MANIFEST_PATH = Path(__file__).with_name("musetalk-model-manifest.json")


def _relative_name(name):
    if not isinstance(name, str) or not name:
        raise ValueError("MuseTalk inventory needs a relative file path.")
    relative = PurePosixPath(name)
    if relative.is_absolute() or "\\" in name or ":" in name or ".." in relative.parts:
        raise ValueError(f"Invalid MuseTalk inventory path: {name}")
    if str(relative) != name or name == ".":
        raise ValueError(f"Invalid MuseTalk inventory path: {name}")
    return name


def _inventory_entries(inventory):
    entries = []
    paths = set()
    for item in inventory["files"]:
        name = _relative_name(item["path"])
        _relative_name(item["filename"])
        if name.casefold() in paths:
            raise ValueError(f"Duplicate MuseTalk inventory path: {name}")
        paths.add(name.casefold())
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", item["repo_id"]):
            raise ValueError(f"Invalid MuseTalk repository: {name}")
        if not re.fullmatch(r"[0-9a-f]{40}", item["revision"]):
            raise ValueError(f"MuseTalk inventory requires an immutable revision: {name}")
        if type(item["size"]) is not int or item["size"] <= 0:
            raise ValueError(f"Invalid MuseTalk inventory size: {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError(f"Invalid MuseTalk inventory checksum: {name}")
        entries.append(item)
    if not entries:
        raise ValueError("MuseTalk inventory must not be empty.")
    return entries


def _is_alias(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _target(root, name):
    name = _relative_name(name)
    path = root / name
    parent = root
    for part in PurePosixPath(name).parts[:-1]:
        parent = parent / part
        if _is_alias(parent) or not parent.resolve().is_relative_to(root):
            raise ValueError(f"MuseTalk destination has a redirected parent: {name}")
    if path.is_dir():
        raise ValueError(f"MuseTalk file destination is a directory: {name}")
    return path


def _matches(path, item):
    try:
        info = path.stat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_size != item["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest() == item["sha256"]


def ensure_musetalk_models(root, *, download_files, inventory=None):
    """Verify all required files before publishing any staged repair.

    Explicit model-root aliases and valid leaf cache links are supported. Parent
    redirects beneath that root are refused; replacing a bad leaf link replaces
    the link itself. Publication is atomic per file, not a multi-file transaction.
    """
    if inventory is None:
        inventory = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = _inventory_entries(inventory)
    root = Path(root).resolve()
    repairs = []
    report = {"reused": 0, "downloaded": 0}
    for item in entries:
        target = _target(root, item["path"])
        if _matches(target, item):
            report["reused"] += 1
        else:
            repairs.append(item)
    if not repairs:
        return report

    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".musetalk-download-", dir=root) as directory:
        stage = Path(directory)
        jobs = [{"repo_id": item["repo_id"], "revision": item["revision"],
                 "filename": item["filename"], "local_dir": str(stage / str(index))}
                for index, item in enumerate(repairs)]
        download_files(jobs)
        staged = []
        for index, item in enumerate(repairs):
            path = _target(stage, f"{index}/{item['filename']}")
            if _is_alias(path) or not _matches(path, item):
                raise ValueError(f"MuseTalk staged file failed integrity verification: {item['path']}; previous files preserved.")
            staged.append(path)
        # All downloads passed verification before touching any existing file.
        for item, path in zip(repairs, staged):
            target = _target(root, item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target = _target(root, item["path"])
            path.replace(target)
            report["downloaded"] += 1
    return report
