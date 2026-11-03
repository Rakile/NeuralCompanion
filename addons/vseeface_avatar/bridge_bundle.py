"""Offline, dependency-free verification of the distributed VSeeFace bridge."""
from pathlib import Path
import hashlib
import json

SUPPORTED_ASSEMBLIES = {
    '1.13.38c4': '5a24888245967b07a5884a8bd40059e33ff3141608177e7bd4f5c26df67838fe',
    '1.13.38c5': 'bfe25e23fad5647c2da46a1c995a235f97c5bfdb4f9c6ed9a921ab1ef75d4150',
}
LOADER_SHA256 = '41a089e5b1b1f0713b331346baf6677b1184c69eabebf51101097954e854c749'
LOADER_NAME = 'BepInEx_win_x64_5.4.23.3.zip'
PAYLOAD_PATHS = {'NCVSeeFaceBridge.dll', LOADER_NAME, 'THIRD_PARTY_NOTICES.md',
                 'third_party_source/UnityDoorstop-851712b.zip',
                 *('licenses/'+name+'.txt' for name in ('BepInEx','BepInEx.Harmony','UnityDoorstop','HarmonyX','Mono.Cecil','MonoMod'))}


def digest(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_child(root: Path, relative: str) -> Path:
    relative = str(relative).replace('\\', '/')
    path = Path(relative)
    if not relative or path.is_absolute() or ':' in relative or '..' in path.parts:
        raise ValueError('Unsafe bridge inventory path: '+relative)
    base = root.resolve()
    target = (base/path).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ValueError('Bridge inventory escapes its directory: '+relative)
    # Do not follow junctions/symlinks into another tree, even for an owned path.
    for part in (base/path).parents:
        if part == base: break
        if part.is_symlink() or (part.exists() and part.resolve() != part.absolute()):
            raise ValueError('Linked bridge destination is unsupported: '+relative)
    if (base/path).is_symlink():
        raise ValueError('Linked bridge file is unsupported: '+relative)
    return target


def verify_bridge_bundle(app_root: Path) -> dict:
    addon = Path(app_root)/'addons/vseeface_avatar'
    payload, source = addon/'bridge_payload', addon/'bridge_source'
    data = json.loads((payload/'manifest.json').read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or data.get('protocol_version') != 1:
        raise ValueError('Unsupported bridge package manifest')
    if data.get('supported_assemblies') != SUPPORTED_ASSEMBLIES:
        raise ValueError('Bridge supported assembly inventory changed')
    files, sources = data.get('files', {}), data.get('source_files', {})
    if not isinstance(files, dict) or not isinstance(sources, dict):
        raise ValueError('Invalid bridge manifest file/source inventories')
    if set(files) != PAYLOAD_PATHS or not {'BridgePlugin.cs', 'Build-Bridge.ps1', 'README.md', 'StatusHeartbeat.cs'}.issubset(sources):
        raise ValueError('Bridge package is missing required payload/source/notices')
    if files.get(LOADER_NAME) != LOADER_SHA256:
        raise ValueError('The pinned BepInEx loader digest changed')
    for base, inventory in ((payload, files), (source, sources)):
        if not isinstance(inventory, dict) or not inventory:
            raise ValueError('Invalid bridge file inventory')
        for relative, expected in inventory.items():
            path = safe_child(base, relative)
            if digest(path) != expected:
                raise ValueError('Bridge package checksum mismatch: '+relative)
        for path in base.rglob('*'):
            if not path.is_file() or 'build' in path.relative_to(base).parts:
                continue
            relative = path.relative_to(base).as_posix()
            if relative in {'manifest.json', '.gitignore'}: continue
            if relative not in inventory:
                raise ValueError('Unlisted bridge package file: '+relative)
            if path.name.lower() in {'assembly-csharp.dll', 'assembly-csharp-firstpass.dll', 'vrm.dll', 'vseeface.exe'}:
                raise ValueError('VSeeFace files cannot be redistributed: '+relative)
    return data
