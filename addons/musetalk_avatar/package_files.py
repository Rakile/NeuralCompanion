"""Permanent removal of one verified, directly managed avatar package folder."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from .avatar_packs import sanitize_pack_token, load_avatar_pack_manifest


def _is_link(path):
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def package_deletion_info(packs_root, manifest_path, pack_id, engine):
    root = Path(os.path.abspath(packs_root))
    manifest = Path(os.path.abspath(manifest_path))
    target = manifest.parent
    if manifest.name != 'manifest.json' or target.parent != root or target == root:
        raise ValueError('Only a directly managed avatar package can be deleted.')
    if not root.is_dir() or not target.is_dir() or any(_is_link(p) for p in (root, target, manifest)):
        raise ValueError('Linked or redirected package folders cannot be deleted.')
    resolved_root, resolved_target = root.resolve(), target.resolve()
    if resolved_target.parent != resolved_root:
        raise ValueError('Package folder escaped the managed avatar_packs directory.')
    data = manifest.read_bytes()
    raw = json.loads(data)
    identity = sanitize_pack_token(raw.get('id') or target.name, target.name)
    if not pack_id or identity != pack_id or str(raw.get('avatar_engine') or 'musetalk').strip().lower() != engine:
        raise ValueError('The selected package identity or avatar engine changed.')
    info = target.stat()
    token = hashlib.sha256(data + str((str(resolved_target), info.st_dev, info.st_ino)).encode()).hexdigest()
    return {'pack_id':pack_id, 'display_name':str(raw.get('display_name') or pack_id),
            'token':token, 'directory':str(resolved_target)}


def delete_package_files(packs_root, manifest_path, pack_id, engine, token):
    info = package_deletion_info(packs_root, manifest_path, pack_id, engine)
    if not token or token != info['token']:
        raise ValueError('Package changed since confirmation. Review it and try again.')
    target = Path(info['directory'])
    # Inspect before removing anything. Never traverse a Windows junction or symlink.
    def scan_error(error):
        raise error
    for directory, folders, files in os.walk(target, followlinks=False, onerror=scan_error):
        for name in folders + files:
            if _is_link(Path(directory) / name):
                raise ValueError('Package contains linked or redirected files; deletion was blocked.')
    for other in Path(packs_root).absolute().iterdir():
        if other == target or not other.is_dir():
            continue
        manifest = other / 'manifest.json'
        if not manifest.is_file():
            continue
        # Use the same whitespace/implicit local-path resolution as playback.
        pack = load_avatar_pack_manifest(manifest)
        for variant in pack.variants.values():
            if variant.avatar_path and Path(variant.avatar_path).resolve().is_relative_to(target):
                raise ValueError('Another avatar package references files in this package. Remove that reference first.')
    # Recheck the confirmed identity after the potentially long tree scan.
    if package_deletion_info(packs_root, manifest_path, pack_id, engine)['token'] != token:
        raise ValueError('Package changed during deletion checks; nothing was removed.')
    shutil.rmtree(target)
    return info
