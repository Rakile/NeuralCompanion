"""Read-only identity and ownership checks for managed avatar variant folders."""
import hashlib
import json
import os
from pathlib import Path

from .avatar_packs import load_avatar_pack_manifest, sanitize_pack_token
from .package_files import _is_link, package_deletion_info


def variant_file_info(packs_root, manifest_path, pack_id, variant_id, engine):
    info=package_deletion_info(packs_root,manifest_path,pack_id,engine)
    manifest=Path(os.path.abspath(manifest_path))
    raw=json.loads(manifest.read_text(encoding='utf-8'))
    variants=raw.get('variants') or {}
    if not variant_id or variant_id not in variants:
        raise ValueError('This avatar no longer belongs to the selected package.')
    variant=variants[variant_id]
    if not isinstance(variant,dict):
        raise ValueError('Invalid avatar entry.')
    value=str(variant.get('avatar_path') or '').strip()
    if value:
        target=Path(value)
        if not target.is_absolute():
            target=manifest.parent/target
    else:
        names=(variant_id,sanitize_pack_token(variant.get('avatar_id') or variant_id,variant_id))
        target=next((manifest.parent/name for name in names if (manifest.parent/name).is_dir()),manifest.parent/variant_id)
    target=Path(os.path.abspath(target))
    if target.parent != manifest.parent or target.resolve().parent != manifest.parent.resolve():
        raise ValueError('Only the selected avatar managed folder can be changed; external source files are preserved.')
    exists=target.exists()
    if target.is_symlink() or (exists and (_is_link(target) or not target.is_dir())):
        raise ValueError('Linked or redirected avatar folders cannot be changed.')
    identity=(target.stat().st_dev,target.stat().st_ino) if exists else None
    token=hashlib.sha256((info['token']+'\0'+variant_id+'\0'+str(identity)).encode()).hexdigest()
    return {'pack_id':pack_id,'variant_id':variant_id,'token':token,'directory':str(target),'exists':exists}


def checked_variant_files(packs_root,manifest_path,pack_id,variant_id,engine,token):
    info=variant_file_info(packs_root,manifest_path,pack_id,variant_id,engine)
    if not token or token != info['token']:
        raise ValueError('Avatar or package changed. Review the selected emotion and try again.')
    target=Path(info['directory'])
    def scan_error(error):
        raise error
    if target.exists():
        for directory,folders,files in os.walk(target,followlinks=False,onerror=scan_error):
            for name in folders+files:
                if _is_link(Path(directory)/name):
                    raise ValueError('Avatar contains linked or redirected files; no files were changed.')
    selected_manifest=Path(manifest_path).resolve()
    for folder in Path(packs_root).absolute().iterdir():
        other=folder/'manifest.json'
        if not other.is_file():
            continue
        pack=load_avatar_pack_manifest(other)
        for key,variant in pack.variants.items():
            if other.resolve() == selected_manifest and key == variant_id:
                continue
            if variant.avatar_path:
                reference=Path(variant.avatar_path).resolve()
                if reference.is_relative_to(target) or target.is_relative_to(reference):
                    raise ValueError('This avatar folder is shared or referenced by another avatar. Change that reference first.')
    if variant_file_info(packs_root,manifest_path,pack_id,variant_id,engine)['token'] != token:
        raise ValueError('Avatar changed during the file checks; no files were changed.')
    return target
