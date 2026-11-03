"""Verify the reviewed PocketTTS wheel using only the Python standard library."""
from __future__ import annotations

import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


_PROJECT = "pocket-tts"
_VERSION = "3.3.0"
_WHEEL = "pocket_tts-3.3.0-py3-none-any.whl"
_DIST = "pocket_tts-3.3.0.dist-info/"
_ORIGIN = {
    "project": _PROJECT,
    "version": _VERSION,
    "upstream_repository": "https://github.com/kyutai-labs/pocket-tts",
    "upstream_commit": "b94db177bc0f77517d9b124843e25605d6f9aed8",
    "source_archive_sha256": "ea05521f39364a8fb1292ec149e4d56708cbdfcb250ff6831a7dc5c9bf50581c",
}


def _relative_name(name):
    if not isinstance(name, str) or not name:
        raise ValueError("empty file path")
    path = PurePosixPath(name)
    if (path.is_absolute() or "\\" in name or ":" in name or ".." in path.parts
            or str(path) != name or name == "."):
        raise ValueError(f"unsafe file path: {name}")
    return name


def _local_file(root, name):
    _relative_name(name)
    path = root / name
    current = root
    for part in PurePosixPath(name).parts:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"redirected bundle path: {name}")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f"not a local bundle file: {name}")
    return path


def _checked_file(root, entry, expected_name):
    if entry["filename"] != expected_name:
        raise ValueError(f"unexpected bundle filename: {entry['filename']}")
    if type(entry["size"]) is not int or entry["size"] <= 0:
        raise ValueError(f"invalid bundle size: {expected_name}")
    if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
        raise ValueError(f"invalid bundle SHA256: {expected_name}")
    path = _local_file(root, "vendor/pockettts/" + entry["filename"])
    data = path.read_bytes()
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"size or SHA256 mismatch: {expected_name}")
    return path, data


def _header(message, name, expected):
    if message.get_all(name, []) != [expected]:
        raise ValueError(f"unexpected wheel {name}; expected {expected}")


def _verify_wheel(data, license_data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = []
        seen = set()
        for info in archive.infolist():
            name = _relative_name(info.filename.rstrip("/") if info.is_dir() else info.filename)
            if name.casefold() in seen:
                raise ValueError(f"duplicate wheel member: {name}")
            seen.add(name.casefold())
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"redirected wheel member: {name}")
            if not info.is_dir():
                names.append(name)

        metadata = BytesParser().parsebytes(archive.read(_DIST + "METADATA"))
        _header(metadata, "Name", _PROJECT)
        _header(metadata, "Version", _VERSION)
        _header(metadata, "Requires-Python", "<3.15,>=3.10")
        _header(metadata, "License-File", "LICENSE")
        wheel = BytesParser().parsebytes(archive.read(_DIST + "WHEEL"))
        _header(wheel, "Wheel-Version", "1.0")
        _header(wheel, "Root-Is-Purelib", "true")
        _header(wheel, "Tag", "py3-none-any")
        if archive.read(_DIST + "licenses/LICENSE") != license_data:
            raise ValueError("wheel MIT license does not match the distributed LICENSE")
        # Upstream's MIT notice has no title; preserve and verify its exact bytes.
        if hashlib.sha256(license_data).hexdigest() != "23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3":
            raise ValueError("distributed LICENSE is not the expected MIT license")

        record_name = _DIST + "RECORD"
        rows = csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"), newline=""))
        recorded = set()
        for row in rows:
            if len(row) != 3:
                raise ValueError("malformed wheel RECORD row")
            name, digest, size = row
            _relative_name(name)
            if name in recorded or name not in names:
                raise ValueError(f"duplicate or absent RECORD member: {name}")
            recorded.add(name)
            if name == record_name:
                if digest or size:
                    raise ValueError("wheel RECORD must not hash itself")
                continue
            contents = archive.read(name)
            expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).decode("ascii").rstrip("=")
            if digest != expected or size != str(len(contents)):
                raise ValueError(f"wheel RECORD integrity mismatch: {name}")
        if recorded != set(names):
            raise ValueError("wheel RECORD does not cover every file")


def verify_pockettts_bundle(repo_root):
    """Return verified bundle metadata and ``wheel_path``; never mutate or download.

    A damaged or incomplete distribution must be repaired from the same NC
    release. Neither pip nor a moving upstream source is a repair fallback.
    """
    try:
        root = Path(repo_root).resolve()
        manifest_path = _local_file(root, "vendor/pockettts/manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
            raise ValueError("unsupported manifest schema_version")
        for key, expected in _ORIGIN.items():
            if manifest[key] != expected:
                raise ValueError(f"unexpected snapshot {key}")
        wheel_path, wheel_data = _checked_file(root, manifest["wheel"], _WHEEL)
        _, license_data = _checked_file(root, manifest["license"], "LICENSE")
        _verify_wheel(wheel_data, license_data)
        return {**manifest, "wheel_path": wheel_path.resolve()}
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, csv.Error) as exc:
        raise ValueError(
            f"PocketTTS bundle verification failed: {exc}. "
            "Restore vendor/pockettts from the same Neural Companion release and retry; "
            "no online PocketTTS fallback is used."
        ) from exc
