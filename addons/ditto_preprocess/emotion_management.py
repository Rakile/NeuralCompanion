"""Friendly package variant operations; native generated expressions stay separate."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import uuid

from addons.musetalk_avatar.variant_files import variant_file_info, checked_variant_files
from addons.ditto_avatar.media_cache import validate_prepared_avatar
from addons.ditto_avatar.config import prepare_settings
from addons.ditto_avatar.packages import _MANIFEST_LOCK


class EmotionManagement:
    def _variant_source(self,variant):
        value=variant.metadata.get('ditto_source_media','')
        if not value:
            try:
                value=json.loads((Path(variant.avatar_path)/'avatar.json').read_text(encoding='utf-8')).get('source_path','')
            except (OSError,ValueError):
                pass
        return str(value or '')

    def emotion_entries(self):
        rows=[]
        if self.pack is None:
            return rows
        base_variant=self.pack.default_variant_config
        base_prepared=bool(base_variant and (Path(base_variant.avatar_path)/'avatar.json').is_file())
        for key,variant in self.pack.variants.items():
            folder=Path(variant.avatar_path)
            prepared=(folder/'avatar.json').is_file()
            source=self._variant_source(variant)
            thumbnail=''
            try:
                frames=json.loads((folder/'avatar.json').read_text(encoding='utf-8')).get('frame_paths',[])
                first=(folder/frames[0]).resolve() if frames else None
                if first and first.is_file() and first.is_relative_to(folder.resolve()):
                    thumbnail=first.as_uri()
            except (OSError,ValueError,TypeError):
                pass
            token=''
            reason=''
            try:
                token=variant_file_info(self.store.root,self.store.package_root(self.pack.pack_id)/'manifest.json',self.pack.pack_id,key,'ditto')['token']
            except (OSError,ValueError) as error:
                reason=str(error)
            base=key==self.pack.default_variant
            rows.append(dict(id=key,display_name=variant.display_name or key,tags=variant.normalized_tags(),
                base=base,prepared=prepared,thumbnail=thumbnail,token=token,canRedo=bool(prepared and source and Path(source).exists() and token),
                canDelete=bool(token and not base and base_prepared and len(self.pack.variants)>1),
                redoHelp='Prepare again using the saved source and current crop settings.' if source and Path(source).exists() else 'Original source is unavailable. Choose Replace source.',
                deleteHelp=reason or ('Prepare a base avatar before deleting other entries.' if not base_prepared else 'Choose another base avatar before deleting this one.' if base else 'Permanently delete this entry and its own files. Original media elsewhere is kept.')))
        return rows

    def _emotion_target(self,payload):
        self._editable()
        if self.service.session_running:
            raise RuntimeError('Stop chat or the preview before changing package emotions.')
        data=dict(payload or {})
        if not self.pack or data.get('package_id')!=self.pack.pack_id:
            raise ValueError('Package selection changed. Select the emotion again.')
        key=data.get('variant_id')
        pack=self.store.load(self.pack.pack_id)
        info=variant_file_info(self.store.root,pack.manifest_path,pack.pack_id,key,'ditto')
        if not data.get('token') or data['token']!=info['token']:
            raise ValueError('Emotion changed. Review its current entry before continuing.')
        return data,pack,key,info

    def make_base(self,payload):
        data,pack,key,info=self._emotion_target(payload)
        if not (Path(info['directory'])/'avatar.json').is_file():
            raise ValueError('Prepare this avatar before making it the base.')
        pack.default_variant=key
        self.store.save(pack)
        self.pack=pack
        self._catalog_cache=(0,[])
        self.service._package_state_cache=None
        self.service.status=f'{pack.variants[key].display_name or key} is now the base avatar.'
        return {'ok':True}

    def _set_runtime_values(self,values):
        for key,value in values.items():
            if self.service._config:
                result=self.service._config.update(key,value)
                if result is False or getattr(result,'accepted',True) is False:
                    raise RuntimeError('Could not save the updated avatar selection.')
            self.service._values[key]=value

    @staticmethod
    def _restore_manifest(path,data):
        temporary=path.with_name('.manifest-restore-'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _release_worker_sources(self,client=None):
        if client is None:
            client=self.service._client
            process=getattr(client,'process',None)
            if process is None or process.poll() is not None:
                client=None
        if client is not None:
            result=client.request('release_sources')
            if not result or result.get('sources_released') is not True:
                raise RuntimeError('Could not release the old avatar files. Unload Ditto and try again.')
        with self.service._lock:
            self.service._warmed_key=None
            self.service._visible_choice=None
            self.service._source_cursors.clear()

    def delete_variant(self,payload):
        if dict(payload or {}).get('confirmed') is not True:
            raise ValueError('Confirm permanent deletion of this emotion first.')
        data,pack,key,info=self._emotion_target(payload)
        if key==pack.default_variant or len(pack.variants)<2:
            raise ValueError('Keep a base avatar. Choose another base before deleting this entry.')
        base=pack.default_variant_config
        if base is None or not (Path(base.avatar_path)/'avatar.json').is_file():
            raise ValueError('Prepare another base avatar before deleting this entry.')
        if not self.service._operation.acquire(blocking=False):
            raise RuntimeError('Wait for the current Ditto operation to finish.')
        staged=None
        manifest=Path(pack.manifest_path)
        original=manifest.read_bytes()
        cfg=self.service._base_settings()
        updates={}
        try:
            with self.service._lock:
                self._editable()
                if self.service.session_running:
                    raise RuntimeError('Stop chat or the preview before changing package emotions.')
                self.service.busy=True
            # Keep operation admission, but let the IPC reader finish frame
            # callbacks while the synchronous release request is outstanding.
            self._release_worker_sources()
            with self.service._lock, _MANIFEST_LOCK:
                if self.service.session_running:
                    raise RuntimeError('Chat started while releasing avatar files. Stop chat and try again.')
                target=checked_variant_files(self.store.root,manifest,pack.pack_id,key,'ditto',data['token'])
                removed=pack.variants.pop(key)
                remaining_tags={tag for variant in pack.variants.values() for tag in variant.normalized_tags()}
                removed_tags=set(removed.normalized_tags())-remaining_tags
                for tag in removed_tags:
                    pack.metadata.get('ditto_emotion_map',{}).pop(tag,None)
                pack.transitions=[transition for transition in pack.transitions if key not in (transition.from_variant,transition.to_variant)]
                mapping={name:list(tags) for name,tags in cfg['ditto_enabled_pack_emotions'].items()}
                if pack.pack_id in mapping:
                    mapping[pack.pack_id]=[tag for tag in mapping[pack.pack_id] if tag not in removed_tags]
                    updates['ditto_enabled_pack_emotions']=mapping
                if cfg['ditto_pack_id']==pack.pack_id and cfg['ditto_variant_id']==key:
                    updates.update(ditto_variant_id=pack.default_variant,ditto_avatar_path=pack.default_variant_config.avatar_path)
                previous={name:cfg[name] for name in updates}
                if target.exists():
                    staged=target.with_name('.'+key+'-delete-'+uuid.uuid4().hex)
                    target.rename(staged)
                try:
                    self._set_runtime_values(updates)
                    self.store.save(pack)
                except BaseException as error:
                    try:
                        self._set_runtime_values(previous)
                    except Exception as rollback:
                        error.add_note('Settings restoration failed: '+str(rollback))
                    try:
                        if manifest.read_bytes()!=original:
                            self._restore_manifest(manifest,original)
                    finally:
                        if staged is not None and staged.exists():
                            staged.rename(target)
                    raise
                self.pack=pack
                self.selected_variant=pack.default_variant
                self._restore_wizard()
                self._select_fields()
                self._catalog_cache=(0,[])
                self.service._package_state_cache=None
                self.service._creator_preview_url=''
                self.service._preview_images.clear()
                self.service.last_result={}
                if cfg['ditto_pack_id']==pack.pack_id:
                    self.service.load_idle(self.service._base_settings()['ditto_avatar_path'])
                if staged is not None:
                    try:
                        shutil.rmtree(staged)
                    except OSError as error:
                        raise RuntimeError(f'Emotion removed, but some files could not be deleted at {staged}: {error}') from error
                self.service.status=f'{removed.display_name or key} permanently deleted from {pack.display_name}.'
            return {'ok':True}
        finally:
            self.service.busy=False
            self.service._operation.release()

    def begin_replacement(self,payload,*,redo=False):
        data,pack,key,info=self._emotion_target(payload)
        source=self._variant_source(pack.variants[key]) if redo else str(data.get('source_path') or '')
        path=Path(source).expanduser() if source else None
        if path is None or not path.exists() or path.resolve()==Path(info['directory']).resolve():
            raise ValueError('Original source is unavailable. Choose Replace source and select an image or video.')
        self.pack,self.selected_variant=pack,key
        self._replacement={'package_id':pack.pack_id,'variant_id':key,'token':data['token'],'source_path':str(path.resolve())}
        self._wizard_source=str(path.resolve())
        self._wizard_emotion=pack.variants[key].display_name or key
        self._wizard_draft=True
        self._crop_preview=None
        self.service._fps_choice=None
        self.service.update('ditto_source_path',self._wizard_source)
        self.service._creator_preview_url=''
        self.service.status='Adjust the crop, then save the replacement. Your existing avatar stays usable until preparation succeeds.'
        return self.prepare_replacement() if redo else {'ok':True}

    def prepare_replacement(self,*,video_fps_policy='ask'):
        data=dict(self._replacement or {})
        checked,pack,key,info=self._emotion_target(data)
        manifest=Path(pack.manifest_path)
        final=Path(info['directory'])
        source=Path(data['source_path'])
        pending=final.with_name('.'+key+'-prepare-'+uuid.uuid4().hex)
        backup=final.with_name('.'+key+'-old-'+uuid.uuid4().hex)
        options=prepare_settings(self.service.settings_for_package(pack.pack_id))
        options.update(canvas=pack.metadata.get('ditto_canvas'),video_fps_policy=video_fps_policy)
        def prepare(cancelled):
            swapped=False
            old_moved=False
            original=manifest.read_bytes()
            try:
                client=self.service.client()
                result=client.request('prepare',source_path=str(source),output_dir=str(pending),prepare_options=options,cancel_check=cancelled)
                if result.get('needs_fps_choice'):
                    from addons.ditto_avatar.service import fps_choice_message
                    self.service._fps_choice={**result,'source_path':str(source),'package_id':pack.pack_id,'variant_id':key,'message':fps_choice_message(result)}
                    self.service.status=self.service._fps_choice['message']
                    return result
                evidence=client.request('cache_signature',cancel_check=cancelled)
                validated=validate_prepared_avatar(pending,portable_signature=evidence['portable_signature'],canvas=pack.metadata.get('ditto_canvas'))
                saved_source=str(source)
                if source.resolve().is_relative_to(final.resolve()):
                    copied=pending/'source_media'/source.name
                    copied.parent.mkdir(exist_ok=True)
                    shutil.copytree(source,copied) if source.is_dir() else shutil.copy2(source,copied)
                    saved_source=str(final/'source_media'/source.name)
                    avatar_manifest=pending/'avatar.json'
                    raw=json.loads(avatar_manifest.read_text(encoding='utf-8'))
                    raw['source_path']=saved_source
                    avatar_manifest.write_text(json.dumps(raw),encoding='utf-8')
                self._release_worker_sources(client)
                with self.service._lock, _MANIFEST_LOCK:
                    if cancelled():
                        raise RuntimeError('Preparation cancelled. Your previous avatar is unchanged.')
                    checked_variant_files(self.store.root,manifest,pack.pack_id,key,'ditto',data['token'])
                    if final.exists():
                        final.rename(backup)
                        old_moved=True
                    pending.rename(final)
                    swapped=True
                    pack.variants[key].metadata['ditto_source_media']=saved_source
                    pack.metadata.update(ditto_canvas=list(validated['canvas']),ditto_draft=False)
                    self.store.save(pack)
                    self.pack=pack
                    self._restore_wizard()
                    self._catalog_cache=(0,[])
                    self.service._package_state_cache=None
                    self.service._tuning_cache.pop(pack.pack_id,None)
                    self.service._preview_images.clear()
                    self.service._creator_preview_url=''
                    cfg=self.service._base_settings()
                    if cfg['ditto_pack_id']==pack.pack_id and Path(cfg['ditto_avatar_path']).resolve()==final:
                        self.service.load_idle(str(final))
                    self.service.loaded=True
                    self.service.status=f'Replaced {pack.variants[key].display_name or key}. The package label and base choice are unchanged.'
                # No fallible publication work after disposing the working backup.
                old_moved=False
                try:
                    if backup.exists():
                        shutil.rmtree(backup)
                except OSError as error:
                    raise RuntimeError(f'New avatar saved, but old files could not be fully removed at {backup}: {error}') from error
                return {**result,'avatar_path':str(final)}
            except BaseException:
                if old_moved and backup.exists():
                    if swapped and final.exists():
                        shutil.rmtree(final)
                    backup.rename(final)
                    self._restore_manifest(manifest,original)
                    self.pack=self.store.load(pack.pack_id)
                elif swapped and not old_moved:
                    # A new draft has no previous folder to restore.
                    # Only roll it back if publication did not already succeed.
                    if self._replacement is not None:
                        shutil.rmtree(final)
                        self._restore_manifest(manifest,original)
                        self.pack=self.store.load(pack.pack_id)
                raise
            finally:
                for path in [pending,*pending.parent.glob(pending.name+'.preparing-*')]:
                    if path.exists():
                        shutil.rmtree(path)
        return self._start('Preparing replacement; previous avatar is kept until success…',prepare)
