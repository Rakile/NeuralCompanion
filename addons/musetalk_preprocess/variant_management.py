"""Managed per-entry operations for the MuseTalk creator (no GPU imports)."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4
from addons.musetalk_avatar.variant_files import variant_file_info, checked_variant_files
from addons.musetalk_avatar.avatar_packs import load_avatar_pack_manifest

class MuseTalkVariantManagement:
    def _variant_entries(self):
        pack_id = str(self._state['musetalk_preprocess_target_pack_id'])
        if pack_id in ('', '__standalone__', 'stand_alone'):
            return []
        # Ordinary managed packages have a known manifest. Do not add another
        # complete catalog scan to every snapshot/poll. Imported packages with
        # differing folder/manifest IDs retain the discovery fallback.
        try:
            manifest = self._pack_root(pack_id) / 'manifest.json'
            pack = load_avatar_pack_manifest(manifest) if manifest.is_file() else None
        except (OSError, ValueError, TypeError, AttributeError):
            pack = None
        if pack is None or pack.pack_id != pack_id:
            pack = self._pack_catalog().get(pack_id)
        if pack is None or not pack.manifest_path:
            return []
        entries = []
        revision = int(getattr(self._job_local, 'selection_revision', self._selection_revision))
        for key, variant in pack.variants.items():
            folder = Path(variant.avatar_path)
            prepared = self._variant_prepared(folder)
            source = self._variant_source(variant, folder)
            identity,reason=self._variant_identity(pack,key,variant)
            identity.update(selection_revision=revision, display_name=variant.display_name or key)
            base = key == pack.default_variant
            files = sorted((folder/'full_imgs').glob('*')) if (folder/'full_imgs').is_dir() else []
            entries.append(dict(id=key, display_name=variant.display_name or key,
                tags=list(variant.normalized_tags()), base=base, prepared=prepared,
                thumbnail=files[0].resolve().as_uri() if files else '', identity=identity,
                canRedo=bool(not reason and source and source.exists()),
                canReplace=not bool(reason),
                canDelete=bool(not reason and not base and len(pack.variants)>1),
                redoHelp=reason or ('' if source and source.exists() else 'Saved source is unavailable. Use Replace source.'),
                deleteHelp=reason or ('Choose another prepared entry as base first.' if base else 'Permanently deletes this entry’s managed files. Original source media is kept.')))
        return entries

    @staticmethod
    def _variant_prepared(folder):
        return (folder/'avator_info.json').is_file() and any(path.is_file() for path in (folder/'full_imgs').glob('*'))

    @staticmethod
    def _variant_identity(pack,key,variant):
        manifest=Path(pack.manifest_path)
        try:
            return variant_file_info(manifest.parent.parent,manifest,pack.pack_id,key,'musetalk'),''
        except (ValueError,OSError) as error:
            # A legacy external entry remains readable and may be selected as base;
            # the fallback identity never authorizes file replacement or deletion.
            identity=hashlib.sha256(manifest.read_bytes()+key.encode('utf-8')).hexdigest()
            return {'pack_id':pack.pack_id,'variant_id':key,'token':'read-'+identity,
                    'directory':str(variant.avatar_path)},str(error)

    @staticmethod
    def _variant_source(variant, folder):
        value = str(variant.metadata.get('source_path') or '').strip()
        if not value:
            for name in ('avatar_pose.json','avator_info.json'):
                try:
                    raw=json.loads((folder/name).read_text(encoding='utf-8'))
                    value=str(raw.get('source_path') or raw.get('video_path') or '').strip()
                    if value: break
                except (OSError, ValueError): pass
        return Path(value) if value else None

    @staticmethod
    def _write_variant_manifest(path, payload):
        temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2),encoding='utf-8')
            os.replace(temporary,path)
        finally:
            temporary.unlink(missing_ok=True)

    def _variant_target(self, payload, *, managed=True):
        if not isinstance(payload, dict): raise ValueError('Choose an avatar entry first.')
        revision=int(getattr(self._job_local,'selection_revision',self._selection_revision))
        if int(payload.get('selection_revision',-1)) != revision:
            raise RuntimeError('Avatar selection changed. Review the selected entry again.')
        pack_id=str(payload.get('pack_id') or '')
        if pack_id != self._state['musetalk_preprocess_target_pack_id']:
            raise RuntimeError('Avatar package selection changed.')
        pack=self._pack_catalog().get(pack_id)
        key=str(payload.get('variant_id') or '')
        if pack is None or key not in pack.variants: raise ValueError('Avatar entry no longer exists.')
        variant=pack.variants[key]
        if payload.get('display_name') != (variant.display_name or key):
            raise ValueError('Avatar name changed. Review the entry again.')
        manifest=Path(pack.manifest_path)
        if managed:
            folder=checked_variant_files(manifest.parent.parent,manifest,pack_id,key,'musetalk',payload.get('token'))
        else:
            current,_reason=self._variant_identity(pack,key,variant)
            if payload.get('token') != current['token']:
                raise ValueError('Avatar or package changed. Review the selected entry again.')
            folder=Path(variant.avatar_path)
        return pack,key,variant,manifest,folder

    def _clear_variant_preview(self):
        self._last_preview={'mode':'cleared'}
        self._preview_identity={}
        self._saved_mask={}
        self._pending_override={}

    def _write_variant_config(self, key, value):
        updater=getattr(self._runtime_config,'update',None)
        if not callable(updater): raise RuntimeError('MuseTalk settings are unavailable.')
        result=updater(key,copy.deepcopy(value))
        if result is False or (hasattr(result,'accepted') and not result.accepted):
            raise RuntimeError('Could not update MuseTalk settings; avatar files were kept.')

    def _apply_variant_config(self, updates):
        previous={key:copy.deepcopy(self._runtime_value(key,None)) for key in updates}
        applied=[]
        try:
            for key,value in updates.items():
                self._write_variant_config(key,value)
                applied.append(key)
        except BaseException as error:
            for key in reversed(applied):
                try: self._write_variant_config(key,previous[key])
                except BaseException as rollback: error.add_note('Settings rollback failed: '+str(rollback))
            raise
        return previous

    def _drop_variant_runtime(self, avatar_id, folder):
        residency = self._job_runner.residency_snapshot()
        if residency['release_requested']:
            raise RuntimeError('Preparation was cancelled before publication. The previous version was kept.')
        if residency['loaded'] and not residency['worker_failed']:
            # Existing job admission serializes this request against all inference.
            response = self._bridge_request({'action':'drop_prepared_avatar',
                'avatar_id':avatar_id,'avatar_path_override':str(folder.resolve())},timeout=60)
            if response.get('ok') is not True:
                raise RuntimeError('Could not release the prepared avatar runtime before changing its files.')

    def _variant_action(self, action, payload):
        pack,key,variant,manifest,folder=self._variant_target(payload,managed=action not in {"preview","make_base"})
        raw=json.loads(manifest.read_text(encoding='utf-8'))
        if action == 'preview':
            images=sorted(path for path in (folder/'full_imgs').glob('*')
                          if path.is_file() and path.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp'})[:240]
            if not images: raise FileNotFoundError('This entry has no prepared preview frames.')
            self._clear_variant_preview()
            self._last_preview={'frame_path':str(images[0].resolve()),'mode':'prepared',
                                'frame_urls':[path.resolve().as_uri() for path in images],
                                'fps':24,'selection_revision':int(payload['selection_revision']),
                                'preview_request_id':uuid4().hex}
            return {'variant_id':key}
        if action == 'make_base':
            if not self._variant_prepared(folder):
                raise ValueError('Prepare this entry before using it as base.')
            raw['default_variant']=key
            self._write_variant_manifest(manifest,raw)
            return {'variant_id':key}
        if action == 'delete':
            if key == pack.default_variant or len(pack.variants)<=1:
                raise ValueError('Choose another prepared entry as base before deleting this entry.')
            if payload.get('confirmed') is not True:
                raise PermissionError('Confirm permanent deletion of the named avatar entry.')
            # Preserve a usable prepared base even when a malformed pack says otherwise.
            base=pack.default_variant_config
            if base is None or not self._variant_prepared(Path(base.avatar_path)):
                raise ValueError('Prepare another base entry before deleting this entry.')
            self._drop_variant_runtime(variant.avatar_id,folder)
            del raw['variants'][key]
            transitions=raw.get('transitions')
            if isinstance(transitions,dict):
                raw['transitions']={name:value for name,value in transitions.items()
                    if not (isinstance(value,dict) and (value.get('from_variant')==key or value.get('to_variant')==key))
                    and key not in str(name).split('->')}
            elif isinstance(transitions,list):
                raw['transitions']=[value for value in transitions if value.get('from_variant')!=key and value.get('to_variant')!=key]
            enabled=copy.deepcopy(self._current_enabled_emotions())
            updates={}
            if pack.pack_id in enabled:
                remaining={tag for vkey,v in pack.variants.items() if vkey!=key for tag in v.normalized_tags()}
                enabled[pack.pack_id]=[tag for tag in enabled[pack.pack_id] if tag in remaining]
                updates['musetalk_enabled_pack_emotions']=enabled
            if (str(self._runtime_value('musetalk_avatar_pack_id','')) == pack.pack_id
                    and str(self._runtime_value('musetalk_avatar_id','')) in {key,variant.avatar_id}):
                updates['musetalk_avatar_id']=pack.default_avatar_id
            previous=self._apply_variant_config(updates)
            retired=folder.with_name('.deleted-'+uuid4().hex)
            try:
                if folder.exists(): os.replace(folder,retired)
                self._write_variant_manifest(manifest,raw)
            except BaseException as error:
                if retired.exists(): os.replace(retired,folder)
                for setting,value in previous.items():
                    try: self._write_variant_config(setting,value)
                    except BaseException as rollback: error.add_note('Settings rollback failed: '+str(rollback))
                raise
            if retired.exists(): shutil.rmtree(retired)
            if str(self._state.get('musetalk_selected_avatar_id')) in {key,variant.avatar_id}:
                self._state['musetalk_selected_avatar_id']=pack.default_avatar_id
                self._state['musetalk_avatar_id']=pack.default_avatar_id
                self._state['musetalk_source_path']=''
                self._state['musetalk_emotion_tags']=''
            if pack.pack_id in enabled:
                self._state['musetalk_enabled_pack_emotions']=enabled
            self._clear_variant_preview()
            self._status=f"Permanently deleted '{variant.display_name or key}'. Original source media was kept."
            return {'variant_id':key}
        if action not in {'redo','replace'}: raise ValueError('Unknown avatar entry action.')
        source=(Path(self._local_path(payload.get('source_path'))) if action=='replace' and payload.get('source_path')
                else self._variant_source(variant,folder) if action=='redo' else None)
        if source is None or not source.exists():
            raise FileNotFoundError('Saved source is unavailable. Use Replace source to choose different media.')
        if source.resolve().is_relative_to(folder.resolve()):
            raise ValueError('Use Replace source with media outside this prepared avatar folder.')
        staging=folder.with_name('.prepare-'+uuid4().hex)
        retired=folder.with_name('.previous-'+uuid4().hex)
        published=False
        stage_evicted=False
        try:
            overrides=self._validate_overrides(source)
            response=self._bridge_request(dict(action='prepare_avatar',avatar_id=variant.avatar_id,
                avatar_path_override=str(staging.resolve()),video_path=str(source.resolve()),
                bbox_shift=int(self._state['musetalk_bbox_shift']),recreate=False,
                mask_ranges=copy.deepcopy(self._state['musetalk_mask_ranges']),mask_overrides=overrides,
                create_frame_cache=bool(self._state['musetalk_create_frame_cache']),**self._mask_settings()),timeout=1800)
            self._drop_variant_runtime(variant.avatar_id,staging)
            stage_evicted=True
            if Path(str(response.get('avatar_path') or '')).resolve()!=staging.resolve():
                raise RuntimeError('Preparation returned an unexpected avatar destination.')
            required=('avator_info.json','coords.pkl','mask_coords.pkl','latents.pt')
            if (not all((staging/name).is_file() for name in required)
                    or not any((staging/'full_imgs').glob('*'))
                    or not any((staging/'mask').glob('*'))):
                raise RuntimeError('Preparation did not produce a complete avatar. The previous version was kept.')
            for directory,folders,files in os.walk(staging,followlinks=False):
                for name in folders+files:
                    item=Path(directory)/name
                    if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0) & 0x400:
                        raise ValueError('Preparation produced linked files. The previous version was kept.')
            if self._job_runner.residency_snapshot()['release_requested']:
                raise RuntimeError('Preparation was cancelled before publication. The previous version was kept.')
            # Recheck token after worker work, before publishing; stale file dialogs/jobs cannot overwrite newer data.
            checked_variant_files(manifest.parent.parent,manifest,pack.pack_id,key,'musetalk',payload.get('token'))
            self._write_avatar_metadata(staging)
            pose=json.loads((staging/'avatar_pose.json').read_text(encoding='utf-8'))
            pose.update(avatar_id=variant.avatar_id,emotion_tags=list(variant.tags),source_path=str(source.resolve()))
            (staging/'avatar_pose.json').write_text(json.dumps(pose,indent=2),encoding='utf-8')
            raw['variants'][key]['source_path']=str(source.resolve())
            self._drop_variant_runtime(variant.avatar_id,folder)
            if folder.exists(): os.replace(folder,retired)
            try:
                os.replace(staging,folder)
                self._write_variant_manifest(manifest,raw)
                published=True
            except BaseException:
                if folder.exists(): shutil.rmtree(folder)
                if retired.exists(): os.replace(retired,folder)
                raise
            self._clear_variant_preview()
            self._status=f"Avatar '{variant.display_name or key}' is ready."
            self._progress=100
            return {'variant_id':key,'avatar_path':str(folder)}
        finally:
            try:
                if not stage_evicted and not self._job_runner.residency_snapshot()["release_requested"]:
                    self._drop_variant_runtime(variant.avatar_id,staging)
            finally:
                if staging.exists(): shutil.rmtree(staging)
                if published and retired.exists(): shutil.rmtree(retired)
