"""Package-first Creator jobs over the existing Ditto service and worker."""
from copy import deepcopy
from pathlib import Path
import shutil
import threading
import uuid
import time

from addons.musetalk_avatar.avatar_packs import MuseTalkAvatarPack, MuseTalkAvatarVariant, sanitize_pack_token
from addons.ditto_avatar.packages import DittoPackageStore, valid_id
from addons.ditto_avatar.media_cache import validate_prepared_avatar
from addons.ditto_avatar.config import AVATAR_TUNING_KEYS, package_tuning, prepare_settings
from addons.ditto_avatar.emotions import native_emotion


from .emotion_management import EmotionManagement


class CreatorPackageController(EmotionManagement):
    def __init__(self, service):
        self.service = service
        self.store = DittoPackageStore(service.app_root)
        self.pack = None
        self.selected_variant = ''
        self._thread = None
        self._fields = dict(ditto_package_name='', ditto_variant_name='', ditto_variant_tags='', ditto_variant_default=False,
                            ditto_import_path='')
        self._catalog_cache = (0, [])
        self._wizard_source = ''
        self._wizard_emotion = ''
        self._wizard_draft = False
        self._crop_preview = None
        self._replacement = None

    def wizard_snapshot(self):
        variant = self.pack.variants.get(self.selected_variant) if self.pack else None
        prepared = bool(variant and (Path(variant.avatar_path)/'avatar.json').is_file())
        # Only advertise preparation of the newly chosen source after it succeeds.
        if self._replacement or (self._wizard_source and not self._wizard_draft):
            prepared = False
        still = ''
        if prepared:
            import json
            manifest = json.loads((Path(variant.avatar_path)/'avatar.json').read_text(encoding='utf-8'))
            frames = manifest.get('frame_paths', [])
            if frames:
                still = str(Path(variant.avatar_path)/frames[0])
        pending = [key for key,v in self.pack.variants.items() if not (Path(v.avatar_path)/'avatar.json').is_file()] if self.pack else []
        return dict(step=3 if prepared else 2 if self._wizard_source or (variant and self._wizard_draft) else 1,
                    source=self._wizard_source, name=self._fields['ditto_package_name'],
                    crop_preview=self.crop_snapshot(),
                    emotion=self._wizard_emotion, prepared=prepared, still_path=still,
                    replacement=bool(self._replacement),
                    can_remove_variant=bool(variant and len(self.pack.variants) > 1),
                    pending_variants=pending,
                    selected_for_chat=bool(prepared and self.service.settings().get('ditto_pack_id') == self.pack.pack_id))

    def _crop_context(self):
        cfg = self.service.settings()
        source = Path(cfg['ditto_source_path']).expanduser().resolve()
        if not cfg['ditto_source_path'] or not source.exists():
            raise ValueError('Choose source media before previewing its crop.')
        first = source
        if source.is_dir():
            from addons.ditto_avatar.media_cache import numeric_pngs
            first = numeric_pngs(source)[0]
        stat = first.stat()
        canvas = self.pack.metadata.get('ditto_canvas') if self.pack else None
        return (str(source), str(first), stat.st_mtime_ns, stat.st_size,
                cfg['ditto_max_size'], tuple(canvas) if canvas else None,
                self.pack.pack_id if self.pack else '', self.selected_variant)

    def crop_snapshot(self):
        with self.service._lock:
            if not self._crop_preview:
                return {}
            try:
                if self._crop_preview['context'] != self._crop_context():
                    return {}
            except (OSError, ValueError):
                return {}
            from addons.ditto_avatar.crop_geometry import crop_outline
            cfg = self.service.settings()
            result = self._crop_preview['result']
            return dict(preview_path=result['preview_path'], width=result['width'], height=result['height'],
                points=crop_outline(result['basis'], cfg['ditto_crop_scale'], cfg['ditto_crop_x'],
                                    cfg['ditto_crop_y'], cfg['ditto_crop_rotate']))

    def preview_crop(self):
        self._editable()
        with self.service._lock:
            context = self._crop_context()
            options = prepare_settings(self.service.settings())
            options['canvas'] = list(context[5]) if context[5] else None
        def analyze(cancelled):
            client = self.service.client()
            try:
                result = client.request('crop_preview', source_path=context[0],
                    prepare_options=options, cancel_check=cancelled)
            finally:
                with self.service._lock:
                    if not cancelled() and self.service._client is client:
                        # A no-face/stale result can still leave face models
                        # resident. Keep Unload available independently of UI data.
                        self.service._crop_models_loaded = True
            with self.service._lock:
                if cancelled():
                    return {}
                if context != self._crop_context():
                    self.service.status = 'Source settings changed. Click Preview crop again.'
                    return {}
                # Validate geometry before publishing it to QML.
                from addons.ditto_avatar.crop_geometry import crop_outline
                crop_outline(result['basis'], 1., 0., 0., True)
                self._crop_preview = {'context':context, 'result':result}
                self.service.status = 'Crop preview ready for the first frame. Adjust the crop controls, then prepare.'
            return {'crop_preview': True}
        return self._start('Detecting face for crop preview…', analyze)

    def choose_media(self, path, *, emotion=''):
        self._editable()
        if self.service.session_running:
            raise RuntimeError('Stop chat or the current preview before choosing new media.')
        source = Path(path).expanduser()
        if not source.is_file() or source.suffix.lower() not in (
                '.png','.jpg','.jpeg','.webp','.bmp','.mp4','.mov','.mkv','.avi','.webm'):
            raise ValueError('Choose one image or video file (PNG, JPG, WebP, MP4, MOV, MKV, AVI or WebM).')
        tag = str(emotion or '').strip().lower()
        if tag and (not self.pack or not self.pack.default_variant_config
                    or not (Path(self.pack.default_variant_config.avatar_path)/'avatar.json').is_file()):
            raise ValueError('Prepare your first avatar before adding an emotion.')
        self.service.update('ditto_source_path', str(source.resolve()))
        self.service._fps_choice = None
        self.service._creator_preview_url = ''
        self._wizard_source, self._wizard_emotion, self._wizard_draft = str(source.resolve()), tag, False
        if not tag:
            self.pack, self.selected_variant = None, ''
            self._fields['ditto_package_name'] = source.stem
        self.service.status = 'Media selected. Click Prepare avatar to continue.'
        return {'ok': True}

    def guided_prepare(self):
        self._editable()
        if self._replacement:
            return self.prepare_replacement()
        if not self._wizard_source:
            raise ValueError('Drop an image or video first.')
        if not self._wizard_draft:
            if not self._wizard_emotion:
                name = self._fields['ditto_package_name'].strip() or Path(self._wizard_source).stem
                self._create_unique_package(name)
            tag = self._wizard_emotion or 'neutral'
            stem = sanitize_pack_token(tag, 'avatar')[:64]
            try:
                valid_id(stem)
            except ValueError:
                stem = 'avatar_'+stem
            identifier, number = stem, 1
            # Removed entries retain their prepared files. Never overwrite them,
            # or confuse different custom labels that sanitize to the same ID.
            while ((identifier in self.pack.variants and tag not in self.pack.variants[identifier].normalized_tags())
                   or (identifier not in self.pack.variants and (self.store.package_root(self.pack.pack_id)/identifier).exists())):
                number += 1
                identifier = f'{stem}_{number}'
            existing = self.pack.variants.get(identifier)
            if existing and (Path(existing.avatar_path)/'avatar.json').is_file():
                raise ValueError('This emotion already has an avatar. Choose a different emotion.')
            self.save_variant(identifier, tag.title(), [tag], make_default=not self._wizard_emotion)
            self._wizard_draft = True
        self.pack.variants[self.selected_variant].metadata['ditto_source_media'] = self._wizard_source
        self.store.save(self.pack)
        return self.action('prepare_variant')

    def _create_unique_package(self, name):
        token = sanitize_pack_token(name,'Avatar').strip('-_')[:70] or 'Avatar'
        try:
            valid_id(token)
        except ValueError:
            token = 'Ditto_'+token[:64]
        existing = {p.name.casefold() for p in self.store.root.iterdir()} if self.store.root.is_dir() else set()
        candidate, number = token, 1
        while candidate.casefold() in existing:
            number += 1
            candidate = f'{token}_{number}'
        self.create_package(name if number == 1 else f'{name} {number}', identifier=candidate)

    def _restore_wizard(self):
        self._replacement = None
        self._wizard_source, self._wizard_emotion, self._wizard_draft = '', '', False
        self.service._fps_choice = None
        variant = self.pack.variants.get(self.selected_variant) if self.pack else None
        if variant and not (Path(variant.avatar_path)/'avatar.json').is_file():
            self._wizard_draft = True
            self._wizard_source = str(variant.metadata.get('ditto_source_media') or '')
            if self.selected_variant != self.pack.default_variant:
                self._wizard_emotion = next(iter(variant.normalized_tags()), self.selected_variant)
            if self._wizard_source:
                self.service.update('ditto_source_path', self._wizard_source)

    def _editable(self):
        if self.service.busy or getattr(self.service,'_test_preview_active',False):
            raise RuntimeError('Wait for the current Ditto operation to finish, or cancel it.')
        if (self.service.session_running and not getattr(self.service,'_test_preview_active',False)
                and self.pack and self.pack.pack_id == self.service.settings().get('ditto_pack_id')):
            raise RuntimeError('Unload Ditto before editing its active package.')

    def snapshot(self):
        with self.service._lock:
            pack = self.pack
            variants = [] if pack is None else [dict(id=key, display_name=v.display_name or key,
                tags=v.normalized_tags(), prepared=(Path(v.avatar_path)/'avatar.json').is_file(),
                default=key == pack.default_variant) for key, v in pack.variants.items()]
            root = self.store.package_root(pack.pack_id) if pack else self.store.root
            if time.monotonic()-self._catalog_cache[0] > 2:
                self._catalog_cache = (time.monotonic(), self.store.catalog())
            return dict(packages=self._catalog_cache[1], emotion_entries=self.emotion_entries(), selected_package=pack.pack_id if pack else '',
                variants=variants, selected_variant=self.selected_variant,
                destination=str(root/self.selected_variant) if self.selected_variant else str(root),
                preparation_status=self.service.status,
                native_emotion_map=dict(pack.metadata.get('ditto_emotion_map', {})) if pack else {},
                emotion_tags=sorted(pack.emotion_avatar_map()) if pack else [],
                ditto_creator_pack=pack.pack_id if pack else '', ditto_creator_variant=self.selected_variant,
                render_settings={key:value for key,value in self.service.settings_for_variant(
                    pack.pack_id, self.selected_variant).items() if key in AVATAR_TUNING_KEYS}
                    if pack and self.selected_variant in pack.variants else {},
                wizard=self.wizard_snapshot(), **self._fields)

    def select_package(self, pack_id):
        self._editable()
        self.pack = self.store.load(pack_id)
        self._fields['ditto_package_name'] = self.pack.display_name
        self.selected_variant = self.pack.default_variant
        self.service._creator_preview_url = ''
        self._restore_wizard()
        self._select_fields()
        return self.snapshot()

    def select_variant(self, variant_id):
        self._editable()
        if self.pack is None or variant_id not in self.pack.variants:
            raise ValueError('Choose an avatar from this package.')
        self.selected_variant = variant_id
        self.service._creator_preview_url = ''
        self._restore_wizard()
        self._select_fields()
        return self.snapshot()

    def _select_fields(self):
        variant = self.pack.variants.get(self.selected_variant) if self.pack else None
        self._fields.update(ditto_variant_name=variant.display_name or variant.variant_id if variant else '',
            ditto_variant_tags=', '.join(variant.normalized_tags()) if variant else '',
            ditto_variant_default=bool(variant and self.selected_variant == self.pack.default_variant))

    def update(self, key, value):
        if key in AVATAR_TUNING_KEYS:
            if not self.pack or self.selected_variant not in self.pack.variants:
                raise ValueError('Select an avatar to preview before editing its settings.')
            result = self.service.update_variant_tuning(self.pack.pack_id, self.selected_variant, key, value)
            self.pack = self.store.load(self.pack.pack_id)
            return result
        self._editable()
        if key == 'ditto_creator_pack':
            return self.select_package(str(value))
        if key == 'ditto_creator_variant':
            return self.select_variant(str(value))
        if key in self._fields:
            self._fields[key] = bool(value) if key == 'ditto_variant_default' else str(value or '')
        elif key.startswith('ditto_map_') and self.pack:
            tag = key.removeprefix('ditto_map_')
            pack = deepcopy(self.pack)
            mapping = pack.metadata.setdefault('ditto_emotion_map', {})
            target = native_emotion(value)
            if target is None:
                mapping.pop(tag, None)
            else:
                mapping[tag] = target
            self.store.save(pack)
            self.pack = pack
            self.service._package_state_cache = None
        else:
            raise KeyError(key)
        return {'ok': True}

    def create_package(self, name, *, identifier=None):
        self._editable()
        display = str(name or '').strip()
        if not display:
            raise ValueError('Give the package a name.')
        identifier = valid_id(identifier or sanitize_pack_token(display, 'Ditto'))
        if self.store.package_root(identifier).exists():
            raise ValueError('That package ID already exists; select it or choose another name.')
        cfg = self.service.settings()
        tuning = package_tuning(cfg)
        if not cfg.get('ditto_pack_id'):
            # Preserve the Creator's first-use automatic emotion-avatar behavior.
            tuning['ditto_avatar_selection'] = 'From reply emotion'
        pack = MuseTalkAvatarPack(identifier, display, '', {},
            metadata={'avatar_engine':'ditto', 'ditto_draft':True, 'ditto_emotion_map':{},
                      'ditto_render_settings':tuning})
        self.store.save(pack)
        self._catalog_cache = (0, [])
        self.pack, self.selected_variant = pack, ''
        self._fields['ditto_package_name'] = display
        self._select_fields()
        return self.snapshot()

    def save_variant(self, variant_id, display_name, tags, *, make_default):
        self._editable()
        if self.pack is None:
            raise ValueError('Create or select a package first.')
        identifier = valid_id(variant_id)
        pack = deepcopy(self.pack)
        variant = pack.variants.get(identifier) or MuseTalkAvatarVariant(identifier, identifier)
        variant.display_name = str(display_name or identifier).strip()
        variant.tags = list(tags)
        variant.avatar_path = str(self.store.package_root(pack.pack_id)/identifier)
        pack.variants[identifier] = variant
        if make_default or not pack.default_variant:
            pack.default_variant = identifier
        self.store.save(pack)
        self._catalog_cache = (0, [])
        self.pack, self.selected_variant = pack, identifier
        self._select_fields()
        return self.snapshot()

    def save_package(self):
        self._editable()
        if self.pack is None:
            raise ValueError('Create or select a package first.')
        pack = deepcopy(self.pack)
        pack.display_name = self._fields['ditto_package_name'].strip() or pack.pack_id
        for tag, target in pack.metadata.get('ditto_emotion_map', {}).items():
            if not str(tag).strip() or native_emotion(target) is None:
                raise ValueError('Map reply tags to one of Ditto\'s eight named emotions.')
        self.store.save(pack)
        self._catalog_cache = (0, [])
        self.pack = pack
        return {'ok': True, 'manifest_path':str(self.store.package_root(pack.pack_id)/'manifest.json')}

    def remove_variant(self, payload):
        self._editable()
        if self.service.session_running:
            raise RuntimeError('Stop chat or the current preview before removing an avatar.')
        payload = payload or {}
        if (not self.pack or payload.get('package_id') != self.pack.pack_id
                or payload.get('variant_id') != self.selected_variant
                or self.selected_variant not in self.pack.variants):
            raise ValueError('Avatar selection changed. Select the avatar and confirm removal again.')
        if len(self.pack.variants) < 2:
            raise ValueError('A package must keep at least one avatar.')
        pack = deepcopy(self.pack)
        removed = pack.variants.pop(self.selected_variant)
        prepared = [key for key,v in pack.variants.items() if (Path(v.avatar_path)/'avatar.json').is_file()]
        cfg = self.service.settings()
        if cfg['ditto_pack_id'] == pack.pack_id and not prepared:
            raise ValueError('Prepare another avatar before removing this package\'s last prepared avatar.')
        replacement = prepared[0] if prepared else next(iter(pack.variants))
        if pack.default_variant == self.selected_variant:
            pack.default_variant = replacement
        for tag in removed.normalized_tags():
            pack.metadata.get('ditto_emotion_map', {}).pop(tag, None)
        self.store.save(pack)
        if cfg['ditto_pack_id'] == pack.pack_id and cfg['ditto_variant_id'] == self.selected_variant:
            self.service.update('ditto_variant_id',pack.default_variant)
        self.pack = pack
        self._catalog_cache = (0, [])
        self.service._package_state_cache = None
        self.select_variant(pack.default_variant)
        self.service.status = 'Avatar removed from package. Prepared files and original media have been kept.'
        return {'ok':True}

    def action(self, action, payload=None):
        if action == 'delete_variant':
            return self.delete_variant(payload)
        if action == 'make_base':
            return self.make_base(payload)
        if action in ('replace_variant','redo_variant'):
            return self.begin_replacement(payload,redo=action=='redo_variant')
        if action == 'cancel_replacement':
            self._editable()
            self._restore_wizard()
            self.service.status='Replacement cancelled. Your previous avatar is unchanged.'
            return {'ok':True}
        if action == 'preview_crop':
            return self.preview_crop()
        if action == 'remove_variant':
            return self.remove_variant(payload)
        if action == 'back_to_media':
            self._editable()
            if self.service.session_running:
                raise RuntimeError('Stop chat or the current preview before returning to media selection.')
            # Leave saved packages and unfinished variants available to reopen.
            self.pack, self.selected_variant = None, ''
            self._fields['ditto_package_name'] = ''
            self.service._creator_preview_url = ''
            self._restore_wizard()
            self._select_fields()
            self.service.status = 'Choose an image or video. Your saved avatars have been kept.'
            return {'ok':True}
        if action == 'discard_emotion':
            self._editable()
            if self._wizard_emotion and self._wizard_source and not self._wizard_draft:
                self._restore_wizard()
                self.service.status = 'Emotion media choice cancelled. Your avatar is unchanged.'
                return {'ok':True}
            variant = self.pack.variants.get(self.selected_variant) if self.pack else None
            if not variant or self.selected_variant == self.pack.default_variant or (Path(variant.avatar_path)/'avatar.json').is_file():
                raise ValueError('Only an unfinished optional emotion can be discarded.')
            pack = deepcopy(self.pack)
            del pack.variants[self.selected_variant]
            self.store.save(pack)
            self.pack = pack
            self.select_variant(pack.default_variant)
            self.service.status = 'Unfinished emotion discarded. Your original avatar is ready.'
            return {'ok':True}
        if action == 'guided_import':
            self._editable()
            if self.service.session_running:
                raise RuntimeError('Stop chat before importing an avatar.')
            source = Path(self._fields['ditto_import_path'])
            if not (source/'avatar.json').is_file():
                raise ValueError('Choose a prepared avatar folder containing avatar.json.')
            self._create_unique_package(source.name)
            self.service._fps_choice = None
            self._wizard_source, self._wizard_emotion, self._wizard_draft = '', '', False
            self.service._creator_preview_url = ''
            self.save_variant('neutral','Neutral',['neutral'],make_default=True)
            return self.add_prepared(source,'neutral')
        if action == 'choose_media':
            payload = payload or {}
            return self.choose_media(payload.get('path',''), emotion=payload.get('emotion',''))
        if action == 'guided_prepare':
            return self.guided_prepare()
        if action == 'create_package':
            return self.create_package(self._fields['ditto_package_name'])
        if action == 'new_variant':
            self._editable()
            self.selected_variant = ''
            self._select_fields()
            return {'ok':True}
        if action == 'save_variant':
            name = self._fields['ditto_variant_name'].strip()
            if not name:
                raise ValueError('Give this avatar a name.')
            identifier = self.selected_variant or valid_id(sanitize_pack_token(name, 'avatar'))
            return self.save_variant(identifier, name, self._fields['ditto_variant_tags'].split(','),
                                     make_default=self._fields['ditto_variant_default'])
        if action == 'save_package':
            return self.save_package()
        if action == 'use_package':
            return self.activate()
        if action == 'test_render':
            self._editable()
            if self.service.session_running and not getattr(self.service,'_test_preview_active',False):
                raise RuntimeError('Stop chat and unload Ditto before a Creator preview test.')
            if self.pack is None:
                return self.service.action('test_render', payload)
            if self.selected_variant not in self.pack.variants:
                raise ValueError('Choose a prepared package avatar first.')
            from addons.ditto_avatar.emotions import bind_chunk_choice
            cfg = {**self.service.settings_for_package(self.pack.pack_id), 'ditto_pack_id':self.pack.pack_id, 'ditto_variant_id':self.selected_variant,
                   'ditto_avatar_selection':'Fixed'}
            choice = bind_chunk_choice(cfg,self.store.load(self.pack.pack_id),cfg['ditto_test_emotion'],active_avatar_id=None,last_queued_avatar_id=None)
            if not (Path(choice.avatar_path)/'avatar.json').is_file():
                raise ValueError('Prepare the selected test avatar first.')
            return self.service.action('test_render', {'choice':choice, 'package_id':self.pack.pack_id})
        if action == 'import_prepared':
            if not self._fields['ditto_import_path']:
                raise ValueError('Choose a prepared avatar to import.')
            identifier = self.selected_variant or valid_id(sanitize_pack_token(self._fields['ditto_variant_name'], 'avatar'))
            return self.add_prepared(self._fields['ditto_import_path'], identifier)
        if action in ('prepare_variant', 'prepare_convert', 'prepare_keep'):
            policy = {'prepare_variant':'ask','prepare_convert':'convert','prepare_keep':'keep'}[action]
            source = self.service.settings()['ditto_source_path']
            if not source:
                raise ValueError('Choose an image, video or PNG frame folder.')
            if policy != 'ask':
                choice = self.service._fps_choice
                if not choice or (choice['source_path'], choice['package_id'], choice['variant_id']) != (source,self.pack.pack_id,self.selected_variant):
                    raise ValueError('Source or selected avatar changed. Check its frame rate again.')
            self.service._fps_choice = None
            return self.prepare_replacement(video_fps_policy=policy) if self._replacement else self.prepare_variant(source,self.selected_variant,video_fps_policy=policy)
        if action == 'prepare_cancel':
            self.service._fps_choice = None
            return {'ok':True}
        raise KeyError(action)

    def _start(self, title, callback):
        self._editable()
        if self.service.session_running and not getattr(self.service,'_test_preview_active',False):
            raise RuntimeError('Stop chat and unload Ditto before preparing or importing package avatars.')
        if not self.service._operation.acquire(blocking=False):
            raise RuntimeError('Another Ditto operation is running.')
        generation = self.service._generation
        cancelled = lambda: generation != self.service._generation
        self.service.busy, self.service.status = True, title
        self.service.changes.notify()
        def run():
            try:
                result = callback(cancelled)
                if not cancelled():
                    self.service.last_result = result or {}
            except Exception as error:
                if not cancelled():
                    self.service.status = f'Ditto Creator failed: {error}'
            finally:
                self.service.busy = False
                self.service._operation.release()
                self.service.changes.notify()
        self._thread = threading.Thread(target=run, name='ditto-package-job', daemon=True)
        self._thread.start()
        return {'ok': True, 'started': True}

    def prepare_variant(self, source, variant_id, *, video_fps_policy='ask'):
        if self.pack is None or variant_id not in self.pack.variants:
            raise ValueError('Add/select an avatar in this package first.')
        pack = deepcopy(self.pack)
        final = self.store.package_root(pack.pack_id)/valid_id(variant_id)
        if final.exists():
            raise ValueError('This avatar is already prepared; add a new avatar for different source media.')
        pending = final.with_name('.'+variant_id+'-prepare-'+uuid.uuid4().hex)
        options = prepare_settings(self.service.settings())
        options.update(canvas=pack.metadata.get('ditto_canvas'), video_fps_policy=video_fps_policy)
        def prepare(cancelled):
            published = False
            try:
                client = self.service.client()
                result = client.request('prepare', source_path=str(source), output_dir=str(pending),
                    prepare_options=options, cancel_check=cancelled)
                if result.get('needs_fps_choice'):
                    if not cancelled():
                        from addons.ditto_avatar.service import fps_choice_message
                        message = fps_choice_message(result)
                        self.service._fps_choice = {**result, 'source_path':str(source),
                            'package_id':pack.pack_id, 'variant_id':variant_id,'message':message}
                        self.service.status = message
                    return result
                evidence = client.request('cache_signature', cancel_check=cancelled)
                checked = validate_prepared_avatar(pending, portable_signature=evidence['portable_signature'],
                                                   canvas=pack.metadata.get('ditto_canvas'))
                with self.service._lock:
                    if cancelled():
                        raise RuntimeError('Preparation cancelled.')
                    pending.rename(final)
                    published = True
                    pack.variants[variant_id].avatar_path = str(final)
                    pack.metadata.update(ditto_canvas=list(checked['canvas']), ditto_draft=False)
                    self.store.save(pack)
                    self.pack = pack
                    self.service.loaded = True
                    self.service.status = f'Prepared {pack.variants[variant_id].display_name or variant_id} in {pack.display_name}.'
                return {**result, 'avatar_path':str(final)}
            except BaseException:
                if published:
                    shutil.rmtree(final)
                raise
            finally:
                for path in [pending, *pending.parent.glob(pending.name+'.preparing-*')]:
                    if path.exists():
                        shutil.rmtree(path)
        return self._start('Preparing package avatar…', prepare)

    def add_prepared(self, source, variant_id):
        if self.pack is None:
            raise ValueError('Create or select a package first.')
        pack_id = self.pack.pack_id
        variant_id = valid_id(variant_id)
        def import_avatar(cancelled):
            evidence = self.service.client().request('cache_signature', cancel_check=cancelled)
            target = self.store.import_prepared(pack_id, variant_id, Path(source), evidence=evidence,
                                               cancel_check=cancelled, commit_lock=self.service._lock)
            with self.service._lock:
                if not cancelled():
                    self.pack, self.selected_variant = self.store.load(pack_id), variant_id
                    self._select_fields()
                    self.service.status = 'Prepared avatar copied into the package; original preserved.'
            return dict(avatar_path=str(target))
        return self._start('Importing prepared avatar…', import_avatar)

    def activate(self):
        self._editable()
        if self.service.session_running:
            raise RuntimeError('Unload Ditto before changing the active package.')
        if self.pack is None or not self.pack.variants or not self.pack.default_variant_config:
            raise ValueError('Prepare a default avatar first.')
        for variant in self.pack.variants.values():
            if not (Path(variant.avatar_path)/'avatar.json').is_file():
                raise ValueError(f'Prepare {variant.display_name or variant.variant_id} before using the package.')
        cfg = self.service.settings()
        if (not cfg.get('ditto_pack_id') and
                'ditto_render_settings' not in self.store.load(self.pack.pack_id).metadata):
            self.service.update('ditto_avatar_selection', 'From reply emotion')
        self.service.update('ditto_pack_id', self.pack.pack_id)
        self.service.update('ditto_variant_id', self.selected_variant or self.pack.default_variant)
        self.service.update('ditto_avatar_path', self.pack.default_variant_config.avatar_path)
        config = getattr(self.service, '_config', None)
        if config is not None:
            config.update('avatar_mode', 'ditto')
        self.service.status = f'{self.pack.display_name} selected for Ditto chat.'
        return {'ok': True}
