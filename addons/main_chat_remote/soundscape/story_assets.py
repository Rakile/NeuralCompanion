"""Optional versioned story copies, independent of mutable library membership."""
import copy
import json
from pathlib import Path
from uuid import uuid4

from .library import SoundLibrary
from .media import file_hash
from .models import defaults, identity, metadata
from .state import atomic_json, SoundscapeStateStore


class SoundscapeStoryAssets:
    def __init__(self,state:SoundscapeStateStore,library:SoundLibrary):
        self.state,self.library=state,library

    def capture(self,conversation_id:str,target:Path)->dict:
        target.mkdir(parents=True,exist_ok=True)
        state=self.state.snapshot(conversation_id)
        ids=[state[layer]['asset_id'] for layer in ('ambience','music') if state[layer]['asset_id']]
        assets=self.library.export_assets(ids,target/'sounds')
        if self.state.snapshot(conversation_id)['revision']!=state['revision']:
            raise ValueError('The conversation changed during Save. Try again.')
        bundle={'version':1,'state':state,'assets':assets}
        atomic_json(target/'soundscape.json',bundle)
        return bundle

    def validate(self,folder:Path)->dict:
        path=folder/'soundscape.json'
        if not path.exists():return {'version':1,'state':defaults('legacy'),'assets':[]}
        if path.is_symlink() or path.stat().st_size>128*1024:raise ValueError('Invalid saved soundscape.')
        bundle=json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(bundle,dict) or bundle.get('version')!=1 or not isinstance(bundle.get('assets'),list)
                or len(bundle['assets'])>2):raise ValueError('Invalid saved soundscape.')
        saved=bundle.get('state')
        if not isinstance(saved,dict):raise ValueError('Invalid saved soundscape state.')
        SoundscapeStateStore._validated(saved.get('conversation_id',''),saved)
        ids=set()
        for item in bundle['assets']:
            key=identity(item['id'],asset=True)
            if key in ids:raise ValueError('Duplicate saved sound.')
            ids.add(key);SoundLibrary._validate_descriptor(item['media'])
            metadata({k:item[k] for k in ('title','description','kind','tags','loop')}
                     | {k:item[k] for k in ('category','gain','discarded') if k in item})
            media=folder/'sounds'/(key+'.ogg')
            if (media.is_symlink() or media.resolve().parent!= (folder/'sounds').resolve()
                    or not media.is_file() or media.stat().st_size!=item['media']['byte_length']
                    or file_hash(media)!=item['media']['sha256']):raise ValueError('Saved sound is missing or damaged.')
        if any(saved[layer]['asset_id'] and saved[layer]['asset_id'] not in ids for layer in ('ambience','music')):
            raise ValueError('A selected sound was not saved.')
        return bundle

    def restore(self,conversation_id:str,folder:Path)->dict:
        bundle=self.validate(folder);saved=copy.deepcopy(bundle['state']);mapping={}
        for item in bundle['assets']:
            details=metadata({k:item[k] for k in ('title','description','kind','tags','loop')}
                             | {k:item[k] for k in ('category','gain','discarded') if k in item})
            assets=self.library.list_assets()
            excluded=next((a for a in assets if a.get('discarded') and a['media']['sha256']==item['media']['sha256']),None)
            existing=excluded or next((a for a in assets if a['media']['sha256']==item['media']['sha256']
                and all(a[k]==v for k,v in details.items())),None)
            if existing is None:
                source=folder/'sounds'/(item['id']+'.ogg')
                existing=self.library.save_generated(source,source,item['media'],details,uuid4().hex,owner='story-library')
            mapping[item['id']]=existing['id']
        for layer in ('ambience','music'):
            saved[layer]['asset_id']=mapping.get(saved[layer]['asset_id'])
        return self.state.restore(conversation_id,saved)

    def forget(self,conversation_id:str)->None:
        # New scope created by a failed Open; no live playback may reference it.
        self.state.restore(conversation_id,defaults(conversation_id))
