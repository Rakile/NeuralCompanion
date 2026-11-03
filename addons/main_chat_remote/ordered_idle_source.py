"""Desktop-authored idle ranges from its selected prepared avatar inventory.

No cache file, playback cursor, media encoder, inference or model is opened here.
The existing pack readers resolve variant identity; only confined prepared PNGs
are exposed over the private Desktop/backend bridge.
"""
import hashlib
import json
from pathlib import Path
import re

from addons.musetalk_avatar.avatar_packs import load_avatar_pack_manifest, build_implicit_avatar_pack, build_standalone_avatar_pack
from .idle_loop_catalog import _confined
from .dev_musetalk_live import idle_frames


class OrderedIdleSource:
    def __init__(self, runtime_root, selection):
        self.root = Path(runtime_root).resolve(strict=True)
        self.selection = selection
        self.roots = (self.root / 'avatar_packs', self.root / 'MuseTalk/results/v15/avatar_packs',
                      self.root / 'MuseTalk/results/v15/avatars')
        self._key = None; self._sources = {}; self._avatars = {}

    def _path(self, path):
        try: return _confined(path, self.roots)
        except (OSError, ValueError): raise ValueError('ordered_idle_source_path') from None

    def _inventory(self, config):
        selected, default = config.get('musetalk_avatar_pack_id', ''), config.get('musetalk_avatar_id', 'default_avatar')
        if (not isinstance(selected, str) or selected and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', selected)
                or not isinstance(default, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', default)):
            raise ValueError('ordered_idle_selection')
        if not selected or selected == 'single__' + default:
            self._path(self.roots[2] / default)
            pack = build_standalone_avatar_pack(default, avatars_dir=self.roots[2])
        else:
            folder = next((r / selected for r in self.roots[:2] if (r / selected).is_dir()), None)
            if folder is None: raise ValueError('ordered_idle_pack_unavailable')
            folder = self._path(folder)
            manifest = folder / 'manifest.json'
            if manifest.is_file():
                self._path(manifest)
                if manifest.stat().st_size > 256*1024: raise ValueError('ordered_idle_manifest_size')
                raw = json.loads(manifest.read_text('utf-8'))
                variants = raw.get('variants')
                if type(variants) is not dict or not 1 <= len(variants) <= 128: raise ValueError('ordered_idle_inventory')
                for key, variant in variants.items():
                    if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key)
                            or type(variant) is not dict): raise ValueError('ordered_idle_inventory')
                    path = variant.get('avatar_path')
                    if path:
                        if not isinstance(path, str): raise ValueError('ordered_idle_source_path')
                        self._path(folder / path)
                pack = load_avatar_pack_manifest(manifest, avatars_dir=self.roots[2])
            else:
                children = tuple(folder.iterdir())
                if len(children) > 256: raise ValueError('ordered_idle_inventory')
                for child in children:
                    if child.is_dir() or child.is_symlink(): self._path(child)
                pack = build_implicit_avatar_pack(folder)
        if pack is None or not 1 <= len(pack.variants) <= 128: raise ValueError('ordered_idle_inventory')
        sources, avatars = {}, {}
        for variant in pack.variants.values():
            directory = self._path((Path(variant.avatar_path) if variant.avatar_path else self.roots[2] / variant.avatar_id) / 'full_imgs')
            motion = hashlib.sha256(str(directory).encode()).hexdigest()
            if variant.avatar_id in avatars and avatars[variant.avatar_id] != motion:
                raise ValueError('ordered_idle_avatar_ambiguous')
            avatars[variant.avatar_id] = motion
            sources[motion] = directory
        return sources, avatars

    def plan(self, frontier):
        if frontier.reply_id is not None: raise ValueError('ordered_idle_during_reply')
        selection = self.selection()
        if type(selection) is not dict or type(selection.get('config')) is not dict: raise ValueError('ordered_idle_selection')
        config = selection['config']
        key = (config.get('musetalk_avatar_pack_id', ''), config.get('musetalk_avatar_id', 'default_avatar'))
        if key != self._key:
            sources, avatars = self._inventory(config)
            self._key, self._sources, self._avatars = key, sources, avatars
        last = frontier.last_frame
        motion = last.source_id if last is not None else self._avatars.get(selection.get('current_avatar'))
        directory = self._sources.get(motion)
        if directory is None: raise ValueError('ordered_idle_motion_unknown')
        frames = idle_frames(self._path(directory))
        if last is not None and last.source_frame_count != len(frames): raise ValueError('ordered_idle_source_changed')
        start = (last.frame + 1) % len(frames) if last is not None else 0
        indices = [(start + i) % len(frames) for i in range(12)]
        identity = hashlib.sha256(json.dumps([frontier.stream_id, frontier.generation,
            frontier.next_ordinal, motion, indices], separators=(',', ':')).encode()).hexdigest()[:32]
        return dict(kind='idle', sourceId='idle-' + identity, mediaId=identity, samples=24000,
            replyId=None, sequenceIndex=None, wav=None,
            frames=[dict(path=str(frames[i]), provenance=dict(sourceId=motion, frame=i,
                         sourceFrameCount=len(frames))) for i in indices])
