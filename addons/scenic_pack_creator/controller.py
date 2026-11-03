"""Explicit worker commands; cached snapshots never scan the filesystem."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from urllib.parse import urlsplit
from urllib.request import url2pathname
from uuid import uuid4
from PIL import Image
from addons.scenic_avatar import pack_runtime as packs

class ScenicCreatorController:
    def __init__(self, context):
        self.context = context
        self.root = Path(context.paths.app_root).resolve() / 'ScenicPacks'
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._closed = False
        self._state = dict(available=True, selected='', name='', images=[], packs=[],
            folder_url=self.root.as_uri(), token='', revision=0, status='Choose or create a Scenic pack.', error='')

    def snapshot(self):
        with self._lock:
            return deepcopy(self._state)

    def close(self):
        with self._lock:
            self._closed = True
            self._state['available'] = False

    @staticmethod
    def _linked(path):
        return bool(path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)

    def _check_root(self):
        if self.root.exists() and self._linked(self.root):
            raise ValueError('ScenicPacks must be a local folder, not a link.')

    def _path(self, identifier):
        self._check_root()
        name = str(identifier or '')
        if not name or name != packs.sanitize_pack_id(name) or name.startswith('.'):
            raise ValueError('Choose a valid pack from the list.')
        path = self.root / name
        if path.resolve().parent != self.root.resolve() or (path.exists() and self._linked(path)):
            raise ValueError('Pack folders must stay inside ScenicPacks and cannot be links.')
        return path

    def _load(self, identifier):
        folder = self._path(identifier)
        pack = packs.load_pack(folder / packs.PACK_FILENAME)
        if pack is None:
            raise ValueError('The pack is missing or its manifest cannot be read. Refresh the list.')
        for entry in pack.images:
            if not entry.absolute_path(folder).is_relative_to(folder.resolve()):
                raise ValueError('An image points outside this pack; correct its manifest before editing.')
        return pack

    def _refresh(self, selected=None, status=''):
        self._check_root()
        self.root.mkdir(parents=True, exist_ok=True)
        rows = []
        for folder in sorted(self.root.iterdir(), key=lambda p:p.name.casefold()):
            if not folder.is_dir() or folder.name.startswith('.') or self._linked(folder):continue
            try:pack = self._load(folder.name)
            except (OSError, ValueError, TypeError, KeyError):continue
            image = pack.image_for_tag('neutral')
            path = image.absolute_path(folder) if image else None
            rows.append(dict(id=pack.pack_id, label=pack.pack_name, image_count=len(pack.images),
                tags=sorted(pack.tags()), preview_path=str(path) if path and path.is_file() else ''))
        selected = self._state['selected'] if selected is None else str(selected)
        if selected not in {row['id'] for row in rows}:selected = ''
        pack = self._load(selected) if selected else None
        token = self._fingerprint(pack) if pack else ''
        images = [dict(tag=item.tag, source=item.absolute_path(pack.root).as_uri() + '?revision=' + token,
            available=item.absolute_path(pack.root).is_file()) for item in pack.images] if pack else []
        with self._lock:
            self._state.update(selected=selected, name=pack.pack_name if pack else '', images=images, packs=rows,
                folder_url=(pack.root if pack else self.root).as_uri(), token=token, revision=self._state['revision']+1,
                status=status or 'Pack list refreshed.', error='')

    @staticmethod
    def _fingerprint(pack):
        digest = hashlib.sha256(pack.json_path.read_bytes())
        for entry in pack.images:
            path = entry.absolute_path(pack.root)
            try:
                info = path.stat()
                facts = (entry.image_path, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            except FileNotFoundError:
                facts = (entry.image_path, 'missing')
            digest.update(repr(facts).encode('utf-8'))
        return digest.hexdigest()

    def _editable(self):
        for name in ('runtime_status', 'engine_lifecycle'):
            capability = getattr(self.context.capabilities, name, None)
            state = capability.snapshot() if capability is not None else {}
            if any(state.get(key) for key in ('engine_connected', 'system_running', 'running',
                    'starting', 'stopping', 'initializing', 'cancelling', 'cleanup_pending')):
                raise ValueError('Stop the chat engine before editing Scenic packs.')

    @staticmethod
    def _tag(value):
        tag = packs.normalize_tag(value)
        reserved = {'con','prn','aux','nul',*(f'com{i}' for i in range(1,10)),*(f'lpt{i}' for i in range(1,10))}
        if not tag or tag in reserved:
            raise ValueError('Enter a tag using letters, numbers, underscores or hyphens; Windows device names are not supported.')
        return tag

    def _cleanup(self, path):
        if path.parent.resolve() != self.root.resolve() or not path.name.startswith('.') or self._linked(path):
            raise ValueError('Temporary pack path is not safe to remove.')
        shutil.rmtree(path)

    def _edit(self, pack, operation, changed_tags, token):
        staging = self.root / ('.edit-'+uuid4().hex)
        previous = self.root / ('.previous-'+uuid4().hex)
        original = pack.json_path.read_bytes()
        for directory, dirs, files in os.walk(pack.root, followlinks=False):
            for name in dirs+files:
                if self._linked(Path(directory)/name):raise ValueError('Linked files cannot be edited inside a Scenic pack.')
        moved = False
        try:
            shutil.copytree(pack.root, staging)
            draft = replace(pack, root=staging, json_path=staging/packs.PACK_FILENAME)
            updated = operation(draft)
            # An untouched tag must keep its original image even if an edit
            # overwrote a shared filename or moved/deleted its old path.
            changed_paths = {item.absolute_path(staging) for item in updated.images
                             if item.tag in changed_tags}
            originals = {item.tag: item for item in pack.images}
            protected = []
            for item in updated.images:
                old = originals.get(item.tag)
                if item.tag not in changed_tags and old is not None:
                    source = old.absolute_path(pack.root)
                    target = item.absolute_path(staging)
                    if source.is_file() and target in changed_paths:
                        target = staging / 'images' / ('shared-' + uuid4().hex + source.suffix)
                        item = replace(item, image_path=target.relative_to(staging).as_posix())
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                    elif source.is_file() and not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                protected.append(item)
            updated = replace(updated, images=tuple(protected))
            packs.save_pack(updated)
            raw = json.loads(updated.json_path.read_text(encoding='utf-8'))
            raw = {**json.loads(original), **raw}
            updated.json_path.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
            if self._closed:raise ValueError('Scenic Pack Creator is closing.')
            if self._fingerprint(pack) != token:raise ValueError('This pack changed elsewhere. Refresh before editing.')
            self._editable()
            pack.root.rename(previous);moved = True
            try:staging.rename(pack.root)
            except BaseException:
                previous.rename(pack.root);moved = False;raise
            moved = False
            self._cleanup(previous)
        finally:
            if staging.exists():self._cleanup(staging)
            if moved and previous.exists() and not pack.root.exists():previous.rename(pack.root)

    def command(self, action, payload=None):
        data = dict(payload or {})
        if not self._operation.acquire(blocking=False):
            return dict(ok=False,error='Wait for the current pack operation to finish.',state=self.snapshot())
        try:
            if self._closed:raise ValueError('Scenic Pack Creator is closed.')
            selected = self.snapshot()['selected']
            if action == 'refresh':self._refresh(status='Pack list refreshed.')
            elif action == 'select':
                self._load(str(data.get('pack_id') or ''));self._refresh(data['pack_id'],'Pack opened for editing.')
            else:
                self._editable()
                if action == 'create':
                    name = str(data.get('name') or '').strip()
                    if not name:raise ValueError('Enter a name for the new pack.')
                    identity = packs.sanitize_pack_id(name)
                    final = self._path(identity)
                    self.root.mkdir(parents=True,exist_ok=True)
                    if any(p.name.casefold()==identity.casefold() for p in self.root.iterdir()):
                        raise ValueError('A pack with that name already exists. Open it or choose another name.')
                    temporary = self.root/('.create-'+uuid4().hex)
                    try:
                        pack = packs.create_pack(name,packs_dir=temporary)
                        if self._closed:raise ValueError('Scenic Pack Creator is closing.')
                        self._editable()
                        pack.root.rename(final)
                    finally:
                        if temporary.exists():self._cleanup(temporary)
                    self._refresh(identity,'Created pack. Add images and tags below.')
                else:
                    if data.get('pack_id', selected) != selected:
                        raise ValueError('The selected pack changed. Review the current pack before editing.')
                    pack = self._load(selected)
                    token = str(data.get('token') or '')
                    if not token or self._fingerprint(pack) != token:
                        raise ValueError('This pack changed or the edit is out of date. Refresh before editing.')
                    if action == 'add_image':
                        tag = self._tag(data.get('tag'))
                        if tag in pack.tags() and data.get('confirmed') is not True:
                            raise ValueError('This tag already exists. Confirm replacing its image first.')
                        value = str(data.get('source_path') or '')
                        if value.startswith('file:'):
                            url = urlsplit(value);value = url2pathname(('//'+url.netloc if url.netloc else '')+url.path)
                        source = Path(value)
                        if not value or not source.is_file() or source.suffix.lower() not in packs.IMAGE_EXTENSIONS:
                            raise ValueError('Choose a PNG, JPG, WEBP or BMP image.')
                        with Image.open(source) as image:image.verify()
                        self._edit(pack,lambda draft:packs.add_image(draft,source,tag), {tag}, token)
                    elif action == 'rename_tag':
                        tag,new = self._tag(data.get('tag')),self._tag(data.get('new_tag'))
                        self._edit(pack,lambda draft:packs.update_tag(draft,tag,new,replace_existing=data.get('confirmed') is True), {tag, new}, token)
                    elif action == 'remove_image':
                        tag = self._tag(data.get('tag'))
                        if data.get('confirmed') is not True:raise ValueError('Confirm removing this image from the pack.')
                        if tag not in pack.tags():raise ValueError('Select an image first.')
                        self._edit(pack,lambda draft:packs.remove_tag(draft,tag), {tag}, token)
                    elif action == 'save':
                        name = str(data.get('name') or '').strip()
                        if not name:raise ValueError('Enter a display name for the pack.')
                        def save(draft):
                            draft = replace(draft,pack_name=name);packs.save_pack(draft);return draft
                        self._edit(pack,save, set(), token)
                    else:raise ValueError('Unknown Scenic creator action.')
                    self._refresh(selected,'Saved pack changes.')
            return dict(ok=True,state=self.snapshot())
        except (OSError, ValueError, TypeError, KeyError) as error:
            with self._lock:self._state['error']=str(error)
            return dict(ok=False,error=str(error),state=self.snapshot())
        finally:self._operation.release()
