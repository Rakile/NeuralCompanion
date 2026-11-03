"""Exact soundscape routes behind the existing authenticated phone gateway."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
import re
from urllib.parse import urlsplit, parse_qsl
from uuid import uuid4

from .media import MAX_BYTES
from .models import identity, apply_patch, defaults
from .uploads import PART_BYTES

MAX_BODY=400*1024
_GET={'state':{'client_version'},'library':{'query','kind'},'import/status':{'id'},'generate/status':{'id'}}
_POST={'control','cue/apply','library/update','library/remove','import/init','import/chunk','import/finalize',
       'import/abort','generate/start','generate/cancel','generate/save','generate/discard','feedback','library/discard'}


@dataclass(frozen=True)
class SoundscapeRoute:
    method: str
    action: str
    query: dict
    media_hash: str = ''


def parse_route(method: str, path: str) -> SoundscapeRoute:
    if not isinstance(path,str) or len(path)>2048 or '\\' in path: raise ValueError('Invalid soundscape route.')
    parsed=urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or '%' in parsed.path or '..' in parsed.path:
        raise ValueError('Invalid soundscape route.')
    prefix='/api/soundscape/'
    if not parsed.path.startswith(prefix): raise ValueError('Invalid soundscape route.')
    action=parsed.path[len(prefix):]; pairs=parse_qsl(parsed.query,keep_blank_values=True)
    if len(pairs)!=len(dict(pairs)): raise ValueError('Duplicate soundscape query.')
    query=dict(pairs)
    if method=='GET' and re.fullmatch('media/[0-9a-f]{64}',action):
        if set(query)!={'offset','length'} or any(not re.fullmatch('[0-9]{1,10}',v) for v in query.values()):
            raise ValueError('Invalid sound media part.')
        numbers={key:int(value) for key,value in query.items()}
        if not 0<=numbers['offset']<MAX_BYTES or not 1<=numbers['length']<=PART_BYTES: raise ValueError('Sound media part exceeds its limit.')
        return SoundscapeRoute(method,'media',numbers,action[6:])
    if method=='POST' and action in _POST and not query: return SoundscapeRoute(method,action,{})
    if method!='GET' or action not in _GET or set(query)-_GET[action]: raise ValueError('Soundscape route is not allowed.')
    if 'client_version' in query and query['client_version']!='2':raise ValueError('Unsupported soundscape client.')
    if action.endswith('/status'):
        identity(query.get('id'),asset=True)
    if len(query.get('query',''))>120 or query.get('kind','') not in ('','music','ambience','effect'):
        raise ValueError('Invalid library filter.')
    return SoundscapeRoute(method,action,query)


class SoundscapeAPI:
    def __init__(self, state, library, uploads, jobs, context, *, instance_id=None, director=None, feedback=None):
        self.state=state; self.library=library; self.uploads=uploads; self.jobs=jobs; self.context=context
        self.instance_id=instance_id or uuid4().hex
        self.director=director
        self.feedback=feedback
        self._cue_receipts={}

    def snapshot(self, *, enhanced=False):
        scope=self.context()
        cid=scope.get('conversation_id')
        generation=scope.get('session_generation') or 0
        cue=self.director.snapshot(cid,generation) if self.director and cid else None
        if cue is not None and cue['story_revision']!=scope.get('story_revision'):
            cue=None
        state=self.state.snapshot(cid) if cid else defaults('unbound')
        for layer in ('ambience','music'):
            asset_id=state[layer]['asset_id']
            if asset_id:
                try:asset=self.library.get(asset_id)
                except ValueError:asset=None
                if not asset or asset.get('discarded'):state[layer]['asset_id']=None
        if cue is not None:
            cue={k:v for k,v in cue.items() if k in {'id','conversation_id','session_generation','assistant_id','reply_id','revision','story_revision','actions'} | ({'effect','asset_revisions'} if enhanced else set())}
            if enhanced:
                selected=set(cue['actions'].values()) | ({cue['effect']['asset_id']} if cue.get('effect') else set())
                cue['asset_revisions']={k:v for k,v in cue.get('asset_revisions',{}).items() if k in selected}
        if not enhanced:state.pop('effects',None)
        result={'state':state,
                'session_generation':scope.get('session_generation') or 0,'soundscape_version':1,
                'instance_id':self.instance_id,'conversation_available':bool(cid),
                'follow_story_available':self.director is not None,
                'cue':cue}
        if enhanced:
            records=self.feedback.snapshot(cid)['feedback'] if self.feedback and cid else []
            choices=[]
            for choice in self.feedback.latest(cid) if self.feedback and cid else []:
                if choice['session_generation']!=generation:continue
                public={k:v for k,v in choice.items() if k!='tokens'}
                rating=next((r for r in records if r['choice']['id']==choice['id']),{})
                public.update(good=bool(rating.get('good')),skipped=bool(rating.get('skip')))
                choices.append(public)
            library_revision=hashlib.sha256(json.dumps([(a['id'],a.get('revision',0)) for a in self.library.list_assets()]).encode()).hexdigest()
            result.update(context_version=1,choices=choices,library_revision=library_revision)
        return result

    def dispatch(self, route: SoundscapeRoute, payload, *, owner: str):
        # Supplied by the authenticated gateway, never copied from client JSON.
        if not owner: raise PermissionError('Soundscape authentication required.')
        try:
            if route.method=='POST':
                if not isinstance(payload,dict): raise ValueError('Invalid soundscape request.')
                identity(payload.get('client_request_id'))
            body=payload or {}; action=route.action
            enhanced=route.query.get('client_version')=='2' or body.get('client_version')==2
            if 'client_version' in body and (type(body['client_version']) is not int or body['client_version']!=2):
                raise ValueError('Unsupported soundscape client.')
            snapshot=lambda:self.snapshot(enhanced=enhanced)
            if action=='state': return 200,snapshot()
            if action=='cue/apply':
                return self._apply_cue(body,owner,enhanced)
            if action=='control':
                context=self.context()
                if (not context.get('conversation_id') or body.get('conversation_id')!=context['conversation_id']
                        or type(body.get('session_generation')) is not int
                        or body['session_generation']!=context['session_generation']):
                    return 409,{**snapshot(),'error':'Conversation changed. Refresh sound controls.'}
                patch=body.get('patch'); apply_patch(defaults(context['conversation_id']),patch)
                if 'effects' in patch and not enhanced:raise ValueError('Effect controls require an updated client.')
                if self.director is None and any((patch.get(name) or {}).get('follow_story') for name in ('ambience','music')):
                    return 409,{'error':'Automatic scene selection is unavailable with the current provider. Choose a saved background manually.'}
                for name in ('ambience','music'):
                    asset=(patch.get(name) or {}).get('asset_id')
                    if asset and self.library.get(asset).get('discarded'):raise ValueError('Restore this sound before choosing it.')
                try:
                    result=self.state.update(context['conversation_id'],body.get('expected_revision'),body['client_request_id'],patch)
                except ValueError as exc:
                    if self.state.snapshot(context['conversation_id'])['revision']!=body.get('expected_revision'):
                        return 409,{**snapshot(),'error':'Sound settings changed. Refresh and try again.'}
                    raise exc
                if self.director is not None and result['revision'] != body.get('expected_revision'):
                    self.director.invalidate(context['conversation_id'],'settings_changed')
                if self.feedback:
                    for layer in ('ambience','music'):
                        asset_id=(patch.get(layer) or {}).get('asset_id')
                        if not asset_id:continue
                        asset=self.library.get(asset_id)
                        choice_id=hashlib.sha256(json.dumps([context['conversation_id'],context['session_generation'],result['revision'],layer,asset_id,'manual']).encode()).hexdigest()
                        self.feedback.record_choice({'id':choice_id,'conversation_id':context['conversation_id'],
                            'session_generation':context['session_generation'],'reply_id':'manual','cue_id':'manual',
                            'layer':layer,'asset_id':asset_id,'asset_revision':asset['revision'],'excerpt':'','tokens':[]})
                # Return current revision even when the receipt belongs to an earlier operation.
                return 200,{**snapshot(),'operation_revision':result['revision']}
            if action=='library':
                query=route.query.get('query','').casefold(); kind=route.query.get('kind')
                assets=[a for a in self.library.list_assets() if (not kind or a['kind']==kind)
                        and (not query or query in (a['title']+' '+a['category']+' '+a['description']+' '+' '.join(a['tags'])).casefold())]
                return 200,{'assets':assets}
            if action=='library/update':
                asset=self.library.update(body.get('asset_id'),body.get('expected_revision'),body.get('metadata'),
                    request_id=body['client_request_id'],owner=owner)
                cid=self.context().get('conversation_id')
                if self.director and cid:self.director.invalidate(cid,'metadata_changed')
                return 200,{'asset':asset}
            if action=='library/discard':
                discarded=body.get('discarded')
                if type(discarded) is not bool: raise ValueError('Invalid discard decision.')
                asset=self.library.update(body.get('asset_id'),body.get('expected_revision'),{'discarded':discarded},
                    request_id=body['client_request_id'],owner=owner)
                if discarded:
                    self.state.clear_asset(asset['id'])
                context=self.context()
                if self.director and context.get('conversation_id'):
                    self.director.invalidate(context['conversation_id'],'library_changed')
                return 200,{'asset':asset,**snapshot()}
            if action=='feedback':
                context=self.context();cid=context.get('conversation_id')
                if (not self.feedback or not cid or body.get('conversation_id')!=cid
                        or type(body.get('session_generation')) is not int
                        or body['session_generation']!=context.get('session_generation')):
                    return 409,{'error':'Conversation changed. Refresh the sounds menu.'}
                choice=self.feedback.get_choice(cid,body.get('choice_id'))
                if choice['session_generation']!=body['session_generation']:
                    return 409,{'error':'Sound choice belongs to an earlier session.'}
                result=self.feedback.record(cid,choice['id'],body.get('decision'),body['client_request_id'],owner)
                if body['decision']=='skip' and choice['layer'] in ('ambience','music'):
                    latest=next((c for c in self.feedback.latest(cid) if c['layer']==choice['layer']),None)
                    current=self.state.snapshot(cid)
                    if (latest and latest['id']==choice['id']
                            and current[choice['layer']]['asset_id']==choice['asset_id']):
                        self.state.update(cid,current['revision'],'skip-'+body['client_request_id'],
                            {choice['layer']:{'asset_id':None}},manual=False)
                    if self.director:self.director.invalidate(cid,'sound_skipped')
                return 200,{'feedback':result,**snapshot()}
            if action=='library/remove':
                if self.state.references(body.get('asset_id')):
                    return 409,{'error':'This sound is selected in a conversation. Remove its selection before deleting it.'}
                self.library.remove(body.get('asset_id'),request_id=body['client_request_id'],owner=owner)
                return 200,{'removed':True}
            if action.startswith('import/'):
                if self.uploads is None: raise ValueError('Sound importing is unavailable.')
                operation=action.split('/')[1]
                if operation=='init': return 200,self.uploads.begin(owner,body['client_request_id'],body.get('filename'),body.get('byte_length'),body.get('sha256'),body.get('metadata'))
                if operation=='chunk': return 200,self.uploads.chunk(owner,body.get('id'),body.get('index'),body.get('sha256'),body.get('data'))
                if operation=='status': return 200,self.uploads.status(owner,route.query['id'])
                return 200,getattr(self.uploads,operation)(owner,body.get('id'))
            if action.startswith('generate/'):
                if self.jobs is None: raise ValueError('Sound generation is unavailable.')
                operation=action.split('/')[1]
                if operation=='start': return 200,self.jobs.submit(owner,body['client_request_id'],body.get('request'))
                if operation=='status': return 200,self.jobs.snapshot(owner,route.query['id'])
                if operation=='save': return 200,{'asset':self.jobs.save(owner,body.get('id'),body.get('metadata'))}
                return 200,getattr(self.jobs,operation)(owner,body.get('id'))
            if action=='media':
                try: data=self.library.read_media(route.media_hash,**route.query)
                except ValueError:
                    if self.jobs is None: raise
                    data=self.jobs.read_media(owner,route.media_hash,**route.query)
                return 200,data
            raise ValueError('Unknown sound operation.')
        except (ValueError,TypeError,KeyError):
            return 400,{'error':'Sound request could not be completed. Refresh its settings and check your input.'}
        except OSError:
            return 503,{'error':'Sound storage is unavailable. Check desktop disk space and permissions.'}

    def _effect_allowed(self, effect, cid, generation):
        if not effect:return None
        scope=self.context();state=self.state.snapshot(cid)
        if (scope.get('conversation_id')!=cid or scope.get('session_generation')!=generation
                or not state['enabled'] or state['paused'] or not state['effects']['enabled'] or state['effects']['muted']):return None
        asset=self.library.get(effect['asset_id'])
        if (not asset or asset.get('discarded') or not asset.get('tags') or asset['kind']!='effect'
                or asset.get('revision',0)!=effect['asset_revision']):return None
        return effect

    def _apply_cue(self, body, owner, enhanced):
        context=self.context();cid=context.get('conversation_id');generation=context.get('session_generation')
        snapshot=lambda:self.snapshot(enhanced=enhanced)
        if (not self.director or not cid or body.get('conversation_id')!=cid
                or type(body.get('session_generation')) is not int or body['session_generation']!=generation):
            return 409,{**snapshot(),'error':'Conversation changed. Refresh sound controls.'}
        key=(owner,body['client_request_id'])
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,allow_nan=False).encode()).hexdigest()
        prior=self._cue_receipts.get(key)
        if prior:
            if prior['fingerprint']!=fingerprint:raise ValueError('Scene request identity was reused.')
            grant=self._effect_allowed(prior['effect'],cid,generation) if enhanced else None
            return 200,{**snapshot(),**({'effect_grant':grant} if enhanced else {})}
        cue=self.director.snapshot(cid,generation)
        if (not cue or body.get('cue_id')!=cue['id'] or body.get('reply_id')!=cue['reply_id']
                or body.get('expected_revision')!=cue['revision'] or cue['story_revision']!=context.get('story_revision')):
            return 409,{**snapshot(),'error':'Scene choice expired. The current sound was kept.'}
        current=self.state.snapshot(cid);patch={}
        for layer,decision in cue['actions'].items():
            if (not current[layer]['follow_story'] or decision=='keep'
                    or self.feedback and self.feedback.suppressed(cid,generation,cue['reply_id'],layer)):continue
            if decision!='clear':
                asset=self.library.get(decision)
                if (not asset or asset['kind']!=layer or asset.get('discarded') or not asset.get('tags')
                        or asset.get('revision',0)!=cue['asset_revisions'].get(decision,0)):
                    return 409,{**snapshot(),'error':'Selected sound changed. The current sound was kept.'}
            patch[layer]={'asset_id':None if decision=='clear' else decision,'follow_story':True}
        if patch:
            try:self.state.update(cid,cue['revision'],body['client_request_id'],patch,manual=False)
            except ValueError:return 409,{**snapshot(),'error':'Sound settings changed. The current sound was kept.'}
        grant=None
        effect=cue.get('effect') if enhanced else None
        if effect and self.feedback and not self.feedback.suppressed(cid,generation,cue['reply_id'],'effect'):
            effect=self._effect_allowed(effect,cid,generation)
        else:effect=None
        selected={layer:self.state.snapshot(cid)[layer]['asset_id'] for layer in ('ambience','music')}
        if effect:selected['effect']=effect['asset_id']
        if self.feedback:
            for layer,asset_id in selected.items():
                if not asset_id:continue
                asset=self.library.get(asset_id)
                if not asset or asset.get('discarded'):continue
                choice_id=hashlib.sha256(json.dumps([cid,generation,cue['reply_id'],layer,asset_id]).encode()).hexdigest()
                choice=self.feedback.record_choice({'id':choice_id,'conversation_id':cid,'session_generation':generation,
                    'reply_id':cue['reply_id'],'cue_id':cue['id'],'layer':layer,'asset_id':asset_id,
                    'asset_revision':asset.get('revision',0),'excerpt':cue['excerpt'],'tokens':cue['tokens']})
                if layer=='effect':grant={k:v for k,v in choice.items() if k not in ('tokens','excerpt','layer','id')}
                if layer=='effect':grant['choice_id']=choice_id
        self.director.invalidate(cid,'scene_applied')
        self._cue_receipts[key]={'fingerprint':fingerprint,'effect':copy.deepcopy(grant)}
        while len(self._cue_receipts)>128:del self._cue_receipts[next(iter(self._cue_receipts))]
        return 200,{**snapshot(),**({'effect_grant':grant} if enhanced else {})}

    def close(self):
        if self.director is not None: self.director.close()
        if self.uploads is not None: self.uploads.close()
        if self.jobs is not None: self.jobs.close()
