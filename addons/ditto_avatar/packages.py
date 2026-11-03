"""Ditto validation around MuseTalk's shared lightweight package functions."""
import json
from pathlib import Path
import re
import shutil
import threading
import uuid
from contextlib import nullcontext

from .config import AVATAR_TUNING_KEYS, avatar_tuning, package_tuning

from addons.musetalk_avatar.avatar_packs import (
    MuseTalkAvatarPack, MuseTalkAvatarVariant, avatar_pack_engine,
    discover_avatar_packs, load_avatar_pack_manifest, save_avatar_pack_manifest)
from addons.musetalk_avatar.pack_runtime import normalize_enabled_pack_emotions

try:
    from .media_cache import validate_prepared_avatar
except ImportError:
    from media_cache import validate_prepared_avatar


# Serialize manifest read/modify/replace across Creator and runtime store instances.
_MANIFEST_LOCK = threading.RLock()


def valid_id(value):
    text = str(value or '')
    reserved = {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', text) or text.upper() in reserved:
        raise ValueError('Use a package/avatar ID of letters, numbers, underscores or hyphens; Windows device names are reserved.')
    return text


def effective_emotion_avatar_map(pack, config):
    mapping = pack.emotion_avatar_map()
    enabled = normalize_enabled_pack_emotions(config.get('ditto_enabled_pack_emotions')).get(pack.pack_id)
    return mapping if enabled is None else {tag: avatar for tag, avatar in mapping.items() if tag in enabled}


def enabled_variant_ids(pack, config):
    wanted = set(effective_emotion_avatar_map(pack, config).values()) | {pack.default_avatar_id}
    fixed = str(config.get('ditto_variant_id') or '')
    return tuple(key for key, variant in pack.variants.items() if variant.avatar_id in wanted or key == fixed)


class DittoPackageStore:
    def __init__(self, app_root):
        self.root = Path(app_root).resolve() / 'avatar_packs'

    def package_root(self, pack_id):
        name = valid_id(pack_id)
        if self.root.is_dir():
            for path in self.root.iterdir():
                if path.name.casefold() == name.casefold() and path.name != name:
                    raise ValueError(f'Package ID already exists as {path.name}; choose another ID.')
        target = (self.root / name).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError('Package path escaped avatar_packs.')
        return target

    def catalog(self):
        packs = discover_avatar_packs(default_avatar_id='', packs_dir=self.root,
            engine='ditto', include_legacy=False, include_standalone=False)
        result = []
        for pack_id in packs:
            try:
                pack = self.load(pack_id)
                from addons.musetalk_avatar.package_files import package_deletion_info
                try:
                    token = package_deletion_info(self.root, pack.manifest_path, pack_id, 'ditto')['token']
                except (ValueError, OSError):
                    token = ''
                result.append(dict(id=pack_id, display_name=pack.display_name, delete_token=token,
                    variant_count=len(pack.variants), draft=bool(pack.metadata.get('ditto_draft'))))
            except (ValueError, OSError, KeyError, TypeError):
                continue
        return result

    def load(self, pack_id):
        root = self.package_root(pack_id)
        raw = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if str(raw.get('avatar_engine') or 'musetalk').lower() != 'ditto':
            raise ValueError('This package belongs to another avatar engine.')
        if 'ditto_render_settings' in raw:
            package_tuning(raw['ditto_render_settings'])
        variants = raw.get('variants')
        if not isinstance(variants, dict):
            raise ValueError('Invalid package variants.')
        for key, value in variants.items():
            valid_id(key)
            if not isinstance(value, dict):
                raise ValueError('Invalid package avatar entry.')
            if 'ditto_render_settings' in value:
                avatar_tuning(value['ditto_render_settings'])
            name = value.get('avatar_path') or key
            if Path(name).is_absolute() or ':' in name or '\\' in name or '..' in Path(name).parts:
                raise ValueError('Package avatar paths must be relative and contained.')
            if not (root/name).resolve().is_relative_to(root):
                raise ValueError('Package avatar escaped its folder.')
        pack = load_avatar_pack_manifest(root / 'manifest.json')
        if raw.get('ditto_draft') and not variants:
            pack.variants.clear()
            pack.default_variant = ''
        elif raw.get('default_variant') not in variants or set(pack.variants) != set(variants):
            raise ValueError('Package references an invalid default or unresolved avatar.')
        return pack

    def save(self, pack, *, render_settings=None, variant_settings=None):
        with _MANIFEST_LOCK:
            return self._save(pack, render_settings=render_settings, variant_settings=variant_settings)

    def _save(self, pack, *, render_settings=None, variant_settings=None):
        root = self.package_root(pack.pack_id)
        if avatar_pack_engine(pack) != 'ditto':
            raise ValueError('Ditto packages require avatar_engine: ditto.')
        existing = root / 'manifest.json'
        old = {}
        if existing.is_file():
            old = json.loads(existing.read_text(encoding='utf-8'))
            if str(old.get('avatar_engine') or 'musetalk').lower() != 'ditto':
                raise ValueError('Package ID belongs to another engine; choose a new ID.')
        if pack.variants and pack.default_variant not in pack.variants:
            raise ValueError('Choose a default avatar in this package.')
        seen = {}
        for key, variant in pack.variants.items():
            valid_id(key)
            valid_id(variant.avatar_id)
            path = Path(variant.avatar_path).resolve()
            if not path.is_relative_to(root) or path == root:
                raise ValueError('Prepared avatars must live inside their package.')
            # Preserve an explicit portable path even for a not-yet-prepared draft.
            # The shared serializer otherwise elides conventional folder names.
            variant.metadata['avatar_path'] = path.relative_to(root).as_posix()
            for tag in variant.normalized_tags():
                if tag in seen and seen[tag] != key:
                    raise ValueError(f'Emotion {tag} is assigned to both {seen[tag]} and {key}.')
                seen[tag] = key
        # Preserve newer per-avatar profiles when Creator saves a stale package.
        for key, variant in pack.variants.items():
            old_variant = old.get('variants', {}).get(key, {})
            profile = old_variant.get('ditto_render_settings', variant.metadata.get('ditto_render_settings'))
            if variant_settings is not None and key in variant_settings:
                profile = variant_settings[key]
            if profile is not None:
                normalized = avatar_tuning(profile)
                # Partial imported profiles retain their package fallback.
                variant.metadata['ditto_render_settings'] = {
                    key:normalized[key] for key in profile if key in AVATAR_TUNING_KEYS}
        # A Creator may still hold an older package object while runtime tuning
        # is edited. Ordinary metadata saves must retain the latest disk profile.
        tuning = old.get('ditto_render_settings', pack.metadata.get('ditto_render_settings'))
        if render_settings is not None:
            tuning = {**(tuning or {}), **package_tuning(render_settings)}
        if tuning is not None:
            package_tuning(tuning)
            pack.metadata['ditto_render_settings'] = tuning
        return save_avatar_pack_manifest(pack, packs_dir=self.root)

    def save_tuning(self, pack_id, values):
        with _MANIFEST_LOCK:
            pack = self.load(pack_id)
            self.save(pack, render_settings=package_tuning(values))

    def save_variant_tuning(self, pack_id, variant_id, values):
        with _MANIFEST_LOCK:
            pack = self.load(pack_id)
            if variant_id not in pack.variants:
                raise ValueError('Choose an avatar from this package.')
            self.save(pack, variant_settings={variant_id:avatar_tuning(values)})

    def import_prepared(self, pack_id, variant_id, source, *, evidence, cancel_check=lambda: False, commit_lock=None):
        variant_id = valid_id(variant_id)
        pack = self.load(pack_id)
        destination = self.package_root(pack_id) / variant_id
        if destination.exists():
            raise ValueError('This avatar already has prepared data; choose a new avatar ID.')
        signature = evidence['portable_signature']
        checked = validate_prepared_avatar(source, portable_signature=signature,
            legacy_signature=evidence.get('legacy_signature'), canvas=pack.metadata.get('ditto_canvas'),
            compatible_signatures=evidence.get('compatible_signatures', ()),
            compatible_legacy_signatures=evidence.get('compatible_legacy_signatures', ()))
        if checked['legacy_validated'] and evidence.get('source_portable_signature') != signature:
            raise ValueError('Legacy source and destination model compatibility could not be established; prepare again.')
        source = checked['root']
        temporary = destination.with_name('.' + variant_id + '-import-' + uuid.uuid4().hex)
        published = False
        try:
            temporary.mkdir(parents=True)
            files = [source/name for name in checked['manifest']['frame_paths']]
            files += [p for p in (source/'features').rglob('*') if p.is_file() and p.suffix in ('.json','.npy')]
            for file in files:
                if cancel_check():
                    raise RuntimeError('Avatar import cancelled.')
                if not file.resolve().is_relative_to(source):
                    raise ValueError('Prepared payload escaped its source folder.')
                target = temporary / file.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
            manifest = {**checked['manifest'], 'schema_version':2, 'signature_kind':'content-v1',
                        'model_signature':signature}
            (temporary/'avatar.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            validate_prepared_avatar(temporary, portable_signature=signature, canvas=checked['canvas'])
            with commit_lock if commit_lock is not None else nullcontext():
                if cancel_check():
                    raise RuntimeError('Avatar import cancelled.')
                temporary.rename(destination)
                published = True
                variant = pack.variants.get(variant_id) or MuseTalkAvatarVariant(variant_id,variant_id)
                variant.avatar_path = str(destination)
                pack.variants[variant_id] = variant
                pack.default_variant = pack.default_variant or variant_id
                pack.metadata.update(ditto_canvas=list(checked['canvas']), ditto_draft=False)
                self.save(pack)
            return destination
        except BaseException:
            if published:
                shutil.rmtree(destination)
            raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
